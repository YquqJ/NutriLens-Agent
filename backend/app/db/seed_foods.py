"""
食物库 seed 脚本（M3.8）。

用法：uv run python -m app.db.seed_foods

幂等策略：按 name 去重——已存在的跳过、不更新（数值落库固化的原则：
改数据走显式修订，不靠重跑 seed 静默覆盖历史记录的换算依据）。
"""

from app.db.foods_data import FOODS
from app.db.models import Food
from app.db.session import SessionLocal


def seed_foods() -> int:
    """把 foods_data.FOODS 灌入 foods 表，返回本次新增条数。"""
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.query(Food.name).all()}
        added = 0
        for name, category, alias, calories, protein, fat, carbs in FOODS:
            if name in existing:
                continue
            db.add(
                Food(
                    name=name,
                    category=category,
                    alias=alias,
                    calories=calories,
                    protein=protein,
                    fat=fat,
                    carbs=carbs,
                )
            )
            added += 1
        db.commit()
        return added
    finally:
        db.close()


if __name__ == "__main__":
    total_new = seed_foods()
    print(f"食物库 seed 完成：本次新增 {total_new} 条（已存在的跳过）")
