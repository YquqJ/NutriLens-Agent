"""
Embedding 客户端（M4.1）。

text-embedding-v3 走 DashScope 的 OpenAI 兼容模式（/embeddings 端点），
直接复用 openai SDK —— 与 LLM 调用通道统一（同一 base_url + key），
区别只在端点路径与返回结构。

设计要点：
- dimensions=1024 显式传参，与 KnowledgeChunk.embedding 的 Vector(1024)
  列对齐（text-embedding-v3 支持 64-1024 可选维度，不传默认 1024，
  显式写死避免模型侧默认值变化时静默错位）；
- 单批上限 10 条（DashScope embeddings 端点限制），批量入库自动分批；
- 返回按 index 排序 —— SDK 不保证 data 顺序与输入一致，乱序向量
  入库后检索结果会张冠李戴，这类 bug 极难排查。
"""

from functools import lru_cache
from typing import Sequence

from openai import OpenAI

from app.core.config import settings

# DashScope embeddings 端点单次请求的文本条数上限
_BATCH_SIZE = 10
_DIMENSIONS = 1024


@lru_cache
def _client() -> OpenAI:
    """进程级客户端单例（线程安全，连接池复用）。"""
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        # 检索入口也会调用 embedding；若这里无限等待，即使 ChatOpenAI
        # 有超时，qa_agent 仍会在生成前卡住。
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    )


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """批量 embedding：texts → 向量列表（顺序与输入一一对应）。"""
    if not texts:
        return []
    client = _client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = list(texts[i : i + _BATCH_SIZE])
        resp = client.embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=_DIMENSIONS,
        )
        # 按 index 排序还原输入顺序（防端点乱序返回）
        vectors.extend(d.embedding for d in sorted(resp.data, key=lambda d: d.index))
    return vectors


def embed_query(text: str) -> list[float]:
    """单条查询文本的 embedding（检索路的输入）。"""
    return embed_texts([text])[0]
