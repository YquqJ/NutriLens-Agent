"""PDF 文本提取与章节切片的离线测试，不依赖数据库或模型服务。"""

from app.rag.document_loader import PDF_SOURCE_PATH, extract_pdf_chunks, file_sha256


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
