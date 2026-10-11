"""
LangGraph 全局 State 定义 —— 整张图各节点共享的数据结构。

设计要点：
- messages 是唯一的"累积型"状态（add_messages reducer：新消息 append 而非覆盖），
  也是短期记忆的载体 —— checkpointer 按 thread_id 持久化整个 state，
  下次请求自动恢复，天然实现"会话历史"；
- user_id / image_url 等请求级上下文由 API 层每次 invoke 时注入；
- hop_count 由 supervisor 维护，防止 worker 之间来回踢皮球造成死循环
  （LangGraph 的 recursion_limit 是兜底，业务层主动计数更可控）。
"""

from typing import Annotated, Literal, Optional

from typing_extensions import TypedDict

from langgraph.graph.message import add_messages

# 餐次类型（贯穿 Agent 工具与前端确认卡片）
MealType = Literal["breakfast", "lunch", "dinner", "snack"]

# 营养数据置信度三档：
#   db_exact     食物库精确命中
#   db_fuzzy     食物库模糊命中（近似匹配）
#   llm_estimate 库未命中，LLM 估算
Confidence = Literal["db_exact", "db_fuzzy", "llm_estimate"]

# 图片分析的终态。recognized_foods=None 本身无法区分“没有食物”和“识图失败”，
# 因此必须由状态字段保留前置感知节点的结论，供路由和 worker 做不同处理。
ImageAnalysisStatus = Literal["no_image", "recognized", "no_food_detected", "failed"]
NoTaskReason = Literal["out_of_scope", "small_talk", "unclear", "no_action"]
WorkerStatus = Literal[
    "success",
    "retryable_error",
    "quality_insufficient",
    "needs_user_input",
    "fatal_error",
]
SideEffectStatus = Literal["none", "committed", "unknown"]
WorkerOutcome = TypedDict(
    "WorkerOutcome",
    {
        "status": WorkerStatus,
        "error_code": str,
        "retryable": bool,
        "side_effect": SideEffectStatus,
    },
)
FinishReason = Literal[
    "out_of_scope",
    "small_talk",
    "unclear",
    "no_action",
    "completed",
    "route_limit",
    "worker_failed",
]


class DietItemDraft(TypedDict):
    """HITL 确认卡片上的一个食物条目（interrupt 挂起时的草稿）。"""

    food_name: str
    grams: float
    calories: float
    protein: float
    fat: float
    carbs: float
    confidence: Confidence


class AgentState(TypedDict):
    """Supervisor 图的全局状态。"""

    # ---- 对话消息（短期记忆，append-only） ----
    messages: Annotated[list, add_messages]

    # ---- 摘要记忆：messages 超出阈值时，旧消息被折叠成滚动摘要（见 memory.py） ----
    summary: str

    # ---- 请求上下文（每次 invoke 由 API 层注入） ----
    user_id: str
    image_url: Optional[str]  # 本条用户消息携带的食物图片（OSS URL）
    recognized_foods: Optional[list[dict]]  # 图片识别结果（analyze_image 节点预置，供 supervisor/diet_agent 共用）
    image_analysis_status: Optional[ImageAnalysisStatus]
    image_analysis_error: Optional[str]  # 仅记录异常类型，避免把底层服务细节暴露给用户

    # ---- supervisor 路由决策结果 ----
    next_agent: str
    task: str  # 改写后的子任务指令（含指代消解，交给专职 agent 独立执行）
    task_plan: Optional[list[dict]]  # 本轮一次性生成的有序单域任务计划
    task_index: int  # 下一个待派发任务的游标
    plan_initialized: bool  # 本轮是否已经生成过任务计划
    hop_count: int  # 已派发次数，>=8 后强制结束（四任务各允许一次重试）
    plan_requested: bool  # 本轮是否明确生成计划（供 SSE 出站层归档最终交付）
    finish_reason: Optional[FinishReason]  # 本轮结束原因；新轮次重置
    worker_outcome: Optional[WorkerOutcome]  # 最近一次 Worker 的结构化结果
    worker_retry_count: int  # 当前任务已重试次数；首版最多一次
    worker_retry_context: str  # 重试时注入 Worker 的失败上下文
    worker_message_start: int  # 最近一次 Worker 输出在 messages 中的起点
    worker_message_end: int  # 最近一次 Worker 输出在 messages 中的终点
    worker_discarded_ranges: list[dict]  # 最终回复提取时应跳过的失败尝试区间
    worker_failures: list[dict]  # 已跳过的失败子任务，供最终兜底和观测

    # ---- HITL：待确认的饮食草稿 ----
    # interrupt() 挂起前由工具写入 state，恢复后由工具消费
    pending_diet_items: Optional[list[DietItemDraft]]
    pending_meal_type: Optional[MealType]

    # ---- 供前端渲染的元数据 ----
    agent_trace: list[str]  # 本轮参与的 agent 序列，如 ["diet_agent"]
    tool_calls: list[dict]  # 本轮工具调用轨迹 [{name, args, result}]（SSE 也用）
    citations: list[dict]  # QA 检索证据 [{index, label, section, page_number, content}]（SSE / 历史回放）
