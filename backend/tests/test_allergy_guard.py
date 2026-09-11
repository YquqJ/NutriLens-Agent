"""饮食记录过敏风险防线的确定性测试。"""

import uuid
from datetime import date

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.agents.diet_agent import _diet_prompt
from app.core.security import hash_password
from app.db.models import User, UserProfile
from app.db.session import SessionLocal
from app.services import diet as diet_service
from app.services.allergy import assess_food_allergy_risks


def test_seafood_allergy_matches_food_and_returns_explainable_risk():
    risks = assess_food_allergy_risks("对海鲜过敏", ["清蒸虾", "米饭"])

    assert len(risks) == 1
    assert risks[0]["allergen"] == "海鲜"
    assert risks[0]["foods"] == ["清蒸虾"]
    assert "清蒸虾" in risks[0]["message"]


def test_plain_preference_does_not_become_allergy_warning():
    assert assess_food_allergy_risks("不喜欢海鲜", ["虾"]) == []


def test_non_allergy_profile_note_does_not_block_recording():
    assert assess_food_allergy_risks("喜欢海鲜", ["虾"]) == []


def test_diet_prompt_only_exposes_current_turn_to_worker():
    state = {
        "messages": [
            HumanMessage("完善我的档案"),
            ToolMessage(content="对海鲜过敏", tool_call_id="profile-1"),
            HumanMessage("我午饭吃了虾，请帮我记录"),
        ],
        "task": "记录今日午餐：虾",
    }

    prompt = _diet_prompt(state)
    assert len(prompt) == 2
    assert prompt[1].content == "我午饭吃了虾，请帮我记录"


@pytest.fixture
def allergy_user():
    db = SessionLocal()
    user = User(
        username=f"allergy_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("x"),
    )
    db.add(user)
    db.commit()
    db.add(UserProfile(user_id=user.id, goal_note="对海鲜过敏"))
    db.commit()
    user_id = user.id
    db.close()
    yield user_id
    db = SessionLocal()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    db.close()


def _shrimp_item() -> dict:
    return {
        "food_name": "虾",
        "grams": 100,
        "calories": 100,
        "protein": 20,
        "fat": 1,
        "carbs": 1,
    }


def test_service_blocks_agent_write_without_explicit_ack(allergy_user):
    db = SessionLocal()
    try:
        with pytest.raises(diet_service.AllergyConfirmationRequired):
            diet_service.create_diet_record(
                db,
                user_id=allergy_user,
                meal_type="lunch",
                items=[_shrimp_item()],
                source="agent",
            )
        assert diet_service.get_diet_records(db, allergy_user, date.today()) == []
    finally:
        db.close()


def test_service_allows_agent_write_after_explicit_ack(allergy_user):
    db = SessionLocal()
    try:
        result = diet_service.create_diet_record(
            db,
            user_id=allergy_user,
            meal_type="lunch",
            items=[_shrimp_item()],
            source="agent",
            allergy_acknowledged=True,
        )
        assert result["record_id"]
    finally:
        db.close()
