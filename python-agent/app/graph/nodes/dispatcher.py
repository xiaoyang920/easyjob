"""
Dispatcher 节点
对应 Java: DispatcherNode.java

使用 LangGraph 的 Send API 实现并行调度
"""
from langgraph.types import Send

from app.graph.state import AgentState
from app.services.observability import trace_node


@trace_node("dispatcher")
def dispatcher_node(state: AgentState) -> list[Send]:
    """
    调度节点：根据 active_workers 并行分发任务
    
    对应 Java: DispatcherNode.apply() + CompletableFuture.allOf()
    
    LangGraph 的 Send API 会自动并行执行返回的节点列表
    """
    active_workers = state["active_workers"]
    
    # 返回 Send 列表，LangGraph 会并行执行这些节点
    sends = []
    for worker in active_workers:
        if worker == "search":
            sends.append(Send("search_worker", state))
        elif worker == "chat":
            sends.append(Send("chat_worker", state))
        elif worker == "analysis":
            sends.append(Send("analysis_worker", state))
        elif worker == "writing":
            sends.append(Send("writing_worker", state))
    
    # 如果没有任何 worker，默认使用 chat
    if not sends:
        sends.append(Send("chat_worker", state))
    
    return sends
