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


def _migrate_knowledge_schema() -> None:
    """为已有开发数据库补齐知识文档关联。

    项目尚未引入 Alembic；这里仅覆盖本次知识库表的向前兼容。不会删除用户、
    会话或健康记录。source_title 已迁移到 knowledge_documents，切片表只保留
    文档外键与定位信息，避免来源标题在每个切片重复存储。
    """
    statements = (
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS document_id INTEGER",
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER",
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS section VARCHAR(256)",
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS chunk_index INTEGER",
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)",
        "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document ON knowledge_chunks (document_id)",
        # 新库由 SQLAlchemy 自动创建默认外键名；早期本迁移曾使用显式名，
        # 先删除该兼容名，避免同一列出现两条等价外键约束。
        "ALTER TABLE knowledge_chunks DROP CONSTRAINT IF EXISTS fk_knowledge_chunks_document",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'knowledge_chunks'::regclass
                  AND confrelid = 'knowledge_documents'::regclass
                  AND contype = 'f'
            ) THEN
                ALTER TABLE knowledge_chunks
                ADD CONSTRAINT fk_knowledge_chunks_document
                FOREIGN KEY (document_id) REFERENCES knowledge_documents(id)
                ON DELETE CASCADE;
            END IF;
        END $$
        """,
        # source_title 是旧手工 seed 的反范式字段；正式来源统一从 document 关联读取。
        "ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS source_title",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_knowledge_chunks_document_hash'
            ) THEN
                ALTER TABLE knowledge_chunks
                ADD CONSTRAINT uq_knowledge_chunks_document_hash
                UNIQUE (document_id, content_hash);
            END IF;
        END $$
        """,
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _migrate_message_schema() -> None:
    """为历史消息补充参与 agent、引用与性能指标，旧字段保持可空兼容。"""
    with engine.begin() as conn:
        for statement in (
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS citations TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS agent_names TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS duration_ms INTEGER",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS input_tokens INTEGER",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS output_tokens INTEGER",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS total_tokens INTEGER",
        ):
            conn.execute(text(statement))


def _migrate_conversation_schema() -> None:
    """为挂起确认的会话补充待合并性能指标。"""
    with engine.begin() as conn:
        for statement in (
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_duration_ms INTEGER",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_input_tokens INTEGER",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_output_tokens INTEGER",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS pending_total_tokens INTEGER",
        ):
            conn.execute(text(statement))


def init_db() -> None:
    # 1. pgvector 扩展（镜像 pgvector/pgvector:pg16 已预装二进制，这里只需启用）
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # 2. 建业务表（已存在的表跳过 —— 与 alembic 相比的取舍：
    Base.metadata.create_all(engine)
    _migrate_knowledge_schema()
    _migrate_conversation_schema()
    _migrate_message_schema()

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
