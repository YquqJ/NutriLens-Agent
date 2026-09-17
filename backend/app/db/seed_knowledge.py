"""知识文档导入脚本。

用法：uv run python -m app.db.seed_knowledge

流程：PDF 文本提取 → 按页码/章节切片 → 批量向量化 → 入库。导入以源文件
SHA-256 为幂等键：文件未变直接跳过；文件更新时，仅删除该文档的旧切片并重建。
首次运行还会清除没有 document_id 的历史手工 seed 切片，不影响业务表。
"""

from pathlib import Path

from sqlalchemy import delete, func, select

from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionLocal
from app.rag.embedding import embed_texts
from app.rag.document_loader import (
    KNOWLEDGE_SOURCES,
    PARSER_VERSION,
    PDF_SOURCE_KEY,
    PDF_SOURCE_PATH,
    PDF_SOURCE_TITLE,
    SplitMode,
    extract_pdf_chunks,
    file_sha256,
)


def _repository_relative_path(path: Path) -> str:
    """避免把开发机绝对路径写入数据库，保证换机器后的元数据可复现。"""
    backend_dir = Path(__file__).resolve().parents[2]
    return str(path.resolve().relative_to(backend_dir.parent.resolve())).replace("\\", "/")


def seed_knowledge(
    source_path: Path = PDF_SOURCE_PATH,
    *,
    split_mode: SplitMode = "section_aware",
    source_key: str = PDF_SOURCE_KEY,
    source_title: str = PDF_SOURCE_TITLE,
) -> int:
    """导入知识 PDF，返回本次实际新建的切片数量。"""
    source_path = source_path.resolve()
    parser_version = f"{PARSER_VERSION}:{split_mode}"
    page_count, extracted_chunks = extract_pdf_chunks(
        source_path, split_mode=split_mode
    )
    source_hash = file_sha256(source_path)
    source_path_text = _repository_relative_path(source_path)

    db = SessionLocal()
    try:
        document = db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.source_key == source_key)
        )
        # 只在首次切换来源时清理历史手工常量 seed。之后不再碰无归属切片，
        # 为将来的私有文档/测试数据保留独立的生命周期。
        if document is None:
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id.is_(None)))
        if (
            document
            and document.content_hash == source_hash
            and document.parser_version == parser_version
        ):
            current_count = db.scalar(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
            )
            if current_count:
                # 文件仅移动或重命名时内容哈希不会变化，但文档清单中的路径、
                # 标题等元数据仍应与当前注册表保持一致。
                document.source_title = source_title
                document.source_path = source_path_text
                document.source_type = "pdf"
                document.page_count = page_count
                db.commit()
                return 0

        if document is None:
            document = KnowledgeDocument(
                source_key=source_key,
                source_title=source_title,
                source_path=source_path_text,
                source_type="pdf",
                content_hash=source_hash,
                parser_version=parser_version,
                page_count=page_count,
            )
            db.add(document)
            db.flush()
        else:
            db.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
            )
            document.source_title = source_title
            document.source_path = source_path_text
            document.source_type = "pdf"
            document.content_hash = source_hash
            document.parser_version = parser_version
            document.page_count = page_count

        vectors = embed_texts([chunk.content for chunk in extracted_chunks])
        if len(vectors) != len(extracted_chunks):
            raise RuntimeError("embedding 返回数量与知识切片数量不一致")

        db.add_all(
            KnowledgeChunk(
                document_id=document.id,
                content=chunk.content,
                topic=chunk.section.split(" / ", 1)[0][:32],
                page_number=chunk.page_number,
                section=chunk.section,
                chunk_index=chunk.chunk_index,
                content_hash=chunk.content_hash,
                embedding=vector,
            )
            for chunk, vector in zip(extracted_chunks, vectors)
        )
        db.commit()
        return len(extracted_chunks)
    finally:
        db.close()


def seed_all_knowledge(*, split_mode: SplitMode = "section_aware") -> int:
    """导入注册表中的全部知识文档，返回实际新建的切片总数。"""
    return sum(
        seed_knowledge(
            source.path,
            split_mode=split_mode,
            source_key=source.source_key,
            source_title=source.source_title,
        )
        for source in KNOWLEDGE_SOURCES
    )


if __name__ == "__main__":
    added = seed_all_knowledge()
    print(f"知识库 PDF 导入完成：本次新增 {added} 条（未变化文档自动跳过）")
