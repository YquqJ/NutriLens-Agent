"""运行 RAG 检索消融及端到端回答质量对比。"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import KnowledgeChunk
from app.db.seed_knowledge import seed_all_knowledge
from app.db.session import SessionLocal
from app.rag.eval import load_eval_queries, run_ablation
from app.rag.qa_eval import run_qa_judge_eval

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_EVAL_DATA = _BACKEND_DIR / "tests" / "eval_data" / "rag_queries_v3.json"
_DEFAULT_OUTPUT = _BACKEND_DIR / "reports" / "rag-eval-v3.json"
_COMPARISON_METRICS = ("recall@4", "mrr", "ndcg@4")
_QUALITY_METRICS = ("faithfulness", "answer_relevance")


def validate_query_count(queries: list[dict[str, Any]], limit: int | None = None) -> None:
    """Full run must use exactly 100 queries; --limit explicitly enables smoke runs."""
    expected = limit if limit is not None else 100
    if len(queries) != expected:
        raise ValueError(f"评测 query 数量应为恰好 {expected} 条，实际为 {len(queries)} 条")


def _metric_comparison(baseline: float | None, current: float | None) -> dict[str, Any]:
    delta = current - baseline if baseline is not None and current is not None else None
    return {
        "vector": baseline,
        "hybrid_rerank": current,
        "delta": delta,
        "delta_percentage_points": delta * 100 if delta is not None else None,
        "relative_improvement_percent": (
            delta / baseline * 100
            if delta is not None and baseline not in (None, 0)
            else None
        ),
    }


def build_comparison_report(
    *, retrieval: dict[str, Any], answer_quality: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """把基线和当前方案并列，并计算绝对百分点及相对提升。"""
    retrieval_modes = retrieval.get("results", {})
    return {
        "schema_version": "rag-full-eval-v1",
        "comparison": {
            "baseline": "vector",
            "current": "hybrid_rerank",
            "retrieval": {
                metric: _metric_comparison(
                    retrieval_modes.get("vector", {}).get("metrics", {}).get(metric),
                    retrieval_modes.get("hybrid_rerank", {}).get("metrics", {}).get(metric),
                )
                for metric in _COMPARISON_METRICS
            },
            "answer_quality": {
                metric: _metric_comparison(
                    answer_quality.get("vector", {}).get("metrics", {}).get(metric),
                    answer_quality.get("hybrid_rerank", {}).get("metrics", {}).get(metric),
                )
                for metric in _QUALITY_METRICS
            },
        },
        "retrieval_ablation": retrieval,
        "answer_quality_eval": answer_quality,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 NutriLens 100-query RAG 全量评测")
    parser.add_argument("--eval-data", type=Path, default=_DEFAULT_EVAL_DATA)
    parser.add_argument("--limit", type=int, help="小批量冒烟评测；完整评测应省略此参数")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        parser.error("未配置 DASHSCOPE_API_KEY")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须至少为 1")
    if args.top_k < 4:
        parser.error("--top-k 必须至少为 4，才能计算 Recall@4")

    eval_data = args.eval_data.resolve()
    queries = load_eval_queries(eval_data)
    if args.limit is not None:
        queries = queries[: args.limit]
    try:
        validate_query_count(queries, args.limit)
    except ValueError as exc:
        parser.error(str(exc))

    dataset_version = json.loads(eval_data.read_text(encoding="utf-8")).get(
        "schema_version", "unspecified"
    )
    seeded = seed_all_knowledge()
    db = SessionLocal()
    try:
        retrieval = run_ablation(db, queries, top_k=args.top_k)
        total_chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    finally:
        db.close()

    answer_quality = {
        mode: run_qa_judge_eval(
            queries,
            dataset_version=dataset_version,
            retrieval_mode=mode,
        )
        for mode in ("vector", "hybrid_rerank")
    }
    report = build_comparison_report(
        retrieval=retrieval, answer_quality=answer_quality
    )
    report["metadata"] = {
        "dataset_version": dataset_version,
        "dataset_path": str(eval_data),
        "query_count": len(queries),
        "top_k": args.top_k,
        "seeded_chunks": seeded,
        "total_chunks": total_chunks,
        "generation_model": settings.text_model,
        "judge_model": settings.text_model,
    }

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["comparison"], ensure_ascii=False, indent=2))
    print(f"完整报告已写入：{output}")
    if any(result["n_failed"] for result in answer_quality.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
