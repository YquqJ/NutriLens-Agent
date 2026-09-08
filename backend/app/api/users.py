"""用户档案路由：身体数据 / 目标的查询与更新。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import User, UserProfile
from app.db.session import get_db
from app.schemas.user import UserProfileIn, UserProfileOut
from app.services.profile import recalc_profile_metrics

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me/profile", response_model=UserProfileOut)
def get_profile(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """查询档案。无档案时返回空档案（前端引导填写），不报 404。"""
    profile = db.get(UserProfile, user.id)
    if profile is None:
        return UserProfileOut(
            gender=None, age=None, height_cm=None, weight_kg=None,
            activity_level=None, goal=None, goal_note="",
            bmr=None, tdee=None, calorie_target=None,
        )
    return profile


@router.put("/me/profile", response_model=UserProfileOut)
def update_profile(
    req: UserProfileIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新档案（partial update：只覆盖请求中出现且非 None 的字段），
    每次更新后重算 BMR/TDEE/热量目标并回填缓存。
    """
    profile = db.get(UserProfile, user.id)
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)

    # 仅覆盖显式传入的字段（PUT 语义这里做成 patch 式，前端交互更友好）
    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)

    profile.bmr, profile.tdee, profile.calorie_target = recalc_profile_metrics(
        profile.gender, profile.weight_kg, profile.height_cm,
        profile.age, profile.activity_level, profile.goal,
    )
    db.commit()
    db.refresh(profile)
    return profile
