"""健康计划的归档与读取服务。"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Plan


def _title_from_content(content: str) -> str:
    """从计划正文提取一个稳定、适合列表展示的标题。"""
    for line in content.splitlines():
        value = line.strip().lstrip("#*- ").strip()
        if value:
            return value[:128]
    return "个性化健康计划"


def get_active_plan(db: Session, user_id: int) -> Plan | None:
    """返回用户最新启用的计划，没有则返回 None。"""
    return db.scalar(
        select(Plan)
        .where(Plan.user_id == user_id, Plan.is_active.is_(True))
        .order_by(Plan.updated_at.desc(), Plan.id.desc())
    )


def save_active_plan(
    db: Session,
    *,
    user_id: int,
    content: str,
    conversation_id: str | None = None,
    title: str | None = None,
) -> Plan:
    """将最新计划设为当前计划，并保留此前计划作为历史版本。"""
    db.execute(
        update(Plan)
        .where(Plan.user_id == user_id, Plan.is_active.is_(True))
        .values(is_active=False)
    )
    plan = Plan(
        user_id=user_id,
        conversation_id=conversation_id,
        title=(title or _title_from_content(content))[:128],
        content=content.strip(),
        is_active=True,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan
