"""
exercise_agent / plan_agent 端到端测试（真实 LLM + 真实 DB）。

- exercise_agent：文字报运动 → 直接落库（无 HITL），MET 表自动查。
- plan_agent：已有档案 → 读档出计划（数字来自档案而非 LLM 计算）。
"""

import uuid
from datetime import date

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.exercise_agent import _exercise_prompt, make_exercise_agent
from app.agents.plan_agent import make_plan_agent
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal
from app.services import exercise as exercise_service
from app.services import profile as profile_service


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


def _cfg(test_user: int) -> dict:
    return {
        "configurable": {
            "thread_id": f"t-{uuid.uuid4().hex[:8]}",
            "user_id": test_user,
        }
    }


def test_exercise_prompt_replaces_mixed_user_request_with_scoped_task():
    """运动 worker 只执行已分配的运动子任务。"""
    state = {
        "messages": [HumanMessage("昨天我吃了方便面，又跑了半小时")],
        "task": "记录 2026-09-19 的跑步，时长 30 分钟",
    }

    messages = _exercise_prompt(state)

    assert messages[1].content == "记录 2026-09-19 的跑步，时长 30 分钟"
    assert "方便面" not in messages[1].content


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_exercise_agent_records_run(test_user):
    """'我下午慢跑了半小时' → 落库一条运动记录（无 interrupt）。"""
    agent = make_exercise_agent(checkpointer=MemorySaver())
    result = agent.invoke(
        {
            "messages": [HumanMessage("我下午慢跑了半小时")],
            "task": "记录今天下午的慢跑，时长30分钟",
            "hop_count": 1,
        },
        _cfg(test_user),
    )
    # 运动写库不做 HITL，全程不应挂起
    assert "__interrupt__" not in result
    assert result["messages"][-1].content

    db = SessionLocal()
    try:
        recs = exercise_service.get_exercise_records(db, test_user, date.today())
        assert recs, "运动记录未落库"
        rec = recs[-1]
        assert rec["duration_minutes"] == 30
        assert rec["met"] > 0
        assert rec["calories_burned"] > 0
    finally:
        db.close()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_plan_agent_generates_plan_from_profile(test_user):
    """已有档案的用户要减脂计划 → 先读档（get_profile），计划引用档案数字。"""
    # 先铺档案：男/30/175/70/中度/减脂 → bmr=1648.8 tdee=2555.6 target=2055.6
    db = SessionLocal()
    try:
        profile_service.apply_profile_update(
            db,
            test_user,
            {
                "gender": "male",
                "age": 30,
                "height_cm": 175,
                "weight_kg": 70,
                "activity_level": "moderate",
                "goal": "lose",
                "goal_note": "对花生过敏",
            },
        )
    finally:
        db.close()

    agent = make_plan_agent(checkpointer=MemorySaver())
    result = agent.invoke(
        {
            "messages": [HumanMessage("帮我出一周的减脂饮食计划")],
            "task": "为用户生成一周减脂饮食计划（注意其档案中的过敏信息）",
            "hop_count": 1,
        },
        _cfg(test_user),
    )

    # 1. 必须先读了档案（工具调用轨迹中出现 get_profile）
    tool_names = [
        tc["name"] for m in result["messages"] for tc in getattr(m, "tool_calls", None) or []
    ]
    assert "get_profile" in tool_names, "出计划前应先读档案"

    # 2. 计划内容引用了档案中的计算数字（而非自己编算）
    #    容差设计：模型可能四舍五入（2055.6→2056）或加千分位（2,055），
    #    去掉逗号后匹配"精确值或 ±1 取整"的数字序列
    content = result["messages"][-1].content
    assert content
    digits = content.replace(",", "").replace("，", "")
    profile_numbers = ["2055", "2056", "2555", "2556", "1648", "1649"]
    assert any(n in digits for n in profile_numbers), (
        "计划应引用档案中的 BMR/TDEE/热量目标数字"
    )

    # 3. 过敏偏好生效（宽松断言：提及花生或过敏）
    assert "花生" in content or "过敏" in content
