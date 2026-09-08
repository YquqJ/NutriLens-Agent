"""
饮食记录 service：食物检索、记录 CRUD、每日汇总。

同一层会被两种调用方使用（保证行为一致）：
1. REST 路由（前端表单直接增删查）；
2. LangGraph 工具（Agent 通过 create_diet_record 等工具间接调用）。
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DietRecord, DietRecordItem, ExerciseRecord, Food, UserProfile


# ----------------------------------------------------------------------
# 食物检索
# ----------------------------------------------------------------------
def search_foods(db: Session, query: str, top_k: int = 5) -> list[dict]:
    """
    按名称模糊检索食物（LIKE '%q%'，name 与 alias 字段都参与匹配）。

    匹配分级（返回 match_type 字段，Agent 与前端据此展示置信度）：
    - exact  ：name 或 alias 完全相等（如"苹果"）
    - prefix ：name 或 alias 以 query 开头（如 query="牛" 命中"牛肉"）
    - fuzzy  ：包含 query（如 query="肉" 命中"涮羊肉"）
    按分级排序优先返回高置信结果。
    """
    q = query.strip()
    if not q:
        return []

    stmt = (
        select(Food)
        .where((Food.name.contains(q)) | (Food.alias.contains(q)))
        .limit(top_k * 3)  # 多取一些再按分级排序截断
    )
    rows = db.scalars(stmt).all()

    def match_rank(food: Food) -> tuple[int, str]:
        names = [food.name, *[a.strip() for a in food.alias.split(",") if a.strip()]]
        for n in names:
            if n == q:
                return 0, "exact"
        for n in names:
            if n.startswith(q):
                return 1, "prefix"
        return 2, "fuzzy"

    ranked = sorted((match_rank(f), f) for f in rows)[:top_k]
    return [
        {
            "food_id": f.id,
            "name": f.name,
            "category": f.category,
            # 每 100g 的营养值
            "calories_per_100g": f.calories,
            "protein_per_100g": f.protein,
            "fat_per_100g": f.fat,
            "carbs_per_100g": f.carbs,
            "match_type": rank[1],
        }
        for rank, f in ranked
    ]


def calc_item_nutrition(food: Food, grams: float) -> dict:
    """按克数换算食物营养值（每 100g 值 × grams / 100）。"""
    k = grams / 100
    return {
        "calories": round(food.calories * k, 1),
        "protein": round(food.protein * k, 1),
        "fat": round(food.fat * k, 1),
        "carbs": round(food.carbs * k, 1),
    }


# ----------------------------------------------------------------------
# 饮食记录 CRUD
# ----------------------------------------------------------------------
def create_diet_record(
    db: Session,
    user_id: int,
    meal_type: str,
    items: list[dict],
    record_date: date | None = None,
    source: str = "manual",
) -> dict:
    """
    写入一条饮食记录。

    items 元素结构：{food_name, grams, calories, protein, fat, carbs, confidence}
    （营养值由调用方算好传入 —— Agent 工具层负责查库换算，本层只管落库）
    """
    rec = DietRecord(
        user_id=user_id,
        record_date=record_date or date.today(),
        meal_type=meal_type,
        source=source,
        total_calories=round(sum(i["calories"] for i in items), 1),
        total_protein=round(sum(i["protein"] for i in items), 1),
        total_fat=round(sum(i["fat"] for i in items), 1),
        total_carbs=round(sum(i["carbs"] for i in items), 1),
    )
    rec.items = [
        DietRecordItem(
            food_name=i["food_name"],
            grams=i["grams"],
            calories=i["calories"],
            protein=i.get("protein", 0),
            fat=i.get("fat", 0),
            carbs=i.get("carbs", 0),
            confidence=i.get("confidence", "db_exact"),
        )
        for i in items
    ]
    db.add(rec)
    db.commit()
    return {"record_id": rec.id, "total_calories": rec.total_calories}


def get_diet_records(db: Session, user_id: int, day: date) -> list[dict]:
    """按日期取饮食记录（含明细）。"""
    recs = db.scalars(
        select(DietRecord)
        .where(DietRecord.user_id == user_id, DietRecord.record_date == day)
        .order_by(DietRecord.id)
    ).all()
    return [
        {
            "id": r.id,
            "meal_type": r.meal_type,
            "source": r.source,
            "record_date": r.record_date.isoformat(),
            "totals": {
                "calories": r.total_calories,
                "protein": r.total_protein,
                "fat": r.total_fat,
                "carbs": r.total_carbs,
            },
            "items": [
                {
                    "id": it.id,
                    "food_name": it.food_name,
                    "grams": it.grams,
                    "calories": it.calories,
                    "protein": it.protein,
                    "fat": it.fat,
                    "carbs": it.carbs,
                    "confidence": it.confidence,
                }
                for it in r.items
            ],
        }
        for r in recs
    ]


def delete_diet_record(db: Session, user_id: int, record_id: int) -> bool:
    """删除饮食记录（校验归属，防止横向越权删他人记录）。"""
    rec = db.get(DietRecord, record_id)
    if rec is None or rec.user_id != user_id:
        return False
    db.delete(rec)  # items 级联删除
    db.commit()
    return True


# ----------------------------------------------------------------------
# 每日汇总（看板与 Agent 问答共用）
# ----------------------------------------------------------------------
def get_daily_summary(db: Session, user_id: int, day: date) -> dict:
    """
    汇总某日的热量收支：摄入、消耗、净收支、目标、剩余额度、宏量营养素分布。

    目标值从 user_profiles 读 calorie_target（档案未填则为 None，
    前端展示"请先完善档案"，Agent 回答也会引导用户填写）。
    """
    # 多列聚合一次查回（摄入总量 + 三大宏量营养素），单行元组
    totals = db.execute(
        select(
            func.coalesce(func.sum(DietRecord.total_calories), 0.0),
            func.coalesce(func.sum(DietRecord.total_protein), 0.0),
            func.coalesce(func.sum(DietRecord.total_fat), 0.0),
            func.coalesce(func.sum(DietRecord.total_carbs), 0.0),
        ).where(DietRecord.user_id == user_id, DietRecord.record_date == day)
    ).one()

    burned = db.scalar(
        select(func.coalesce(func.sum(ExerciseRecord.calories_burned), 0.0)).where(
            ExerciseRecord.user_id == user_id, ExerciseRecord.record_date == day
        )
    )

    profile = db.get(UserProfile, user_id)
    target = profile.calorie_target if profile else None

    intake_kcal = float(totals[0])
    burned_kcal = float(burned or 0)
    return {
        "date": day.isoformat(),
        "intake": round(intake_kcal, 1),
        "burned": round(burned_kcal, 1),
        "net": round(intake_kcal - burned_kcal, 1),
        "calorie_target": target,
        "remaining": round(target - intake_kcal + burned_kcal, 1) if target else None,
        "macros": {
            "protein": round(float(totals[1]), 1),
            "fat": round(float(totals[2]), 1),
            "carbs": round(float(totals[3]), 1),
        },
    }
