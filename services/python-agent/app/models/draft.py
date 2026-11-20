from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

DRAFT_SUMMARY_MAX_LENGTH = 500
DRAFT_SUMMARY_TARGET_LENGTH = 300


class DraftOutput(BaseModel):
    title: str = Field(min_length=1, max_length=50, description="文章标题，≤50 字")
    summary: str = Field(max_length=DRAFT_SUMMARY_MAX_LENGTH, description="文章摘要，建议150～300字符，最多500字符")
    content: str = Field(min_length=1, max_length=100000, description="完整 Markdown 正文")


class EditedDraft(DraftOutput):
    model_config = ConfigDict(extra="forbid")
    content_format: Literal["markdown", "html"] = "markdown"

    @model_validator(mode="after")
    def nonblank(self):
        self.title = self.title.strip()
        if not self.title or not self.content.strip():
            raise ValueError("标题和正文不能为空")
        return self
