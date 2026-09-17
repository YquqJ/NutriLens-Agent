"""命令行运行 RAG 检索消融评测。

用法：
    uv run python -m app.rag.run_ablation
    uv run python -m app.rag.run_ablation --split-mode fixed

真实 embedding、数据库和 rerank 需要按项目配置提供外部服务；输出 JSON
便于保存成一次可复现的实验报告。
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from app.db.models import KnowledgeChunk
from app.db.seed_knowledge import seed_all_knowledge
from app.db.session import SessionLocal
from app.rag.eval import load_eval_queries, run_ablation


_EVAL_DATA = Path(__file__).resolve().parents[2] / "tests" / "eval_data" / "rag_queries.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 NutriLens RAG 消融评测")
    parser.add_argument(
        "--split-mode",
        choices=("section_aware", "fixed"),
        default="section_aware",
        help="导入知识库时的切分策略",
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--eval-data",
        type=Path,
        default=_EVAL_DATA,
        help="Golden Dataset JSON 路径（相对当前工作目录或绝对路径）",
    )
    args = parser.parse_args()

    eval_data = args.eval_data.resolve()
    queries = load_eval_queries(eval_data)
    seeded = seed_all_knowledge(split_mode=args.split_mode)
    db = SessionLocal()
    try:
        report = run_ablation(db, queries, top_k=args.top_k)
        total_chunks = db.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    finally:
        db.close()

    report["metadata"] = {
        "split_mode": args.split_mode,
        "seeded_chunks": seeded,
        "total_chunks": total_chunks,
        "eval_data": str(eval_data.relative_to(_EVAL_DATA.parents[2])).replace("\\", "/"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
