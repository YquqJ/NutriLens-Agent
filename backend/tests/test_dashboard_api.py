import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password
from app.db.models import DietRecord, ExerciseRecord, User, UserProfile
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def dashboard_user():
    db = SessionLocal()
    user = User(username=f"dashboard_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(UserProfile(user_id=user.id, calorie_target=1800))
    db.add_all(
        [
            DietRecord(user_id=user.id, record_date=date(2026, 9, 2), total_calories=600, total_protein=30, total_fat=20, total_carbs=70, meal_type="lunch"),
            DietRecord(user_id=user.id, record_date=date(2026, 9, 2), total_calories=400, total_protein=20, total_fat=10, total_carbs=50, meal_type="dinner"),
            ExerciseRecord(user_id=user.id, record_date=date(2026, 9, 2), exercise_type="跑步", duration_minutes=30, met=8, calories_burned=250),
        ]
    )
    db.commit()
    token = create_access_token(user.id)
    yield {"user_id": user.id, "headers": {"Authorization": f"Bearer {token}"}}
    db.query(DietRecord).filter(DietRecord.user_id == user.id).delete()
    db.query(ExerciseRecord).filter(ExerciseRecord.user_id == user.id).delete()
    db.query(UserProfile).filter(UserProfile.user_id == user.id).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.commit()
    db.close()


def test_monthly_summary_returns_daily_aggregates(dashboard_user):
    response = client.get(
        "/api/dashboard/monthly-summary",
        params={"month": "2026-09"},
        headers=dashboard_user["headers"],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] == "2026-09"
    assert len(payload["days"]) == 30
    assert payload["days"][0]["date"] == "2026-09-01"
    assert payload["days"][-1]["date"] == "2026-09-30"

    day = next(item for item in payload["days"] if item["date"] == "2026-09-02")
    assert day["intake"] == 1000
    assert day["burned"] == 250
    assert day["net"] == 750
    assert day["remaining"] == 1050
    assert day["macros"] == {"protein": 50, "fat": 30, "carbs": 120}
    assert all(item["calorie_target"] == 1800 for item in payload["days"])
