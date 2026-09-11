"""
食物库 seed 脚本（M3.8）。

用法：uv run python -m app.db.seed_foods

数据源：app/db/foods.csv —— 每 100g 可食部，参考《中国食物成分表》
常见值整理固化（demo 用途，非临床数据）。数据以 CSV 承载、与代码分离，
便于替换数据源或人工校验（Excel 可直接打开编辑）。

alias 为逗号分隔的同物异名（如"西红柿,番茄"），检索时与 name 一起参与
LIKE 匹配与精确分级（见 services/diet.py search_foods）。

幂等策略：按 name 去重——已存在的跳过、不更新（数值落库固化的原则：
改数据走显式修订，不靠重跑 seed 静默覆盖历史记录的换算依据）。
"""

import csv
from pathlib import Path

from app.db.models import Food
from app.db.session import SessionLocal

_CSV_PATH = Path(__file__).with_name("foods.csv")


def _load_rows() -> list[dict]:
    """读 foods.csv，营养值转 float，返回 Food 构造参数列表。"""
    with _CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
        rows = []
        for r in csv.DictReader(f):
            rows.append(
                {
                    "name": r["name"].strip(),
                    "category": r["category"].strip(),
                    "alias": r["alias"].strip(),
                    "calories": float(r["calories"]),
                    "protein": float(r["protein"]),
                    "fat": float(r["fat"]),
                    "carbs": float(r["carbs"]),
                }
            )
    return rows


def seed_foods() -> int:
    """把 foods.csv 灌入 foods 表，返回本次新增条数。"""
    db = SessionLocal()
    try:
        existing = {name for (name,) in db.query(Food.name).all()}
        added = 0
        for row in _load_rows():
            if row["name"] in existing:
                continue
            db.add(Food(**row))
            added += 1
        db.commit()
        return added
    finally:
        db.close()


if __name__ == "__main__":
    total_new = seed_foods()
    print(f"食物库 seed 完成：本次新增 {total_new} 条（已存在的跳过）")
