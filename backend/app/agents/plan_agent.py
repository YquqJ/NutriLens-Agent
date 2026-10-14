"""
plan_agent —— 个性化计划专职 worker。

职责边界（面试重点）：
1. 数字由 service 层算：BMR/TDEE/热量目标在档案更新时已由
   Mifflin-St Jeor 公式算好落库，plan_agent 只负责"读数 + 解释 + 排方案"，
   绝不让 LLM 做算术；
2. 档案缺失时先补档：用户说"帮我出个减脂计划"但没填过身高体重，
   agent 要先问基本信息（或从对话中提取后 update_profile），
   数字齐了才能出计划 —— 宁可多一轮对话，不出无依据的计划。
"""

from datetime import date
from typing import Optional

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_text_llm
from app.agents.state import AgentState
from app.tools.profile import get_profile, update_profile


class PlanAgentState(AgentState):
    """plan_agent 子图专用 state（remaining_steps 为 react 内部必需键）。"""

    remaining_steps: int


PLAN_TOOLS = [get_profile, update_profile]

PLAN_SYSTEM_PROMPT = """你是健康计划顾问，负责给用户生成个性化饮食/运动计划，并管理其身体档案。只执行交给你的任务，不闲聊。

工作纪律：
1. 出计划前必须先 get_profile 读档案：BMR、TDEE、calorie_target 都在档案里，
   直接引用这些数字，禁止自己计算或编造数值；
2. 档案不完整（关键数据缺失）时：先向用户询问缺失项，用户给出后用
   update_profile 补档（只传新增/变更字段），然后基于新档案出计划；
3. 计划要落地：具体到每餐吃什么量级（与 calorie_target 对得上）、
   每周运动频率/项目/时长，并结合 goal_note 里的偏好与过敏信息；
4. 用户只是更新档案不出计划时，更新完简短确认即可；
5.【过程纪律】调用工具前和工具调用之间，不要输出任何解释、计划或过程文字——
   直接调用 get_profile，让档案读取只体现在工具轨迹里，不要在文本里复述要做什么；
6.【交付纪律】档案齐全时，必须一次性输出完整计划正文（每餐吃什么、吃多少、
   运动怎么安排），禁止只说"接下来我将…""好的，我这就…"之类的承诺性开场白
   就结束本轮——开场白只是铺垫，正文必须紧跟其后，没给完整计划就不算完成任务。"""


def _plan_prompt(state: AgentState) -> list:
    """完整消息列表：SystemMessage(人设+任务) + 对话历史。"""
    task = state.get("task") or ""
    system = SystemMessage(
        content=(
            f"{PLAN_SYSTEM_PROMPT}\n\n"
            f"【当前日期】{date.today().isoformat()}（回答涉及今天/昨天/明天时以此为准，不要臆测日期）。\n\n"
            f"【当前任务】{task}"
            + (
                f"\n\n【重试说明】{state['worker_retry_context']}"
                if state.get("worker_retry_context")
                else ""
            )
        )
    )
    return [system] + state["messages"]


def make_plan_agent(checkpointer: Optional[BaseCheckpointSaver] = None):
    """构造 plan_agent（编译好的子图）。checkpointer 用法同 diet_agent。"""
    llm = get_text_llm()
    return create_react_agent(
        llm,
        PLAN_TOOLS,
        prompt=_plan_prompt,
        state_schema=PlanAgentState,
        checkpointer=checkpointer,
    )
