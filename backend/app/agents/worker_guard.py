"""Semantic admission checks that stop a wrongly routed worker before execution."""

from typing import Literal, Optional

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from app.agents.llm import get_router_llm


WorkerName = Literal["diet_agent", "exercise_agent", "qa_agent", "plan_agent"]


class WorkerAdmissionDecision(BaseModel):
    """Whether a task may enter its candidate worker."""

    approved: bool
    reason: str = Field(min_length=1)
    suggested_agent: Optional[WorkerName] = None


WORKER_ADMISSION_PROMPT = """你是健康管理系统的 Worker 准入审核器。你不回答用户问题，也不执行任何工具。

审查“当前用户原话”和“候选任务”是否适合交给“候选 Worker”。
- diet_agent 仅处理用户饮食记录、查询、删除和每日营养汇总；
- exercise_agent 仅处理用户运动记录、查询、删除和消耗计算；
- qa_agent 处理营养/运动通用知识、术语解释和一般建议；
- plan_agent 仅处理个人档案读取/更新，以及基于个人档案的个性化计划。

如果任务与当前用户原话或候选 Worker 的职责不一致，必须拒绝（approved=false），说明原因，并在能确定时给出 suggested_agent。
拒绝时意味着候选 Worker 不得调用任何工具。若一致则批准。"""


def make_worker_admission_guard() -> Runnable:
    """Build a deterministic structured LLM used only before worker execution."""
    return get_router_llm().with_structured_output(WorkerAdmissionDecision)
