"""
记忆管理（会话摘要压缩）测试 —— 不依赖真实 LLM。

分层：
1. 节点级（注入桩 summarizer）：超阈值 → summary 写入 + messages 裁剪；
   未超阈值 → no-op 且不触发 LLM；
2. 图级：RemoveMessage 经真实 add_messages 通道把 messages 真正瘦身；
3. supervisor 注入：summary 以系统消息进入路由决策输入。
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agents.graph import build_graph
from app.agents.memory import KEEP_TAIL, MAX_MESSAGES, make_summarize_node
from app.agents.state import AgentState
from app.agents.supervisor import make_supervisor_node


class _StubSummarizer:
    """伪摘要器：记录调用次数，返回固定摘要。"""

    def __init__(self, text: str = "摘要：用户记录了多次饮食"):
        self.text = text
        self.calls = 0

    def invoke(self, msgs):
        self.calls += 1
        return AIMessage(content=self.text)


def _msgs(n: int) -> list:
    return [HumanMessage(content=f"m{i}", id=f"id-{i}") for i in range(n)]


def test_below_threshold_is_noop():
    stub = _StubSummarizer()
    node = make_summarize_node(stub)
    out = node({"messages": _msgs(MAX_MESSAGES), "summary": ""})
    assert out == {}
    assert stub.calls == 0


def test_above_threshold_summarizes_and_trims():
    stub = _StubSummarizer("折叠后的摘要")
    node = make_summarize_node(stub)
    out = node({"messages": _msgs(MAX_MESSAGES + 5), "summary": ""})
    assert out["summary"] == "折叠后的摘要"
    # 只删旧消息：数量 = 超出阈值的部分 = 总数 - KEEP_TAIL
    assert len(out["messages"]) == (MAX_MESSAGES + 5) - KEEP_TAIL
    assert stub.calls == 1


def test_removemessage_trims_channel_in_real_graph():
    """真实 StateGraph + add_messages：RemoveMessage 真能把通道瘦身。"""
    g = StateGraph(AgentState)
    g.add_node("summarize", make_summarize_node(_StubSummarizer("折叠摘要")))
    g.add_edge(START, "summarize")
    g.add_edge("summarize", END)
    app = g.compile()
    out = app.invoke(
        {"messages": [HumanMessage(content=f"m{i}") for i in range(MAX_MESSAGES + 5)]}
    )
    assert len(out["messages"]) == KEEP_TAIL
    assert out["summary"] == "折叠摘要"


def test_supervisor_injects_summary():
    captured = {}

    class _StubRouter:
        def invoke(self, msgs):
            captured["msgs"] = msgs

            class _D:
                next_agent = "FINISH"
                task = "done"

            return _D()

    node = make_supervisor_node(router=_StubRouter())
    node(
        {
            "messages": [HumanMessage(content="今天吃了啥")],
            "summary": "用户处于减脂期，昨天记录了午餐牛肉面",
            "hop_count": 0,
            "agent_trace": [],
        }
    )
    assert any(
        isinstance(m, tuple) and m[0] == "system" and "历史对话摘要" in m[1]
        for m in captured["msgs"]
    )


def test_build_graph_compacts_and_supervisor_sees_summary():
    """整图接线：turn_reset → summarize → supervisor，摘要裁剪并流入 supervisor。"""
    seen = []

    def _finish_supervisor(state) -> Command:
        seen.append(state.get("summary"))
        return Command(
            goto=END, update={"next_agent": "FINISH", "task": "done", "hop_count": 0}
        )

    graph = build_graph(
        checkpointer=MemorySaver(),
        supervisor_node=_finish_supervisor,
        summarize_node=make_summarize_node(_StubSummarizer("折叠摘要")),
    )
    cfg = {"configurable": {"thread_id": "t1", "user_id": 1}}
    graph.invoke(
        {
            "messages": [HumanMessage(content=f"m{i}") for i in range(MAX_MESSAGES + 5)],
            "user_id": "1",
        },
        cfg,
    )
    final = graph.get_state(cfg).values
    assert len(final["messages"]) == KEEP_TAIL
    assert final["summary"] == "折叠摘要"
    assert seen == ["折叠摘要"]