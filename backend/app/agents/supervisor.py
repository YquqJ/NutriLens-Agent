"""
Supervisor 路由节点 —— 多 Agent 系统的调度核心。

职责（一次只做一件事：路由，不干活）：
1. 看完整对话历史，决定下一个执行者（四个专职 agent 之一）还是结束；
2. 把用户请求"改写"成独立子任务指令（指代消解）：
   用户说"那再记一笔，跟昨天一样的"——supervisor 结合历史把它改写成
   "查询用户昨天午餐的饮食记录并新建一条相同内容的今日午餐记录"，
   交给 worker 后 worker 不需要任何对话上下文就能独立执行；
3. hop_count 防死循环：worker 之间不允许互相踢皮球，
   路由次数 >= MAX_HOPS 强制结束（LangGraph recursion_limit 是兜底，
   业务层主动计数更可控）。

可测试性设计：make_supervisor_node(router=...) 的 router 可注入 ——
单测注入桩（伪造固定决策），不依赖真实 LLM；联调时用 qwen-plus。
"""

from typing import Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langgraph.graph import END
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.llm import get_text_llm
from app.agents.state import AgentState

# 路由目标：四个专职 agent + 结束
RouteTarget = Literal["diet_agent", "exercise_agent", "qa_agent", "plan_agent", "FINISH"]

# 防死循环上限：最多路由 2 次（用户请求 → agent A → （极少）agent B → 结束）
MAX_HOPS = 2

AGENT_DUTIES: dict[str, str] = {
    "diet_agent": (
        "饮食记录与查询：拍照识别食物、文字描述解析成记录（含营养匹配与用户确认）、"
        "查/删饮食记录、查每日营养汇总。涉及'吃了什么/多少克/卡路里摄入'选它。"
    ),
    "exercise_agent": (
        "运动记录与查询：记录一次运动（类型/时长）、按 MET 计算消耗、查/删运动记录。"
        "涉及'跑了多久/消耗多少'选它。"
    ),
    "qa_agent": (
        "营养/健身知识问答与建议咨询：'减脂期怎么吃''蛋白质摄入量'等开放性问题选它。"
        "注意：查用户自己的记录不归它（那是 diet/exercise_agent 的事）。"
    ),
    "plan_agent": (
        "个性化饮食/运动计划生成：读身体档案算 BMR/TDEE，按减脂/增肌/维持目标出方案；"
        "查看或更新身体档案（身高体重/活动水平/偏好）也归它。"
    ),
}


class RouteDecision(BaseModel):
    """路由决策的结构化输出约束。"""

    next_agent: RouteTarget = Field(description="下一个执行的 agent 或 FINISH")
    task: str = Field(
        description=(
            "改写后的子任务指令：脱离对话上下文也能独立执行的一句中文任务描述，"
            "必须补全指代（'那顿饭'→具体内容）、补全默认值（未说日期默认今天）"
        )
    )


SUPERVISOR_SYSTEM_PROMPT = """你是健康管理系统的调度员（supervisor）。你的唯一职责是路由，不要自己回答问题。

可用执行者：
{duties}
以及 FINISH：任务已完成（结果已在对话中）或用户只是寒暄/没有可执行任务。

判断规则：
1. 依据完整对话历史判断用户最新意图，只选一个执行者；
2. task 字段把用户请求改写成独立指令：补全指代消解（他/它/昨天那顿→具体内容），未提及的日期默认今天；
3. worker 的执行结果会回到你这里：如果结果已经足以回答用户，选 FINISH；
4. 拿不准属于谁时，按最贴近用户目的的那个选。"""


def make_supervisor_node(
    router: Optional[Runnable] = None,
) -> callable:
    """
    构造 supervisor 节点函数。

    参数 router：已绑定结构化输出的决策器（messages → RouteDecision）。
    生产路径由本函数内部用 qwen-plus 构建；测试注入桩。
    """
    if router is None:
        llm: BaseChatModel = get_text_llm(streaming=False)  # 路由是一次结构化输出，关流式
        router = llm.with_structured_output(RouteDecision)

    def supervisor(state: AgentState) -> Command[RouteTarget]:
        # ---- 1. 防死循环：超限强制结束 ----
        hop_count = state.get("hop_count", 0)
        if hop_count >= MAX_HOPS:
            return Command(
                goto=END,
                update={
                    "next_agent": "FINISH",
                    "task": "已达最大路由次数，强制结束以避免 agent 间循环",
                    "hop_count": hop_count,
                },
            )

        # ---- 2. 路由决策（qwen-plus 结构化输出）----
        decision: RouteDecision = router.invoke(
            [
                (
                    "system",
                    SUPERVISOR_SYSTEM_PROMPT.format(
                        duties="\n".join(f"- {k}：{v}" for k, v in AGENT_DUTIES.items())
                    ),
                ),
                *state["messages"],
            ]
        )

        # ---- 3. 更新路由状态并跳转 ----
        return Command(
            goto=END if decision.next_agent == "FINISH" else decision.next_agent,
            update={
                "next_agent": decision.next_agent,
                "task": decision.task,
                "hop_count": hop_count + 1,
                "agent_trace": state.get("agent_trace", [])
                + [f"supervisor→{decision.next_agent}"],
            },
        )

    return supervisor
