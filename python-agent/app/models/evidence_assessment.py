"""Evidence selection returned with Main's next action, without a separate LLM."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceConflict(BaseModel):
    model_config = ConfigDict(extra='forbid')
    citation_ids: list[str] = Field(min_length=2, max_length=8)
    description: str = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def unique_sources(self):
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError('冲突必须指向不同的真实来源编号')
        return self


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_ids: list[str] = Field(default_factory=list, max_length=80,
        description="从已有成功任务中选择支持用户目标的原始引用id，不是任务id，不得新增或重编号。")
    adequacy: Literal["sufficient", "partial", "none"]
    reason: str = Field(min_length=1, max_length=500,
        description="针对用户整体目标评价所选资料，不把分数或分块数当成充分性。")
    missing_aspects: list[str] = Field(default_factory=list, max_length=8,
        description="尚缺少的内容；继续检索时据此生成新查询，不重复原查询。")
    conflicts: list[EvidenceConflict] = Field(default_factory=list, max_length=8,
        description='尚未解决的资料矛盾及原始引用编号；不能静默合并为确定结论。无冲突为空。')

    @model_validator(mode="after")
    def check_selection(self):
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("相关资料标识不能重复")
        if bool(self.selected_ids) != (self.adequacy != "none"):
            raise ValueError("资料充分性与选择结果不一致")
        if self.adequacy == "sufficient" and self.missing_aspects:
            raise ValueError("资料充分时不能同时声明尚缺内容")
        if self.conflicts and self.adequacy != 'partial':
            raise ValueError('尚有来源冲突时只能标记部分充分')
        if any(not set(conflict.citation_ids) <= set(self.selected_ids) for conflict in self.conflicts):
            raise ValueError('来源冲突只能引用已选择的资料')
        if any(not aspect.strip() or len(aspect) > 300 for aspect in self.missing_aspects):
            raise ValueError("资料缺口必须是非空且不超过300字的说明")
        return self
