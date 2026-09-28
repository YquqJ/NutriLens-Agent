"""Langfuse 与 LangGraph 的可选集成。

将回调配置附加在图的根 RunnableConfig 上，LangChain 会把它传播到图内的
Agent、工具和模型调用。关闭开关或缺少密钥时保持完全无侵入。
"""

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_enabled() -> bool:
    return bool(
        getattr(settings, "langfuse_enabled", False)
        and getattr(settings, "langfuse_public_key", "")
        and getattr(settings, "langfuse_secret_key", "")
    )


@lru_cache
def _get_langfuse_client() -> Any:
    """初始化并缓存 Langfuse SDK 客户端。"""
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def _create_callback_handler() -> Any:
    """延迟导入 SDK，确保关闭观测时不引入运行时依赖。"""
    _get_langfuse_client()
    from langfuse.langchain import CallbackHandler

    return CallbackHandler(public_key=settings.langfuse_public_key)


def add_langfuse_observability(
    config: dict[str, Any],
    *,
    conversation_id: str,
    user_id: int,
    entrypoint: str,
) -> dict[str, Any]:
    """返回携带 Langfuse 回调与会话元数据的 RunnableConfig 副本。"""
    result = dict(config)
    if not _is_enabled():
        return result

    try:
        handler = _create_callback_handler()
    except Exception:
        logger.exception("Langfuse 回调初始化失败，本次请求将跳过追踪")
        return result

    metadata = dict(result.get("metadata") or {})
    metadata.update(
        {
            "langfuse_session_id": conversation_id,
            "langfuse_user_id": str(user_id),
            "langfuse_tags": ["nutrilens", entrypoint],
            "langfuse_trace_name": f"nutrilens.{entrypoint}",
            "conversation_id": conversation_id,
            "entrypoint": entrypoint,
        }
    )
    result["callbacks"] = [*(result.get("callbacks") or []), handler]
    result["metadata"] = metadata
    result["run_name"] = f"nutrilens.{entrypoint}"
    return result
