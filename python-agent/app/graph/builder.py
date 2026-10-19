"""
builder.py — 构建 LangGraph 图 + Redis Checkpointer
"""
import asyncio
from urllib.parse import quote
from langgraph.graph import StateGraph, START, END
from app.services.checkpoint_store import LatestRunRedisSaver
from langgraph.graph.state import CompiledStateGraph

from app.config import settings
from app.graph.nodes.reflector import reflector_node
from app.graph.state import AgentState
from app.graph.nodes.planner import planner_node
from app.graph.nodes.dispatcher import dispatcher_node
from app.graph.nodes.search_worker import search_worker_node
from app.graph.nodes.chat_worker import chat_worker_node
from app.graph.writing_graph import build_writing_graph
from app.graph.nodes.analysis_worker import analysis_worker_node
from app.graph.nodes.synthesizer import synthesizer_node
from app.graph.staged_runtime import final_gate, guard_node
from app.graph.main_agent import main_agent_node, main_dispatcher
from app.graph.action_runtime import (main_retrieve_node, main_delegate_node,
    prepare_draft, draft_dispatcher, collect_draft)


def _build_legacy_graph() -> StateGraph:
    """历史扁平图回归入口；真实 get_graph() 不使用此图。"""
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("search_worker", search_worker_node)
    graph.add_node("chat_worker", chat_worker_node)
    graph.add_node("analysis_worker", analysis_worker_node)
    graph.add_node("writing_worker", build_writing_graph())
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


def _build_graph() -> StateGraph:
    from app.graph.delivery_recovery import after_retrieve, after_final_gate
    graph = StateGraph(AgentState)
    graph.add_node("main_agent", guard_node("main_agent", main_agent_node))
    graph.add_node("main_retrieve", guard_node("main_retrieve", main_retrieve_node))
    graph.add_node("main_delegate", guard_node("main_delegate", main_delegate_node))
    graph.add_node("prepare_draft", guard_node("prepare_draft", prepare_draft))
    graph.add_node("writing_worker", build_writing_graph(staged=True))
    graph.add_node("collect_draft", guard_node("collect_draft", collect_draft))
    graph.add_node("final_gate", guard_node("final_gate", final_gate))
    graph.add_edge(START, "main_agent")
    graph.add_conditional_edges("main_agent", main_dispatcher)
    graph.add_conditional_edges("main_retrieve", after_retrieve, ['main_agent', 'final_gate'])
    graph.add_edge("main_delegate", "main_agent")
    graph.add_conditional_edges("prepare_draft", draft_dispatcher)
    graph.add_edge("writing_worker", "collect_draft")
    graph.add_edge("collect_draft", "main_agent")
    graph.add_conditional_edges("final_gate", after_final_gate, ['main_agent', END])
    return graph

# -------- 全局单例 --------

_compiled_graph: CompiledStateGraph | None = None
_checkpointer: LatestRunRedisSaver | None = None
_graph_lock = asyncio.Lock()

async def get_graph()->CompiledStateGraph:
    global _compiled_graph, _checkpointer
    async with _graph_lock:
        if _compiled_graph is None:
            password_part = f":{quote(settings.REDIS_STACK_PASSWORD, safe='')}@" if settings.REDIS_STACK_PASSWORD else ""
            redis_url = f"redis://{password_part}{settings.REDIS_STACK_HOST}:{settings.REDIS_STACK_PORT}/{settings.REDIS_STACK_DB}"
            saver = LatestRunRedisSaver(redis_url=redis_url)
            try:
                await saver.__aenter__()
                _compiled_graph = _build_graph().compile(checkpointer=saver)
                _checkpointer = saver
            except BaseException:
                await saver.__aexit__(None, None, None)
                raise
    return _compiled_graph


async def close_graph():
    global _compiled_graph, _checkpointer
    async with _graph_lock:
        if _checkpointer is not None:
            await _checkpointer.__aexit__(None, None, None)
        _checkpointer = None
        _compiled_graph = None
