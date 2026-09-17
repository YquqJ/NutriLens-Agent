"""当前健康计划的读取与手动同步接口。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.models import Conversation, User
from app.db.session import get_db
from app.schemas.plan import PlanCreate, PlanOut
from app.services import plan as plan_service

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("/current", response_model=PlanOut | None)
def get_current_plan(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """读取当前启用计划；尚未生成时返回 null。"""
    return plan_service.get_active_plan(db, user.id)


@router.post("/current", response_model=PlanOut, status_code=201)
def save_current_plan(
    req: PlanCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """将历史对话中的计划正文同步为当前计划。"""
    if req.conversation_id:
        conversation = db.get(Conversation, req.conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    return plan_service.save_active_plan(
        db,
        user_id=user.id,
        content=req.content,
        conversation_id=req.conversation_id,
        title=req.title,
    )
