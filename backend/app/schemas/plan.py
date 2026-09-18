"""健康计划 API 模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class PlanCreate(BaseModel):
    """把已有对话中的一份计划手动同步为当前计划。"""

    content: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=128)


class PlanOut(BaseModel):
    id: int
    title: str
    content: str
    conversation_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
