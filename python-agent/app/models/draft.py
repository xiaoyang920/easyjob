from pydantic import BaseModel, Field

DRAFT_SUMMARY_MAX_LENGTH = 500
DRAFT_SUMMARY_TARGET_LENGTH = 300


class DraftOutput(BaseModel):
    title: str = Field(min_length=1, max_length=50, description="文章标题，≤50 字")
    summary: str = Field(max_length=DRAFT_SUMMARY_MAX_LENGTH, description="文章摘要，建议150～300字符，最多500字符")
    content: str = Field(min_length=1, max_length=100000, description="完整 Markdown 正文")
