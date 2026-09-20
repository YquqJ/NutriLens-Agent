"""
diet_agent 端到端测试（真实 LLM + 真实 DB）。

验证 SPEC M3.4 验收标准：文字"我午饭吃了一碗牛肉面"全流程落库，
含 HITL 完整闭环：
    文本 → 路由到饮食工具链 → search_food → create_diet_record
    → interrupt 挂起 → 模拟用户编辑克数确认 → 落库 → 汇报

这是整个项目第一次把 LLM、工具、数据库、LangGraph interrupt
串成一条链 —— 挂起/恢复的往返靠 MemorySaver checkpoint 驱动。
"""

import uuid
from datetime import date

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.diet_agent import DIET_TOOLS, _diet_prompt, make_diet_agent
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal
from app.services import diet as diet_service


@pytest.fixture
def test_user():
    db = SessionLocal()
    user = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    user_id = user.id
    yield user_id
    # bulk delete 走 DB 外键级联，清掉饮食记录
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    db.close()


# ---- 纯函数单元测试（不依赖 LLM/DB）----
def test_diet_prompt_does_not_retry_image_analysis_when_status_is_missing():
    """图片分析只属于前置节点；worker 不应获得 URL 后自行二次识图。"""
    state = {
        "messages": [HumanMessage("这是我昨天吃的午饭")],
        "task": "记录昨日午餐",
        "image_url": "https://example.com/food.jpg",
    }
    system = _diet_prompt(state)[0].content
    assert "https://example.com/food.jpg" not in system
    assert "图片分析状态缺失" in system
    assert "analyze_food_image" not in [tool.name for tool in DIET_TOOLS]


def test_diet_prompt_omits_image_when_absent():
    """无图时不应注入图片 URL。"""
    state = {"messages": [HumanMessage("我午饭吃了一碗牛肉面")], "task": "记录午餐"}
    system = _diet_prompt(state)[0].content
    assert "https://example.com/food.jpg" not in system


def test_diet_prompt_injects_today_date():
    """worker 提示词必须带真实日期，否则模型凭记忆臆测"今天"（曾固答 2024-06-13）。"""
    state = {"messages": [HumanMessage("我今天热量缺口多少")], "task": "查今日热量缺口"}
    system = _diet_prompt(state)[0].content
    assert date.today().isoformat() in system


def test_diet_prompt_replaces_mixed_user_request_with_scoped_task():
    """饮食 worker 不能因看到原始复合请求而尝试调用运动 agent。"""
    state = {
        "messages": [HumanMessage("昨天我吃了方便面，又跑了半小时")],
        "task": "记录 2026-09-19 的晚餐：方便面一份",
    }

    messages = _diet_prompt(state)

    assert messages[1].content == "记录 2026-09-19 的晚餐：方便面一份"
    assert "跑了半小时" not in messages[1].content


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_diet_agent_full_flow_with_hitl(test_user):
    agent = make_diet_agent(checkpointer=MemorySaver())
    # 与生产一致的上下文注入：thread_id 供 checkpoint，user_id 供工具层
    cfg = {"configurable": {"thread_id": f"t-diet-{uuid.uuid4().hex[:8]}", "user_id": test_user}}

    # ---- 1. 首轮：Agent 执行到 create_diet_record 时挂起 ----
    result = agent.invoke(
        {
            "messages": [HumanMessage("我午饭吃了一碗牛肉面")],
            "task": "记录今日午餐：牛肉面一碗",
            "hop_count": 1,
        },
        cfg,
    )
    assert "__interrupt__" in result, "应在写库前 interrupt 挂起"
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "diet_confirm"
    assert payload["meal_type"] == "lunch"
    assert len(payload["items"]) >= 1
    # 模型可能拆成多个条目（面条/牛肉/青菜），任一条目命中即可
    assert any("牛肉" in it["food_name"] or "面" in it["food_name"] for it in payload["items"])

    # ---- 2. 模拟前端确认卡片：编辑克数后提交 ----
    items = payload["items"]
    items[0]["grams"] = 500.0
    resumed = agent.invoke(Command(resume={"items": items}), cfg)

    # ---- 3. Agent 汇报了结果 ----
    final = resumed["messages"][-1].content
    assert final, "Agent 应有最终回复"

    # ---- 4. 落库断言：今天、午餐、克数为用户编辑值 ----
    db = SessionLocal()
    try:
        recs = diet_service.get_diet_records(db, test_user, date.today())
        assert recs, "饮食记录未落库"
        lunches = [r for r in recs if r["meal_type"] == "lunch"]
        assert lunches, "餐次应为 lunch"
        # resume 后 Agent 不得重复写库（二次调用 create_diet_record 是回归信号）
        assert len(lunches) == 1, f"午餐记录应恰好 1 条，实际 {len(lunches)} 条（疑似重复落库）"
        all_items = [it for r in lunches for it in r["items"]]
        edited = [it for it in all_items if it["grams"] == 500.0]
        assert edited, "应存在克数为用户编辑值(500)的条目"
        assert all(it["calories"] > 0 for it in all_items)
        # 置信度必须是三档之一：M3.8 食物库 seed 后"牛肉面"能查库命中
        # （db_exact/db_fuzzy），此前库为空只能 llm_estimate
        assert all(it["confidence"] in ("db_exact", "db_fuzzy", "llm_estimate") for it in all_items)
    finally:
        db.close()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_diet_agent_hitl_cancel(test_user):
    """用户点取消（resume=False）：不落库，Agent 告知已取消。"""
    agent = make_diet_agent(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": f"t-diet-{uuid.uuid4().hex[:8]}", "user_id": test_user}}

    result = agent.invoke(
        {
            "messages": [HumanMessage("晚饭吃了两个包子")],
            "task": "记录今日晚餐：包子两个",
            "hop_count": 1,
        },
        cfg,
    )
    assert "__interrupt__" in result
    resumed = agent.invoke(Command(resume=False), cfg)
    assert resumed["messages"][-1].content

    db = SessionLocal()
    try:
        recs = diet_service.get_diet_records(db, test_user, date.today())
        dinners = [r for r in recs if r["meal_type"] == "dinner"]
        assert not dinners, "取消后不应有晚餐记录"
    finally:
        db.close()
