"""
Supervisor 图组装测试（M3.6）。

分层策略（与 test_supervisor.py 一致）：
1. 逻辑测试（无 LLM）：桩 supervisor 直接 FINISH，验证星型接线与
   checkpoint 的基本读写（MemorySaver）；
2. E2E（真实 LLM + PostgresSaver + 真实 DB）：
   - SPEC 验收标准：同一 thread_id 二次 invoke 能续上历史；
   - HITL interrupt 挂起 → Command(resume) 恢复 → 落库
     （回归 NutriLensPostgresSaver 的 pending_sends 编解码补丁：
     补丁坏掉时 resume 会因 PUSH 任务丢失而抛 INVALID_CHAT_HISTORY）。
"""

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END
from langgraph.types import Command

from app.agents.graph import build_graph, get_checkpointer
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import DietRecord, User
from app.db.session import SessionLocal


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


def _finish_supervisor(state: dict) -> Command:
    """桩 supervisor：不做路由决策，无条件直接结束。"""
    return Command(
        goto=END,
        update={
            "next_agent": "FINISH",
            "task": "桩：直接结束",
            "hop_count": state.get("hop_count", 0) + 1,
        },
    )


def test_graph_wiring_and_checkpoint_roundtrip():
    """桩 FINISH：图可编译运行；同 thread_id 二次 invoke，messages 由 checkpoint 续上。"""
    graph = build_graph(checkpointer=MemorySaver(), supervisor_node=_finish_supervisor)
    cfg = {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}

    r1 = graph.invoke({"messages": [HumanMessage("你好")], "user_id": "u1"}, cfg)
    assert r1["next_agent"] == "FINISH"

    # 第二次 invoke 未传第一条消息，但 checkpoint 里应有它（历史续上）
    r2 = graph.invoke({"messages": [HumanMessage("还在吗")], "user_id": "u1"}, cfg)
    human_texts = [m.content for m in r2["messages"]]
    assert "你好" in human_texts
    assert "还在吗" in human_texts


# ======================================================================
# E2E：真实 LLM + PostgresSaver（需要 DASHSCOPE_API_KEY 与本地 PG，未配置自动跳过）
# ======================================================================
@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_same_thread_second_invoke_continues_history(test_user):
    """验收：同一 thread_id 二次 invoke 续上历史（PostgresSaver 真实持久化）。"""
    graph = build_graph(checkpointer=get_checkpointer())
    cfg = {
        "configurable": {
            "thread_id": f"t-{uuid.uuid4().hex[:8]}",
            "user_id": test_user,
        }
    }

    # 第一轮：报一次运动 → supervisor 路由 exercise_agent → 落库 → 回到
    # supervisor → FINISH（agent_trace 应记录完整流转）
    r1 = graph.invoke(
        {"messages": [HumanMessage("我下午慢跑了半小时")], "user_id": test_user},
        cfg,
    )
    assert r1["agent_trace"], "agent_trace 未记录流转"
    assert any("exercise_agent" in t for t in r1["agent_trace"])

    # 第二轮：追问总量。这一问只有结合历史才路由正确
    # （"总共"指向第一轮的慢跑记录，而非凭空的知识问答）
    r2 = graph.invoke(
        {"messages": [HumanMessage("我今天总共运动了多久？")], "user_id": test_user},
        cfg,
    )

    # 1. 历史续上：第一轮的用户消息仍在 state（checkpoint 跨 invoke 生效）
    texts = [m.content for m in r2["messages"]]
    assert any("慢跑" in t for t in texts)

    # 2. 追问得到基于记录的回答：今天总时长 30 分钟
    assert "30" in r2["messages"][-1].content


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_interrupt_resume_through_graph(test_user):
    """全图 HITL：饮食记录 interrupt 挂起 → Command(resume) 确认 → 落库。

    这条链路把 worker 子图的 interrupt 传播到外层图，且恢复依赖
    checkpoint 里的 pending_sends（Send 对象）跨进程往返 —— 是
    NutriLensPostgresSaver 补丁的核心回归测试。
    """
    graph = build_graph(checkpointer=get_checkpointer())
    cfg = {
        "configurable": {
            "thread_id": f"t-{uuid.uuid4().hex[:8]}",
            "user_id": test_user,
        }
    }

    r1 = graph.invoke(
        {"messages": [HumanMessage("我午饭吃了一碗牛肉面")], "user_id": test_user},
        cfg,
    )
    assert "__interrupt__" in r1, "饮食写库前应 interrupt 挂起"
    payload = r1["__interrupt__"][0].value
    assert payload["type"] == "diet_confirm"
    assert payload["items"], "确认卡片应携带食物草稿"

    # 模拟前端确认（不改克数）
    resumed = graph.invoke(Command(resume={"items": payload["items"]}), cfg)
    assert resumed["messages"][-1].content

    db = SessionLocal()
    try:
        records = db.query(DietRecord).filter(DietRecord.user_id == test_user).all()
        assert len(records) == 1, "确认后应恰好落一条饮食记录"
        assert records[0].meal_type == "lunch"
    finally:
        db.close()
