"""Evidence selection returned with Main's next action, without a separate LLM."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError


class EvidenceConflict(BaseModel):
    model_config = ConfigDict(extra='forbid')
    citation_ids: list[str] = Field(min_length=2, max_length=8)
    description: str = Field(min_length=1, max_length=400)

    @model_validator(mode='after')
    def unique_sources(self):
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise PydanticCustomError('evidence_conflict_duplicate_ids', '冲突必须指向不同的真实来源编号')
        return self


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_ids: list[str] = Field(max_length=80,
        description="必填，所有action（包括write_draft）都必须显式输出。从已有成功任务中选择支持用户目标的原始引用id，不是任务id，不得新增或重编号。没有相关证据填[]且adequacy必须为none；partial/sufficient必须至少选一个真实引用。")
    adequacy: Literal["sufficient", "partial", "none"] = Field(
        description="none仅对应selected_ids=[]且conflicts=[]；partial对应非空selected_ids，仍有缺口或未解决矛盾；sufficient对应非空selected_ids且missing_aspects=[]、conflicts=[]。有未解决矛盾不能填sufficient。")
    reason: str = Field(min_length=1, max_length=500,
        description="针对用户整体目标评价所选资料，不把分数或分块数当成充分性。")
    missing_aspects: list[str] = Field(default_factory=list, max_length=8,
        description="尚缺少的内容；sufficient时必须为[]。partial/none且可补充时逐项写出缺口，下一步retrieve据此生成新查询，不重复原查询。")
    conflicts: list[EvidenceConflict] = Field(default_factory=list, max_length=8,
        description='尚未解决的资料矛盾及原始引用编号。非空时adequacy必须为partial，且每个冲突至少关联两个不同、已在selected_ids中的来源。无未解决冲突填[]。')

    @model_validator(mode="after")
    def check_selection(self):
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise PydanticCustomError('evidence_selection_duplicate_ids', '相关资料标识不能重复')
        if bool(self.selected_ids) != (self.adequacy != "none"):
            raise PydanticCustomError('evidence_adequacy_selection_mismatch',
                                      '资料充分性与选择结果不一致：selected_ids为空时必须为none；partial/sufficient必须有相关引用')
        if self.adequacy == "sufficient" and self.missing_aspects:
            raise PydanticCustomError('evidence_sufficient_has_gaps', '资料充分时不能同时声明尚缺内容；仍缺资料应标记partial')
        if self.conflicts and self.adequacy != 'partial':
            raise PydanticCustomError('evidence_unresolved_conflict', '尚有来源冲突时只能标记部分充分：adequacy必须为partial')
        if any(not set(conflict.citation_ids) <= set(self.selected_ids) for conflict in self.conflicts):
            raise PydanticCustomError('evidence_conflict_not_selected', '来源冲突只能引用已选择的资料')
        if any(not aspect.strip() or len(aspect) > 300 for aspect in self.missing_aspects):
            raise PydanticCustomError('evidence_gap_invalid', '资料缺口必须是非空且不超过300字的说明')
        return self
