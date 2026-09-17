"""Golden evidence 必须独立于具体的文档切分策略。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.rag.document_loader import (
    KNOWLEDGE_SOURCES,
    PDF_SOURCE_KEY,
    extract_pdf_chunks,
)
from app.rag.eval import load_eval_queries, resolve_relevant_ids


_EVAL_DATA = Path(__file__).parent / "eval_data" / "rag_queries.json"
_EVAL_DATA_V2 = Path(__file__).parent / "eval_data" / "rag_queries_v2.json"


def test_resolve_relevant_ids_normalizes_whitespace_and_checks_page():
    chunks = [
        SimpleNamespace(
            id=11,
            page_number=1,
            content_hash="hash-11",
            content="标题\n体重变化 = 能量摄入 - 能量消耗。",
        ),
        SimpleNamespace(
            id=12,
            page_number=2,
            content_hash="hash-12",
            content="体重变化 = 能量摄入 - 能量消耗。",
        ),
    ]
    query = {
        "query": "体重为什么变化？",
        "relevant_evidence": [
            {
                "page_number": 1,
                "text": "体重变化 = 能量摄入  -  能量消耗。",
            }
        ],
    }

    assert resolve_relevant_ids(chunks, query) == {11}


def test_resolve_relevant_ids_rejects_unmatched_evidence():
    chunks = [
        SimpleNamespace(
            id=11,
            page_number=1,
            content_hash="hash-11",
            content="现有知识内容",
        )
    ]
    query = {
        "query": "缺失证据的问题",
        "relevant_evidence": [{"page_number": 1, "text": "不存在的证据"}],
    }

    with pytest.raises(ValueError, match="缺失证据的问题"):
        resolve_relevant_ids(chunks, query)


def test_resolve_relevant_ids_uses_source_key_for_multi_document_corpus():
    chunks = [
        SimpleNamespace(
            id=11,
            source_key="diet_pdf",
            page_number=2,
            content_hash="diet-hash",
            content="相同页面中的稳定证据文本",
        ),
        SimpleNamespace(
            id=12,
            source_key="exercise_pdf",
            page_number=2,
            content_hash="exercise-hash",
            content="相同页面中的稳定证据文本",
        ),
    ]
    query = {
        "query": "证据来自哪份文档？",
        "relevant_evidence": [
            {
                "source_key": "exercise_pdf",
                "page_number": 2,
                "text": "稳定证据文本",
            }
        ],
    }

    assert resolve_relevant_ids(chunks, query) == {12}


def test_load_eval_queries_composes_included_datasets(tmp_path):
    base = tmp_path / "base.json"
    base.write_text(
        json.dumps(
                {
                    "default_source_key": "base_pdf",
                    "evidence": {
                    "base_fact": {"page_number": 1, "text": "基础证据"}
                },
                "queries": [
                    {
                        "query": "基础问题",
                        "relevant_evidence_ids": ["base_fact"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    child = tmp_path / "child.json"
    child.write_text(
        json.dumps(
            {
                "includes": ["base.json"],
                "evidence": {
                    "child_fact": {"page_number": 2, "text": "新增证据"}
                },
                "queries": [
                    {
                        "query": "新增问题",
                        "relevant_evidence_ids": ["child_fact"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    queries = load_eval_queries(child)

    assert [query["query"] for query in queries] == ["基础问题", "新增问题"]
    assert queries[0]["relevant_evidence"][0]["text"] == "基础证据"
    assert queries[0]["relevant_evidence"][0]["source_key"] == "base_pdf"
    assert queries[1]["relevant_evidence"][0]["text"] == "新增证据"


@pytest.mark.parametrize("split_mode", ["fixed", "section_aware"])
def test_eval_dataset_resolves_under_each_split_mode(split_mode):
    queries = load_eval_queries(_EVAL_DATA)
    _, extracted = extract_pdf_chunks(split_mode=split_mode)
    chunks = [
        SimpleNamespace(
            id=index,
            source_key=PDF_SOURCE_KEY,
            page_number=chunk.page_number,
            content_hash=chunk.content_hash,
            content=chunk.content,
        )
        for index, chunk in enumerate(extracted, start=1)
    ]

    positive_queries = [q for q in queries if q["relevant_evidence"]]

    assert len(positive_queries) == 42
    for query in positive_queries:
        assert resolve_relevant_ids(chunks, query), query["query"]


@pytest.mark.parametrize("split_mode", ["fixed", "section_aware"])
def test_multi_document_eval_dataset_resolves_under_each_split_mode(split_mode):
    queries = load_eval_queries(_EVAL_DATA_V2)
    chunks = []
    chunk_id = 1
    for source in KNOWLEDGE_SOURCES:
        _, extracted = extract_pdf_chunks(source.path, split_mode=split_mode)
        for chunk in extracted:
            chunks.append(
                SimpleNamespace(
                    id=chunk_id,
                    source_key=source.source_key,
                    page_number=chunk.page_number,
                    content_hash=chunk.content_hash,
                    content=chunk.content,
                )
            )
            chunk_id += 1

    positive_queries = [q for q in queries if q["relevant_evidence"]]

    assert len(queries) == 37
    assert len(positive_queries) == 32
    for query in positive_queries:
        assert resolve_relevant_ids(chunks, query), query["query"]
