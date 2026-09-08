"""
档案域工具（plan_agent 与 qa_agent 共用的基础工具）。

设计要点：
1. 档案是"长期记忆"的载体：身高体重/目标/偏好（如"对花生过敏"）
   跨会话生效，agent 每次回答前可先读档案做个性化（比如给减脂用户
   的建议与增肌用户不同）。
2. update_profile 走 Pydantic 嵌套模型参数 + exclude_unset 语义：
   LLM 只传它掌握的字段，未提及的字段不动 —— 和 REST 的
   PUT /me/profile 完全同一条 service 路径，两端口行为一致。
3. BMR/TDEE 等计算结果只在 service 层算好回填，LLM 不做算术。
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.schemas.user import UserProfileOut
from app.services import profile as profile_service
from app.tools.context import get_current_user_id, get_session


def _profile_dict(profile) -> dict:
    """ORM → dict（复用 API 的响应模型，保证两端口字段一致）。"""
    return UserProfileOut.model_validate(profile).model_dump()


class ProfileUpdate(BaseModel):
    """要更新的档案字段（全部可空 = 只改传入的键）。

    约束与 schemas/user.UserProfileIn 一致 —— LLM 传非法枚举值
    会在参数校验层被拦下，而不是落一个脏值进库。
    """

    gender: str | None = Field(default=None, pattern="^(male|female)$")
    age: int | None = Field(default=None, ge=10, le=100)
    height_cm: float | None = Field(default=None, gt=80, lt=250)
    weight_kg: float | None = Field(default=None, gt=25, lt=300)
    activity_level: str | None = Field(
        default=None, pattern="^(sedentary|light|moderate|active)$"
    )
    goal: str | None = Field(default=None, pattern="^(lose|maintain|gain)$")
    goal_note: str | None = None  # 长期偏好/过敏，自由文本


@tool
def get_profile() -> dict:
    """
    查询当前用户的身体档案与目标（性别/年龄/身高/体重/活动水平/
    目标/长期偏好），以及计算好的 BMR/TDEE/每日热量目标。
    个性化建议前应先调用此工具。
    """
    user_id = get_current_user_id()
    with get_session() as db:
        profile = profile_service.get_profile(db, user_id)
    if profile is None:
        return {
            "found": False,
            "hint": "用户尚未填写档案，可先询问基本信息（性别/年龄/身高/体重/活动水平/目标）再调用 update_profile",
        }
    return {"found": True, "profile": _profile_dict(profile)}


@tool
def update_profile(updates: ProfileUpdate) -> dict:
    """
    更新（部分更新）当前用户的身体档案。只传需要修改的字段。
    字段：gender(male/female)、age、height_cm、weight_kg、
    activity_level(sedentary/light/moderate/active)、
    goal(lose/maintain/gain)、goal_note(长期偏好/过敏，自由文本)。
    更新后自动重算 BMR/TDEE/热量目标并返回最新档案。
    """
    # exclude_unset：LLM 没提的字段不覆盖（如只说"我最近 68kg 了"就只改体重）
    data = updates.model_dump(exclude_unset=True)

    user_id = get_current_user_id()
    with get_session() as db:
        profile = profile_service.apply_profile_update(db, user_id, data)
    return {"status": "updated", "profile": _profile_dict(profile)}
