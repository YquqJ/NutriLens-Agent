"""FastAPI 依赖注入：从请求头解析 JWT → 当前用户。"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import User
from app.db.session import get_db

# auto_error=False：token 缺失时不自动 403，由本依赖统一抛 401（语义更准）
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    校验 `Authorization: Bearer <jwt>` 并加载用户。
    任何 REST 路由需要登录时：`user: User = Depends(get_current_user)`。
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或未登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise unauthorized

    user = db.get(User, user_id)
    if user is None:  # token 有效但用户已删（如测试数据被清理）
        raise unauthorized
    return user
