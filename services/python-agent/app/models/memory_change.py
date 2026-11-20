"""Main proposes explicit user changes; identity and persistence belong to the server."""
from typing import Literal
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.memory_identity import canonical_key, canonical_value
from app.models.user_profile import merge_topics


class MemoryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["profile", "constraint", "decision"]
    operation: Literal["set", "remove"] = "set"
    scope: Literal["user", "conversation"] = "conversation"
    key: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")
    value: str | list[str] | None = None
    record_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    source_quote: str = Field(min_length=2, max_length=1000)

    @model_validator(mode='before')
    @classmethod
    def normalize_identity(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            data['key'] = canonical_key(data.get('kind'), data.get('key'))
            if isinstance(data.get('value'), str):
                data['value'] = data['value'].strip()
                data['value'] = canonical_value(data.get('kind'), data.get('key'), data['value'])
        return data

    @model_validator(mode="after")
    def check_change(self):
        if self.operation == "set":
            if self.value is None or (isinstance(self.value, str) and not self.value.strip()):
                raise ValueError("新增或替换记忆需要非空内容")
            if isinstance(self.value, list) and (not self.value or len(self.value) > 40 or
                    any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in self.value)):
                raise ValueError("关注领域最多40个非空短条目")
            if isinstance(self.value, str) and len(self.value) > 1000:
                raise ValueError("记忆内容超出长度限制")
        elif self.value is not None:
            raise ValueError("删除操作不能附带新内容")
        if self.kind == "profile":
            if self.scope != "user" or self.record_id:
                raise ValueError("画像只属于当前用户，不使用事件id")
            if self.key not in ("topics", "experience") and not re.fullmatch(r"preferences\.[a-z][a-z0-9_]{0,39}", self.key):
                raise ValueError("画像字段必须是背景字段或preferences中的偏好")
            if self.operation == "set" and isinstance(self.value, list) != (self.key == "topics"):
                raise ValueError("关注领域使用列表，学习背景/回答偏好使用字符串")
            if isinstance(self.value, list):
                self.value = merge_topics(self.value)
        else:
            if isinstance(self.value, list):
                raise ValueError("约束和决策使用文本")
            if self.kind == "constraint" and self.key == "web_search" and self.operation == "set" and self.value not in ("deny", "allow"):
                raise ValueError("联网约束web_search仅允许deny或allow")
            if self.operation == "remove" and not self.record_id:
                raise ValueError("删除约束或决策必须引用已知id")
        return self


def validate_memory_changes(state, changes):
    if not changes:
        return
    if state.get("memory_changes_applied") or state.get('memory_changes_queued'):
        raise ValueError("本次运行已处理记忆变更，不能重复修改")
    source = state.get("memory_source_message", state["user_message"])
    known = {str(c["id"]): c for c in state.get("active_constraints", [])}
    for result in (state.get("task_results") or {}).values():
        if result.get("status") == "succeeded" and result.get("retrieval_target") == "memory":
            for item in result.get("memory_sources", []):
                if item.get("id", "").startswith("memory:"):
                    known[item["id"].split(":", 1)[1]] = item
    keys = set()
    for change in changes:
        if change.source_quote not in source:
            raise ValueError("记忆变更必须引用当前用户原话，不能依据历史或工具内容写入")
        identity = (change.kind, change.scope, canonical_key(change.kind, change.key))
        if identity in keys:
            raise ValueError("同一批变更不能重复修改相同记忆字段")
        keys.add(identity)
        if change.record_id:
            old = known.get(change.record_id)
            if not old or old.get("type") != change.kind or old.get("scope") != change.scope or canonical_key(change.kind, old.get("key")) != canonical_key(change.kind, change.key):
                raise ValueError("变更目标必须来自当前有效约束或本轮成功召回的相同范围记忆")
