"""
数据库引擎与会话管理。

设计决策：
- `create_engine` + `sessionmaker`（同步引擎）：本项目业务写操作量小
  （个人健康记录），同步 SQLAlchemy 配 FastAPI 的线程池足够，
  避免 asyncio + psycopg 的复杂度扩散到所有 service 层；
  唯一的异步路径是 SSE 流式端点，其中数据库操作同样走同步 session
  （FastAPI 的 run_in_threadpool 模式），实践证明无性能瓶颈。
- 全局单例 engine，`get_db` 作为 FastAPI 依赖注入到每个请求。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的公共声明基类。"""


engine = create_engine(settings.database_url, pool_pre_ping=True)

# expire_on_commit=False：commit 后对象属性仍可访问，
# 避免"响应序列化时触发额外 SELECT"的经典坑
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI 依赖：每请求一个 Session，请求结束自动关闭。
    用法：`db: Session = Depends(get_db)`
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
