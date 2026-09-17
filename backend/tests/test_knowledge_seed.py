"""
知识库 seed 测试（M4.4）。

验收（SPEC 相关）：seed 后 retrieve 能召回领域切片（M4.5 qa_agent 的
验收问题"减脂期每天吃多少蛋白质"应稳定命中蛋白质相关切片）。
"""

import pytest

from app.core.config import settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.seed_knowledge import seed_knowledge
from app.db.session import SessionLocal
from app.rag.document_loader import PDF_SOURCE_KEY
from app.rag.retriever import retrieve


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_knowledge_seed_and_retrieve():
    # 幂等：第二遍 0 新增
    first = seed_knowledge()
    second = seed_knowledge()
    assert second == 0

    db = SessionLocal()
    try:
        document = (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.source_key == PDF_SOURCE_KEY)
            .one()
        )
        chunks = db.query(KnowledgeChunk).filter_by(document_id=document.id).all()
        assert len(chunks) >= 20, "PDF 应生成足量知识切片"
        assert all(chunk.page_number and chunk.section for chunk in chunks)
        assert document.page_count == 13

        # SPEC M4.5 验收问题：应命中蛋白质相关切片
        results = retrieve(db, "减脂期每天吃多少蛋白质", top_k=3)
        assert results, "应有召回"
        assert any("蛋白质" in r["content"] for r in results)
        # 来源可见（回答引用的依据）
        assert all(
            r["source_title"] and r["page_number"] and r["section"]
            for r in results
        )
    finally:
        db.close()
