"""
SSE 流式端点测试（M3.7）。

分层：
1. 逻辑测试（无 LLM）：无挂起中断时 resume 应 400（防止把 resume 值
   灌进无中断的 checkpoint）；
2. E2E（真实 LLM + PostgresSaver + TestClient）：SPEC 验收链路 ——
   发消息 → SSE 收到 agent_trace/tool 分片/interrupt → resume 确认 →
   饮食记录落库 + messages 表出现 user/assistant 两条 → done 帧。

SSE 解析：TestClient 流式响应按行读，按 W3C 格式配对 event/data 行。
"""

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from openai import APITimeoutError

from app.api.chat import (
    _collect_turn_final_reports,
    _extract_tool_calls,
    _collect_turn_final_reports,
    _normalize_assistant_content,
    _run_graph_and_stream,
)
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.models import Conversation, DietRecord, Message, User
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers():
    """建测试用户 + JWT 头 + 独立会话（conversation id 即 thread_id）。"""
    db = SessionLocal()
    user = User(username=f"t_{uuid.uuid4().hex[:8]}", password_hash=hash_password("x"))
    db.add(user)
    db.commit()
    conv = Conversation(id=uuid.uuid4().hex, user_id=user.id)
    db.add(conv)
    db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    yield {"headers": headers, "conversation_id": conv.id, "user_id": user.id}
    # 清理：饮食记录 → 会话（消息级联）→ 用户
    db.query(DietRecord).filter(DietRecord.user_id == user.id).delete()
    db.query(Conversation).filter(Conversation.id == conv.id).delete()
    db.query(User).filter(User.id == user.id).delete()
    db.commit()
    db.close()


def _collect_sse(resp) -> list[tuple[str, dict]]:
    """把 SSE 流解析成 [(event, data), ...]。"""
    events: list[tuple[str, dict]] = []
    event, data = None, None
    for line in resp.iter_lines():
        if line.startswith("event: "):
            event = line[len("event: "):]
        elif line.startswith("data: "):
            data = line[len("data: "):]
        elif line == "" and event is not None:
            events.append((event, json.loads(data)))
            event, data = None, None
    return events


def test_extract_tool_calls_only_returns_current_turn():
    """回归：worker 子图 messages 累积历轮工具，_extract_tool_calls 必须只提炼
    最后一条 HumanMessage 之后的工具，历史轮的工具不得跨轮重提
    （曾导致 tool_trace 每轮越滚越大的累加 bug）。"""
    old_human = HumanMessage(content="我午饭吃了牛肉面")
    old_ai = AIMessage(
        content="",
        tool_calls=[{"id": "old_call", "name": "search_food", "args": {"query": "牛肉面"}}],
    )
    old_tool = ToolMessage(content="匹配 1 条", tool_call_id="old_call")

    new_human = HumanMessage(content="我今天热量缺口多少")
    new_ai = AIMessage(
        content="",
        tool_calls=[{"id": "new_call", "name": "get_daily_summary", "args": {}}],
    )
    new_tool = ToolMessage(content="剩余 800 千卡", tool_call_id="new_call")

    update = {
        "messages": [old_human, old_ai, old_tool, new_human, new_ai, new_tool],
    }
    names = [t["name"] for t in _extract_tool_calls(update)]
    assert names == ["get_daily_summary"]


def test_collect_turn_final_reports_keeps_each_worker_result_in_mixed_turn():
    """同一轮跨 worker 接力时，后一个汇报不能覆盖前一个汇报。"""
    messages = [
        HumanMessage(content="上一轮消息"),
        AIMessage(content="上一轮回复"),
        HumanMessage(content="昨天我吃了方便面，又跑了半小时"),
        AIMessage(
            content="",
            tool_calls=[{"id": "diet-tool", "name": "create_diet_record", "args": {}}],
        ),
        AIMessage(content="已记录晚餐方便面，共 760 千卡。"),
        AIMessage(
            content="",
            tool_calls=[{"id": "exercise-tool", "name": "create_exercise_record", "args": {}}],
        ),
        AIMessage(content="已记录跑步 30 分钟，消耗 343 千卡。"),
    ]

    reports = _collect_turn_final_reports(messages)

    assert reports == [
        "已记录晚餐方便面，共 760 千卡。",
        "已记录跑步 30 分钟，消耗 343 千卡。",
    ]


def test_collect_turn_final_reports_uses_confirmed_meal_from_tool_result():
    """最终汇报的餐次必须来自 HITL 后工具结果，而不是模型初始推断。"""
    messages = [
        HumanMessage(content="我吃了一碗面"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "create-diet",
                    "name": "create_diet_record",
                    "args": {"meal_type": "dinner"},
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "status": "created",
                    "record_id": 12,
                    "meal_type": "lunch",
                    "record_date": "2026-09-19",
                    "total_calories": 441,
                    "items": [
                        {
                            "food_name": "一碗面",
                            "grams": 490,
                            "confidence": "llm_estimate",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            tool_call_id="create-diet",
        ),
        AIMessage(content="已为 2026-09-19 添加一条晚餐记录，一碗面 490g，441 千卡。"),
    ]

    reports = _collect_turn_final_reports(messages)

    assert reports == [
        "已为2026-09-19添加一条午餐记录：一碗面（490g），合计441千卡。"
        "食物营养值由模型常识估算，仅供参考。"
    ]


def test_resume_without_pending_interrupt_returns_400(auth_headers):
    """没有挂起的 interrupt 时 resume 必须拒绝，不能静默改写 checkpoint。"""
    url = f"/api/conversations/{auth_headers['conversation_id']}/chat/resume"
    r = client.post(
        url, json={"value": False}, headers=auth_headers["headers"]
    )
    assert r.status_code == 400


def test_messages_are_returned_in_page_no_order(auth_headers):
    """历史消息按 pageNo 反向分页查询，但每页仍按发送先后顺序返回。"""
    cid = auth_headers["conversation_id"]
    db = SessionLocal()
    try:
        db.add_all(
            [
                Message(conversation_id=cid, role="user", content=f"消息 {i}")
                for i in range(1, 66)
            ]
        )
        db.commit()
    finally:
        db.close()

    url = f"/api/conversations/{cid}/messages"
    first = client.get(
        url,
        params={"pageNo": 1, "pageSize": 30},
        headers=auth_headers["headers"],
    )

    assert first.status_code == 200
    assert first.json()["total"] == 65
    assert first.json()["pageNo"] == 1
    assert first.json()["pageSize"] == 30
    assert first.json()["hasMore"] is True
    assert [item["content"] for item in first.json()["items"]] == [
        f"消息 {i}" for i in range(36, 66)
    ]

    last = client.get(
        url,
        params={"pageNo": 3, "pageSize": 30},
        headers=auth_headers["headers"],
    )

    assert last.status_code == 200
    assert last.json()["hasMore"] is False
    assert [item["content"] for item in last.json()["items"]] == [
        f"消息 {i}" for i in range(1, 6)
    ]


def test_invalid_record_date_returns_422_instead_of_server_error(auth_headers):
    """非法日期是请求参数错误，不能让 ValueError 冒泡成 500。"""
    r = client.get(
        "/api/diet/records",
        params={"date": "not-a-date"},
        headers=auth_headers["headers"],
    )

    assert r.status_code == 422
    assert "日期格式" in r.json()["detail"]


def test_image_recognition_json_is_rendered_as_natural_language():
    """图片识别的内部结构不能直接泄漏到助手正文。"""
    raw = json.dumps(
        {
            "items": [
                {"food_name": "虾", "estimated_grams": 150},
                {"food_name": "米饭", "estimated_grams": 100},
            ]
        },
        ensure_ascii=False,
    )

    visible = _normalize_assistant_content(raw)

    assert visible == "我识别到这顿饭包括：虾约150克、米饭约100克。请确认是否记录。"
    assert '"items"' not in visible


def test_normalize_assistant_content_keeps_normal_reply_unchanged():
    reply = "已为你记录午餐，共 520 千卡。"

    assert _normalize_assistant_content(reply) == reply


def test_image_interrupt_done_contains_normalized_content_without_token_leak(monkeypatch):
    """带图识别在 interrupt 前不能把内部 JSON 作为 token 泄漏给前端。"""
    raw = json.dumps(
        {"items": [{"food_name": "虾", "estimated_grams": 150}]},
        ensure_ascii=False,
    )

    class ImageInterruptGraph:
        def stream(self, *_args, **_kwargs):
            yield "messages", (AIMessageChunk(content=raw), {})
            yield "updates", {
                "__interrupt__": [
                    SimpleNamespace(value={"type": "diet_confirm"})
                ]
            }

    monkeypatch.setattr("app.api.chat.get_graph", lambda: ImageInterruptGraph())

    frames = list(
        _run_graph_and_stream(
            {"image_url": "https://example.test/food.jpg"},
            {},
            "test-conversation",
        )
    )

    assert all('event: token' not in frame for frame in frames)
    done = next(frame for frame in frames if frame.startswith("event: done"))
    payload = json.loads(done.split("data: ", 1)[1])
    assert payload["interrupted"] is True
    assert payload["content"] == "我识别到这顿饭包括：虾约150克。请确认是否记录。"


@pytest.mark.parametrize(
    "error",
    [
        APITimeoutError(httpx.Request("POST", "https://example.test")),
        httpx.ReadTimeout("读取模型响应超时"),
    ],
)
def test_chat_stream_returns_friendly_sse_error_when_llm_times_out(monkeypatch, error):
    """模型超时必须结束 SSE，而不是让前端和 LangSmith 一直显示运行中。"""
    class TimeoutGraph:
        def stream(self, *_args, **_kwargs):
            raise error
            yield  # pragma: no cover - 仅令其保持 generator 形态

    monkeypatch.setattr("app.api.chat.get_graph", lambda: TimeoutGraph())

    frames = list(_run_graph_and_stream({}, {}, "test-conversation"))

    assert len(frames) == 1
    assert 'event: error' in frames[0]
    assert '"code": "llm_timeout"' in frames[0]
    assert "AI 服务响应超时，请稍后重试。" in frames[0]


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_chat_stream_interrupt_then_resume(auth_headers):
    """验收链路：发消息 → interrupt → resume 确认 → 落库 → 消息表可见。"""
    cid = auth_headers["conversation_id"]
    headers = auth_headers["headers"]

    # ---- 第一段流：发消息，应收到 interrupt 事件（饮食确认草稿）----
    with client.stream(
        "POST",
        f"/api/conversations/{cid}/chat",
        json={"content": "我午饭吃了一碗牛肉面"},
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _collect_sse(resp)

    by_type = {}
    for ev, data in events:
        by_type.setdefault(ev, []).append(data)

    assert "interrupt" in by_type, "饮食写库前应收到 interrupt 事件"
    payload = by_type["interrupt"][0]["payload"]
    assert payload["type"] == "diet_confirm"
    assert payload["meal_type"] == "lunch"
    assert payload["items"], "确认卡片应携带食物草稿"
    # 路由轨迹可见（supervisor 把这条消息派给了 diet_agent）
    traces = [d["to"] for d in by_type.get("agent_trace", [])]
    assert "diet_agent" in traces
    # 流以 interrupted 的 done 帧收尾
    assert by_type["done"][0]["interrupted"] is True

    # ---- 第二段流：确认（不改克数）→ 落库 + assistant 汇报 ----
    with client.stream(
        "POST",
        f"/api/conversations/{cid}/chat/resume",
        json={"value": {"items": payload["items"], "meal_type": "dinner"}},
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        events2 = _collect_sse(resp)

    by_type2 = {}
    for ev, data in events2:
        by_type2.setdefault(ev, []).append(data)
    assert by_type2["done"][0]["interrupted"] is False
    assert by_type2["done"][0]["persisted"] is True
    assert "晚餐记录" in by_type2["done"][0]["content"]
    # 恢复后应有工具轨迹事件（search_food 等在此补发）与回复 token
    assert "tool_calls" in by_type2 or "token" in by_type2

    # ---- 落库断言：一条饮食记录 ----
    db = SessionLocal()
    try:
        records = db.query(DietRecord).filter(
            DietRecord.user_id == auth_headers["user_id"]
        ).all()
        assert len(records) == 1
        assert records[0].meal_type == "dinner"

        # messages 表：user 一条 + assistant 一条（含 agent_name 与轨迹）
        msgs = db.query(Message).filter(Message.conversation_id == cid).all()
        roles = sorted(m.role for m in msgs)
        assert roles == ["assistant", "user"]
        assistant = next(m for m in msgs if m.role == "assistant")
        assert assistant.content
        assert assistant.agent_name == "diet_agent"
        trace = json.loads(assistant.tool_trace)
        assert any(t["name"] == "create_diet_record" for t in trace)

        # 首条消息应已生成语义化会话标题（不再是默认"新会话"）
        conv = db.get(Conversation, cid)
        assert conv.title and conv.title != "新会话"
    finally:
        db.close()
