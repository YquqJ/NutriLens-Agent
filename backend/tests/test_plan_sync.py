"""当前计划存储与读取的回归测试。"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.main import app
from app.services import plan as plan_service


@pytest.fixture
def test_user():
    db = SessionLocal()
    user = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    user_id = user.id
    yield user_id
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    db.close()


def test_saving_a_new_plan_replaces_the_current_plan(test_user):
    """同一用户的新计划应替换旧计划，页面只读取一份当前计划。"""
    db = SessionLocal()
    try:
        db.add_all(
            [
                Conversation(id="conversation-a", user_id=test_user),
                Conversation(id="conversation-b", user_id=test_user),
            ]
        )
        db.commit()
        first = plan_service.save_active_plan(
            db,
            user_id=test_user,
            conversation_id="conversation-a",
            content="每日 1800 千卡\n运动：每周慢跑 3 次",
        )
        second = plan_service.save_active_plan(
            db,
            user_id=test_user,
            conversation_id="conversation-b",
            content="每日 1900 千卡\n运动：每周力量训练 3 次",
        )

        db.refresh(first)
        assert first.is_active is False
        assert second.is_active is True

        current = plan_service.get_active_plan(db, test_user)
        assert current is not None
        assert current.id == second.id
        assert current.conversation_id == "conversation-b"
        assert "力量训练" in current.content
    finally:
        db.close()


def test_current_plan_api_returns_the_saved_plan():
    """计划页读取的 API 只返回当前用户自己的最新计划。"""
    client = TestClient(app)
    username = f"t_{uuid.uuid4().hex[:8]}"
    registered = client.post(
        "/api/auth/register", json={"username": username, "password": "test123456"}
    )
    assert registered.status_code == 201

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        plan_service.save_active_plan(
            db, user_id=user.id, content="减脂计划\n饮食：优先蛋白质\n运动：每周跑步三次"
        )
    finally:
        db.close()

    response = client.get(
        "/api/plans/current",
        headers={"Authorization": f"Bearer {registered.json()['token']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "减脂计划"
    assert "每周跑步三次" in body["content"]

    db = SessionLocal()
    try:
        db.query(User).filter(User.username == username).delete()
        db.commit()
    finally:
        db.close()
