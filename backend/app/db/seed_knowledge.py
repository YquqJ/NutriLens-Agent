"""
知识库 seed 脚本（M4.4）。

用法：uv run python -m app.db.seed_knowledge

流程：knowledge_data.KNOWLEDGE → embed_texts 批量向量化 → 入
knowledge_chunks 表。幂等：按 content 精确去重，已存在的跳过
（改内容属于数据修订，走删除重灌，不静默覆盖）。
"""

from sqlalchemy import select

from app.db.models import KnowledgeChunk
from app.db.session import SessionLocal
from app.rag.embedding import embed_texts
from app.rag.knowledge_data import KNOWLEDGE


def seed_knowledge() -> int:
    """把知识切片向量化并入库，返回本次新增条数。"""
    db = SessionLocal()
    try:
        existing = set(db.scalars(select(KnowledgeChunk.content)).all())
        pending = [
            (source, topic, content)
            for source, topic, content in KNOWLEDGE
            if content not in existing
        ]
        if not pending:
            return 0

        vectors = embed_texts([c for _, _, c in pending])
        db.add_all(
            KnowledgeChunk(
                content=content,
                source_title=source,
                topic=topic,
                embedding=vec,
            )
            for (source, topic, content), vec in zip(pending, vectors)
        )
        db.commit()
        return len(pending)
    finally:
        db.close()


if __name__ == "__main__":
    added = seed_knowledge()
    print(f"知识库 seed 完成：本次新增 {added} 条（已存在的跳过）")
