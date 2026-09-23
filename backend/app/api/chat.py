"""
对话流式端点（M3.7）—— supervisor 图的 HTTP 门面。

职责：
1. 把用户消息喂给图（thread_id = conversation_id），以 SSE 分帧推送
   五类事件：token / agent_trace / tool_calls / citations / interrupt；
2. HITL 恢复：interrupt 挂起后前端调 resume 端点，传 Command(resume=value)；
3. 消息落库 messages 表：user 消息在流开始前落，assistant 汇报在流结束后落
   （含 agent_name 与 tool_trace JSON，供 /messages 历史回放渲染）。

SSE 分帧格式（W3C 标准，前端按行解析）：
    event: token
    data: {"content": "已"}
    （帧与帧之间空行分隔；不支持断线重连，刷新页面走历史回放。）

关键设计：
- chat 与 resume 两个入口共用一个同步生成器：两者只是"喂给图的输入"不同
  （{"messages": [...]} vs Command(resume=...)），事件分帧与落库逻辑只有一份。
  用同步 stream 而非 astream：astream 走 checkpointer 的 async 接口
  （aget_tuple 等），同步版 PostgresSaver 未实现会直接 NotImplementedError，
  而我们的 pending_sends 补丁打在同步类上 —— starlette 的 StreamingResponse
  原生支持同步迭代器（starlette 会在线程池里逐帧拉取），不必为此迁移异步版；
- 生成器内不持有 FastAPI 依赖注入的 db 会话（StreamingResponse 的发送
  生命周期与依赖 teardown 交错容易踩坑），落库时自开短会话；
- token 只来自 worker 的文本输出：supervisor 是非流式结构化输出不产 token；
  AIMessageChunk 里 content 为空的分片是 tool_call 编码，不推给前端；
- 工具调用轨迹两个来源：react worker（diet/exercise/plan）从其节点 updates
  的 messages 差量配对提取（AIMessage.tool_calls 与 ToolMessage 按
  tool_call_id 对应）；qa_agent 是普通节点，轨迹由 update["tool_calls"]
  直接带回。注意：HITL 挂起发生在工具内部时，该节点的差量要等 resume
  之后才产出 —— 即 interrupt 之前已执行的工具（如 search_food）的轨迹
  事件会在恢复后补发，顺序上晚于 interrupt 事件。
"""

import json
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from httpx import TimeoutException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from openai import APITimeoutError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.graph import WORKERS, get_graph
from app.agents.llm import get_text_llm
from app.core.deps import get_current_user
from app.db.models import Conversation, Message, User
from app.db.session import SessionLocal, get_db
from app.services import plan as plan_service

router = APIRouter(prefix="/api/conversations", tags=["chat"])

# 工具结果（如检索命中列表）落库轨迹时截断，避免 tool_trace 膨胀
_TOOL_RESULT_MAX = 2000

# ---- 会话标题（首条消息语义概括）----
_TITLE_SYSTEM = (
    "你是会话标题生成器。根据用户的第一条消息，生成一个 4～10 个汉字的简短会话标题，"
    "概括其核心意图（如：早餐分析、减脂计划、热量缺口查询）。只输出标题本身，"
    "不要引号、标点、序号或任何解释。"
)
_TITLE_FALLBACK_LEN = 12


def _normalize_assistant_content(content: str) -> str:
    """把误泄漏到助手正文的图片识别 JSON 转成用户可读摘要。

    图片识别结果是内部协议，不应直接展示给用户。正常的自然语言回复
    原样返回；只有形如 ``{"items": [{"food_name": ..., ...}]}`` 的结果
    才做确定性转换，避免误伤普通回答。
    """
    if not content:
        return content

    candidate = content.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
        if candidate.lower().startswith("json\n"):
            candidate = candidate[5:].lstrip()

    try:
        payload = json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return content

    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return content

    items: list[str] = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        name = item.get("food_name")
        grams = item.get("estimated_grams")
        if not isinstance(name, str) or not name.strip():
            continue
        if isinstance(grams, (int, float)) and not isinstance(grams, bool):
            grams_text = f"{grams:g}"
            items.append(f"{name.strip()}约{grams_text}克")
        else:
            items.append(name.strip())

    if not items:
        return content
    return f"我识别到这顿饭包括：{'、'.join(items)}。请确认是否记录。"


async def _generate_title(content: str) -> str:
    """根据会话首条消息生成语义标题；LLM 失败时退回截取首条前 N 字。"""
    try:
        llm = get_text_llm(streaming=False)
        resp = await llm.ainvoke(
            [SystemMessage(content=_TITLE_SYSTEM), HumanMessage(content=content)]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        title = raw.strip().strip("「」“”\"'《》").strip()
        if title:
            return title[:24]
    except Exception:  # 兜底：LLM/网络异常不阻断对话
        pass
    s = content.strip()
    return s[:_TITLE_FALLBACK_LEN] if s else "新会话"


class ChatRequest(BaseModel):
    """发一条对话消息。image_url 为本条消息携带的食物照片（OSS URL）。"""

    content: str
    image_url: Optional[str] = None


class ResumeRequest(BaseModel):
    """恢复挂起的 interrupt。value 即 resume 值：
    饮食确认场景为 {"items": [...], "allergy_acknowledged": bool}
    （条目可能被用户编辑过）或 False（取消）。"""

    value: Any


def _sse(event: str, data: dict) -> str:
    """组装一帧 SSE。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _extract_tool_calls(update: dict) -> list[dict]:
    """
    从 worker 节点的 messages 配出「本轮」工具调用轨迹 [{name, args, result}]。

    react 循环里 AIMessage.tool_calls 携带 {id, name, args}，执行结果在
    ToolMessage（tool_call_id 一一对应），两者按 id 配对。关键：worker 子图的
    messages 是 add_messages 累积的——历轮的 AIMessage.tool_calls + ToolMessage
    都还在里面，直接遍历会把上一轮的工具重提一遍、tool_trace 跨轮越滚越大。
    因此以「最后一条 HumanMessage」为界，只提炼其后的消息：Human 消息总是每轮
    开头才追加，其后的工具必属本轮（resume 恢复中断不会新增 Human，本轮
    interrupt 前已执行的工具仍被正确归入当前这一轮）。
    """
    msgs = update.get("messages") or []
    # 找本轮边界：最后一条 HumanMessage 之后才是本轮新消息
    start = len(msgs)
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].type == "human":
            start = i + 1
            break
    calls: dict[str, dict] = {}  # tool_call_id -> {name, args, result}
    for m in msgs[start:]:
        if m.type == "ai":
            for tc in m.tool_calls or []:
                calls[tc["id"]] = {"name": tc["name"], "args": tc["args"], "result": None}
        elif m.type == "tool" and m.tool_call_id in calls:
            result = m.content if isinstance(m.content, str) else str(m.content)
            if len(result) > _TOOL_RESULT_MAX:
                result = result[:_TOOL_RESULT_MAX] + "…(截断)"
            calls[m.tool_call_id]["result"] = result
    return list(calls.values())


def _collect_turn_final_reports(messages: list) -> list[str]:
    """提取本轮每个 worker 的终态汇报，供多领域请求合并展示。

    同一轮可能按“饮食 → 运动”接力执行。messages 是 append-only 的，若出站层
    只取最后一条 AIMessage，后一个 worker 的汇报会遮住前一个 worker 的结果。
    工具调用对应的 AIMessage 带 tool_calls，不属于用户可见的终态汇报，需排除。
    """
    start = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", None) == "human":
            start = i + 1
            break

    reports: list[str] = []
    tool_names: dict[str, str] = {}
    skip_next_diet_report = False
    for message in messages[start:]:
        message_type = getattr(message, "type", None)
        if message_type == "ai":
            calls = getattr(message, "tool_calls", None) or []
            if calls:
                tool_names.update(
                    {call.get("id"): call.get("name", "") for call in calls}
                )
                continue
            if skip_next_diet_report:
                skip_next_diet_report = False
                continue
        elif message_type == "tool":
            call_id = getattr(message, "tool_call_id", None)
            if tool_names.get(call_id) == "create_diet_record":
                report = _diet_record_report(getattr(message, "content", ""))
                if report:
                    reports.append(report)
                    skip_next_diet_report = True
            continue
        if message_type != "ai":
            continue
        content = message.content if isinstance(message.content, str) else ""
        content = content.strip()
        if content and content not in reports:
            reports.append(content)
    return reports


def _diet_record_report(raw_result: Any) -> Optional[str]:
    """用写库工具的确认后结果生成确定性饮食回执，避免模型改写错餐次。"""
    if not isinstance(raw_result, str):
        return None
    try:
        result = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(result, dict) or result.get("status") != "created":
        return None

    meal_labels = {
        "breakfast": "早餐",
        "lunch": "午餐",
        "dinner": "晚餐",
        "snack": "加餐",
    }
    meal_label = meal_labels.get(result.get("meal_type"))
    record_date = result.get("record_date")
    items = result.get("items")
    if not meal_label or not record_date or not isinstance(items, list) or not items:
        return None

    item_summary = "、".join(
        f"{item['food_name']}（{item['grams']:g}g）"
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("food_name"), str)
        and isinstance(item.get("grams"), (int, float))
    )
    if not item_summary:
        return None

    total_calories = result.get("total_calories")
    if not isinstance(total_calories, (int, float)):
        return None
    report = (
        f"已为{record_date}添加一条{meal_label}记录：{item_summary}，"
        f"合计{total_calories:g}千卡。"
    )
    if any(item.get("confidence") == "llm_estimate" for item in items if isinstance(item, dict)):
        report += "食物营养值由模型常识估算，仅供参考。"
    return report


def _run_graph_and_stream(
    graph_input: Any, cfg: dict, conversation_id: str
) -> Iterator[str]:
    """跑图 → SSE 事件流 → 落库 assistant 汇报。chat 与 resume 共用。"""
    graph = get_graph()
    token_buffer: list[str] = []  # 兜底文本（正常取最终 state 的最后一条 AI 消息）
    tool_trace: list[dict] = []  # 本轮全部工具调用（落 messages.tool_trace）
    citations: list[dict] = []  # QA 结构化证据（落 messages.citations，供前端抽屉回放）
    seen_calls: set[str] = set()  # 已发过的工具调用内容键（resume 后 react 子图会重放相同差量）
    current_agent: Optional[str] = None  # 产出最终回复的 agent（落 agent_name）
    interrupted = False
    # 首轮带图请求可能先收到视觉模型的结构化 JSON。先暂存 token，
    # 避免 JSON 在确认卡片出现前闪现给用户；完成/中断时统一走正文规范化。
    hold_tokens = isinstance(graph_input, dict) and bool(graph_input.get("image_url"))

    try:
        for mode, chunk in graph.stream(
            graph_input, cfg, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                msg, _meta = chunk
                # 只推文本增量：content 为空的分片是 tool_call 编码，跳过
                if msg.type == "AIMessageChunk" and isinstance(msg.content, str) and msg.content:
                    token_buffer.append(msg.content)
                    if not hold_tokens:
                        yield _sse("token", {"content": msg.content})
                continue

            # ---- updates：节点级状态差量 ----
            if "__interrupt__" in chunk:
                # 图在工具内部挂起，payload 即前端确认卡片的输入
                intr = chunk["__interrupt__"][0]
                interrupted = True
                yield _sse("interrupt", {"payload": intr.value})
                continue

            sup = chunk.get("supervisor")
            if sup and "next_agent" in sup:
                # 路由决策 → agent_trace 事件（前端渲染 agent 徽章切换）
                yield _sse(
                    "agent_trace",
                    {"to": sup["next_agent"], "task": sup.get("task", "")},
                )
                continue

            for node, update in chunk.items():
                if node in WORKERS and isinstance(update, dict):
                    current_agent = node  # resume 路径没有 supervisor 决策事件，从这里兜住
                    if update.get("citations"):
                        citations = list(update["citations"])
                        yield _sse("citations", {"items": citations})
                    # 工具轨迹两个来源：react worker 从 messages 差量配对提取；
                    # qa_agent 是普通节点，轨迹由节点 update 的 tool_calls 直接带回
                    new_calls = _extract_tool_calls(update) + list(
                        update.get("tool_calls") or []
                    )
                    for tc in new_calls:
                        # resume 恢复时 react 子图节点差量会整段重放（同一批
                        # AIMessage/ToolMessage 再发一次），按内容键去重，
                        # 避免 tool_calls 事件与落库轨迹翻倍
                        key = json.dumps(tc, ensure_ascii=False, sort_keys=True, default=str)
                        if key in seen_calls:
                            continue
                        seen_calls.add(key)
                        yield _sse("tool_calls", tc)
                        tool_trace.append(tc)

        if interrupted:
            # 挂起等用户：不落 assistant 消息（草稿在 interrupt 事件里，
            # resume 完成后由下一轮流统一落库），也不结束会话
            yield _sse(
                "done",
                {
                    "interrupted": True,
                    "content": _normalize_assistant_content("".join(token_buffer)),
                },
            )
            return

        # ---- 流结束：合并本轮各 worker 的终态汇报 ----
        final_state = graph.get_state(cfg).values
        reports = _collect_turn_final_reports(final_state.get("messages") or [])
        content = "\n\n".join(_normalize_assistant_content(report) for report in reports)
        content = content or _normalize_assistant_content("".join(token_buffer))

        if content:
            db = SessionLocal()
            try:
                # 计划的来源是 plan_agent 的最终交付，不依赖模型额外调用保存工具。
                # 路由到 plan_agent 时由 supervisor 写 plan_requested，避免其收尾
                # 再次改写 task 后丢失“这是计划生成”的判断依据。
                if current_agent == "plan_agent" and final_state.get("plan_requested"):
                    plan_service.save_active_plan(
                        db,
                        user_id=int(cfg["configurable"]["user_id"]),
                        conversation_id=conversation_id,
                        content=content,
                    )
                db.add(
                    Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=content,
                        agent_name=current_agent,
                        tool_trace=json.dumps(tool_trace, ensure_ascii=False),
                        citations=json.dumps(citations, ensure_ascii=False) if citations else None,
                    )
                )
                db.commit()
            finally:
                db.close()
        yield _sse(
            "done",
            {
                "interrupted": False,
                "agent_name": current_agent,
                "persisted": bool(content),
                # 权威终稿：流式 token 可能混入 react agent 的工具间叙述（"现在我将…"），
                # 前端收到 done 后用 content 替换累积的 token 文本，保证最终消息干净
                "content": content,
                "citations": citations,
            },
        )
    except (APITimeoutError, TimeoutException):
        # 上游模型连接在 LLM_TIMEOUT_SECONDS 内没有返回。图执行以异常结束，
        # LangSmith 能收到失败状态；同时 SSE 给用户可行动的、非技术化提示。
        yield _sse(
            "error",
            {
                "code": "llm_timeout",
                "message": "AI 服务响应超时，请稍后重试。",
            },
        )
    except Exception as e:
        # 流中途异常：以 error 帧收尾（HTTP 状态码已 200，无法再改）
        yield _sse("error", {"message": f"{type(e).__name__}: {e}"})


def _get_own_conversation(
    conversation_id: str, user: User, db: Session
) -> Conversation:
    """加载会话并校验属主（thread_id 即会话 id，越权等于操作别人的线程）。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: str,
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发消息并以 SSE 流式返回 Agent 的执行过程与回复。"""
    conv = _get_own_conversation(conversation_id, user, db)

    # user 消息先落库（流失败也有痕迹），顺带刷新会话活跃时间（列表按此排序）
    db.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content=req.content,
            image_url=req.image_url,
        )
    )
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    # 首条消息给会话起语义化标题（如"早餐分析"），后续消息不再更新
    if conv.title == "新会话":
        conv.title = await _generate_title(req.content)
        db.commit()

    # user_id 双写：state 里是 AgentState 的字段（str），configurable 里是
    # 工具层 ensure_config() 的取值来源（int）—— 两套消费者各取所需
    graph_input = {
        "messages": [HumanMessage(content=req.content)],
        "user_id": str(user.id),
        "image_url": req.image_url,
    }
    cfg = {"configurable": {"thread_id": conv.id, "user_id": user.id}}

    return StreamingResponse(
        _run_graph_and_stream(graph_input, cfg, conv.id),
        media_type="text/event-stream",
    )


@router.post("/{conversation_id}/chat/resume")
async def resume_chat(
    conversation_id: str,
    req: ResumeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复挂起的 interrupt（用户点了确认/取消），继续以 SSE 流式返回。"""
    conv = _get_own_conversation(conversation_id, user, db)
    graph = get_graph()
    cfg = {"configurable": {"thread_id": conv.id, "user_id": user.id}}

    # state.next 非空 = 图停在某个节点上等 resume；空 = 没有挂起的操作，
    # 此时灌 resume 值会变成往 checkpoint 写一条无意义的 resume 记录，拦掉
    if not graph.get_state(cfg).next:
        raise HTTPException(status_code=400, detail="当前没有待确认的操作")

    return StreamingResponse(
        _run_graph_and_stream(Command(resume=req.value), cfg, conv.id),
        media_type="text/event-stream",
    )
