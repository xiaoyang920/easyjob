"""
Agent 状态定义
对应 Java: OverAllState + AgentStateFactory
"""
from typing import TypedDict, Annotated
from app.graph.staged_plan import merge_task_results


def merge_turn_results(current: list[dict], update: list[dict] | None) -> list[dict]:
    """None resets a new turn; worker updates within a turn accumulate."""
    return [] if update is None else [*(current or []), *update]


class AgentState(TypedDict):
    run_id: str
    execution_token: str
    conversation_id: int
    origin_article_id: int | None
    article_context: dict
    memory_context: str
    user_profile: dict
    active_constraints: list[dict]
    constraint_overrides: list[str]
    memory_source_message: str
    memory_changes_applied: bool
    memory_changes_queued: bool
    pending_memory_changes: list[dict]
    memory_write_job_id: str
    memory_write_status: str
    memory_change_log: list[dict]
    main_action: str
    execution_mode: str
    task_id: str
    current_task: dict
    capabilities: list[str]
    retrieval_status: str
    main_round: int
    main_decision: dict
    decision_contract_audit: dict
    action_history: list[dict]
    observations: list[dict]
    previous_run: dict
    grounding_audit: dict
    delivery_evidence: dict
    delivery_review: dict
    backend_boundary: dict
    correction_count: int
    business_complete: bool
    action_task_ids: list[str]
    plan: dict
    stages: list[list[str]]
    task_results: Annotated[dict, merge_task_results]
    stop_reason: str
    """
    Agent 全局状态
    
    对应 Java OverAllState 中的字段:
    - userMessage -> user_message
    - historyMessages -> history_messages
    - activeWorkers -> active_workers
    - taskDescriptions -> task_descriptions
    - workerResults -> worker_results
    - finalReply -> final_reply
    """
    # 用户输入
    user_message: str
    user_image_paths: list[str]
    #当前用户 ID，从请求参数传入
    user_id: int

    # 历史消息 (多轮对话)
    history_messages: list[dict]
    context_compaction: dict
    
    # Planner 输出：需要执行的 Worker 列表
    active_workers: list[str]
    
    # Planner 输出：每个 Worker 的任务描述
    task_descriptions: dict[str, str]

    # Planner 输出：需要的skill
    required_skills: list[str]
    
    # Worker 执行结果 (可累加)
    worker_results: Annotated[list[dict], merge_turn_results]
    
    # 最终回复
    final_reply: str

    cancelled: bool # 用户是否已取消，默认 False

    # 文章卡片（搜索到的文章，给前端展示卡片用，不经过 LLM）
    # Annotated[list, add]：多个 worker 返回的卡片自动合并
    article_cards: Annotated[list[dict], merge_turn_results]

    # 反思循环
    needs_retry: bool  # 是否需要重试
    retry_count: int  # 已重试次数
    reflection_feedback: str  # 反思反馈（注入给 worker 改进）
    # 草稿文章 ID
    draft_article_id: int | None
    #引用
    citations: Annotated[list[dict], merge_turn_results]
