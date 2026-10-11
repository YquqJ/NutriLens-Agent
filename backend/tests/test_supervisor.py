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
from pydantic import ValidationError

from app.agents.supervisor import (
    MAX_HOPS,
    PlannedTask,
    RouteDecision,
    TaskPlanDecision,
    make_supervisor_node,
)
from app.agents.graph import _turn_reset
from app.core.config import settings


def _stub_router(decision: RouteDecision):
    """伪造 router：无论输入，永远返回给定决策。"""
    return RunnableLambda(lambda _: decision)


class _CountingPlanner:
    """测试一次性任务规划只调用一次，并记录每次输入。"""

    def __init__(self, decision: TaskPlanDecision):
        self.decision = decision
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return self.decision


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
    assert cmd.update["finish_reason"] is None
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
    assert cmd.update["finish_reason"] == "route_limit"
    # 强制结束时 hop_count 不再累加（保持原值，标识已终止）
    assert cmd.update["hop_count"] == MAX_HOPS


def test_allows_fourth_worker_route_before_guard():
    """MAX_HOPS=4 时，第四次路由仍可派发 Worker。"""
    supervisor = make_supervisor_node(
        _stub_router(RouteDecision(next_agent="plan_agent", task="生成计划"))
    )
    cmd = supervisor(
        {
            "messages": [HumanMessage("还需要生成计划")],
            "hop_count": 3,
            "agent_trace": [
                "supervisor→diet_agent",
                "supervisor→exercise_agent",
                "supervisor→qa_agent",
            ],
        }
    )
    assert cmd.goto == "plan_agent"
    assert cmd.update["hop_count"] == 4


def test_plans_composite_request_once_then_dispatches_serially():
    """首次路由生成完整计划，后续只推进游标，不重复调用规划器。"""
    planner = _CountingPlanner(
        TaskPlanDecision(
            tasks=[
                PlannedTask(
                    next_agent="diet_agent", task="记录今天早餐：鸡蛋和包子"
                ),
                PlannedTask(
                    next_agent="exercise_agent", task="记录今天跑步 30 分钟"
                ),
            ],
            finish_reason=None,
        )
    )
    supervisor = make_supervisor_node(planner)
    base_state = {"messages": [HumanMessage("记录早餐并记录跑步")], "hop_count": 0}

    first = supervisor(base_state)
    assert planner.calls == 1
    assert first.goto == "diet_agent"
    assert first.update["task"] == "记录今天早餐：鸡蛋和包子"
    assert first.update["task_index"] == 1
    assert first.update["task_plan"] == [
        {"next_agent": "diet_agent", "task": "记录今天早餐：鸡蛋和包子"},
        {"next_agent": "exercise_agent", "task": "记录今天跑步 30 分钟"},
    ]

    second = supervisor(
        {
            **base_state,
            **first.update,
            "hop_count": 1,
            "agent_trace": ["supervisor→diet_agent"],
        }
    )
    assert planner.calls == 1
    assert second.goto == "exercise_agent"
    assert second.update["task"] == "记录今天跑步 30 分钟"
    assert second.update["task_index"] == 2

    finished = supervisor(
        {
            **base_state,
            **first.update,
            **second.update,
            "hop_count": 2,
            "agent_trace": [
                "supervisor→diet_agent",
                "supervisor→exercise_agent",
            ],
        }
    )
    assert planner.calls == 1
    assert finished.goto == END
    assert finished.update["next_agent"] == "FINISH"
    assert finished.update["finish_reason"] == "completed"


@pytest.mark.parametrize(
    "reason",
    ["out_of_scope", "small_talk", "unclear", "no_action"],
)
def test_empty_task_plan_preserves_structured_finish_reason(reason):
    planner = _CountingPlanner(TaskPlanDecision(tasks=[], finish_reason=reason))
    supervisor = make_supervisor_node(planner)

    cmd = supervisor({"messages": [HumanMessage("随便问个无关问题")], "hop_count": 0})

    assert cmd.goto == END
    assert cmd.update["next_agent"] == "FINISH"
    assert cmd.update["finish_reason"] == reason


def test_empty_task_plan_with_null_reason_falls_back_to_unclear():
    planner = _CountingPlanner(TaskPlanDecision(tasks=[], finish_reason=None))

    cmd = make_supervisor_node(planner)(
        {"messages": [HumanMessage("帮我看看这个")], "hop_count": 0}
    )

    assert cmd.goto == END
    assert cmd.update["finish_reason"] == "unclear"


def test_task_plan_requires_explicit_finish_reason():
    """结构化规划结果不能省略结束原因字段。"""
    with pytest.raises(ValidationError):
        TaskPlanDecision(tasks=[])


def test_merges_non_contiguous_tasks_for_same_worker_without_dropping_them():
    """同一 Worker 的非连续子任务也应合并，而不是静默丢弃。"""
    planner = _CountingPlanner(
        TaskPlanDecision(
            tasks=[
                PlannedTask(next_agent="diet_agent", task="记录早餐：鸡蛋"),
                PlannedTask(next_agent="exercise_agent", task="记录跑步 30 分钟"),
                PlannedTask(next_agent="diet_agent", task="记录午餐：牛肉面"),
            ],
            finish_reason=None,
        )
    )
    cmd = make_supervisor_node(planner)(
        {"messages": [HumanMessage("记录早餐、跑步和午餐")], "hop_count": 0}
    )
    assert cmd.update["task_plan"] == [
        {"next_agent": "diet_agent", "task": "记录早餐：鸡蛋；记录午餐：牛肉面"},
        {"next_agent": "exercise_agent", "task": "记录跑步 30 分钟"},
    ]


def test_turn_reset_clears_previous_task_plan():
    """新用户轮次清空旧计划；HITL resume 不经过该入口节点。"""
    reset = _turn_reset(
        {
            "task_plan": [{"next_agent": "diet_agent", "task": "旧任务"}],
            "task_index": 1,
            "plan_initialized": True,
            "hop_count": 4,
            "finish_reason": "out_of_scope",
        }
    )
    assert reset["task_plan"] is None
    assert reset["task_index"] == 0
    assert reset["plan_initialized"] is False
    assert reset["hop_count"] == 0
    assert reset["finish_reason"] is None


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
