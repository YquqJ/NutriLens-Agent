"""
档案域工具测试 + users API 重构后的回归。

验证点（对应 SPEC M3.2 验收标准）：
1. 工具直调读写 user_profiles（含无档案提示分支）；
2. 部分更新语义：只传体重，其他字段不丢，BMR/TDEE 正确重算；
3. 参数校验：非法枚举值在工具入参层被拦下（Pydantic args schema）；
4. REST 路由改走 service 后行为不变（put 后数值与冒烟手算一致）。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import User, UserProfile
from app.db.session import SessionLocal
from app.main import app
from app.tools.profile import get_profile, update_profile


@pytest.fixture
def test_user():
    """临时用户（无档案）。"""
    db = SessionLocal()
    user = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    user_id = user.id
    yield user_id
    # 先删 profile 再删用户：工具在别的 session 建的 profile 对本 session 不可见，
    # ORM 删用户时会懒加载 relationship 并尝试将外键置 NULL（主键非空 → 报错）；
    # 显式删掉后，用户行由 DB 外键 ON DELETE CASCADE 兜底
    profile = db.get(UserProfile, user_id)
    if profile is not None:
        db.delete(profile)
    db.execute(
        User.__table__.delete().where(User.id == user_id)
    )
    db.commit()
    db.close()


def _invoke(tool, args: dict, user_id: int):
    """按生产路径的调用形态执行工具。"""
    return tool.invoke(args, config={"configurable": {"user_id": user_id}})


def test_get_profile_without_profile(test_user):
    """无档案：返回提示而非报错（LLM 可据此引导用户补信息）。"""
    result = _invoke(get_profile, {}, test_user)
    assert result["found"] is False
    assert "update_profile" in result["hint"]


def test_update_then_get_profile(test_user):
    """工具写入 → 读回：BMR/TDEE 与冒烟手算一致（男/30/175/70/中度/减脂）。"""
    updated = _invoke(
        update_profile,
        {
            "updates": {
                "gender": "male",
                "age": 30,
                "height_cm": 175,
                "weight_kg": 70,
                "activity_level": "moderate",
                "goal": "lose",
                "goal_note": "allergy: peanut",
            }
        },
        test_user,
    )
    assert updated["status"] == "updated"
    p = updated["profile"]
    assert p["bmr"] == 1648.8
    assert p["tdee"] == 2555.6
    assert p["calorie_target"] == 2055.6

    # 读回一致
    got = _invoke(get_profile, {}, test_user)
    assert got["found"] is True
    assert got["profile"]["goal_note"] == "allergy: peanut"


def test_partial_update_keeps_other_fields(test_user):
    """只更新体重：其他字段不丢，BMR 按 75kg 重算。"""
    _invoke(
        update_profile,
        {
            "updates": {
                "gender": "male",
                "age": 30,
                "height_cm": 175,
                "weight_kg": 70,
                "activity_level": "moderate",
                "goal": "lose",
            }
        },
        test_user,
    )
    # 只传体重 75
    result = _invoke(update_profile, {"updates": {"weight_kg": 75}}, test_user)
    p = result["profile"]
    assert p["age"] == 30  # 未提及的字段保留
    assert p["weight_kg"] == 75
    # BMR = 10×75 + 6.25×175 − 5×30 + 5 = 1698.75 → 1698.8
    assert p["bmr"] == 1698.8
    assert p["tdee"] == round(1698.75 * 1.55, 1)  # 2633.1


def test_invalid_enum_rejected_by_args_schema(test_user):
    """非法 gender 在工具入参校验层被拦下，不落库。"""
    with pytest.raises(Exception):  # langchain 包装的 ValidationError
        _invoke(
            update_profile, {"updates": {"gender": "unknown"}}, test_user
        )


def test_rest_put_profile_unchanged_after_refactor(test_user):
    """回归：路由下沉到 service 后，REST 行为与冒烟结果一致。"""
    client = TestClient(app)
    username = f"t_{uuid.uuid4().hex[:8]}"
    reg = client.post(
        "/api/auth/register", json={"username": username, "password": "test123456"}
    )
    assert reg.status_code == 201
    token = reg.json()["token"]

    resp = client.put(
        "/api/users/me/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "gender": "male",
            "age": 30,
            "height_cm": 175,
            "weight_kg": 70,
            "activity_level": "moderate",
            "goal": "lose",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["bmr"], body["tdee"], body["calorie_target"]) == (
        1648.8,
        2555.6,
        2055.6,
    )

    # 清理注册产生的用户（bulk delete 走 DB 外键级联，顺带清掉 profile）
    db = SessionLocal()
    db.query(User).filter(User.username == username).delete()
    db.commit()
    db.close()
