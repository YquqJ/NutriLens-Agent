"""用户档案（身体数据/目标）相关模型。"""

from pydantic import BaseModel, Field


class UserProfileIn(BaseModel):
    """PUT /api/users/me/profile 请求体。全部字段可空 = 允许渐进完善档案。"""

    gender: str | None = Field(default=None, pattern="^(male|female)$")
    age: int | None = Field(default=None, ge=10, le=100)
    height_cm: float | None = Field(default=None, gt=80, lt=250)
    weight_kg: float | None = Field(default=None, gt=25, lt=300)
    # 活动水平四档，对应系数：久坐1.2 / 轻度1.375 / 中度1.55 / 高度1.725
    activity_level: str | None = Field(
        default=None, pattern="^(sedentary|light|moderate|active)$"
    )
    goal: str | None = Field(default=None, pattern="^(lose|maintain|gain)$")
    goal_note: str | None = None  # 长期偏好/过敏，自由文本


class UserProfileOut(BaseModel):
    gender: str | None
    age: int | None
    height_cm: float | None
    weight_kg: float | None
    activity_level: str | None
    goal: str | None
    goal_note: str
    # 计算结果（无档案数据时为 None）
    bmr: float | None
    tdee: float | None
    calorie_target: float | None

    model_config = {"from_attributes": True}
