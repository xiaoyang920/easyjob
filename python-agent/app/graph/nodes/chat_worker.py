"""
Chat Worker 节点
对应 Java: ChatWorkerNode.java
"""
import time

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from app.config import settings, get_llm
from app.graph.state import AgentState
from app.services.logging_config import get_logger, truncate
from app.services.observability import trace_node
from app.skills.registry import skill_registry

log = get_logger(__name__)

CHAT_SYSTEM_PROMPT = """你是一个智能博客平台助手，负责日常对话和技术问答。

【职责】
- 友好、专业地回答用户问题
- 对于技术问题，给出准确、实用的解答
- 对于平台相关问题，引导用户使用平台功能

【注意】
- 保持回复简洁有条理
- 如果不确定，诚实告知
"""

@trace_node("chat")
async def chat_worker_node(state: AgentState) -> dict:
    """
    聊天 Worker：日常对话和简单问答
    
    对应 Java: ChatWorkerNode.apply()
    """
    if state.get("cancelled"):
        return {"worker_results": []}

    task_input = state["task_descriptions"].get("chat", state["user_message"])

    # 如果有反思反馈，注入到任务描述中
    feedback = state.get("reflection_feedback", "")
    if feedback:
        task_input = f"{task_input}\n\n【上一次回复的改进意见】{feedback}\n请特别注意改进以上问题。"

    history_messages = state["history_messages"]

    required_skills =  state.get("required_skills", [])
    system_prompt = CHAT_SYSTEM_PROMPT
    for skill_name in required_skills:
        content = skill_registry.get_content(skill_name)
        if content:
            system_prompt += f"\n\n【{skill_name} 领域知识】\n{content}"

    llm = get_llm()
    
    # 构建消息列表（直接使用 LangChain 消息对象，不需要模板中转）
    messages = [SystemMessage(content=system_prompt)]
    
    for msg in history_messages[-10:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    
    messages.append(HumanMessage(content=task_input))

    log.info("[chat_worker] 启动 | task=%r | history=%d | skills=%s",
             truncate(task_input, 200), len(history_messages[-10:]), required_skills)

    t0 = time.perf_counter()
    response = await llm.ainvoke(messages)
    cost = (time.perf_counter() - t0) * 1000

    log.info("[chat_worker] 完成 | %.0fms | reply=%r", cost, truncate(response.content, 300))

    return {
        "worker_results": [{
            "worker_name": "chat",
            "result": response.content
        }]
    }
