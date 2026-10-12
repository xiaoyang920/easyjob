from app.graph.state import AgentState


def create_initial_state(user_id: int, user_message: str, history_messages: list[dict]) -> AgentState:
    return {
        "user_id": user_id, "user_message": user_message,
        "history_messages": list(history_messages),
        "origin_article_id": None, "article_context": {},
        "context_compaction": {"attempted_versions": []},
        "active_workers": [], "task_descriptions": {}, "required_skills": [],
        # None is an explicit reset signal for the result reducers on a new turn.
        "worker_results": None, "article_cards": None, "citations": None,
        "final_reply": "", "cancelled": False, "needs_retry": False,
        "retry_count": 0, "reflection_feedback": "", "draft_article_id": None,
        "plan": {}, "stages": [], "task_results": None, "stop_reason": "",
        "run_id": "", "execution_token": "", "memory_context": "",
        "user_profile": {}, "active_constraints": [], "constraint_overrides": [],
        "memory_source_message": user_message, "memory_changes_applied": False, "memory_change_log": [],
        "memory_changes_queued": False, "pending_memory_changes": [], "memory_write_job_id": "", "memory_write_status": "",
        "main_action": "", "execution_mode": "", "retrieval_status": "",
        "current_task": {}, "task_id": "", "capabilities": [],
        "main_round": 0, "main_decision": {}, "action_history": [],
        "observations": [], "correction_count": 0, "business_complete": False,
        "action_task_ids": [],
        "previous_run": {},
        "grounding_audit": {},
        "delivery_evidence": {},
        "delivery_review": {},
        "backend_boundary": {},
    }
