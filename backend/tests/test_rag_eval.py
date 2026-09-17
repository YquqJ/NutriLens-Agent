"""RAG 真实评测（E2E）：真实 embedding + pgvector，跑 Recall@K / MRR / nDCG。

用 `uv run pytest -m eval` 显式触发（日常 pytest 不跑）；未配 DASHSCOPE_API_KEY
时自动跳过。首版只做宽松 smoke 断言，严格阈值待真实基线出来后追加。
"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.db.seed_knowledge import seed_knowledge
from app.db.session import SessionLocal
from app.rag.eval import load_eval_queries, run_eval

_EVAL_DATA = Path(__file__).parent / "eval_data" / "rag_queries.json"

pytestmark = pytest.mark.eval


def _load_queries() -> list[dict]:
    return load_eval_queries(_EVAL_DATA)


@pytest.mark.skipif(not settings.dashscope_api_key, reason="未配置 DASHSCOPE_API_KEY")
def test_rag_retrieval_quality():
    queries = _load_queries()
    assert queries, "评测集为空"

    seed_knowledge()  # 幂等：未 seed 则导入，已 seed 则跳过

    db = SessionLocal()
    try:
        report = run_eval(db, queries)
    finally:
        db.close()

    print("\n" + "=" * 60)
    print(
        f"RAG 检索评测报告（{report['n_queries']} 条："
        f"正例 {report['n_positive']} / 负例 {report['n_negative']}）"
    )
    print("  hybrid_search（召回 + RRF，无 rerank）:")
    for k, v in report["hybrid_search"].items():
        print(f"    {k}: {v:.3f}")
    print("  retrieve（含 rerank 精排）:")
    for k, v in report["retrieve"].items():
        print(f"    {k}: {v:.3f}")
    print(
        f"  top1 rrf_score 均值："
        f"正例 {report['positive_top1_rrf']:.4f} / "
        f"负例 {report['negative_top1_rrf']:.4f}"
    )
    print("  负例（拒答场景）top-3 命中（观察是否误召回库内无关内容）:")
    for n in report["negatives"]:
        titles = " | ".join(t["section"] or t["title"] for t in n["top_titles"])
        print(f"    · {n['query']}  ->  [{titles}]")
    print("=" * 60)

    # smoke 断言：先跑通、拿到基线；严格阈值留待看到真实数字后追加
    assert report["n_positive"] > 0
    assert report["n_negative"] > 0
    assert report["hybrid_search"]["recall@8"] > 0.0
    assert report["retrieve"]["recall@4"] > 0.0
