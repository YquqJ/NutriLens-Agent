"""
数据库初始化脚本。

职责（幂等，可重复执行）：
1. 启用 pgvector 扩展（knowledge_chunks.embedding 列依赖）；
2. 建全部业务表（Base.metadata.create_all）；
3. 建 knowledge_chunks 的 HNSW 向量索引（向量列建表后单独建索引）。

运行：uv run python -m app.db.init_db
"""

from sqlalchemy import text

from app.db.models import KnowledgeChunk
from app.db.session import Base, engine


def init_db() -> None:
    # 1. pgvector 扩展（镜像 pgvector/pgvector:pg16 已预装二进制，这里只需启用）
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 2. 建业务表（已存在的表跳过 —— 与 alembic 相比的取舍：
    #    作品集项目表结构简单、无线上数据迁移需求，create_all 够用）
    Base.metadata.create_all(engine)

    # 3. HNSW 向量索引：cosine 距离 + 内积均可，文本 embedding 惯例用 cosine
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding
                ON knowledge_chunks
                USING hnsw (embedding vector_cosine_ops)
                """
            )
        )
    print(f"数据库初始化完成（含向量索引）。表：{', '.join(sorted(Base.metadata.tables))}")


if __name__ == "__main__":
    init_db()
