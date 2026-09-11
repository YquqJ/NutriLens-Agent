"""
混合检索测试（M4.2）。E2E：真实 embedding API + 真实 DB（临时切片）。
"""

import uuid

import pytest

from app.core.config import settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.rag.embedding import embed_texts
from app.rag.retriever import hybrid_search, keyword_search, vector_search

# 临时知识切片：主题刻意分散，验证语义/字面两路的互补
_CHUNKS = [
    ("减脂期建议保持每日 300-500 千卡的热量缺口，逐步降低体脂率，避免过度节食。", "减脂指南"),
    ("减脂期间每公斤体重摄入 1.6-2.2 克蛋白质，可在热量受限时最大限度保留瘦体重。", "减脂指南"),
    ("深蹲、硬拉、卧推是力量训练三大项，建议每周安排 2-3 次抗阻训练。", "力量训练入门"),
    ("维生素 C 是水溶性维生素，成人每日推荐摄入 100 毫克，柑橘类水果含量丰富。", "微量营养素手册"),
    ("有氧运动持续 30 分钟以上可显著提升心肺耐力，心率控制在最大心率的 60%-80%。", "有氧运动指南"),
    ("BM25 是基于词频的经典检索算法，与向量检索互补，常用于混合检索的关键词路。", "检索技术概论"),
]


@pytest.fixture
def seeded_chunks():
    """插入临时切片（带真实向量），用例结束清理。"""
    db = SessionLocal()
    contents = [c for c, _ in _CHUNKS]
    vectors = embed_texts(contents)  # 未配 key 时这里会失败——整个文件都有 skipif 守卫
    try:
        document = KnowledgeDocument(
            source_key=f"test_retriever_{uuid.uuid4().hex}",
            source_title="检索测试文档",
            source_path="tests://retriever",
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
                content=content,
                topic=f"test_{uuid.uuid4().hex[:8]}",
                page_number=1,
                section=source,
                chunk_index=index,
                content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                embedding=vec,
            )
            for index, ((content, source), vec) in enumerate(zip(_CHUNKS, vectors))
        ]
        db.add_all(chunks)
        db.commit()
        ids = [c.id for c in chunks]
        yield ids
    finally:
        db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(ids)).delete(
            synchronize_session=False
        )
        db.delete(document)
        db.commit()
        db.close()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_vector_path_semantic_recall(seeded_chunks):
    """向量路：语义改写（'怎么才能瘦下来'）应召回减脂主题切片。"""
    db = SessionLocal()
    try:
        from app.rag.embedding import embed_query

        hits = vector_search(db, embed_query("怎么才能瘦下来"), 3)
        assert any("热量缺口" in h.content or "减脂" in h.document.source_title for h in hits)
    finally:
        db.close()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_keyword_path_literal_match(seeded_chunks):
    """关键词路：精确字面（'BM25'）应命中检索技术切片。"""
    db = SessionLocal()
    try:
        hits = keyword_search(db, "BM25 算法", 3)
        assert hits and "BM25" in hits[0].content
    finally:
        db.close()


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_hybrid_fusion(seeded_chunks):
    """融合路：两路都能召回的目标切片排最前，且带 rrf_score 与 ranked_by。"""
    db = SessionLocal()
    try:
        results = hybrid_search(db, "减脂期每天吃多少蛋白质", top_k=3)
        assert results, "应至少召回一条"
        assert "蛋白质" in results[0]["content"] or "减脂" in results[0]["source_title"]
        # 融合元数据完整（qa_agent 检索轨迹与调试依赖）
        assert results[0]["rrf_score"] > 0
        assert results[0]["ranked_by"]
        assert results[0]["section"] and results[0]["chunk_index"] is not None
    finally:
        db.close()
