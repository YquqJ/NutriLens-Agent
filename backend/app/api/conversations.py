"""会话管理路由：列表 / 新建 / 历史消息 / 删除。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
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


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拉取会话全部消息（前端切换会话时回放历史，含 agent 徽章与工具轨迹）。"""
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "image_url": m.image_url,
            "agent_name": m.agent_name,
            "tool_trace": m.tool_trace,
            "citations": m.citations,
            "created_at": m.created_at.isoformat(),
        }
        for m in conv.messages
    ]


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
