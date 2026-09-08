"""认证路由：注册 / 登录 / 当前用户。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserMeResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """注册：用户名唯一，密码 bcrypt 哈希落库，成功即返回 token（免二次登录）。"""
    exists = db.scalar(select(User).where(User.username == req.username))
    if exists:
        raise HTTPException(status_code=400, detail="用户名已被占用")
    user = User(username=req.username, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    return TokenResponse(token=create_access_token(user.id), username=user.username)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    """登录：校验密码后签发 JWT。"""
    user = db.scalar(select(User).where(User.username == req.username))
    if user is None or not verify_password(req.password, user.password_hash):
        # 用户不存在与密码错误返回同一文案 —— 不泄露用户名是否存在
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return TokenResponse(token=create_access_token(user.id), username=user.username)


@router.get("/me", response_model=UserMeResponse)
def me(user: User = Depends(get_current_user)):
    """解析 token 返回当前用户（前端启动时校验 token 有效性用）。"""
    return UserMeResponse(id=user.id, username=user.username)
