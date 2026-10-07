"""
重排测试（M4.3）。E2E：真实 DashScope 原生 rerank API。
"""

import uuid

import pytest

from app.core.config import settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.rag.embedding import embed_texts
from app.rag.rerank import rerank
from app.rag.retriever import retrieve

_DOCS = [
    "维生素 C 是水溶性维生素，柑橘类水果含量丰富。",
    "减脂期间每公斤体重摄入 1.6-2.2 克蛋白质，可保留瘦体重。",
    "深蹲是训练下肢肌群的复合动作。",
    "橄榄油富含单不饱和脂肪酸。",
]


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_rerank_relevant_first():
    """与 query 最相关的文档应排第一（index 对应原始下标）。"""
    results = rerank("减脂期蛋白质摄入量", _DOCS, top_n=4)
    assert results[0][0] == 1  # 蛋白质那条
    assert results[0][1] > 0
    # 分数降序
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_retrieve_pipeline_with_rerank():
    """组合管线：临时切片入库 → retrieve 应把最相关切片排最前。"""
    db = SessionLocal()
    vectors = embed_texts(_DOCS)
    try:
        document = KnowledgeDocument(
            source_key=f"test_rerank_{uuid.uuid4().hex}",
            source_title="重排测试文档",
            source_path="tests://rerank",
            source_type="test",
            content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            parser_version="test",
            page_count=1,
        )
        db.add(document)
        db.flush()
        chunks = [
            KnowledgeChunk(
                document_id=document.id,
                content=c,
                topic=f"test_{uuid.uuid4().hex[:8]}",
                page_number=1,
                section=f"测试章节_{i}",
                chunk_index=i,
                content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                embedding=v,
            )
            for i, (c, v) in enumerate(zip(_DOCS, vectors))
        ]
        db.add_all(chunks)
        db.commit()

        results = retrieve(db, "减脂期蛋白质摄入量", top_k=3)
        assert results, "应召回切片"
        assert "蛋白质" in results[0]["content"]
        assert "relevance_score" in results[0]
        assert results[0]["source_title"]
    finally:
        db.query(KnowledgeChunk).filter(
            KnowledgeChunk.id.in_([c.id for c in chunks])
        ).delete(synchronize_session=False)
        db.delete(document)
        db.commit()
        db.close()
import httpx
import pytest

from app.rag import rerank as rerank_module


def test_rerank_retries_rate_limit_with_exponential_backoff(monkeypatch):
    request = httpx.Request("POST", rerank_module._RERANK_URL)
    responses = [
        httpx.Response(429, request=request),
        httpx.Response(
            200,
            request=request,
            json={"output": {"results": [{"index": 0, "relevance_score": 0.91}]}},
        ),
    ]
    calls = []
    delays = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr(rerank_module.httpx, "post", fake_post)
    monkeypatch.setattr(rerank_module.time, "sleep", delays.append)
    monkeypatch.setattr(rerank_module.random, "uniform", lambda _low, high: high)

    result = rerank_module.rerank("牛肉面", ["牛肉面营养信息"], top_n=1)

    assert result == [(0, 0.91)]
    assert len(calls) == 2
    assert delays == [0.5]


def test_rerank_does_not_retry_non_retryable_client_error(monkeypatch):
    request = httpx.Request("POST", rerank_module._RERANK_URL)
    calls = []
    delays = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return httpx.Response(400, request=request)

    monkeypatch.setattr(rerank_module.httpx, "post", fake_post)
    monkeypatch.setattr(rerank_module.time, "sleep", delays.append)

    with pytest.raises(httpx.HTTPStatusError):
        rerank_module.rerank("牛肉面", ["牛肉面营养信息"], top_n=1)

    assert len(calls) == 1
    assert delays == []

