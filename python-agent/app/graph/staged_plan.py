"""Model requests choose actions; backend tasks describe execution, never authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator
from app.services.query_rewrite import QueryFilters


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    instruction: str = Field(min_length=1, max_length=4000)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    required_skills: list[str] = Field(default_factory=list, max_length=4)
    requires_evidence: bool = False


class DraftRequest(TaskSpec):
    """Writing execution and approval belong to the backend, not the model."""
    draft_source_task_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,39}$",
        description="修改已有本人草稿时，填写已读取全文的成功任务ID，并将其列入depends_on；新建时为空")


class DelegatedTask(TaskSpec):
    subagent: Literal["search", "analysis"]
    allow_web: bool = False
    article_ids: list[PositiveInt] = Field(default_factory=list, max_length=8)
    filters: QueryFilters | None = None
    search_query: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def check_web_request(self):
        if self.search_query is not None and self.subagent != "search":
            raise ValueError("只有知识检索任务可指定检索词")
        if self.allow_web and self.subagent != "search":
            raise ValueError("只有检索任务可以请求联网能力")
        if self.article_ids and self.subagent != "search":
            raise ValueError("只有知识检索任务可以限定文章范围")
        if self.filters is not None and self.subagent != "search":
            raise ValueError("只有知识检索任务可以指定过滤条件")
        if len(set(self.article_ids)) != len(self.article_ids):
            raise ValueError("文章范围不能包含重复ID")
        return self


class DependencyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[DelegatedTask] = Field(min_length=1, max_length=8)


class ExecutionTask(TaskSpec):
    """Backend-only contract; this schema is never exposed to Main's LLM."""
    kind: Literal["search", "analysis", "writing"]
    actor: Literal["main", "subagent"]
    retrieval_target: Literal["knowledge", "memory", "drafts"] | None = None
    draft_source_task_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,39}$")
    allow_web: bool = False
    article_ids: list[PositiveInt] = Field(default_factory=list, max_length=8)
    filters: QueryFilters | None = None
    search_query: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def check_execution(self):
        if self.search_query is not None and (self.kind != "search" or self.retrieval_target == "memory"):
            raise ValueError("只有知识检索任务可指定检索词")
        if self.kind == "search":
            # Existing checkpoints and delegated Search keep their knowledge semantics.
            if self.retrieval_target is None:
                self.retrieval_target = "knowledge"
        elif self.retrieval_target is not None:
            raise ValueError("只有检索任务可以指定检索目标")
        if self.article_ids and (self.kind != "search" or self.retrieval_target not in ("knowledge", "drafts")):
            raise ValueError("只有知识检索任务可以限定文章范围")
        if self.filters is not None and (self.kind != "search" or self.retrieval_target != "knowledge"):
            raise ValueError("只有知识检索任务可以指定过滤条件")
        if len(set(self.article_ids)) != len(self.article_ids):
            raise ValueError("文章范围不能包含重复ID")
        if self.retrieval_target == "memory":
            if self.actor != "main" or self.allow_web or self.requires_evidence:
                raise ValueError("记忆召回仅允许 Main 读取自身记忆，不使用联网或文章证据")
        if self.retrieval_target == "drafts" and (self.actor != "main" or self.allow_web or self.requires_evidence or len(self.article_ids) > 1):
            raise ValueError("草稿仅允许Main读取本人资料，一次读取一篇，不联网或作为公共证据")
        if self.draft_source_task_id and (self.kind != "writing" or self.draft_source_task_id not in self.depends_on):
            raise ValueError("修改草稿必须依赖已读取的源任务")
        if self.allow_web and self.kind != "search":
            raise ValueError("分析和写作不能请求联网能力")
        if self.kind == "writing" and self.actor != "main":
            raise ValueError("草稿只能进入主代理的审批业务流程")
        return self


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[ExecutionTask] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def check_business_boundary(self):
        if any(t.kind == "writing" for t in self.tasks) and len(self.tasks) != 1:
            raise ValueError("草稿必须作为独立审批动作执行")
        return self


def compile_delegate_task(task: DelegatedTask) -> ExecutionTask:
    return ExecutionTask(**task.model_dump(exclude={"subagent"}), kind=task.subagent, actor="subagent")


def load_execution_task(data: dict, actor: str | None = None) -> ExecutionTask:
    """Normalize old server-owned checkpoints, never new model requests."""
    if "kind" in data:
        task = ExecutionTask.model_validate(data)
    else:
        legacy = dict(data)
        kind = legacy.pop("subagent", None)
        legacy_actor = legacy.pop("actor", None)
        if actor is not None and legacy_actor is not None and legacy_actor != actor:
            raise ValueError("执行者与服务端调度路径不一致")
        task = ExecutionTask(**legacy, kind=kind,
                             actor=actor or legacy_actor or ("main" if kind == "writing" else "subagent"))
    if actor is not None and task.actor != actor:
        raise ValueError("执行者与服务端调度路径不一致")
    return task


def load_execution_plan(data: dict, actor: str) -> ExecutionPlan:
    if set(data) != {"tasks"}:
        raise ValueError("执行计划格式无效")
    return ExecutionPlan(tasks=[load_execution_task(t, actor) for t in data["tasks"]])


def build_execution_stages(plan: DependencyPlan | ExecutionPlan, completed: dict | None = None) -> list[list[str]]:
    """DAG validation only. Capability and business checks are separate."""
    completed = completed or {}
    tasks = {task.task_id: task for task in plan.tasks}
    if len(tasks) != len(plan.tasks):
        raise ValueError("重复 task_id")
    if set(tasks) & set(completed):
        raise ValueError("新任务不能覆盖已存在结果")
    for task in plan.tasks:
        if len(set(task.depends_on)) != len(task.depends_on) or task.task_id in task.depends_on:
            raise ValueError("重复依赖或自依赖")
        for dep in task.depends_on:
            if dep not in tasks and (dep not in completed or completed[dep]["status"] != "succeeded"):
                raise ValueError("依赖不存在或未成功")
    remaining = set(tasks)
    done = set(completed)
    stages = []
    while remaining:
        ready = [t.task_id for t in plan.tasks if t.task_id in remaining and set(t.depends_on) <= done]
        if not ready:
            raise ValueError("依赖图有环")
        stages.append(ready)
        done.update(ready)
        remaining.difference_update(ready)
    return stages


def merge_task_results(current: dict | None, update: dict | None) -> dict:
    if update is None:
        return {}
    result = dict(current or {})
    for task_id, value in update.items():
        if task_id in result and result[task_id] != value:
            raise ValueError(f"Task {task_id} 存在冲突结果")
        result[task_id] = value
    return result
