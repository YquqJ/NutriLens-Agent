"""
JWT 签发/校验 与 密码哈希。

技术选型说明（面试口径）：
- 密码哈希用 bcrypt 官方库而非 passlib：passlib 1.7.4 与 bcrypt>=4.0 存在
  已知的兼容性问题（`__about__` 属性缺失导致告警且长期未维护）；
- JWT 用 PyJWT（轻量、无额外依赖），负载中只放 user_id 与过期时间，
  不放敏感信息。
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# JWT 算法与签发者（校验时要求一致，防止跨服务混用）
_ALGORITHM = "HS256"
_ISSUER = "nutrilens"


def hash_password(plain: str) -> str:
    """明文密码 → bcrypt 哈希。bcrypt 自带随机盐，无需额外处理。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与存储的 bcrypt 哈希是否匹配。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # 哈希格式非法时按不匹配处理，而不是抛异常（防止恶意构造的哈希打崩接口）
        return False


def create_access_token(user_id: int) -> str:
    """签发 JWT。负载：用户 id、过期时间、签发者。"""
    payload = {
        "sub": str(user_id),
        "iss": _ISSUER,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """校验 JWT 并返回 user_id；无效/过期返回 None（由调用方决定 401）。"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
        )
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
