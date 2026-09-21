"""Agent 任务离线评测的确定性评分器。

真实模型运行会有随机性，但指标口径不能随模型输出漂移。本模块只读取版本化
任务集与一次执行的观测值，判定路由、工具集合、数据库副作用和 HITL 是否符合
预期；真实图执行与外部服务调用由后续运行器负责。
"""

import json
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import DietRecord, ExerciseRecord, User, UserProfile
from app.db.session import SessionLocal
from app.services import diet as diet_service
from app.services import exercise as exercise_service
from app.services import profile as profile_service


_EVALUATION_WORKER_CONTEXT_MODES = {
    "optimized_scoped_task": "scoped_task",
    "baseline_raw_context": "raw_message",
}


def worker_context_mode_for_evaluation(evaluation_mode: str) -> str:
    """将可公开说明的评测模式映射为图的 worker 上下文策略。"""
    try:
        return _EVALUATION_WORKER_CONTEXT_MODES[evaluation_mode]
    except KeyError as exc:
        supported = "、".join(_EVALUATION_WORKER_CONTEXT_MODES)
        raise ValueError(
            f"不支持的评测模式：{evaluation_mode}（可选：{supported}）"
        ) from exc


def load_agent_task_cases(path: Path) -> dict[str, Any]:
    """加载并校验最小任务集结构，避免空数据集产生无意义的 100% 指标。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("schema_version"):
        raise ValueError("任务评测集缺少 schema_version")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("任务评测集至少包含一条 cases 用例")

    seen_ids: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id:
            raise ValueError("任务评测用例缺少 id")
        if case_id in seen_ids:
            raise ValueError(f"任务评测用例 id 重复：{case_id}")
        seen_ids.add(case_id)
        for field in ("category", "input", "expected_agents"):
            if not case.get(field):
                raise ValueError(f"任务评测用例缺少 {field}：{case_id}")
        for field in ("required_tools", "allowed_tools", "forbidden_tools"):
            if not isinstance(case.get(field, []), list):
                raise ValueError(f"任务评测用例 {field} 必须是列表：{case_id}")
        if not isinstance(case.get("expected_effects", {}), dict):
            raise ValueError(f"任务评测用例 expected_effects 必须是对象：{case_id}")
    return data


def _agent_names(agent_trace: list[str]) -> list[str]:
    """从 supervisor 的可读轨迹中提取实际 worker 名称，保留首次出现顺序。"""
    names: list[str] = []
    for trace in agent_trace:
        target = trace.rsplit("→", 1)[-1]
        if target and target != "FINISH" and target not in names:
            names.append(target)
    return names


def _tool_names(tool_calls: list[dict[str, Any]]) -> list[str]:
    """从工具轨迹提取工具名并去重；同一工具重试不应改变工具集合判定。"""
    names: list[str] = []
    for call in tool_calls:
        name = call.get("name")
        if name and name not in names:
            names.append(name)
    return names


def build_hitl_resume(mode: str, payload: dict[str, Any]) -> dict[str, Any] | bool:
    """按前端协议构造确认卡片的恢复值，评测不绕开生产 HITL 流程。"""
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("HITL 确认载荷缺少 items")
    if mode == "confirm":
        return {"items": items}
    if mode == "cancel":
        return False
    if mode == "allergy_confirm":
        return {"items": items, "allergy_acknowledged": True}
    raise ValueError(f"不支持的 HITL 评测模式：{mode}")


def extract_turn_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """从最终消息中提取本轮 React 工具调用，并与对应结果配对。"""
    start = 0
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "type", None) == "human":
            start = index
            break

    calls: dict[str, dict[str, Any]] = {}
    for message in messages[start:]:
        if getattr(message, "type", None) == "ai":
            for tool_call in getattr(message, "tool_calls", None) or []:
                calls[tool_call["id"]] = {
                    "name": tool_call["name"],
                    "args": tool_call["args"],
                    "result": None,
                }
        elif getattr(message, "type", None) == "tool":
            call_id = getattr(message, "tool_call_id", None)
            if call_id in calls:
                content = getattr(message, "content", "")
                calls[call_id]["result"] = (
                    content if isinstance(content, str) else str(content)
                )
    return list(calls.values())


_DEFAULT_PROFILE = {
    "gender": "male",
    "age": 28,
    "height_cm": 175.0,
    "weight_kg": 70.0,
    "activity_level": "moderate",
    "goal": "lose",
    "goal_note": "",
}


def _record_date(raw_value: str | None) -> date | None:
    """把任务集的可选日期解析为 date；缺省由 service 使用真实当天。"""
    return date.fromisoformat(raw_value) if raw_value else None


def _seed_case_setup(db, user_id: int, setup: dict[str, Any]) -> None:
    """为查询、删除和过敏类样例准备最小前置数据，不污染真实用户。"""
    profile_updates = {**_DEFAULT_PROFILE, **dict(setup.get("profile") or {})}
    profile_service.apply_profile_update(db, user_id, profile_updates)

    for record in setup.get("diet_records", []):
        diet_service.create_diet_record(
            db,
            user_id=user_id,
            meal_type=record["meal_type"],
            items=record["items"],
            record_date=_record_date(record.get("record_date")),
            source="eval",
        )
    for record in setup.get("exercise_records", []):
        exercise_service.create_exercise_record(
            db,
            user_id=user_id,
            exercise_type=record["exercise_type"],
            duration_minutes=float(record["duration_minutes"]),
            met=float(record["met"]),
            record_date=_record_date(record.get("record_date")),
            source="eval",
        )


@contextmanager
def _isolated_eval_user(setup: dict[str, Any]) -> Iterator[int]:
    """为单个 episode 创建独立用户；退出时依赖外键级联彻底清理测试数据。"""
    db = SessionLocal()
    user_id: int | None = None
    try:
        user = User(
            username=f"agent_eval_{uuid.uuid4().hex}",
            password_hash=hash_password("agent-eval"),
        )
        db.add(user)
        db.commit()
        user_id = user.id
        _seed_case_setup(db, user_id, setup)
        yield user_id
    finally:
        if user_id is not None:
            db.query(User).filter(User.id == user_id).delete()
            db.commit()
        db.close()


def _collect_effects(user_id: int) -> dict[str, int]:
    """读取评测关心的持久化副作用，所有计数均只针对隔离测试用户。"""
    db = SessionLocal()
    try:
        diet_count = db.scalar(
            select(func.count(DietRecord.id)).where(DietRecord.user_id == user_id)
        )
        exercise_count = db.scalar(
            select(func.count(ExerciseRecord.id)).where(ExerciseRecord.user_id == user_id)
        )
        return {
            "diet_record_count": int(diet_count or 0),
            "exercise_record_count": int(exercise_count or 0),
            "profile_exists": int(db.get(UserProfile, user_id) is not None),
        }
    finally:
        db.close()


def _merge_tool_calls(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并 React 与普通节点轨迹；同一调用只保留一次，保障报告易读。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for call in group:
            key = json.dumps(call, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                merged.append(call)
    return merged


def run_agent_task_episode(graph, case: dict[str, Any]) -> dict[str, Any]:
    """通过真实图执行一个任务样例，并返回确定性评分后的逐例报告。"""
    thread_id = f"agent-eval-{uuid.uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    observed_hitl = "none"
    error: str | None = None
    final_state: dict[str, Any] = {}

    with _isolated_eval_user(dict(case.get("setup") or {})) as user_id:
        config["configurable"]["user_id"] = user_id
        try:
            result = graph.invoke(
                {
                    "messages": [HumanMessage(content=case["input"])],
                    "user_id": user_id,
                    "image_url": None,
                    "recognized_foods": None,
                    "image_analysis_status": "no_image",
                    "image_analysis_error": None,
                },
                config,
            )
            interruptions = 0
            while result.get("__interrupt__"):
                interruptions += 1
                if interruptions > 2:
                    error = "HITL 中断次数超过上限"
                    break
                payload = result["__interrupt__"][0].value
                expected_mode = case.get("hitl", "none")
                if expected_mode == "none":
                    observed_hitl = "unexpected_interrupt"
                    error = "任务未预期出现 HITL 中断"
                    break
                if expected_mode == "allergy_confirm" and not payload.get(
                    "requires_allergy_confirmation"
                ):
                    observed_hitl = "confirm"
                else:
                    observed_hitl = expected_mode
                result = graph.invoke(
                    Command(resume=build_hitl_resume(expected_mode, payload)), config
                )
            final_state = dict(graph.get_state(config).values)
        except Exception as exc:  # 真实模型/网络异常同样要进入报告，不中断整批评测。
            error = f"{type(exc).__name__}: {exc}"
            try:
                final_state = dict(graph.get_state(config).values)
            except Exception:
                final_state = {}

        observed = {
            "agent_trace": list(final_state.get("agent_trace") or []),
            "tool_calls": _merge_tool_calls(
                extract_turn_tool_calls(list(final_state.get("messages") or [])),
                list(final_state.get("tool_calls") or []),
            ),
            "effects": _collect_effects(user_id),
            "hitl": observed_hitl,
            "error": error,
        }
    return evaluate_episode(case, observed)


def run_agent_task_eval(
    dataset: dict[str, Any],
    *,
    repeats: int = 3,
    case_limit: int | None = None,
    evaluation_mode: str = "optimized_scoped_task",
) -> dict[str, Any]:
    """使用真实 Qwen + LangGraph 批跑固定任务集，并返回可 JSON 序列化报告。"""
    if repeats < 1:
        raise ValueError("repeats 必须至少为 1")
    if not settings.dashscope_api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，无法运行真实 Agent 评测")

    from app.agents.graph import build_graph

    worker_context_mode = worker_context_mode_for_evaluation(evaluation_mode)
    cases = list(dataset["cases"])
    if case_limit is not None:
        if case_limit < 1:
            raise ValueError("case_limit 必须至少为 1")
        cases = cases[:case_limit]
    graph = build_graph(
        checkpointer=MemorySaver(), worker_context_mode=worker_context_mode
    )
    reports = [
        run_agent_task_episode(graph, case)
        for case in cases
        for _ in range(repeats)
    ]
    summary = aggregate_reports(reports, dataset_version=dataset["schema_version"])
    summary.update(
        {
            "schema_version": "agent-task-eval-report-v1",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "model": settings.text_model,
            "repeats": repeats,
            "case_count": len(cases),
            "evaluation_mode": evaluation_mode,
            "worker_context_mode": worker_context_mode,
        }
    )
    return summary


def evaluate_episode(case: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    """按固定任务契约判定单次执行，输出可用于失败复盘的完整明细。"""
    expected_agents = list(case.get("expected_agents", []))
    actual_agents = _agent_names(list(observed.get("agent_trace") or []))
    missing_agents = [agent for agent in expected_agents if agent not in actual_agents]
    agent_correct = not missing_agents

    actual_tools = _tool_names(list(observed.get("tool_calls") or []))
    required_tools = list(case.get("required_tools", []))
    allowed_tools = set(case.get("allowed_tools", []))
    forbidden_tools = set(case.get("forbidden_tools", []))
    missing_required_tools = [name for name in required_tools if name not in actual_tools]
    forbidden_tool_calls = [name for name in actual_tools if name in forbidden_tools]
    # 已明确禁止的工具单列，避免同一次错误同时被记为“未允许”而双重统计。
    unexpected_tools = [
        name
        for name in actual_tools
        if name not in allowed_tools and name not in forbidden_tools
    ]
    tool_correct = not (
        missing_required_tools or unexpected_tools or forbidden_tool_calls
    )

    expected_effects = dict(case.get("expected_effects") or {})
    actual_effects = dict(observed.get("effects") or {})
    effect_mismatches = [
        {"key": key, "expected": expected, "actual": actual_effects.get(key)}
        for key, expected in expected_effects.items()
        if actual_effects.get(key) != expected
    ]
    effects_correct = not effect_mismatches

    expected_hitl = case.get("hitl")
    actual_hitl = observed.get("hitl")
    hitl_correct = expected_hitl is None or expected_hitl == actual_hitl

    failure_reasons: list[str] = []
    failure_reasons.extend(f"未路由至预期 agent：{name}" for name in missing_agents)
    failure_reasons.extend(f"缺少必需工具：{name}" for name in missing_required_tools)
    failure_reasons.extend(f"出现未允许工具：{name}" for name in unexpected_tools)
    failure_reasons.extend(f"出现禁止工具：{name}" for name in forbidden_tool_calls)
    failure_reasons.extend(
        "数据库副作用不匹配：{key}（期望 {expected}，实际 {actual}）".format(**item)
        for item in effect_mismatches
    )
    if not hitl_correct:
        failure_reasons.append(
            f"HITL 结果不匹配：期望 {expected_hitl}，实际 {actual_hitl}"
        )
    if observed.get("error"):
        failure_reasons.append(f"执行异常：{observed['error']}")

    task_completed = (
        agent_correct
        and tool_correct
        and effects_correct
        and hitl_correct
        and not observed.get("error")
    )
    return {
        "case_id": case["id"],
        "category": case["category"],
        "input": case["input"],
        "actual_agents": actual_agents,
        "actual_tools": actual_tools,
        "agent_correct": agent_correct,
        "tool_correct": tool_correct,
        "effects_correct": effects_correct,
        "hitl_correct": hitl_correct,
        "task_completed": task_completed,
        "missing_agents": missing_agents,
        "missing_required_tools": missing_required_tools,
        "unexpected_tools": unexpected_tools,
        "forbidden_tool_calls": forbidden_tool_calls,
        "effect_mismatches": effect_mismatches,
        "failure_reasons": failure_reasons,
        "observed": observed,
    }


def _rate(reports: list[dict[str, Any]], key: str) -> float:
    """返回 episode 维度成功率；空集返回 0，防止假阳性。"""
    return sum(bool(report[key]) for report in reports) / len(reports) if reports else 0.0


def aggregate_reports(
    reports: list[dict[str, Any]], *, dataset_version: str
) -> dict[str, Any]:
    """聚合总分、分类分与失败计数，供 CLI 落盘及简历基线引用。"""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        grouped[report["category"]].append(report)

    categories = {
        category: {
            "episodes": len(items),
            "task_completion_rate": _rate(items, "task_completed"),
            "tool_call_accuracy": _rate(items, "tool_correct"),
        }
        for category, items in sorted(grouped.items())
    }
    return {
        "dataset_version": dataset_version,
        "episodes": len(reports),
        "task_completion_rate": _rate(reports, "task_completed"),
        "tool_call_accuracy": _rate(reports, "tool_correct"),
        "categories": categories,
        "reports": reports,
    }
