"""
exercise_agent —— 运动记录专职 worker。

与 diet_agent 的差异（对照阅读）：
1. 无 HITL：运动"类型+时长"是用户直述，写库不需要确认 interrupt；
2. MET 降级在工具层自动处理（表未命中返回提示 → LLM 估算重试），
   提示词只需告诉模型这个机制，不用自己记 MET 值。
"""

from datetime import date
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_text_llm
from app.agents.state import AgentState
from app.tools.exercise import (
    create_exercise_record,
    delete_exercise_record,
    get_exercise_records,
)


class ExerciseAgentState(AgentState):
    """exercise_agent 子图专用 state（remaining_steps 为 react 内部必需键）。"""

    remaining_steps: int


EXERCISE_TOOLS = [
    create_exercise_record,
    get_exercise_records,
    delete_exercise_record,
]

EXERCISE_SYSTEM_PROMPT = """你是运动记录员，负责用户运动的记录与查询。只执行交给你的任务，不闲聊。

工作纪律：
1. 记录运动用 create_exercise_record：met 参数不填，工具会先查 MET 表；
   若返回 met_not_found，按运动强度估算一个 met 重试（轻度≈3，中度≈5，高强度≈8），
   同一运动禁止反复重试不同 met 值；
2. 消耗热量由工具按用户体重计算，不要自己心算报数；
3. 用户没说时长就先追问，禁止自行假定时长；
4. 未说明日期默认今天；完成后用一两句话汇报（运动、时长、消耗了多少千卡）。
5.【任务边界】只执行“当前任务”中属于运动领域的部分。你不能调用其他 agent；
   若原始对话还包含饮食、计划或问答需求，不要处理、不要尝试把 agent 名当作工具调用。"""


def _exercise_prompt(state: AgentState, *, use_scoped_task: bool = True) -> list:
    """完整消息列表：SystemMessage(人设+任务) + 对话历史。

    callable prompt 的返回值是模型的完整输入（见 diet_agent 踩坑记录），
    必须拼上 state["messages"]，否则模型失去历史。
    """
    task = state.get("task") or ""
    system = SystemMessage(
        content=(
            f"{EXERCISE_SYSTEM_PROMPT}\n\n"
            f"【当前日期】{date.today().isoformat()}（回答涉及今天/昨天/明天时以此为准，不要臆测日期）。\n\n"
            f"【当前任务】{task}"
            + (
                f"\n\n【重试说明】{state['worker_retry_context']}"
                if state.get("worker_retry_context")
                else ""
            )
        )
    )
    messages = state.get("messages") or []
    current_turn_start = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            current_turn_start = i
            break

    current_turn_messages = messages[current_turn_start:]
    # task 是 supervisor 分配给运动 worker 的独立子任务。用它替换原始用户文本，
    # 使复合请求的饮食部分不会重新干扰运动子图的工具选择。
    if task and use_scoped_task:
        scoped_task = HumanMessage(content=task)
        if current_turn_messages and getattr(current_turn_messages[0], "type", None) == "human":
            current_turn_messages = [scoped_task, *current_turn_messages[1:]]
        else:
            current_turn_messages = [scoped_task, *current_turn_messages]
    return [system] + current_turn_messages


def make_exercise_agent(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    *,
    use_scoped_task: bool = True,
):
    """构造 exercise_agent（编译好的子图）。checkpointer 用法同 diet_agent。"""
    llm = get_text_llm()
    return create_react_agent(
        llm,
        EXERCISE_TOOLS,
        prompt=lambda state: _exercise_prompt(state, use_scoped_task=use_scoped_task),
        state_schema=ExerciseAgentState,
        checkpointer=checkpointer,
    )
