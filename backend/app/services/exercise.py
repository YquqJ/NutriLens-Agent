"""
运动记录 service：MET 表、运动消耗计算、记录 CRUD。

公式出处：ACSM（美国运动医学会）通用公式
    消耗热量(kcal) = MET × 体重(kg) × 时长(h)

MET（代谢当量）表内置 ~40 项常见运动的取值（数据综合自
Compendium of Physical Activities 的常用条目，取整便于查询）。
未知运动由 Agent 工具层让 LLM 估计 MET 并标注，本层只做确定性计算。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ExerciseRecord, UserProfile

# 常见运动的 MET 值（1 MET ≈ 静坐耗能）。键为中文运动名。
MET_TABLE: dict[str, float] = {
    "散步": 3.0,
    "快走": 4.3,
    "慢跑": 7.0,
    "跑步": 9.8,
    "骑自行车": 7.5,
    "动感单车": 8.5,
    "游泳": 8.3,
    "自由泳": 8.3,
    "蛙泳": 5.3,
    "跳绳": 11.8,
    "瑜伽": 3.0,
    "普拉提": 3.8,
    "太极": 3.3,
    "健美操": 6.0,
    "有氧操": 6.5,
    "力量训练": 5.0,
    "举重": 5.0,
    "深蹲": 5.0,
    "俯卧撑": 8.0,
    "引体向上": 8.0,
    "平板支撑": 3.8,
    "卷腹": 3.8,
    "拉伸": 2.3,
    "篮球": 8.0,
    "足球": 10.0,
    "羽毛球": 5.5,
    "乒乓球": 4.0,
    "网球": 7.3,
    "排球": 5.0,
    "羽毛球（双打）": 5.5,
    "登山": 6.0,
    "爬楼梯": 8.0,
    "徒步": 5.3,
    "滑雪": 7.0,
    "拳击": 9.0,
    "HIIT": 8.0,
    "高强度间歇训练": 8.0,
    "椭圆机": 5.0,
    "划船机": 7.0,
    "飞盘": 3.8,
}

# MET 表匹配不到时的默认值（标注为 LLM 估算时由工具层处理，
# 这里保守取中等强度）
_DEFAULT_MET = 5.0


def lookup_met(exercise_type: str) -> float | None:
    """查 MET 值。精确命中返回值；未命中返回 None（调用方决定降级策略）。"""
    return MET_TABLE.get(exercise_type.strip())


def calc_exercise_calories(
    met: float, weight_kg: float, duration_minutes: float
) -> float:
    """MET 公式：kcal = MET × 体重(kg) × 时长(h)。"""
    return round(met * weight_kg * duration_minutes / 60, 1)


def create_exercise_record(
    db: Session,
    user_id: int,
    exercise_type: str,
    duration_minutes: float,
    met: float,
    record_date: date | None = None,
    source: str = "manual",
) -> dict:
    """
    写入运动记录。热量消耗在写入时按用户当前体重固化落库
    （体重会变，历史记录不应随档案更新而漂移）。
    """
    # 读取用户当前体重做计算（无档案时按 65kg 假设并标注）
    profile = db.get(UserProfile, user_id)
    weight = profile.weight_kg if profile and profile.weight_kg else 65.0

    burned = calc_exercise_calories(met, weight, duration_minutes)
    rec = ExerciseRecord(
        user_id=user_id,
        record_date=record_date or date.today(),
        exercise_type=exercise_type,
        duration_minutes=duration_minutes,
        met=met,
        calories_burned=burned,
        source=source,
    )
    db.add(rec)
    db.commit()
    return {
        "record_id": rec.id,
        "met": met,
        "calories_burned": burned,
        "weight_used": weight,
    }


def _serialize_exercise_record(r: ExerciseRecord) -> dict:
    """单条运动记录的响应序列化（get / update 共用）。"""
    return {
        "id": r.id,
        "exercise_type": r.exercise_type,
        "duration_minutes": r.duration_minutes,
        "met": r.met,
        "calories_burned": r.calories_burned,
        "record_date": r.record_date.isoformat(),
    }


def get_exercise_records(db: Session, user_id: int, day: date) -> list[dict]:
    """按日期取运动记录。"""
    recs = db.scalars(
        select(ExerciseRecord)
        .where(ExerciseRecord.user_id == user_id, ExerciseRecord.record_date == day)
        .order_by(ExerciseRecord.id)
    ).all()
    return [_serialize_exercise_record(r) for r in recs]


def update_exercise_record(
    db: Session, user_id: int, record_id: int, duration_minutes: float
) -> dict | None:
    """
    编辑运动记录时长，消耗按 MET 公式线性重算（MET 与体重已固化在记录里，
    时长变化时 kcal = MET × 体重 × 时长(h) 等比例缩放）。
    """
    rec = db.get(ExerciseRecord, record_id)
    if rec is None or rec.user_id != user_id:
        return None
    if duration_minutes <= 0:
        return None
    k = duration_minutes / rec.duration_minutes
    rec.duration_minutes = duration_minutes
    rec.calories_burned = round(rec.calories_burned * k, 1)
    db.commit()
    return _serialize_exercise_record(rec)


def delete_exercise_record(db: Session, user_id: int, record_id: int) -> bool:
    """删除运动记录（校验归属）。"""
    rec = db.get(ExerciseRecord, record_id)
    if rec is None or rec.user_id != user_id:
        return False
    db.delete(rec)
    db.commit()
    return True
