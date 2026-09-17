"""
Agent 状态定义
对应 Java: OverAllState + AgentStateFactory
"""
from typing import TypedDict, Annotated
from operator import add


class AgentState(TypedDict):
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
    #当前用户 ID，从请求参数传入
    user_id: int

    # 历史消息 (多轮对话)
    history_messages: list[dict]
    
    # Planner 输出：需要执行的 Worker 列表
    active_workers: list[str]
    
    # Planner 输出：每个 Worker 的任务描述
    task_descriptions: dict[str, str]

    # Planner 输出：需要的skill
    required_skills: list[str]
    
    # Worker 执行结果 (可累加)
    worker_results: Annotated[list[dict], add]
    
    # 最终回复
    final_reply: str

    cancelled: bool # 用户是否已取消，默认 False

    # 文章卡片（搜索到的文章，给前端展示卡片用，不经过 LLM）
    # Annotated[list, add]：多个 worker 返回的卡片自动合并
    article_cards: Annotated[list[dict], add]

    # 反思循环
    needs_retry: bool  # 是否需要重试
    retry_count: int  # 已重试次数
    reflection_feedback: str  # 反思反馈（注入给 worker 改进）
    # 草稿文章 ID
    draft_article_id: int | None
    #引用
    citations: Annotated[list[dict], add]