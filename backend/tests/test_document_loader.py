"""PDF 文本提取与章节切片的离线测试，不依赖数据库或模型服务。"""

from app.rag.document_loader import (
    KNOWLEDGE_SOURCES,
    PDF_SOURCE_PATH,
    extract_pdf_chunks,
    file_sha256,
)


def test_pdf_source_extracts_traceable_chunks():
    page_count, chunks = extract_pdf_chunks()

    assert PDF_SOURCE_PATH.is_file()
    assert page_count == 13
    assert len(chunks) >= 20
    assert all(chunk.content and chunk.page_number >= 1 for chunk in chunks)
    assert all(chunk.section and chunk.content_hash for chunk in chunks)
    assert any("蛋白质" in chunk.content for chunk in chunks)
    assert any(chunk.page_number == 13 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_pdf_source_hash_is_stable_for_same_file():
    assert file_sha256(PDF_SOURCE_PATH) == file_sha256(PDF_SOURCE_PATH)


def test_pdf_source_supports_fixed_split_experiment_mode():
    page_count, chunks = extract_pdf_chunks(split_mode="fixed")

    assert page_count == 13
    assert len(chunks) >= 20
    assert all(chunk.section.startswith("第") is False for chunk in chunks)
    assert all(chunk.section.startswith("page:") for chunk in chunks)


def test_all_registered_knowledge_sources_are_traceable_pdfs():
    assert len(KNOWLEDGE_SOURCES) == 3
    assert len({source.source_key for source in KNOWLEDGE_SOURCES}) == 3

    extracted_by_key = {}
    for source in KNOWLEDGE_SOURCES:
        assert source.path.is_file(), source.path
        page_count, chunks = extract_pdf_chunks(source.path)
        extracted_by_key[source.source_key] = chunks
        assert page_count >= 5
        assert chunks
        assert all(chunk.page_number and chunk.section for chunk in chunks)

    assert any(
        "食品标签阅读" in chunk.section
        for chunk in extracted_by_key["adult_diet_weight_management_pdf"]
    )
    assert any(
        "FITT运动处方" in chunk.section
        for chunk in extracted_by_key["exercise_recovery_safety_pdf"]
    )
