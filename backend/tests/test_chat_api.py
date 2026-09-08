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

import pytest
from fastapi.testclient import TestClient

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


def test_resume_without_pending_interrupt_returns_400(auth_headers):
    """没有挂起的 interrupt 时 resume 必须拒绝，不能静默改写 checkpoint。"""
    url = f"/api/conversations/{auth_headers['conversation_id']}/chat/resume"
    r = client.post(
        url, json={"value": False}, headers=auth_headers["headers"]
    )
    assert r.status_code == 400


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
        json={"value": {"items": payload["items"]}},
        headers=headers,
    ) as resp:
        assert resp.status_code == 200
        events2 = _collect_sse(resp)

    by_type2 = {}
    for ev, data in events2:
        by_type2.setdefault(ev, []).append(data)
    assert by_type2["done"][0]["interrupted"] is False
    assert by_type2["done"][0]["persisted"] is True
    # 恢复后应有工具轨迹事件（search_food 等在此补发）与回复 token
    assert "tool_calls" in by_type2 or "token" in by_type2

    # ---- 落库断言：一条饮食记录 ----
    db = SessionLocal()
    try:
        records = db.query(DietRecord).filter(
            DietRecord.user_id == auth_headers["user_id"]
        ).all()
        assert len(records) == 1
        assert records[0].meal_type == "lunch"

        # messages 表：user 一条 + assistant 一条（含 agent_name 与轨迹）
        msgs = db.query(Message).filter(Message.conversation_id == cid).all()
        roles = sorted(m.role for m in msgs)
        assert roles == ["assistant", "user"]
        assistant = next(m for m in msgs if m.role == "assistant")
        assert assistant.content
        assert assistant.agent_name == "diet_agent"
        trace = json.loads(assistant.tool_trace)
        assert any(t["name"] == "create_diet_record" for t in trace)
    finally:
        db.close()
