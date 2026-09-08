"""
运动域工具测试。

两层验证（对应 SPEC M3.1 验收标准）：
1. 单元层：MET 查表与消耗公式 —— 纯数学，无外部依赖；
2. 集成层：@tool 工具直调（真实 PostgreSQL）—— 验证 ensure_config 上下文
   注入、service 落库、CRUD 全链路。

工具直调要点：@tool 包装后的函数通过 .invoke(args, config=...) 调用，
config 中的 configurable.user_id 会被 tools/context.py 的 ensure_config
读到 —— 这正是生产路径中 API 层的注入方式，测试模拟同一形态。
"""

import uuid

import pytest

from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal
from app.services.exercise import calc_exercise_calories, lookup_met
from app.tools.exercise import (
    create_exercise_record,
    delete_exercise_record,
    get_exercise_records,
)


# ======================================================================
# 单元层：MET 表与公式
# ======================================================================
def test_lookup_met_hit():
    """精确命中：慢跑 7.0。"""
    assert lookup_met("慢跑") == 7.0


def test_lookup_met_miss():
    """未命中返回 None（调用方决定降级策略），且应容忍首尾空格。"""
    assert lookup_met("不存在的运动") is None
    assert lookup_met("  慢跑  ") == 7.0


def test_calc_exercise_calories():
    """MET 公式：kcal = MET × 体重(kg) × 时长(h)。70kg 慢跑 30 分钟。"""
    # 7.0 × 70 × 0.5 = 245.0
    assert calc_exercise_calories(7.0, 70, 30) == 245.0


# ======================================================================
# 集成层：工具直调（真实数据库）
# ======================================================================
@pytest.fixture
def test_user():
    """临时用户（测试结束级联删除其所有记录）。"""
    db = SessionLocal()
    user = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    yield user.id
    db.delete(user)
    db.commit()
    db.close()


def _invoke(tool, args: dict, user_id: int):
    """按生产路径的调用形态执行工具（user_id 走 configurable 注入）。"""
    return tool.invoke(args, config={"configurable": {"user_id": user_id}})


def test_exercise_tools_crud_flow(test_user):
    """create → get → delete 全链路：MET 表命中路径。"""
    # 创建：不传 met，应自动查表（慢跑 → 7.0）
    created = _invoke(
        create_exercise_record,
        {"exercise_type": "慢跑", "duration_minutes": 30},
        test_user,
    )
    assert created["status"] == "created"
    assert created["met"] == 7.0
    # 消耗 = 7.0 × 65kg（无档案默认体重）× 0.5h = 227.5
    assert created["calories_burned"] == 227.5
    record_id = created["record_id"]

    # 查询：今天的记录里能查到
    got = _invoke(get_exercise_records, {}, test_user)
    assert any(r["id"] == record_id for r in got["records"])

    # 删除
    deleted = _invoke(delete_exercise_record, {"record_id": record_id}, test_user)
    assert deleted["status"] == "deleted"
    got = _invoke(get_exercise_records, {}, test_user)
    assert all(r["id"] != record_id for r in got["records"])


def test_create_with_unknown_exercise_returns_hint(test_user):
    """MET 表未收录：不落库，返回提示让 LLM 估算 met 重试。"""
    result = _invoke(
        create_exercise_record,
        {"exercise_type": "不存在的运动", "duration_minutes": 20},
        test_user,
    )
    assert result["status"] == "met_not_found"
    assert "met" in result["hint"]

    # 按提示带上估算 met 重试 → 落库成功
    retry = _invoke(
        create_exercise_record,
        {"exercise_type": "不存在的运动", "duration_minutes": 20, "met": 5.0},
        test_user,
    )
    assert retry["status"] == "created"
    assert retry["met"] == 5.0
    # 清理（fixture 只删用户，级联会带走记录，但显式删一遍验证 delete 分支）
    _invoke(delete_exercise_record, {"record_id": retry["record_id"]}, test_user)


def test_delete_other_users_record_fails(test_user):
    """归属校验：删别人的记录应返回 not_found（不越权）。"""
    other_db = SessionLocal()
    other = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    other_db.add(other)
    other_db.commit()
    try:
        created = _invoke(
            create_exercise_record,
            {"exercise_type": "游泳", "duration_minutes": 40},
            other.id,
        )
        # test_user 试图删 other 的记录
        result = _invoke(
            delete_exercise_record, {"record_id": created["record_id"]}, test_user
        )
        assert result["status"] == "not_found"
    finally:
        other_db.delete(other)
        other_db.commit()
        other_db.close()
