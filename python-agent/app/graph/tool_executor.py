"""
通用 Tool 调用循环

search_worker / writing_worker / analysis_worker 都有一段几乎相同的代码：
  LLM + bind_tools → 检查 tool_calls → 执行工具 → 追加结果 → 再调 LLM

这个模块把这段逻辑抽成一个函数，只维护一份。
"""
import asyncio
import time

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables.config import ensure_config, merge_configs

from app.config import get_llm, settings
from app.utils.context_budget import ensure_request_budget
from app.services.logging_config import get_logger, truncate
from app.services.observability import get_langfuse_callback

MAX_RESULT_LENGTH = 3000  # 单次 Tool 返回最大字符数
log = get_logger(__name__)


async def run_tool_agent(
    system_prompt: str,
    user_input: str,
    tools: list[BaseTool] | None = None,
    max_rounds: int = 2,
    history_messages: list[BaseMessage] | None = None,
    timeout: float = 120.0,
    tag: str = "tool_agent",
) -> str:
    """
    :param tag: 调用方标识，打日志时区分是 writing / search / analysis 等
    """
    try:
        return await asyncio.wait_for(
            _run_tool_agent_inner(system_prompt, user_input, tools, max_rounds, history_messages, tag),
            timeout,
        )
    except asyncio.TimeoutError:
        log.warning("[%s] Tool Agent 超时 (%.0fs)", tag, timeout)
        raise


async def _run_tool_agent_inner(
    system_prompt: str,
    user_input: str,
    tools: list[BaseTool] | None = None,
    max_rounds: int = 3,
    history_messages: list[BaseMessage] | None = None,
    tag: str = "tool_agent",
) -> str:
    """
    通用的 LLM + Tool 多轮调用循环
    """
    llm = get_llm(max_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
    tool_map = {t.name: t for t in tools} if tools else {}

    log.info("[%s] 启动 | tools=%s | max_rounds=%d | input=%r",
             tag, list(tool_map.keys()) or "无", max_rounds, truncate(user_input, 200))

    if tools:
        llm_bound = llm.bind_tools(tools)
    else:
        llm_bound = llm

    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]

    if history_messages:
        messages.extend(history_messages)

    messages.append(HumanMessage(content=user_input))
    callbacks = []
    lf_cb = get_langfuse_callback()
    if lf_cb:
        callbacks.append(lf_cb)
    # Keep the parent graph's metrics/events instead of replacing them with a
    # worker-local tracing list (including an empty list when tracing is off).
    call_config = merge_configs(ensure_config(), {"callbacks": callbacks})
    if tag == 'writing_worker' and not tools:
        # Only the user-facing draft body is previewable; the later metadata
        # extraction call and all tool-enabled workers remain private.
        call_config = merge_configs(call_config, {'metadata': {'public_preview': 'draft'}})

    for round_idx in range(max_rounds):
        ensure_request_budget(messages, tools or [], settings.WORKER_OUTPUT_MAX_TOKENS)
        t0 = time.perf_counter()
        response = await llm_bound.ainvoke(messages, config=call_config)
        cost = (time.perf_counter() - t0) * 1000

        if not response.tool_calls:
            log.info("[%s] round#%d LLM 无工具调用，直接出结果 | %.0fms | content=%r",
                     tag, round_idx + 1, cost, truncate(response.content, 300))
            content = response.content or ""
            if not content.strip():
                log.warning("[%s] round#%d 返回空 content 且无 tool_calls，强制再生成一次", tag, round_idx + 1)
                messages.append(HumanMessage(
                    content="请基于以上信息，直接给出最终答复。不要再调用工具。"
                ))
                t1 = time.perf_counter()
                ensure_request_budget(messages, output_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
                response = await llm.ainvoke(messages, config=call_config)
                cost1 = (time.perf_counter() - t1) * 1000
                content = response.content or ""
                if not content.strip():
                    raise RuntimeError("模型未产生有效内容")
                log.info("[%s] 兜底生成完成 | %.0fms | content=%r", tag, cost1, truncate(content, 300))
            return content

        log.info("[%s] round#%d LLM 请求调用 %d 个工具 | %.0fms | calls=%s",
                 tag, round_idx + 1, len(response.tool_calls), cost,
                 [{"name": tc["name"], "args": truncate(tc.get("args"), 120)} for tc in response.tool_calls])

        messages.append(response)
        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})
            fn = tool_map.get(tool_name)

            t_tool = time.perf_counter()
            if fn:
                allow, reason = _validate_args(tool_name, tool_args)
                if not allow:
                    log.warning("[%s] 工具 %s 参数校验不通过: %s", tag, tool_name, reason)
                    raise ValueError(f"工具 {tool_name} 参数无效：{reason}")
                else:
                    try:
                        # async tool 必须走 ainvoke；StructuredTool 的 invoke 对 async func 会抛 "does not support sync invocation"
                        result = await fn.ainvoke(tool_args)
                        result_raw_len = len(str(result))
                        result = _truncate_result(result)
                        elapsed = (time.perf_counter() - t_tool) * 1000
                        log.info("[%s] 工具 %s 返回 | %.0fms | %d chars | %r",
                                 tag, tool_name, elapsed, result_raw_len, truncate(result, 300))
                    except Exception as e:
                        elapsed = (time.perf_counter() - t_tool) * 1000
                        log.error("[%s] 工具 %s 执行失败 | %.0fms | err=%s",
                                  tag, tool_name, elapsed, e)
                        raise RuntimeError(f"工具 {tool_name} 执行失败") from e
            else:
                log.warning("[%s] 工具 %s 不存在", tag, tool_name)
                raise ValueError(f"工具 {tool_name} 不存在或无权调用")
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    # 轮数用完，最后一次调用拿最终回复
    # 关键修复：最后一次汇总不再绑 tools。
    # 若仍绑 tools，DeepSeek/OpenAI 在 function calling 模式下会选择继续 tool_call，
    # 此时 response.content 为空字符串（content 与 tool_calls 互斥），导致上层拿到空回复。
    log.info("[%s] 轮数用尽，最终一次 LLM 汇总（不带 tools，强制出 content）", tag)
    messages.append(HumanMessage(
        content="请基于以上所有信息，直接给出最终答复给用户。不要再调用工具，不要输出过渡语。"
    ))
    t0 = time.perf_counter()
    ensure_request_budget(messages, output_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
    response = await llm.ainvoke(messages, config=call_config)
    cost = (time.perf_counter() - t0) * 1000
    final_content = response.content or ""
    log.info("[%s] 完成 | 最终回复 %.0fms | content=%r",
             tag, cost, truncate(final_content, 300))

    # 兜底：若仍为空（极少数 provider 异常），返回一条友好提示
    if not final_content.strip():
        log.warning("[%s] 最终回复为空，使用兜底文案", tag)
        raise RuntimeError("模型未产生有效内容")
    return final_content


def _validate_args(tool_name: str, args: dict) -> tuple[bool, str]:
    if tool_name == "web_search" and len(args.get("query", "")) > 200:
        return False, "搜索查询过长，请精简后重试"
    return True, ""


def _truncate_result(result: str) -> str:
    if len(result) > MAX_RESULT_LENGTH:
        return result[:MAX_RESULT_LENGTH] + "\n...[结果已截断]"
    return result
