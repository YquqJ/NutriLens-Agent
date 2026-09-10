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

from datetime import date
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
    get_daily_summary,
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
    get_daily_summary,
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
3. 用户消息带图片时（图片 URL 会在系统提示的【图片】里给出），先用 analyze_food_image 识别，
   再逐项 search_food 匹配营养；
4. 餐次判定：早餐/午餐/晚餐/加餐；未说明日期默认今天；
5. 完成后用一两句话汇报结果（记了什么、合计多少千卡、数据置信度如何）。
   【汇报纪律】克数与营养值必须以 create_diet_record 的返回结果（items/total_calories）
   为准 —— 用户可能在确认环节修改过克数，返回值才是实际落库值；
   禁止在汇报中复述你自己的估算草稿。
6.【过程纪律】调用工具前和工具调用之间，不要输出任何解释、计划或过程文字——直接调用工具，
   让每一步在工具轨迹里体现，不要在文本里复述指令或过程。只在全部完成后按第 5 条汇报。
7.【热量缺口】用户问"今天还剩多少热量/热量缺口/还能吃多少/今天吃超标了吗"时，
   用 get_daily_summary 查当日收支：remaining=剩余可摄入（目标−已摄入+运动消耗）、
   intake=已摄入、burned=运动消耗、calorie_target=每日目标、net=净收支。
   直接引用这些数字回答；档案未填时 calorie_target/remaining 为 null，
   此时应引导用户先完善身体档案，而不是只答"尚未记录"。"""


def _diet_prompt(state: AgentState) -> list:
    """动态 prompt：返回完整的模型输入消息列表。

    注意（0.2.3 踩坑）：callable prompt 的返回值会"整体"作为模型输入，
    只返回字符串会导致模型每轮看不到历史消息与工具结果 —— 死循环。
    必须 [SystemMessage(人设+任务)] + state["messages"] 拼全量。
    """
    task = state.get("task") or ""
    system_text = (
        f"{DIET_SYSTEM_PROMPT}\n\n"
        f"【当前日期】{date.today().isoformat()}（回答涉及今天/昨天/明天时以此为准，不要臆测日期）。\n\n"
        f"【当前任务】{task}"
    )
    recognized = state.get("recognized_foods") or []
    image_url = state.get("image_url")
    if recognized:
        foods = "、".join(f"{f['food_name']} 约{f['estimated_grams']}g" for f in recognized)
        # 图片已在 analyze_image 前置节点识别好（感知与决策分离），这里只把结果
        # 作为事实注入，agent 无需也不应重复调 analyze_food_image。
        system_text += (
            f"\n\n【图片识别结果】本条消息的照片已识别出食物：{foods}。"
            "请直接对上述每种食物 search_food 匹配营养、按克数换算后 create_diet_record 落库；"
            "不要重复调用 analyze_food_image，也不要替换成其他食物。"
        )
    elif image_url:
        # 识别尚未完成/失败时的兜底：仍把 URL 交给 agent 走工具识别
        system_text += (
            f"\n\n【图片】本条用户消息携带食物图片，URL：{image_url}。"
            "必须先调用 analyze_food_image(image_url=该URL) 识别图中食物，"
            "再逐项 search_food 匹配营养、create_diet_record 落库。"
        )
    system = SystemMessage(content=system_text)
    return [system] + state["messages"]


def make_analyze_image_node(recognizer: Optional[callable] = None) -> callable:
    """图片感知前置节点：本条消息带图时，确定性地先识别图片里的食物，结果写
    state["recognized_foods"]，供 supervisor 与 diet_agent 共用。

    为什么这么做（面试重点）：识别本来靠 react agent 自主调 analyze_food_image
    工具，但这耦合了「感知」与「决策」——agent 受历史上下文干扰时会漏调视觉工具、
    改去幻觉食物（实测：记完"香肠"后再发"这是我的晚饭"+图，被误判成"把香肠改成晚餐"）。
    把感知剥离成图里的确定性前置节点后，图像识别只发生一次、结果作为事实注入下游，
    agent 不再需要"记得"去看图。recognizer 可注入（测试用桩）。
    """
    if recognizer is None:
        def recognizer(url: str) -> list[dict]:
            return (analyze_food_image.invoke({"image_url": url}) or {}).get("items") or []

    def analyze_image(state: AgentState) -> dict:
        url = state.get("image_url")
        if not url:
            return {"recognized_foods": None}
        try:
            items = recognizer(url)
        except Exception:
            items = []  # 识别失败不卡死链路：留给 diet_agent 走文本兜底
        return {
            "recognized_foods": [
                {
                    "food_name": it["food_name"],
                    "estimated_grams": it["estimated_grams"],
                    "visual_description": it.get("visual_description", ""),
                }
                for it in items
            ] or None
        }

    return analyze_image


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
