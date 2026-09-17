"""
Supervisor 路由节点测试。

分层策略：
1. 桩路由（RunnableLambda 伪造固定决策）—— 测试节点自身逻辑：
   跳转指令、状态更新、hop_count 累加、防死循环强制结束；
2. 真实 LLM 测试 —— 仅在配置了 DASHSCOPE_API_KEY 时运行（联调用），
   验证 qwen-plus 的路由质量与指代消解改写。
"""

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END

from app.agents.supervisor import (
    MAX_HOPS,
    RouteDecision,
    make_supervisor_node,
)
from app.core.config import settings


def _stub_router(decision: RouteDecision):
    """伪造 router：无论输入，永远返回给定决策。"""
    return RunnableLambda(lambda _: decision)


def test_routes_to_agent_with_rewritten_task():
    """正常路由：goto 正确、task 透传、hop_count 累加、trace 记录。"""
    decision = RouteDecision(
        next_agent="diet_agent", task="记录今日午餐：牛肉面一碗"
    )
    supervisor = make_supervisor_node(_stub_router(decision))

    cmd = supervisor({"messages": [HumanMessage("我午饭吃了一碗牛肉面")], "hop_count": 0})

    assert cmd.goto == "diet_agent"
    assert cmd.update["next_agent"] == "diet_agent"
    assert cmd.update["task"] == "记录今日午餐：牛肉面一碗"
    assert cmd.update["hop_count"] == 1
    assert cmd.update["agent_trace"] == ["supervisor→diet_agent"]


def test_routes_to_finish():
    """路由到 FINISH：goto 跳到 END（图的终点）。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="FINISH", task="已完成"))
    )
    cmd = supervisor({"messages": [HumanMessage("你好")], "hop_count": 0})
    assert cmd.goto == END
    assert cmd.update["next_agent"] == "FINISH"


def test_hop_guard_forces_end():
    """防死循环：达到 MAX_HOPS 后无视路由决策，强制结束。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="diet_agent", task="还想再记一笔"))
    )
    cmd = supervisor(
        {"messages": [HumanMessage("再记一笔")], "hop_count": MAX_HOPS}
    )
    assert cmd.goto == END
    assert cmd.update["next_agent"] == "FINISH"
    # 强制结束时 hop_count 不再累加（保持原值，标识已终止）
    assert cmd.update["hop_count"] == MAX_HOPS


def test_agent_trace_accumulates():
    """trace 是追加不是覆盖：第二轮路由保留第一轮记录。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="qa_agent", task="回答问题"))
    )
    cmd = supervisor(
        {
            "messages": [HumanMessage("蛋白质吃多少")],
            "hop_count": 1,
            "agent_trace": ["supervisor→diet_agent"],
        }
    )
    assert cmd.update["agent_trace"] == [
        "supervisor→diet_agent",
        "supervisor→qa_agent",
    ]


def test_blocks_rerouting_same_agent_consecutively():
    """硬兜底：同一轮内 supervisor 不能把同一个 agent 连续路由两次。

    LLM 未识别出"已答完"时会把刚跑完的 agent 再派一遍（qa_agent 被
    连续路由两次 → 流里出现两段重复回答），代码层在此强制 FINISH。
    """
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="qa_agent", task="再给点建议"))
    )
    cmd = supervisor(
        {
            "messages": [HumanMessage("建议我之后怎么吃")],
            "hop_count": 1,
            "agent_trace": ["supervisor→qa_agent"],
        }
    )
    assert cmd.goto == END
    assert cmd.update["next_agent"] == "FINISH"


def test_allows_routing_to_different_agent():
    """硬兜底不误伤跨 agent 接力：上一个 agent 是 diet_agent，本次派 plan_agent 应放行。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="plan_agent", task="出个减脂计划"))
    )
    cmd = supervisor(
        {
            "messages": [HumanMessage("出个减脂计划")],
            "hop_count": 1,
            "agent_trace": ["supervisor→diet_agent"],
        }
    )
    assert cmd.goto == "plan_agent"


def test_marks_a_plan_generation_turn_for_result_persistence():
    """计划生成标记不能依赖收尾 supervisor 的 task 文案。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="plan_agent", task="生成一周饮食与运动计划"))
    )
    cmd = supervisor(
        {"messages": [HumanMessage("给我做一周计划")], "hop_count": 0}
    )
    assert cmd.update["plan_requested"] is True


# ======================================================================
# 真实 LLM 联调（需要 DASHSCOPE_API_KEY，未配置自动跳过）
# ======================================================================
@pytest.mark.skipif(
    not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY"
)
class TestRealLLMRouting:
    def test_diet_message_routes_to_diet_agent(self):
        """典型饮食意图 → diet_agent，且 task 是改写后的独立指令。"""
        supervisor = make_supervisor_node()
        cmd = supervisor(
            {"messages": [HumanMessage("我午饭吃了一碗牛肉面")], "hop_count": 0}
        )
        assert cmd.goto == "diet_agent"
        # 指代消解的最低要求：改写后的 task 里不该只剩代词
        assert len(cmd.update["task"]) > 5

    def test_greeting_routes_to_finish(self):
        """寒暄/无任务 → FINISH，不浪费 worker 调用。"""
        supervisor = make_supervisor_node()
        cmd = supervisor({"messages": [HumanMessage("你好呀")], "hop_count": 0})
        assert cmd.goto == END

    def test_coreference_rewrite(self):
        """指代消解：结合历史把'它'改写成具体内容。"""
        from langchain_core.messages import AIMessage

        supervisor = make_supervisor_node()
        cmd = supervisor(
            {
                "messages": [
                    HumanMessage("我早上跑了个五公里"),
                    AIMessage("已记录晨跑 5 公里"),
                    HumanMessage("那这个消耗了多少卡？"),
                ],
                "hop_count": 0,
            }
        )
        assert cmd.goto == "exercise_agent"
        # 改写后的 task 不应再含"它/这个"等悬空指代
        assert "它" not in cmd.update["task"]
