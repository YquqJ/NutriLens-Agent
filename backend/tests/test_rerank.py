"""
重排测试（M4.3）。E2E：真实 DashScope 原生 rerank API。
"""

import uuid

import pytest

from app.core.config import settings
from app.db.models import KnowledgeChunk
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
        chunks = [
            KnowledgeChunk(
                content=c,
                source_title=f"测试文档_{i}",
                topic=f"test_{uuid.uuid4().hex[:8]}",
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
        db.commit()
        db.close()
