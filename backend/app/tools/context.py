"""
工具运行时上下文：从 LangGraph 的 RunnableConfig 中提取当前用户。

背景：@tool 函数的签名由 Pydantic args schema 生成、对 LLM 可见 ——
不能把 user_id / db 这类"调用方上下文"放进参数（LLM 不该也没法填）。

LangGraph 的 ToolNode 调用工具时会透传 invoke config，
因此这里用 ensure_config() 读取 API 层 invoke 时注入的 configurable：

    graph.astream(input, config={"configurable": {
        "thread_id": conversation_id,
        "user_id": 42,        # ← 工具层从这里取
    }})

DB 会话：每次工具调用开一个短生命周期 Session（用完即关）。
工具是同步函数跑在线程池里，不存在跨协程共享连接的问题。
"""

from typing import Any

from langchain_core.runnables import ensure_config
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_current_user_id() -> int:
    """读取本次图运行绑定的用户 id（API 层注入）。"""
    config: dict[str, Any] = ensure_config()  # type: ignore[assignment]
    user_id = config.get("configurable", {}).get("user_id")
    if user_id is None:
        raise RuntimeError("工具上下文缺少 user_id —— 请检查 graph.invoke 的 config")
    return int(user_id)


def get_session() -> Session:
    """为本次工具调用创建独立的数据库会话（短事务，用完关闭）。"""
    return SessionLocal()
