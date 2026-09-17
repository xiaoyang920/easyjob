from app.graph.state import AgentState
from app.graph.tool_executor import run_tool_agent
from app.services.observability import trace_node
from app.services.tool_registry import tool_registry
from app.skills.registry import skill_registry


ANALYSIS_SYSTEM_PROMPT = """你是一个数据分析专家。

【职责】
- 对给定的主题进行深入分析
- 如果手头没有足够的数据，可以调用工具搜索相关资料
- 输出结构化的分析结果：趋势、对比、建议

【可用工具】
- search_articles：搜索平台内已有的技术文章
- search_articles_by_knn：基于语义搜索平台文章
- web_search：联网搜索最新数据

【分析要求】
- 使用数据和事实支撑观点
- 提供对比表格或列表
- 给出可操作的建议
"""
@trace_node("analysis")
async def analysis_worker_node(state: AgentState) -> dict:
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("analysis", state["user_message"])
    # 如果有反思反馈，注入到任务描述中
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"
    # 动态获取技能
    required_skills =  state.get("required_skills", [])
    system_prompt = ANALYSIS_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"
    # 动态获取工具（包含本地 + MCP 工具）
    all_tools = tool_registry.get_all_tools()
    result = await run_tool_agent(
        system_prompt=system_prompt,
        user_input=task_input,
        tools=all_tools,
        max_rounds=2,
        tag="analysis_worker",
    )

    return {
        "worker_results": [{
            "worker_name": "analysis",
            "result": result,
        }]
    }