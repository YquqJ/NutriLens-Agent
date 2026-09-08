"""
饮食 / 运动 / 看板数据路由（前端页面直连，不经过 Agent）。

与 Agent 工具写入路径共用同一 service 层 —— 保证"表单手填"与
"对话录入"两条路径的数据行为完全一致。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DietRecord, ExerciseRecord, UserProfile

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.services import diet as diet_service
from app.services import exercise as exercise_service

router = APIRouter(prefix="/api", tags=["records"])


def _parse_date(s: str | None) -> date:
    """Query 参数日期解析（YYYY-MM-DD），缺省今天。"""
    return date.fromisoformat(s) if s else date.today()


# ----------------------------------------------------------------------
# 饮食记录
# ----------------------------------------------------------------------
@router.get("/diet/records")
def list_diet_records(
    date_str: str | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return diet_service.get_diet_records(db, user.id, _parse_date(date_str))


@router.delete("/diet/records/{record_id}", status_code=204)
def delete_diet_record(
    record_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not diet_service.delete_diet_record(db, user.id, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")


# ----------------------------------------------------------------------
# 运动记录
# ----------------------------------------------------------------------
@router.get("/exercise/records")
def list_exercise_records(
    date_str: str | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return exercise_service.get_exercise_records(db, user.id, _parse_date(date_str))


@router.delete("/exercise/records/{record_id}", status_code=204)
def delete_exercise_record(
    record_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not exercise_service.delete_exercise_record(db, user.id, record_id):
        raise HTTPException(status_code=404, detail="记录不存在")


# ----------------------------------------------------------------------
# 看板
# ----------------------------------------------------------------------
@router.get("/dashboard/summary")
def dashboard_summary(
    date_str: str | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单日热量收支汇总（环图 + 宏量营养素条的数据源）。"""
    return diet_service.get_daily_summary(db, user.id, _parse_date(date_str))


@router.get("/dashboard/trend")
def dashboard_trend(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    近 N 天逐日摄入/消耗/目标序列（趋势折线图数据源）。
    返回按日期升序的完整序列 —— 无记录的日期补零，前端免做对齐。
    """
    today = date.today()
    start = today - timedelta(days=days - 1)

    # 按天聚合摄入
    intake_rows = db.execute(
        select(DietRecord.record_date, DietRecord.total_calories)
        .where(
            DietRecord.user_id == user.id,
            DietRecord.record_date >= start,
            DietRecord.record_date <= today,
        )
    ).all()
    intake_by_day: dict[date, float] = {}
    for d, kcal in intake_rows:
        intake_by_day[d] = intake_by_day.get(d, 0) + (kcal or 0)

    # 按天聚合消耗
    burn_rows = db.execute(
        select(ExerciseRecord.record_date, ExerciseRecord.calories_burned)
        .where(
            ExerciseRecord.user_id == user.id,
            ExerciseRecord.record_date >= start,
            ExerciseRecord.record_date <= today,
        )
    ).all()
    burn_by_day: dict[date, float] = {}
    for d, kcal in burn_rows:
        burn_by_day[d] = burn_by_day.get(d, 0) + (kcal or 0)

    profile = db.get(UserProfile, user.id)
    target = profile.calorie_target if profile else None

    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        series.append(
            {
                "date": d.isoformat(),
                "intake": round(intake_by_day.get(d, 0), 1),
                "burned": round(burn_by_day.get(d, 0), 1),
                "calorie_target": target,
            }
        )
    return {"days": days, "series": series}
