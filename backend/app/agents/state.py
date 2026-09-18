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
    hop_count: int  # 已路由次数，>=2 后强制结束
    plan_requested: bool  # 本轮是否明确生成计划（供 SSE 出站层归档最终交付）

    # ---- HITL：待确认的饮食草稿 ----
    # interrupt() 挂起前由工具写入 state，恢复后由工具消费
    pending_diet_items: Optional[list[DietItemDraft]]
    pending_meal_type: Optional[MealType]

    # ---- 供前端渲染的元数据 ----
    agent_trace: list[str]  # 本轮参与的 agent 序列，如 ["diet_agent"]
    tool_calls: list[dict]  # 本轮工具调用轨迹 [{name, args, result}]（SSE 也用）
    citations: list[dict]  # QA 检索证据 [{index, label, section, page_number, content}]（SSE / 历史回放）
