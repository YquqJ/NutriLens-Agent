"""
diet_agent —— 饮食记录专职 worker。

三个关键设计（面试重点）：

1. 作为"子图节点"加入 supervisor 图，而不是在节点函数里手动 .invoke：
   只有子图节点形态，工具里 interrupt() 抛出的 GraphInterrupt 才能被
   外层图的运行时正确捕获并挂起（手动嵌套 invoke 会丢中断）。
   子图状态 schema 复用 AgentState —— supervisor 改写好的 task、
   messages 全部直接可见，无需搬运转接。

2. task 驱动：系统提示词只讲"你是谁、工具怎么用"，当前任务由
   supervisor 改写后经 state["task"] 注入（动态 prompt 函数）。
   worker 不看对话全史也能干活 —— 指代消解已在 supervisor 完成。

3. 提示词里的"数据纪律"：营养数值必须先查食物库（search_food），
   未命中才允许常识估算并标注 llm_estimate —— 置信度分级
   （db_exact/db_fuzzy/llm_estimate）是整个产品的数据可信度根基。
"""

from typing import Optional

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_text_llm
from app.agents.state import AgentState
from app.tools.diet import (
    analyze_food_image,
    create_diet_record,
    delete_diet_record,
    get_diet_records,
    search_food,
)


class DietAgentState(AgentState):
    """diet_agent 子图专用 state：全局 state + react agent 内部键。

    remaining_steps 是 create_react_agent 的防死循环计数器（工具
    调用轮次上限），其 state_schema 硬性要求此键，缺了直接 ValueError。
    """

    remaining_steps: int

DIET_TOOLS = [
    analyze_food_image,
    search_food,
    create_diet_record,
    get_diet_records,
    delete_diet_record,
]

DIET_SYSTEM_PROMPT = """你是饮食记录员，负责用户饮食的记录与查询。只执行交给你的任务，不闲聊。

工作纪律：
1. 营养数据一律先查食物库（search_food），按克数换算；库未命中才允许按常识估算，
   此时 confidence 必须填 "llm_estimate"，并在回复中提醒用户数值仅供参考；
1a.【重要】每种食物最多查询一次：search_food 返回 found=false 即视为库中无此食物，
   必须立即改用常识估算并继续流程（调 create_diet_record 落库）——
   换参数重查同一食物是错误行为，会导致死循环；
2. 写入记录必须用 create_diet_record（系统会请求用户确认，无需你额外确认）；
3. 用户消息带图片时（图片 URL 会在任务里给出），先用 analyze_food_image 识别，
   再逐项 search_food 匹配营养；
4. 餐次判定：早餐/午餐/晚餐/加餐；未说明日期默认今天；
5. 完成后用一两句话汇报结果（记了什么、合计多少千卡、数据置信度如何）。"""


def _diet_prompt(state: AgentState) -> list:
    """动态 prompt：返回完整的模型输入消息列表。

    注意（0.2.3 踩坑）：callable prompt 的返回值会"整体"作为模型输入，
    只返回字符串会导致模型每轮看不到历史消息与工具结果 —— 死循环。
    必须 [SystemMessage(人设+任务)] + state["messages"] 拼全量。
    """
    task = state.get("task") or ""
    system = SystemMessage(content=f"{DIET_SYSTEM_PROMPT}\n\n【当前任务】{task}")
    return [system] + state["messages"]


def make_diet_agent(checkpointer: Optional[BaseCheckpointSaver] = None):
    """
    构造 diet_agent（编译好的子图，可直接 add_node 进 supervisor 图）。

    checkpointer：生产路径由外层 supervisor 图统一挂 PostgresSaver，
    此处不传；独立运行/测试时传 MemorySaver（interrupt 依赖 checkpoint）。
    """
    llm = get_text_llm()
    return create_react_agent(
        llm,
        DIET_TOOLS,
        prompt=_diet_prompt,
        state_schema=DietAgentState,  # 继承全局 state：task/messages 直接可见
        checkpointer=checkpointer,
    )
