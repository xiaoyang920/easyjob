"""Checkpoint draft generation separately from approval and saving."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.graph.nodes.writing_worker import (
    draft_generate_node, draft_approval_node, draft_save_node, draft_reject_node,
)


class WritingInput(TypedDict):
    user_id: int
    user_message: str
    task_descriptions: dict[str, str]
    required_skills: list[str]
    reflection_feedback: str
    cancelled: bool
    run_id: str
    execution_token: str
    conversation_id: int
    task_id: str
    current_task: dict
    dependency_context: str
    citations: list[dict]
    dependency_cards: list[dict]
    execution_mode: str
    capabilities: list[str]
    user_profile: dict
    active_constraints: list[dict]


class WritingOutput(TypedDict):
    worker_results: list[dict]
    draft_article_id: int | None
    task_results: dict


class WritingState(WritingInput, WritingOutput):
    draft: dict
    pending_article_id: int
    decision: str
    revision: str
    draft_html: str
    draft_hash: str


class StagedWritingOutput(TypedDict):
    task_results: dict


def build_writing_graph(staged=False):
    from app.graph.staged_runtime import guard_node
    graph = StateGraph(WritingState, input_schema=WritingInput,
                       output_schema=StagedWritingOutput if staged else WritingOutput)
    graph.add_node("generate_draft", guard_node("generate_draft", draft_generate_node) if staged else draft_generate_node)
    graph.add_node("approve_draft", guard_node("approve_draft", draft_approval_node) if staged else draft_approval_node)
    graph.add_node("save_draft", guard_node("save_draft", draft_save_node) if staged else draft_save_node)
    graph.add_node("reject_draft", guard_node("reject_draft", draft_reject_node) if staged else draft_reject_node)
    graph.add_edge(START, "generate_draft")
    graph.add_conditional_edges("generate_draft", lambda s: "reject" if s.get("cancelled") else "approve",
                                {"reject": "reject_draft", "approve": "approve_draft"})
    graph.add_conditional_edges("approve_draft", lambda s: s["decision"],
                                {"approve": "save_draft", "reject": "reject_draft", "revise": "generate_draft"})
    if staged:
        def complete(state):
            from app.graph.staged_runtime import task_result
            result = task_result(state, state)
            # Successful user rejection is a completed business decision.
            result["status"] = "succeeded"
            return {"task_results": {state["task_id"]: result}}
        graph.add_node("complete_task", complete)
        graph.add_edge("save_draft", "complete_task")
        graph.add_edge("reject_draft", "complete_task")
        graph.add_edge("complete_task", END)
    else:
        graph.add_edge("save_draft", END)
        graph.add_edge("reject_draft", END)
    return graph.compile()
