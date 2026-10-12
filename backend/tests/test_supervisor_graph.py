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
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from typing_extensions import TypedDict

from app.agents.graph import build_graph, get_checkpointer
from app.agents.worker_result import make_worker_node
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


def test_worker_adapter_classifies_read_only_exception_as_retryable():
    class FailingWorker:
        def invoke(self, _state, config=None):
            raise TimeoutError("temporary read failure")

    node = make_worker_node("qa_agent", FailingWorker())
    result = node({"messages": [HumanMessage("蛋白质怎么吃")]}, {})

    assert result["worker_outcome"]["status"] == "retryable_error"
    assert result["worker_outcome"]["side_effect"] == "none"
    assert result["worker_outcome"]["retryable"] is True


def test_worker_adapter_does_not_mark_write_worker_exception_retryable():
    class FailingWorker:
        def invoke(self, _state, config=None):
            raise TimeoutError("write may have committed")

    node = make_worker_node("exercise_agent", FailingWorker())
    result = node({"messages": [HumanMessage("记录慢跑30分钟")]}, {})

    assert result["worker_outcome"]["status"] == "fatal_error"
    assert result["worker_outcome"]["side_effect"] == "unknown"
    assert result["worker_outcome"]["retryable"] is False


def test_worker_adapter_supports_callable_qa_node_and_tracks_new_messages():
    from langchain_core.messages import ToolMessage

    def failing_qa_node(_state):
        return {
            "messages": [
                ToolMessage(
                    content="temporary retrieval failure",
                    tool_call_id="retrieve-1",
                    name="retrieve_knowledge",
                    status="error",
                ),
                AIMessage(content="暂时无法检索到知识库内容。"),
            ]
        }

    original_messages = [HumanMessage("蛋白质怎么吃")]
    result = make_worker_node("qa_agent", failing_qa_node)(
        {"messages": original_messages}, {}
    )

    assert result["worker_outcome"]["error_code"] == "read_tool_error"
    assert result["worker_outcome"]["retryable"] is True
    assert result["worker_message_start"] == 1
    assert result["worker_message_end"] == 3
    assert result["worker_discarded_ranges"] == [{"start": 1, "end": 3}]


def test_worker_rejects_mismatched_route_before_invoking_business_worker():
    """Worker 准入审核拒绝时，业务 Worker 和其工具均不得执行。"""
    calls = []

    class RejectingGuard:
        def invoke(self, _messages):
            return {
                "approved": False,
                "reason": "BMI 概念解释应由知识问答处理",
                "suggested_agent": "qa_agent",
            }

    def mutating_worker(_state):
        calls.append(True)
        return {"messages": [AIMessage(content="不应执行")]}

    result = make_worker_node(
        "diet_agent", mutating_worker, admission_guard=RejectingGuard()
    )(
        {
            "messages": [HumanMessage("BMI是什么")],
            "task": "记录今天早餐",
        }
    )

    assert calls == []
    assert result["worker_outcome"] == {
        "status": "routing_mismatch",
        "error_code": "routing_mismatch",
        "retryable": False,
        "side_effect": "none",
    }
    assert result["routing_mismatch"] == {
        "attempted_agent": "diet_agent",
        "suggested_agent": "qa_agent",
        "reason": "BMI 概念解释应由知识问答处理",
    }


def test_nested_worker_interrupt_propagates_and_resumes():
    class State(TypedDict):
        messages: list

    child_builder = StateGraph(State)

    def confirm_node(_state):
        value = __import__("langgraph.types", fromlist=["interrupt"]).interrupt(
            {"type": "test_confirm"}
        )
        return {"messages": [AIMessage(content=f"confirmed:{value}")]}

    child_builder.add_node("confirm", confirm_node)
    child_builder.add_edge(START, "confirm")
    child_builder.add_edge("confirm", END)
    child = child_builder.compile()

    parent_builder = StateGraph(State)
    parent_builder.add_node("diet_agent", make_worker_node("diet_agent", child))
    parent_builder.add_edge(START, "diet_agent")
    parent = parent_builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "nested-interrupt"}}

    paused = parent.invoke({"messages": [HumanMessage(content="record food")]}, config)
    assert paused["__interrupt__"][0].value == {"type": "test_confirm"}

    resumed = parent.invoke(Command(resume="yes"), config)
    assert resumed["messages"][-1].content == "confirmed:yes"


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
