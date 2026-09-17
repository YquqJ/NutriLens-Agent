"""
食物库 seed 测试（M3.8）。

验收（SPEC）：search_food("西红柿") 命中并带别名"番茄"；
幂等性：重复执行不产生重复数据。
"""

from pathlib import Path

from app.db.models import Food
from app.db.seed_foods import _CSV_PATH, seed_foods
from app.db.session import SessionLocal
from app.services.diet import search_foods


def test_food_csv_is_loaded_from_backend_data_directory():
    """食物 CSV 应放在 backend/data，脱离 app 包代码目录。"""
    backend_root = Path(__file__).resolve().parents[1]
    assert _CSV_PATH == backend_root / "data" / "foods.csv"
    assert _CSV_PATH.is_file()


def test_food_seed_idempotent_and_alias_search():
    # 跑两遍：第二遍应 0 新增（按 name 去重）
    first = seed_foods()
    second = seed_foods()
    assert second == 0

    db = SessionLocal()
    try:
        total = db.query(Food).count()
        # 数据规模（SPEC：~800-1000，当前数据集 789 条）
        assert total >= 700

        # ---- SPEC 验收：西红柿命中 + alias 带"番茄" ----
        tomato = db.query(Food).filter(Food.name == "西红柿").one()
        assert "番茄" in tomato.alias.split(",")

        results = search_foods(db, "西红柿")
        assert results, "查'西红柿'应有命中"
        assert results[0]["name"] == "西红柿"
        assert results[0]["match_type"] == "exact"

        # 反向：用别名"番茄"查也命中同一条
        alias_results = search_foods(db, "番茄")
        assert any(r["name"] == "西红柿" for r in alias_results)

        # 营养值换算链路可用（M3.4 diet_agent 依赖的基础）
        k = tomato.calories * 250 / 100  # 250g 西红柿（20kcal/100g）= 50 kcal
        assert 40 < k < 60
    finally:
        db.close()
