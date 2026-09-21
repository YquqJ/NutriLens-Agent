"""Agent 任务评测的离线口径测试。

这些测试不调用模型或数据库，先锁定“任务完成率”和“工具调用准确率”的判定规则；
真实模型批跑只负责产出观测值，不能绕开这层确定性评分。
"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.eval import (
    aggregate_reports,
    build_hitl_resume,
    evaluate_episode,
    extract_turn_tool_calls,
    load_agent_task_cases,
    worker_context_mode_for_evaluation,
)


_BUILTIN_DATASET = Path(__file__).parent / "eval_data" / "agent_tasks_v1.json"


def _case(**overrides) -> dict:
    """构造一条最小任务用例，个别测试可覆盖字段。"""
    case = {
        "id": "diet_record_01",
        "category": "diet_record",
        "input": "午饭吃了一碗牛肉面",
        "expected_agents": ["diet_agent"],
        "required_tools": ["search_food", "create_diet_record"],
        "allowed_tools": ["search_food", "create_diet_record"],
        "forbidden_tools": ["analyze_food_image"],
        "expected_effects": {"diet_record_count": 1, "exercise_record_count": 0},
        "hitl": "confirm",
    }
    case.update(overrides)
    return case


def _observed(**overrides) -> dict:
    """构造一条符合预期的执行观测。"""
    observed = {
        "agent_trace": ["supervisor→diet_agent"],
        "tool_calls": [{"name": "search_food"}, {"name": "create_diet_record"}],
        "effects": {"diet_record_count": 1, "exercise_record_count": 0},
        "hitl": "confirm",
        "error": None,
    }
    observed.update(overrides)
    return observed


def test_load_agent_task_cases_requires_versioned_non_empty_cases(tmp_path):
    """任务集必须带版本号且至少有一条可执行用例。"""
    dataset_path = tmp_path / "agent_tasks.json"
    dataset_path.write_text(
        json.dumps({"schema_version": "agent-tasks-v1", "cases": [_case()]}),
        encoding="utf-8",
    )

    dataset = load_agent_task_cases(dataset_path)

    assert dataset["schema_version"] == "agent-tasks-v1"
    assert dataset["cases"][0]["id"] == "diet_record_01"

    dataset_path.write_text(json.dumps({"schema_version": "agent-tasks-v1", "cases": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="至少包含一条"):
        load_agent_task_cases(dataset_path)


def test_evaluate_episode_marks_full_task_and_tool_set_correct():
    """路由、工具、副作用和确认结果全部命中时，任务与工具两个指标都记成功。"""
    report = evaluate_episode(_case(), _observed())

    assert report["agent_correct"] is True
    assert report["tool_correct"] is True
    assert report["effects_correct"] is True
    assert report["hitl_correct"] is True
    assert report["task_completed"] is True
    assert report["failure_reasons"] == []


def test_evaluate_episode_reports_routing_tool_effect_and_hitl_failures():
    """单次失败必须给出可复盘的原因，不能只留下一个笼统的失败布尔值。"""
    report = evaluate_episode(
        _case(),
        _observed(
            agent_trace=["supervisor→exercise_agent"],
            tool_calls=[{"name": "search_food"}, {"name": "delete_diet_record"}, {"name": "analyze_food_image"}],
            effects={"diet_record_count": 0, "exercise_record_count": 0},
            hitl="cancel",
        ),
    )

    assert report["task_completed"] is False
    assert report["tool_correct"] is False
    assert report["missing_required_tools"] == ["create_diet_record"]
    assert report["unexpected_tools"] == ["delete_diet_record"]
    assert report["forbidden_tool_calls"] == ["analyze_food_image"]
    assert "未路由至预期 agent：diet_agent" in report["failure_reasons"]
    assert "缺少必需工具：create_diet_record" in report["failure_reasons"]
    assert "出现未允许工具：delete_diet_record" in report["failure_reasons"]
    assert "出现禁止工具：analyze_food_image" in report["failure_reasons"]
    assert "数据库副作用不匹配：diet_record_count（期望 1，实际 0）" in report["failure_reasons"]
    assert "HITL 结果不匹配：期望 confirm，实际 cancel" in report["failure_reasons"]


def test_aggregate_reports_calculates_task_tool_and_category_rates():
    """总报告按 episode 计数，避免一个任务多调用工具时虚高准确率。"""
    completed = evaluate_episode(_case(), _observed())
    failed = evaluate_episode(
        _case(id="exercise_record_01", category="exercise_record"),
        _observed(tool_calls=[{"name": "search_food"}]),
    )

    summary = aggregate_reports([completed, failed], dataset_version="agent-tasks-v1")

    assert summary["dataset_version"] == "agent-tasks-v1"
    assert summary["episodes"] == 2
    assert summary["task_completion_rate"] == 0.5
    assert summary["tool_call_accuracy"] == 0.5
    assert summary["categories"]["diet_record"]["task_completion_rate"] == 1.0
    assert summary["categories"]["exercise_record"]["tool_call_accuracy"] == 0.0


def test_build_hitl_resume_matches_frontend_confirm_cancel_and_allergy_payloads():
    """评测恢复值必须复用前端协议，避免测试走一条生产不存在的捷径。"""
    payload = {"items": [{"food_name": "花生", "grams": 30.0}]}

    assert build_hitl_resume("confirm", payload) == {"items": payload["items"]}
    assert build_hitl_resume("cancel", payload) is False
    assert build_hitl_resume("allergy_confirm", payload) == {
        "items": payload["items"],
        "allergy_acknowledged": True,
    }
    with pytest.raises(ValueError, match="不支持"):
        build_hitl_resume("unknown", payload)


def test_builtin_task_dataset_has_20_versioned_cases_and_all_metric_categories():
    """固定任务集覆盖写入、查询删除、混合意图、HITL 与档案计划，不是临时手工样本。"""
    dataset = load_agent_task_cases(_BUILTIN_DATASET)
    categories = {case["category"] for case in dataset["cases"]}

    assert dataset["schema_version"] == "agent-tasks-v1"
    assert len(dataset["cases"]) == 20
    assert {"diet_record", "exercise_record", "mixed_intent", "hitl", "profile_plan"} <= categories


def test_extract_turn_tool_calls_ignores_previous_turn_and_pairs_tool_result():
    """同一 thread 的历史工具调用不得计入本条评测样例。"""
    messages = [
        HumanMessage("上一轮"),
        AIMessage(content="", tool_calls=[{"id": "old", "name": "old_tool", "args": {}}]),
        ToolMessage("old result", tool_call_id="old"),
        HumanMessage("本轮"),
        AIMessage(content="", tool_calls=[{"id": "new", "name": "search_food", "args": {"query": "苹果"}}]),
        ToolMessage("new result", tool_call_id="new"),
    ]

    calls = extract_turn_tool_calls(messages)

    assert calls == [{"name": "search_food", "args": {"query": "苹果"}, "result": "new result"}]


def test_worker_context_mode_for_evaluation_keeps_ablation_names_explicit():
    """评测报告必须区分生产优化模式与历史基线，拒绝不透明的任意开关。"""
    assert worker_context_mode_for_evaluation("optimized_scoped_task") == "scoped_task"
    assert worker_context_mode_for_evaluation("baseline_raw_context") == "raw_message"
    with pytest.raises(ValueError, match="不支持"):
        worker_context_mode_for_evaluation("disable_tool_validation")
