"""
builder.py — 构建 LangGraph 图 + Redis Checkpointer
"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.graph.nodes.reflector import reflector_node
from app.graph.state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.dispatcher import dispatcher_node
from app.graph.nodes.search_worker import search_worker_node
from app.graph.nodes.chat_worker import chat_worker_node
from app.graph.nodes.writing_worker import writing_worker_node
from app.graph.nodes.analysis_worker import analysis_worker_node
from app.graph.nodes.synthesizer import synthesizer_node


def _build_graph() -> StateGraph:
    """构建图结构（不含 checkpointer）"""
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("search_worker", search_worker_node)
    graph.add_node("chat_worker", chat_worker_node)
    graph.add_node("analysis_worker", analysis_worker_node)
    graph.add_node("writing_worker", writing_worker_node)
    graph.add_node("reflector", reflector_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatcher_node)

    # Worker → Reflector (代替直接到 Synthesizer)
    graph.add_edge("search_worker", "reflector")
    graph.add_edge("chat_worker", "reflector")
    graph.add_edge("analysis_worker", "reflector")
    graph.add_edge("writing_worker", "reflector")

    graph.add_conditional_edges(
        "reflector",
        lambda state: "dispatcher" if state.get("needs_retry") else "synthesizer",
        {"dispatcher": "planner", "synthesizer": "synthesizer"},
        # 注: 重试时回到 planner 让它重新分配，也可以直接回 dispatcher
    )

    graph.add_edge("synthesizer", END)
    return graph

# -------- 全局单例 --------

_compiled_graph: CompiledStateGraph | None = None

async def get_graph()->CompiledStateGraph:
    global _compiled_graph
    if _compiled_graph is None:
        password_part = f":{settings.REDIS_STACK_PASSWORD}@" if settings.REDIS_STACK_PASSWORD else ""
        redis_url = f"redis://{password_part}{settings.REDIS_STACK_HOST}:{settings.REDIS_STACK_PORT}/{settings.REDIS_STACK_DB}"
        _checkpointer = AsyncRedisSaver(redis_url=redis_url)
        await _checkpointer.asetup()
        _compiled_graph = _build_graph().compile(checkpointer=_checkpointer)
    return _compiled_graph
