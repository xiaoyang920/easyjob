"""Shared read-only tool loop with one bounded, permission-preserving repair."""
import asyncio
from difflib import get_close_matches
import json

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables.config import ensure_config, merge_configs
from pydantic import ValidationError

from app.config import get_llm, settings
from app.security.capabilities import require_capability
from app.services.logging_config import get_logger
from app.services.observability import get_langfuse_callback
from app.services.tool_recovery import (
    ToolPolicy, ToolTaskError, ToolInputError, argument_issues, error_message, invoke_read_only,
)
from app.utils.context_budget import ensure_request_budget

log = get_logger(__name__)
MAX_RESULT_LENGTH = 3000


async def run_tool_agent(
    system_prompt: str, user_input: str, tools: list[BaseTool] | None = None,
    max_rounds: int = 2, history_messages: list[BaseMessage] | None = None,
    timeout: float = 120.0, tag: str = "tool_agent", *,
    execution_state: dict | None = None, tool_policies: dict[str, ToolPolicy] | None = None,
    tool_timeout: float = 30.0,
) -> str:
    try:
        return await asyncio.wait_for(_run_tool_agent_inner(
            system_prompt, user_input, tools, max_rounds, history_messages, tag,
            execution_state=execution_state, tool_policies=tool_policies, tool_timeout=tool_timeout), timeout)
    except asyncio.TimeoutError:
        log.warning("[%s] Tool Agent 超时 (%.0fs)", tag, timeout)
        raise


async def _fence(state, policy=None):
    if state is None:
        return
    if state.get('cancelled'):
        raise asyncio.CancelledError()
    # Lazy import: staged_runtime imports the workers that use this module.
    from app.graph.staged_runtime import assert_run
    await assert_run(state)
    if policy is not None:
        require_capability(state, policy.capability)


def _calls(response):
    calls = [*getattr(response, 'tool_calls', []), *getattr(response, 'invalid_tool_calls', [])]
    ids = [call.get('id') for call in calls]
    if len(calls) > 8 or any(not isinstance(i, str) or not i.strip() for i in ids) or len(ids) != len(set(ids)):
        raise ToolTaskError('TOOL_CALL_PROTOCOL', '工具调用编号缺失、重复或单轮调用过多')
    return calls


def _content(response):
    if _calls(response):
        raise ToolTaskError('TOOL_CALL_PROTOCOL', '最终汇总仍返回工具调用，未将其作为成功答复')
    content = response.content or ''
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError('模型未产生有效内容')
    return content


async def _run_tool_agent_inner(
    system_prompt: str, user_input: str, tools: list[BaseTool] | None = None,
    max_rounds: int = 3, history_messages: list[BaseMessage] | None = None,
    tag: str = "tool_agent", *, execution_state=None, tool_policies=None, tool_timeout=30.0,
) -> str:
    if max_rounds < 1 or tool_timeout <= 0:
        raise ValueError('工具轮数和超时必须为正数')
    tools = tools or []
    tool_map = {tool.name: tool for tool in tools}
    if len(tool_map) != len(tools):
        raise ValueError('工具白名单存在重名')
    # Policies are server configuration, never inferred from model output or MCP
    # readOnlyHint annotations. Unclassified tools fail closed.
    from app.services.tool_registry import tool_registry
    policies = {name: (tool_policies or {}).get(name) or tool_registry.policy_for(tool)
                for name, tool in tool_map.items()}
    if any(not policy or not policy.read_only for policy in policies.values()):
        raise PermissionError('工具循环仅允许后端明确授权的只读工具')
    await _fence(execution_state)
    llm = get_llm(max_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
    bound = llm.bind_tools(tools) if tools else llm
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt), *(history_messages or []),
                                   HumanMessage(content=user_input)]
    callback = get_langfuse_callback()
    config = merge_configs(ensure_config(), {'callbacks': [callback] if callback else []})
    if tag == 'writing_worker' and not tools:
        config = merge_configs(config, {'metadata': {'public_preview': 'draft'}})
    # Cache is task-local and read-only. A repair must not repeat successful calls.
    cache, pending, repairs = {}, [], 0
    round_idx, round_limit = 0, max_rounds
    while round_idx < round_limit:
        await _fence(execution_state)
        ensure_request_budget(messages, tools, settings.WORKER_OUTPUT_MAX_TOKENS)
        response = await bound.ainvoke(messages, config=config)
        round_idx += 1
        calls = _calls(response)
        await _fence(execution_state)
        log.info('[%s] round=%d calls=%d repair_attempts=%d', tag, round_idx, len(calls), repairs)
        if not calls:
            if pending:
                raise ToolTaskError('TOOL_REPAIR_ABANDONED', '模型未修正失败的工具调用', repair_attempts=repairs)
            if isinstance(response.content, str) and response.content.strip():
                return response.content
            messages.append(HumanMessage(content='请基于以上信息，直接给出最终答复。不要再调用工具。'))
            ensure_request_budget(messages, output_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
            response = await llm.ainvoke(messages, config=config)
            await _fence(execution_state)
            return _content(response)

        # Authorize the whole batch before executing any call. A typo may only
        # suggest an already allowed tool; it never automatically selects one.
        expected = []
        for call in calls:
            name = call.get('name')
            if name in tool_map:
                await _fence(execution_state, policies[name])
                expected.append({name})
            else:
                candidates = get_close_matches(name or '', list(tool_map), n=2, cutoff=.84)
                if tool_registry.is_registered(name) or len(candidates) != 1:
                    raise PermissionError('模型请求了不在当前任务白名单中的工具')
                await _fence(execution_state, policies[candidates[0]])
                expected.append(set(candidates))
        messages.append(response)
        errors, succeeded = [], set()
        for call, target in zip(calls, expected):
            name = call['name']
            fn = tool_map.get(name)
            issues = argument_issues(fn, call.get('args')) if fn else [
                {'field': 'name', 'message': '工具名不存在，请使用 available_tools 中的准确名称'}]
            code = 'INVALID_ARGUMENTS' if fn else 'UNKNOWN_TOOL'
            if not issues:
                await _fence(execution_state, policies[name])
                key = (name, json.dumps(call['args'], sort_keys=True, ensure_ascii=False, separators=(',', ':')))
                try:
                    if key not in cache:
                        cache[key] = await invoke_read_only(fn, call, config, tool_timeout)
                    result = cache[key]
                except ToolInputError as exc:
                    issues = [{'field': exc.field, 'message': '参数不符合工具输入要求'}]
                except ValidationError:
                    issues = [{'field': '$', 'message': '参数未通过工具输入校验，请按 Schema 修正'}]
                except ToolTaskError as exc:
                    exc.report['repair_attempts'] = repairs
                    exc.report['tool'] = exc.report.get('tool') or name
                    raise
                if not issues:
                    succeeded.add(name)
                    messages.append(ToolMessage(content=result, tool_call_id=call['id'], name=name))
            if issues:
                errors.append(target)
                messages.append(error_message(call, code, issues, list(tool_map)))
        await _fence(execution_state)
        if errors:
            if repairs:
                raise ToolTaskError('TOOL_REPAIR_EXHAUSTED', '工具参数或名称修正一次后仍不合法', repair_attempts=repairs)
            repairs = 1
            pending = errors
            round_limit += 1
        elif pending:
            if any(not (names & succeeded) for names in pending):
                raise ToolTaskError('TOOL_REPAIR_ABANDONED', '模型未完成失败工具的修正', repair_attempts=repairs)
            pending = []
    if pending:
        raise ToolTaskError('TOOL_REPAIR_EXHAUSTED', '工具修正未完成', repair_attempts=repairs)
    await _fence(execution_state)
    messages.append(HumanMessage(content='请基于以上所有信息，直接给出最终答复。不要再调用工具，不要输出过渡语。'))
    ensure_request_budget(messages, output_tokens=settings.WORKER_OUTPUT_MAX_TOKENS)
    response = await llm.ainvoke(messages, config=config)
    await _fence(execution_state)
    return _content(response)
