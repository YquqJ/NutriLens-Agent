"""完整 RAG 基线对比报告的指标差值与数据集规模校验。"""

from pathlib import Path

import pytest

from app.rag.eval import load_eval_queries
from app.rag.run_full_eval import build_comparison_report, validate_query_count


def test_comparison_report_reports_absolute_and_relative_lift():
    report = build_comparison_report(
        retrieval={
            "results": {
                "vector": {"metrics": {"recall@4": 0.5, "mrr": 0.4}},
                "hybrid_rerank": {"metrics": {"recall@4": 0.75, "mrr": 0.6}},
            }
        },
        answer_quality={
            "vector": {
                "metrics": {"faithfulness": 0.8, "answer_relevance": 0.7}
            },
            "hybrid_rerank": {
                "metrics": {"faithfulness": 0.9, "answer_relevance": 0.8}
            },
        },
    )

    assert report["comparison"]["retrieval"]["recall@4"] == {
        "vector": 0.5,
        "hybrid_rerank": 0.75,
        "delta": 0.25,
        "delta_percentage_points": 25.0,
        "relative_improvement_percent": 50.0,
    }
    assert report["comparison"]["answer_quality"]["faithfulness"]["delta"] == pytest.approx(0.1)


def test_validate_query_count_requires_exactly_one_hundred_by_default():
    with pytest.raises(ValueError, match="恰好 100 条"):
        validate_query_count([{"query": str(i)} for i in range(99)])

    validate_query_count([{"query": str(i)} for i in range(100)])
    validate_query_count([{"query": str(i)} for i in range(3)], limit=3)


def test_v3_dataset_has_one_hundred_unique_queries_and_covers_all_sources():
    dataset = Path(__file__).parent / "eval_data" / "rag_queries_v3.json"
    queries = load_eval_queries(dataset)
    sources = {
        evidence["source_key"]
        for query in queries
        for evidence in query["relevant_evidence"]
    }

    assert len(queries) == 100
    assert len({query["query"] for query in queries}) == 100
    assert len(sources) == 8
