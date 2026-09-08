"""
运动域工具（exercise_agent 的工具集）。

设计要点（与 tools/diet.py 对照，面试重点）：
1. 不做 HITL：饮食的克数靠模型估算、误差大，落库前必须用户确认；
   运动的"类型 + 时长"由用户亲口陈述、没有估算环节，直接落库——
   同一项目里两种写库策略并存，说明 HITL 是按"数据可信度"取舍的，
   不是无脑全加。
2. MET 确定性与估算分离：优先查内置 MET 表（Compendium 常用条目，
   services/exercise.py）；未命中返回提示，让 LLM 按运动强度估一个
   MET 重试。估算的 MET 随记录落库、可追溯，历史不漂移。
3. 消耗计算按用户当前体重在 service 层固化，本层只做编排。
"""

from datetime import date
from typing import Optional

from langchain_core.tools import tool

from app.services import exercise as exercise_service
from app.tools.context import get_current_user_id, get_session


@tool
def create_exercise_record(
    exercise_type: str,
    duration_minutes: float,
    met: Optional[float] = None,
    record_date: Optional[str] = None,
) -> dict:
    """
    记录一次运动（如慢跑30分钟）。
    参数：
    - exercise_type: 运动名（中文，如"慢跑""羽毛球"）
    - duration_minutes: 时长（分钟）
    - met: 代谢当量。优先不填——先查内置 MET 表，未命中会返回提示，
      届时按运动强度估算后重试（轻度≈3 / 中度≈5 / 高强度≈8）
    - record_date: YYYY-MM-DD，缺省今天
    """
    # ---- 1. MET 解析：表优先，估算兜底 ----
    if met is None:
        met = exercise_service.lookup_met(exercise_type)
        if met is None:
            return {
                "status": "met_not_found",
                "hint": f"MET 表未收录'{exercise_type}'，请根据运动强度估算 met 后重试（轻度≈3，中度≈5，高强度≈8）",
            }

    # ---- 2. 落库（消耗按当前体重在 service 层计算并固化） ----
    user_id = get_current_user_id()
    with get_session() as db:
        result = exercise_service.create_exercise_record(
            db,
            user_id=user_id,
            exercise_type=exercise_type,
            duration_minutes=duration_minutes,
            met=met,
            record_date=date.fromisoformat(record_date) if record_date else None,
            source="agent",
        )
    return {"status": "created", **result}


@tool
def get_exercise_records(record_date: Optional[str] = None) -> dict:
    """
    查询用户某天的运动记录。参数为 YYYY-MM-DD，缺省今天。
    返回记录列表（类型/时长/MET/消耗）。
    """
    user_id = get_current_user_id()
    day = date.fromisoformat(record_date) if record_date else date.today()
    with get_session() as db:
        records = exercise_service.get_exercise_records(db, user_id, day)
    return {"records": records}


@tool
def delete_exercise_record(record_id: int) -> dict:
    """删除一条运动记录（需要记录 id，先 get_exercise_records 查到）。"""
    user_id = get_current_user_id()
    with get_session() as db:
        ok = exercise_service.delete_exercise_record(db, user_id, record_id)
    return {"status": "deleted" if ok else "not_found"}
