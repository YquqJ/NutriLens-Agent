"""
记忆管理 —— 会话上下文摘要压缩（防 messages 无限累积）。

背景：state.messages 是 add_messages 累积通道（见 state.py），长会话跨数天/数十轮后
每一轮都把全量历史重喂给 supervisor 与各 react worker，token 成本与延迟线性增长、
逼近上下文窗口。这里用 LangGraph 官方的"摘要记忆"模式给通道瘦身：

1. 当 messages 条数 > MAX_MESSAGES 时，把「最旧 KEEP_TAIL 之前的消息」交给 LLM
   折叠成滚动摘要写入 state["summary"]（checkpoint 持久化，跨轮续上）；
2. 用 RemoveMessage(id=...) 删掉被折叠的旧消息，messages 只留最近 KEEP_TAIL 条
   —— 摘要承载长期记忆、近窗口承载短期上下文，合起来仍够 supervisor 做指代消解；
3. 摘要只喂给 supervisor（路由/指代消解需要跨轮上下文）；worker 是 task 驱动
   （supervisor 已把指代消解写进 task），只看近窗口即可，无需摘要。

实验确认：消息在进图通道时会被 LangGraph 补发 UUID id（直接构造 HumanMessage 时
id 为 None），所以 RemoveMessage 按 id 删除在真实链路里可靠，无需手动补 id。
"""

from typing import Optional

from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.runnables import Runnable

from app.agents.llm import get_text_llm
from app.agents.state import AgentState

# 消息数超过此阈值触发压缩；压缩后只保留最近 KEEP_TAIL 条（须 MAX_MESSAGES > KEEP_TAIL）
MAX_MESSAGES = 24
KEEP_TAIL = 8

_SUMMARY_SYSTEM = (
    "你是个人健康管理助手的对话摘要器。把给定的对话压缩成一段要点摘要，"
    "只保留对后续对话有价值的长期信息：用户的身体数据/目标/偏好、已记录的饮食与运动、"
    "进行中的计划、重要结论与待办。丢弃寒暄与被后续消息更新的临时信息。"
    "用中文，不超过 200 字，只输出摘要本身。"
)


def make_summarize_node(summarizer: Optional[Runnable] = None) -> callable:
    """构造摘要压缩节点。summarizer 可注入（测试用桩），生产默认 qwen-plus 非流式。"""
    if summarizer is None:
        summarizer = get_text_llm(streaming=False)

    def summarize(state: AgentState) -> dict:
        msgs = state.get("messages") or []
        if len(msgs) <= MAX_MESSAGES:
            return {}  # 未超阈值：短对话不多一次 LLM 调用、不增延迟

        old = msgs[:-KEEP_TAIL]  # 即将被折叠删除的旧消息
        existing = state.get("summary") or ""
        if existing:
            instructions = (
                f"{_SUMMARY_SYSTEM}\n\n"
                f"此前已经有一份对话摘要：\n{existing}\n"
                "请把下面这段新对话合并进去，形成一份更新后的摘要（合并重复、保留长期要点）。"
            )
        else:
            instructions = f"{_SUMMARY_SYSTEM}\n\n请把下面这段对话压缩成要点摘要。"

        resp = summarizer.invoke([SystemMessage(content=instructions), *old])
        new_summary = (
            resp.content if isinstance(resp.content, str) else str(resp.content)
        ).strip()

        return {
            "summary": new_summary,
            # add_messages 是 append-only，删旧消息只能走 RemoveMessage 原语
            "messages": [RemoveMessage(id=m.id) for m in old],
        }

    return summarize