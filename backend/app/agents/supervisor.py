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
   业务层主动计数更可控）。MAX_HOPS 覆盖四个计划任务各一次安全重试。

可测试性设计：make_supervisor_node(router=...) 的 router 可注入 ——
单测注入桩（伪造固定决策），不依赖真实 LLM；联调时用 qwen-plus。
"""

from datetime import date
from typing import Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.agents.llm import get_router_llm
from app.agents.state import AgentState, NoTaskReason

# 路由目标：四个专职 agent + 结束
RouteTarget = Literal["diet_agent", "exercise_agent", "qa_agent", "plan_agent", "FINISH"]

# 防死循环上限：最多四个计划任务各派发一次，并各允许一次安全重试。
# 这是 Worker 派发次数上限，不限制单个 Worker 内部的工具调用次数。
MAX_HOPS = 8
MAX_WORKER_RETRIES = 1
# 当前轮路由只保留有限的前序对话，避免历史工具结果或旧任务主导意图判断。
ROUTING_CONTEXT_WINDOW = 6
EMPTY_PLAN_REVIEW_REASONS = {"out_of_scope", "no_action", "unclear"}

AGENT_DUTIES: dict[str, str] = {
    "diet_agent": (
        "饮食记录与查询：拍照识别食物、文字描述解析成记录（含营养匹配与用户确认）、"
        "查/删饮食记录、查每日营养汇总（摄入/消耗/热量目标/剩余可摄入热量，即热量缺口）。"
        "涉及'吃了什么/多少克/卡路里摄入/今天还剩多少热量/热量缺口'选它。"
    ),
    "exercise_agent": (
        "运动记录与查询：记录一次运动（类型/时长）、按 MET 计算消耗、查/删运动记录。"
        "涉及'跑了多久/消耗多少'选它。"
    ),
    "qa_agent": (
        "营养/健身知识问答与建议咨询：'减脂期怎么吃''蛋白质摄入量'等开放性问题选它；"
        "BMI、BMR、TDEE、基础代谢、体脂率、热量缺口的定义/公式/原理，以及一般营养"
        "和运动原则都属于知识问答。"
        "注意：查用户自己的记录不归它（那是 diet/exercise_agent 的事）。"
    ),
    "plan_agent": (
        "仅处理个人身体档案的读取/更新（身高体重/活动水平/偏好），或基于用户个人"
        "档案生成个性化饮食/运动计划。单纯解释 BMR/TDEE 等概念不得路由到此。"
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


class PlannedTask(BaseModel):
    """一次性计划中的一个单域任务。"""

    next_agent: Literal["diet_agent", "exercise_agent", "qa_agent", "plan_agent"]
    task: str = Field(min_length=1)


class TaskPlanDecision(BaseModel):
    """Supervisor 首次进入时生成的有序任务计划。"""

    tasks: list[PlannedTask] = Field(default_factory=list, max_length=4)
    finish_reason: Optional[NoTaskReason] = Field(
        description=(
            "tasks 非空时必须为 null；tasks 为空时必须说明原因：out_of_scope（超出健康管理范围）、"
            "small_talk（问候或感谢）、unclear（意图不清，需要用户澄清）、"
            "no_action（仅确认、感谢等没有新问题或请求的消息）"
        )
    )


SUPERVISOR_SYSTEM_PROMPT = """你是健康管理系统的调度员（supervisor）。你的唯一职责是规划和路由，不要自己回答问题。

当前真实日期：{today}（做日期指代消解时以它为准，不要凭记忆猜日期）。

可用执行者：
{duties}
如果用户没有可执行任务，返回空 tasks，并根据原因填写 finish_reason；有任务时 finish_reason 必须为 null。

判断规则：
1. 以【当前用户请求】为唯一需要响应的对象；前序上下文仅用于消解它的指代，
   不得把前序内容中的旧需求当作当前任务。一次性拆出有序 tasks；每个 task 只属于一个执行者。
   若同一领域有多个子请求，合并成该领域一个 task，不要重复添加同一 agent；
2. tasks 按推荐执行顺序排列；最多返回四个 task。不要把其他领域动作写进单个 task；
3. task 字段把用户请求改写成独立指令：补全指代消解（他/它/昨天那顿→具体内容）；
   "今天"一律消解为 {today}，"昨天/明天"据此前后推算；未提及日期默认今天；
4. BMI、BMR、TDEE、基础代谢、体脂率、热量缺口的术语/公式/原理解释，及一般营养或运动
   建议，都是 qa_agent 的可执行知识问题，不能判为 no_action 或 unclear。
5. no_action 仅用于确认、感谢或完全没有新问题/请求的消息；绝不能因为请求不涉及数据库写入而使用。
   超出健康管理范围、寒暄、意图不清、无需新操作时才返回空 tasks，并分别填写
   out_of_scope、small_talk、unclear、no_action。禁止把无关任务硬塞给某个 worker。"""


def _routing_conversation(messages: list) -> list:
    """返回当前请求和仅供指代消解的有限前序对话，排除工具输出。"""
    human_indexes = [
        index for index, message in enumerate(messages) if isinstance(message, HumanMessage)
    ]
    if not human_indexes:
        return []

    current_index = human_indexes[-1]
    preceding = [
        message
        for message in messages[:current_index]
        if isinstance(message, (HumanMessage, AIMessage))
    ][-ROUTING_CONTEXT_WINDOW:]
    return [
        (
            "system",
            "[ROUTING_REFERENCE_ONLY_CONTEXT] 以下前序内容仅用于消解当前请求中的指代，"
            "不得从中引入新的任务。",
        ),
        *preceding,
        ("system", "【当前用户请求】请只路由接下来的这条用户消息。"),
        messages[current_index],
    ]


def make_supervisor_node(
    router: Optional[Runnable] = None,
) -> callable:
    """
    构造 supervisor 节点函数。

    参数 router：已绑定结构化输出的规划器（messages → TaskPlanDecision）。
    生产路径由本函数内部用 qwen-plus 构建；旧版 RouteDecision 测试桩仍兼容。
    """
    if router is None:
        llm: BaseChatModel = get_router_llm()
        router = llm.with_structured_output(TaskPlanDecision)

    def supervisor(state: AgentState) -> Command:
        # 注：返回注解不能用 Command[RouteTarget] —— compile 时 LangGraph 会把
        # 注解里的字面量解析成 goto 目标白名单做校验，"FINISH" 不是图中的
        # 节点名（真正跳的是 END 常量），带了它直接 ValueError。
        hop_count = state.get("hop_count", 0)
        # ---- 1. 首次进入才规划；Worker 回流只推进已持久化计划 ----
        routing_msgs = [
            (
                "system",
                SUPERVISOR_SYSTEM_PROMPT.format(
                    duties="\n".join(f"- {k}：{v}" for k, v in AGENT_DUTIES.items()),
                    today=date.today().isoformat(),
                ),
            )
        ]
        # 摘要记忆：长会话被压缩后，旧消息已从 messages 删掉，路由可能缺跨轮上下文
        # （"昨天那顿"）。把 summary 作为第二条系统消息注入，保证指代消解仍可做。
        summary = state.get("summary")
        if summary:
            routing_msgs.append(
                (
                    "system",
                    "[ROUTING_REFERENCE_ONLY_SUMMARY] 以下历史摘要仅用于消解当前请求中的"
                    f"指代，不得从中引入新的任务。\n{summary}",
                )
            )
        # 图片感知：本条消息带图时，图片里的食物对 supervisor 是未知的（文本路由
        # 看不到图）。不点破，指代消解会拿历史里最近记录的食物（如"香肠"）去填
        # "晚饭"，产出"把香肠改成晚餐"这类错误 task，盖过 diet_agent 的识别指令。
        recognized = state.get("recognized_foods") or []
        if recognized:
            foods = "、".join(f"{f['food_name']}({f['estimated_grams']}g)" for f in recognized)
            routing_msgs.append(
                ("system", f"用户本轮消息附带照片，已识别出食物：{foods}。改写 task 时以这些食物为准，严禁替换成历史对话里的其他食物。")
            )
        elif state.get("image_analysis_status") == "no_food_detected":
            routing_msgs.append(
                ("system", "用户本轮图片已成功分析，但未检测到可记录的食物。若用户意图是通过此图片记录饮食，路由到 diet_agent，并在 task 中明确要求反馈该结论；不得臆测食物或要求再次识图。")
            )
        elif state.get("image_analysis_status") == "failed":
            routing_msgs.append(
                ("system", "用户本轮图片分析失败。若用户意图依赖该图片，路由到 diet_agent，并在 task 中明确要求告知图片暂时无法读取或识别；不得臆测食物或要求再次识图。")
            )
        elif state.get("image_url"):
            routing_msgs.append(
                ("system", "用户本轮消息附带照片但图片食物尚未识别，改写 task 时严禁依据历史臆测食物，应表述为'识别并记录这顿饭'。")
            )
        task_plan = state.get("task_plan")
        task_index = int(state.get("task_index", 0) or 0)
        plan_initialized = bool(state.get("plan_initialized", False))
        no_task_reason: Optional[NoTaskReason] = None
        if not plan_initialized:
            routing_msgs.extend(_routing_conversation(state.get("messages") or []))
            raw_decision = router.invoke(routing_msgs)
            blocked_duplicate_route = False
            if isinstance(raw_decision, RouteDecision):
                trace = state.get("agent_trace", [])
                last_agent = next(
                    (agent for agent in AGENT_DUTIES if trace and trace[-1].endswith(agent)),
                    None,
                )
                if raw_decision.next_agent == last_agent:
                    blocked_duplicate_route = True
                    raw_decision = RouteDecision(
                        next_agent="FINISH",
                        task="上一 agent 已完成本任务，避免同 agent 连续重复路由",
                    )
                planned = [
                    PlannedTask(next_agent=raw_decision.next_agent, task=raw_decision.task)
                ] if raw_decision.next_agent != "FINISH" else []
                no_task_reason = "unclear" if not planned else None
            else:
                planned = list(getattr(raw_decision, "tasks", []) or [])
                no_task_reason = getattr(raw_decision, "finish_reason", None)
            if (
                not blocked_duplicate_route
                and not planned
                and no_task_reason in EMPTY_PLAN_REVIEW_REASONS
            ):
                review_messages = [
                    *routing_msgs,
                    (
                        "system",
                        "【重新审查】你刚刚将当前请求判为空计划。请重新完整理解当前用户请求，"
                        "不要基于上一次结论复述。用户在提问、请求解释或请求建议，本身就是"
                        "可执行任务，必须路由给对应 worker；不能因为它没有数据库写入而判为"
                        "no_action。若存在饮食记录、运动记录、营养/健身问答、档案或计划相关"
                        "意图，必须拆分为对应 tasks。只有确实没有新请求的确认/感谢才保留"
                        "no_action；只有确实与健康管理完全无关时才保留 out_of_scope。",
                    ),
                ]
                reviewed_decision = router.invoke(review_messages)
                if isinstance(reviewed_decision, RouteDecision):
                    planned = (
                        [
                            PlannedTask(
                                next_agent=reviewed_decision.next_agent,
                                task=reviewed_decision.task,
                            )
                        ]
                        if reviewed_decision.next_agent != "FINISH"
                        else []
                    )
                    no_task_reason = "unclear" if not planned else None
                else:
                    planned = list(getattr(reviewed_decision, "tasks", []) or [])
                    no_task_reason = getattr(reviewed_decision, "finish_reason", None)
            # 同一领域的多个子请求合并，避免同一个 Worker 被重复派发。
            # 按首次出现顺序保留领域顺序；即使同一 agent 的任务不连续，
            # 也必须合并而不能静默丢弃后续任务。
            merged_by_agent: dict[str, PlannedTask] = {}
            for item in planned[:4]:
                existing = merged_by_agent.get(item.next_agent)
                if existing is None:
                    merged_by_agent[item.next_agent] = item
                else:
                    merged_by_agent[item.next_agent] = PlannedTask(
                        next_agent=item.next_agent,
                        task=f"{existing.task}；{item.task}",
                    )
            merged = list(merged_by_agent.values())
            task_plan = [item.model_dump() for item in merged[:4]]
            task_index = 0
            plan_initialized = True
        task_plan = task_plan or []
        worker_failures = list(state.get("worker_failures") or [])
        worker_outcome = state.get("worker_outcome")

        # 当前任务计划游标在派发时已前移，因此最近一次 Worker 对应 task_index - 1。
        # 只有明确无副作用的错误才允许重试；副作用未知时直接记录失败并继续计划。
        if worker_outcome and worker_outcome.get("status") not in {
            None,
            "success",
        }:
            completed_index = task_index - 1
            if 0 <= completed_index < len(task_plan):
                failed_task = PlannedTask.model_validate(task_plan[completed_index])
                retry_count = int(state.get("worker_retry_count", 0) or 0)
                can_retry = (
                    worker_outcome.get("status") == "retryable_error"
                    and worker_outcome.get("retryable") is True
                    and worker_outcome.get("side_effect") == "none"
                    and retry_count < MAX_WORKER_RETRIES
                    and hop_count < MAX_HOPS
                )
                if can_retry:
                    return Command(
                        goto=failed_task.next_agent,
                        update={
                            "next_agent": failed_task.next_agent,
                            "task": failed_task.task,
                            "task_index": task_index,
                            "hop_count": hop_count + 1,
                            "worker_outcome": None,
                            "worker_retry_count": retry_count + 1,
                            "worker_retry_context": (
                                "上次执行失败：只读步骤未成功且未执行写入；请重新执行任务一次，"
                                "仍遵守原有确认与数据安全规则。"
                            ),
                            "worker_message_start": len(state.get("messages") or []),
                            "worker_message_end": len(state.get("messages") or []),
                            "agent_trace": state.get("agent_trace", [])
                            + [f"supervisor→{failed_task.next_agent}"],
                        },
                    )

                worker_failures.append(
                    {
                        "agent": failed_task.next_agent,
                        "task": failed_task.task,
                        "error_code": worker_outcome.get("error_code")
                        or "worker_error",
                        "side_effect": worker_outcome.get("side_effect", "unknown"),
                        "message_start": int(
                            state.get("worker_message_start", 0) or 0
                        ),
                        "message_end": int(
                            state.get("worker_message_end", 0) or 0
                        ),
                    }
                )

        if task_index >= len(task_plan):
            if not task_plan and task_index == 0:
                finish_reason = no_task_reason or "unclear"
            else:
                finish_reason = "worker_failed" if worker_failures else "completed"
            return Command(
                goto=END,
                update={
                    "next_agent": "FINISH",
                    "task": (
                        "没有可执行的健康管理任务"
                        if not task_plan
                        else "所有计划任务已完成"
                    ),
                    "task_plan": task_plan,
                    "task_index": task_index,
                    "plan_initialized": plan_initialized,
                    "hop_count": hop_count,
                    "finish_reason": finish_reason,
                    "worker_outcome": None,
                    "worker_retry_count": 0,
                    "worker_retry_context": "",
                    "worker_failures": worker_failures,
                },
            )

        current = PlannedTask.model_validate(task_plan[task_index])
        # 限制本轮所有首次派发与重试的总次数，且只在确实还要派发任务时触发。
        # 这样最后一个 Worker 返回后仍可处理其结果并正常结束。
        if hop_count >= MAX_HOPS:
            return Command(
                goto=END,
                update={
                    "next_agent": "FINISH",
                    "task": "已达最大路由次数，停止后续任务以避免流程循环",
                    "hop_count": hop_count,
                    "finish_reason": "route_limit",
                    "worker_outcome": None,
                    "worker_retry_count": 0,
                    "worker_retry_context": "",
                    "worker_failures": worker_failures,
                },
            )
        next_index = task_index + 1
        # ---- 3. 更新路由状态并跳转 ----
        return Command(
            goto=current.next_agent,
            update={
                "next_agent": current.next_agent,
                "task": current.task,
                "task_plan": task_plan,
                "task_index": next_index,
                "plan_initialized": plan_initialized,
                "hop_count": hop_count + 1,
                "finish_reason": None,
                "worker_outcome": None,
                "worker_retry_count": 0,
                "worker_retry_context": "",
                "worker_message_start": len(state.get("messages") or []),
                "worker_message_end": len(state.get("messages") or []),
                "worker_failures": worker_failures,
                "plan_requested": state.get("plan_requested", False)
                or (
                    current.next_agent == "plan_agent"
                    and "计划" in current.task
                ),
                "agent_trace": state.get("agent_trace", [])
                + [f"supervisor→{current.next_agent}"],
            },
        )

    return supervisor
