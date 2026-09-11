"""引用定位的离线测试。"""

from app.rag.citations import (
    citation_catalog,
    citation_label,
    citation_payloads,
    sanitize_citation_markers,
)


def test_citation_label_distinguishes_chunks_from_same_document():
    base = {
        "source_title": "通用营养与运动科学常识知识库",
        "section": "第二章 宏量营养素详解 / 2.2 蛋白质",
        "page_number": 2,
    }
    first = citation_label({**base, "chunk_index": 8})
    second = citation_label({**base, "chunk_index": 9})

    assert first != second
    assert "2.2 蛋白质" in first
    assert "第 2 页" in first
    assert "片段 9" in first


def test_citation_catalog_keeps_answer_indexes_stable():
    catalog = citation_catalog(
        [
            {
                "source_title": "知识库",
                "section": "第一章",
                "page_number": 1,
                "chunk_index": 0,
            },
            {
                "source_title": "知识库",
                "section": "第二章",
                "page_number": 2,
                "chunk_index": 3,
            },
        ]
    )

    assert catalog.startswith("参考来源：")
    assert "[1]" in catalog and "[2]" in catalog


def test_citation_payload_keeps_the_drawer_content_and_locator_together():
    payload = citation_payloads(
        [
            {
                "source_title": "知识库",
                "section": "第一章",
                "page_number": 1,
                "chunk_index": 0,
                "content": "可供用户核验的完整切片正文。",
            }
        ]
    )

    assert payload == [
        {
            "index": 1,
            "label": "《知识库》· 第一章 · 第 1 页 · 片段 1",
            "source_title": "知识库",
            "section": "第一章",
            "page_number": 1,
            "chunk_index": 0,
            "content": "可供用户核验的完整切片正文。",
        }
    ]


def test_sanitize_citation_markers_keeps_only_current_round_indexes():
    """模型不能把幻觉编号、页码或片段号伪装成可点击引用。"""
    citations = citation_payloads(
        [
            {"source_title": "知识库", "section": "第一章", "content": "证据一"},
            {"source_title": "知识库", "section": "第二章", "content": "证据二"},
            {"source_title": "知识库", "section": "第三章", "content": "证据三"},
            {"source_title": "知识库", "section": "第四章", "content": "证据四"},
            {"source_title": "知识库", "section": "第五章", "content": "证据五"},
            {"source_title": "知识库", "section": "第六章", "content": "证据六"},
        ]
    )

    answer = "力量训练更高效[4][9]；规律进食[2]；避免把片段号写成引用[11][13]。"

    assert sanitize_citation_markers(answer, citations) == (
        "力量训练更高效[4]；规律进食[2]；避免把片段号写成引用。"
    )
