"""
饮食 / 运动 / 看板数据路由（前端页面直连，不经过 Agent）。

与 Agent 工具写入路径共用同一 service 层 —— 保证"表单手填"与
"对话录入"两条路径的数据行为完全一致。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    if not s:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from exc


def _parse_month(s: str | None) -> date:
    """Query 参数月份解析（YYYY-MM），缺省当前月。"""
    if not s:
        today = date.today()
        return today.replace(day=1)
    try:
        year, month = (int(part) for part in s.split("-"))
        return date(year, month, 1)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="月份格式应为 YYYY-MM") from exc


# ----------------------------------------------------------------------
# 编辑请求体（M6.6：记录管理页的编辑能力）
# ----------------------------------------------------------------------
class DietItemUpdate(BaseModel):
    """编辑单个饮食条目：只改克数，营养值由服务层按比例重算。"""

    id: int
    grams: float = Field(gt=0, le=3000)


class DietRecordUpdate(BaseModel):
    items: list[DietItemUpdate]


class ExerciseRecordUpdate(BaseModel):
    duration_minutes: float = Field(gt=0, le=1440)


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


@router.put("/diet/records/{record_id}")
def update_diet_record(
    record_id: int,
    req: DietRecordUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑饮食记录条目克数（营养值按比例重算），返回更新后的完整记录。"""
    updated = diet_service.update_diet_record(
        db, user.id, record_id, [i.model_dump() for i in req.items]
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return updated


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


@router.put("/exercise/records/{record_id}")
def update_exercise_record(
    record_id: int,
    req: ExerciseRecordUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑运动记录时长（消耗按 MET 公式等比例重算），返回更新后的完整记录。"""
    updated = exercise_service.update_exercise_record(
        db, user.id, record_id, req.duration_minutes
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return updated


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


@router.get("/dashboard/monthly-summary")
def dashboard_monthly_summary(
    month: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """整月每日汇总，供记录日历一次性加载。"""
    month_start = _parse_month(month)
    return {
        "month": month_start.strftime("%Y-%m"),
        "days": diet_service.get_monthly_summaries(db, user.id, month_start),
    }
