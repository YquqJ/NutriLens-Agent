"""会话管理路由：列表 / 新建 / 历史消息 / 删除。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Conversation, Message, User
from app.db.session import get_db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    id: str
    title: str
    updated_at: str


class ConversationCreate(BaseModel):
    title: str = "新会话"


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    image_url: str | None
    agent_name: str | None
    tool_trace: str | None
    citations: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    created_at: str


class MessagePageOut(BaseModel):
    items: list[MessageOut]
    total: int
    pageNo: int
    pageSize: int
    hasMore: bool


def _serialize_message(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        image_url=message.image_url,
        agent_name=message.agent_name,
        tool_trace=message.tool_trace,
        citations=message.citations,
        duration_ms=message.duration_ms,
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens,
        total_tokens=message.total_tokens,
        created_at=message.created_at.isoformat(),
    )


@router.get("")
def list_conversations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """当前用户的会话列表，按最近活跃排序。"""
    convs = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    ).all()
    return [
        ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at.isoformat())
        for c in convs
    ]


@router.post("", status_code=201)
def create_conversation(
    req: ConversationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    新建会话。id 生成 UUID 并直接用作 LangGraph thread_id ——
    会话即线程，checkpoint 自动按此 id 持久化与恢复。
    """
    conv = Conversation(id=uuid.uuid4().hex, user_id=user.id, title=req.title)
    db.add(conv)
    db.commit()
    return ConversationOut(
        id=conv.id, title=conv.title, updated_at=conv.updated_at.isoformat()
    )


@router.get("/{conversation_id}/messages", response_model=MessagePageOut)
def get_messages(
    conversation_id: str,
    page_no: int = Query(default=1, ge=1, alias="pageNo"),
    page_size: int = Query(default=30, ge=1, le=100, alias="pageSize"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按最新优先分页读取会话消息，每页仍按发送先后顺序返回。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    total = db.scalar(
        select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id
        )
    ) or 0
    offset = (page_no - 1) * page_size
    items = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    items.reverse()

    return MessagePageOut(
        items=[_serialize_message(message) for message in items],
        total=total,
        pageNo=page_no,
        pageSize=page_size,
        hasMore=offset + len(items) < total,
    )


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除会话（消息级联删除；LangGraph checkpoint 保留不影响）。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(conv)
    db.commit()
