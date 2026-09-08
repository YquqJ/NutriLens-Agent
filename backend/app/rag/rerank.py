"""
重排（M4.3）：gte-rerank-v2，DashScope 原生 API。

为什么不用 OpenAI 兼容模式：rerank 是非生成式任务，OpenAI 协议里
没有对应端点，DashScope 只提供原生 REST 接口
（/api/v1/services/rerank/text-rerank/text-rerank）——这是本项目
唯一一处绕开兼容模式的地方，HTTP 客户端用 httpx（openai SDK 的
传递依赖，不新增包）。

在检索管线中的位置（M4.2 → M4.3 → 生成）：
    混合检索（召回，粗排，求全）→ rerank（精排，求准）→ 喂给 LLM
粗排召回 10 条保证不漏，精排按与 query 的语义相关度重排序取前 5。
"""

import httpx

from app.core.config import settings

_RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)


def rerank(
    query: str, documents: list[str], top_n: int = 5
) -> list[tuple[int, float]]:
    """
    对 documents 按 query 相关度重排。

    返回 [(documents 原始下标, relevance_score)]，按分数降序、截取 top_n。
    调用方持有完整文档列表，用下标回取即可——重排端点只收纯文本，
    结构化元数据（来源等）留在调用侧，不随请求往返。
    """
    resp = httpx.post(
        _RERANK_URL,
        headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
        json={
            "model": settings.rerank_model,
            "input": {"query": query, "documents": documents},
            "parameters": {"return_documents": False, "top_n": top_n},
        },
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()["output"]["results"]
    return [(r["index"], r["relevance_score"]) for r in results]
