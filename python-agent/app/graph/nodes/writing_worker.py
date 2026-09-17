from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.config import get_llm
from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
from app.services.observability import trace_node
from app.services.save_draft_to_article_info import save_draft_to_article_info, extract_title_from_draft, \
    _make_fallback_summary
from app.services.tool_registry import tool_registry
from app.skills.registry import skill_registry
from app.utils.snowflake import snowflake

class DraftOutput(BaseModel):
    title: str = Field(description="文章标题，≤50 字，简洁有信息量")
    summary: str = Field(description="一段话摘要，≤120 字，用于列表页展示")
    content: str = Field(description="完整 markdown 正文，从 # 一级标题开始")
    # 说明：不要求 LLM 产出 tags。AI 草稿的 tags 字段留空，
    # 用户在发布前的编辑器里手工选择（参见 §3.4）。

WRITING_SYSTEM_PROMPT = """你是一个专业的技术写作助手。

【职责】
- 根据用户需求撰写高质量的技术文章、博客、教程
- 如果需要引用数据或案例，使用工具搜索参考资料
- 文章结构清晰，内容准确，语言专业

【可用工具】
- search_articles：搜索平台内已有的技术文章
- search_articles_by_knn：基于语义向量搜索平台文章
- web_search：联网搜索最新信息

【工具使用原则】
1. 先评估是否需要参考资料，简单创作不需要搜索
2. 需要数据支撑、引用案例时，优先用 search_articles
3. 需要最新信息时，用 web_search
4. 最多调用 2 轮工具，然后必须给出最终结果

【输出要求】
- 你的最终回复必须是一篇完整的文章草稿（Markdown 格式）
- 包含标题、正文、代码示例（如果适用）
- 不要输出"让我搜索"、"我来查找"等过渡性文字作为最终回复
- 如果需要搜索，直接调用工具，不要用文字描述搜索意图
"""
STRUCTURIZE_PROMPT = """1.从原 markdown 抽一级标题作为 title（若无则自造一个 ≤50 字的标题）. 2.生成 ≤120 字的 summary. 3.content 原样保留（包括原 markdown 结构）"""
@trace_node("writing")
async def writing_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("writing", state["user_message"])
    # 如果有反思反馈，注入到任务描述中
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"
    #动态拼接skill
    required_skills =  state.get("required_skills", [])
    system_prompt = WRITING_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"
    structured = await generate_draft(task_input, system_prompt)
    #暂停，等用户确认,接收resume的command的resume
    user_decision = interrupt({
        "action": "confirm_publish",
        "draft": structured.content,
        "title": structured.title,
        "summary": structured.summary,
        "message": "草稿已生成，是否发布？",
    })

    # ← resume 后从这里继续，user_decision = Command(resume=...) 传入的值
    if user_decision == "approve":
        article_id = await save_draft_to_article_info(
            user_id=state["user_id"],
            draft=structured,
        )
        return {
            "worker_results": [{
                "worker_name": "writing",
                "result": structured.content,  # 给 synthesizer 的"结果文本"保持 markdown
                "draft_article_id": article_id,
                "draft_title": structured.title,  # 供 SSE __DRAFT_SAVED__ 事件透传给前端
            }],
            "draft_article_id": article_id,
        }
    elif user_decision == "reject":
        return {"worker_results": [{"worker_name": "writing", "result": "用户取消了发布"}]}
    else:
        # 用户给了修改意见，把原草稿 + 修改意见一起传给 LLM 重新生成
        revised = await generate_draft(f"原草稿：\n{structured.content}\n\n用户修改意见：{user_decision}\n\n请根据修改意见重新生成。", system_prompt)
        return {"worker_results": [{"worker_name": "writing", "result": revised.content}]}

async def generate_draft(task_input: str, system_prompt: str) -> DraftOutput:
    # 动态获取工具（包含本地 + MCP 工具）
    all_tools = tool_registry.get_all_tools()
    """生成文章草稿：LLM + Tool 多轮调用"""
    raw_markdown= await run_tool_agent(
        system_prompt=system_prompt,
        user_input=task_input,
        tools=all_tools,
        max_rounds=2,
        tag="writing_worker",
    )
    llm = get_llm().with_structured_output(DraftOutput,method="function_calling")
    structured = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=raw_markdown),
    ])

    # 兜底：LLM 偶尔会少字段
    if not structured.title:
        structured.title = extract_title_from_draft(raw_markdown)
    if not structured.summary:
        structured.summary = _make_fallback_summary(raw_markdown)
    if not structured.content:
        structured.content = raw_markdown
    return structured

