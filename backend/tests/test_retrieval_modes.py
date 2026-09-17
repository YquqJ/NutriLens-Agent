from types import SimpleNamespace

import pytest

from app.rag import eval as rag_eval
from app.rag import retriever


def _chunk(content: str = "内容"):
    return SimpleNamespace(
        id=7,
        document_id=3,
        content=content,
        topic="主题",
        page_number=2,
        section="第一章 / 1.1",
        chunk_index=0,
        document=SimpleNamespace(source_key="test_pdf", source_title="测试文档"),
    )


def test_retrieve_by_mode_vector_normalizes_chunk(monkeypatch):
    chunk = _chunk("向量结果")
    monkeypatch.setattr(retriever, "embed_query", lambda query: [0.1, 0.2])
    monkeypatch.setattr(retriever, "vector_search", lambda db, vec, k: [chunk])

    results = retriever.retrieve_by_mode(object(), "怎么减脂", top_k=3, mode="vector")

    assert results[0]["id"] == 7
    assert results[0]["content"] == "向量结果"
    assert results[0]["source_key"] == "test_pdf"
    assert results[0]["source_title"] == "测试文档"
    assert "rrf_score" not in results[0]


def test_retrieve_by_mode_hybrid_rerank_uses_rerank(monkeypatch):
    candidates = [{"id": 7, "content": "候选", "source_title": "文档"}]
    monkeypatch.setattr(retriever, "hybrid_search", lambda db, query, top_k: candidates)
    monkeypatch.setattr(
        retriever,
        "rerank",
        lambda query, docs, top_n: [(0, 0.93)],
        raising=False,
    )

    results = retriever.retrieve_by_mode(
        object(), "问题", top_k=1, mode="hybrid_rerank"
    )

    assert results[0]["id"] == 7
    assert results[0]["relevance_score"] == pytest.approx(0.93)


def test_retrieve_by_mode_rejects_unknown_mode():
    with pytest.raises(ValueError, match="未知检索模式"):
        retriever.retrieve_by_mode(object(), "问题", top_k=3, mode="unknown")


def test_run_ablation_calls_each_mode_and_returns_comparable_reports(monkeypatch):
    calls = []

    def fake_run_eval(db, queries, *, mode, **kwargs):
        calls.append(mode)
        return {"mode": mode, "n_positive": 1, "metrics": {"recall@8": 0.5}}

    monkeypatch.setattr(rag_eval, "run_eval", fake_run_eval)
    report = rag_eval.run_ablation(
        object(), [{"query": "问题", "relevant_hashes": ["hash"]}],
        modes=["vector", "hybrid_rrf", "hybrid_rerank"],
    )

    assert calls == ["vector", "hybrid_rrf", "hybrid_rerank"]
    assert list(report["results"]) == ["vector", "hybrid_rrf", "hybrid_rerank"]
    assert report["results"]["hybrid_rrf"]["metrics"]["recall@8"] == 0.5
