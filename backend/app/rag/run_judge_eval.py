"""命令行运行端到端 RAG LLM-as-Judge 评测。

用法：uv run python -m app.rag.run_judge_eval [--eval-data tests/eval_data/rag_queries_v2.json]
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.db.seed_knowledge import seed_all_knowledge
from app.rag.eval import load_eval_queries
from app.rag.qa_eval import run_qa_judge_eval

_EVAL_DATA = Path(__file__).resolve().parents[2] / "tests" / "eval_data" / "rag_queries_v2.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 NutriLens RAG LLM-as-Judge 评测")
    parser.add_argument(
        "--eval-data",
        type=Path,
        default=_EVAL_DATA,
        help="Golden Dataset JSON 路径",
    )
    parser.add_argument("--limit", type=int, help="最多评测的问题数")
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        parser.error("未配置 DASHSCOPE_API_KEY")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须至少为 1")

    eval_data = args.eval_data.resolve()
    queries = load_eval_queries(eval_data)
    dataset_version = json.loads(eval_data.read_text(encoding="utf-8")).get(
        "schema_version", "unspecified"
    )
    if args.limit is not None:
        queries = queries[: args.limit]
    if not queries:
        parser.error("评测集为空")

    seeded = seed_all_knowledge()
    report = run_qa_judge_eval(queries, dataset_version=dataset_version)
    report["metadata"] = {
        "dataset": str(eval_data),
        "seeded_chunks": seeded,
        "generation_model": settings.text_model,
    }
    # Windows 传统控制台可能仍使用 GBK；ASCII 转义 JSON 可保证报告稳定落盘/管道传输。
    print(json.dumps(report, ensure_ascii=True, indent=2))
    if report["n_failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
