"""
Synthesizer 节点
对应 Java: SynthesizerNode.java
"""
import time

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import settings, get_llm
from app.graph.state import AgentState
from app.services.logging_config import get_logger, truncate
from app.services.observability import trace_node

log = get_logger(__name__)

SYNTHESIZE_SYSTEM_PROMPT = """你是一个结果汇总助手。你会收到多个专家的工作结果，请将它们整合为一个连贯、完整的回复。

【要求】
- 不要简单拼接，要有逻辑地组织内容
- 保留关键信息，去除重复内容
- 使用清晰的结构（标题、列表等）
- 语言自然流畅，像是一个人在回答
- 不要提及"专家"、"Worker"、"任务"等内部概念"""

@trace_node("synthesizer")
async def synthesizer_node(state: AgentState) -> dict:
    """
    汇总节点：整合多个 Worker 的结果
    
    对应 Java: SynthesizerNode.apply()
    """
    if state.get("cancelled"):
        existing = state.get("worker_results", [])
        if existing:
            parts = [r["result"] for r in existing if r.get("result")]
            return {"final_reply": "（已暂停）\n\n" + "\n\n".join(parts)}
        return {"final_reply": "已暂停，未产生结果。"}

    user_message = state["user_message"]
    worker_results = state["worker_results"]

    writing_result = next(
        (r for r in worker_results
         if r.get("worker_name") == "writing" and r.get("draft_article_id")),
        None,
    )
    other_results = [r for r in worker_results if r is not writing_result]
    has_other_content = any((r.get("result") or "").strip() for r in other_results)

    llm = get_llm()

    # ─── 场景 A：只有 writing 有草稿 ───
    # 不走 LLM，不产生 on_chat_model_stream 事件。
    # main.py 的 chat_stream 里如果 full_reply 为空，reply_text 也是空串，
    # 前端 SSE 流式里看不到新增 token，我们在 generate() 末尾把这句话作为一条完整消息落库即可。
    # 注意：为了让前端 UI 有内容显示，synthesizer 仍然需要让 LLM 走一遍把这句话流式吐出来。
    if writing_result and not has_other_content:
        prompt = (
            f"{SYNTHESIZE_SYSTEM_PROMPT}\n\n"
            f"【用户原始问题】\n{user_message}\n\n"
            f"【说明】用户的草稿已保存至草稿箱，article_id={writing_result['draft_article_id']}。\n"
            f"请对用户说一句简短友好的话告知，不要复述草稿正文、不要再提"
            f"「专家」「worker」等术语，10-30 字以内。"
        )
        messages = [HumanMessage(content=prompt)]
        log.info("[synthesizer] 场景 A（仅草稿） | article_id=%s",
                 writing_result["draft_article_id"])
        response = await llm.ainvoke(messages)
        return {
            "final_reply": response.content,
            "draft_article_id": writing_result["draft_article_id"],
        }

    # ─── 场景 B：writing + 其他 worker 都有产出 ───
    # 只把 other_results 喂给 LLM 汇总，末尾拼接草稿提示（不让 LLM 重写草稿）
    if writing_result:
        results_text = ""
        for wr in other_results:
            name = wr.get("worker_name", "unknown")
            res = wr.get("result", "")
            results_text += f"\n--- {name} 的结果 ---\n{res}\n"

        messages = [HumanMessage(content=(
            f"{SYNTHESIZE_SYSTEM_PROMPT}\n\n"
            f"【用户原始问题】\n{user_message}\n\n"
            f"【各专家的工作结果】\n{results_text}\n\n"
            f"【附加说明】最后请另起一段，对用户说：「另外，我已为你起草了一份文章，可在草稿箱继续编辑。」"
        ))]
        log.info("[synthesizer] 场景 B（草稿 + 其他 worker） | other=%s | article_id=%s",
                 [w.get("worker_name") for w in other_results],
                 writing_result["draft_article_id"])
        response = await llm.ainvoke(messages)
        return {
            "final_reply": response.content,
            "draft_article_id": writing_result["draft_article_id"],
        }

    # ─── 场景 C：没 writing / writing 被拒绝（没 article_id） ───
    if len(worker_results) <= 1:
        if not worker_results:
            return {"final_reply": "抱歉，处理出错了"}
        results_text = worker_results[0].get("result", "")
    else:
        results_text = ""
        for wr in worker_results:
            name = wr.get("worker_name", "unknown")
            res = wr.get("result", "")
            results_text += f"\n--- {name} 的结果 ---\n{res}\n"

    messages = [HumanMessage(content=(
        f"{SYNTHESIZE_SYSTEM_PROMPT}\n\n"
        f"【用户原始问题】\n{user_message}\n\n"
        f"【各专家的工作结果】\n{results_text}"
    ))]
    log.info("[synthesizer] 场景 C（无草稿） | workers=%s | 单路=%s",
             [wr.get("worker_name") for wr in worker_results], len(worker_results) <= 1)
    t0 = time.perf_counter()
    response = await llm.ainvoke(messages)
    cost = (time.perf_counter() - t0) * 1000
    log.info("[synthesizer] 完成 | %.0fms | reply_len=%d",
             cost, len(response.content or ""))
    return {"final_reply": response.content}
