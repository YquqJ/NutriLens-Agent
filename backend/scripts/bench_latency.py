"""
RAG / 问答链路延迟压测脚本（简历性能 bullet 用）。

为什么要有这个脚本：
- 面试官默认「没有数字 ≈ 没做过」。项目目前只有检索质量指标（Recall/MRR/nDCG），
  缺「性能类」数字（延迟、吞吐），而这个岗位（Agent/大模型应用）对延迟最敏感；
- 本项目没有线上流量，所以走「离线压测 + 分位统计」的诚实路线：用现成的评测集
  （tests/eval_data/rag_queries_v2.json，37 条）作为请求集，多次重复计时，
  输出 P50/P90/P95/P99 —— 数字可复现、可被追问时讲清环境。

测量两级：
1. 检索管线（默认，便宜）：embed_query → vector/keyword 两路 → RRF → rerank，
   即 `retriever.retrieve(..., mode="hybrid_rerank")`，与 qa_agent 实际调用一致；
2. 端到端问答（--e2e，较贵）：完整跑 `qa_agent` 节点（检索 + 自检 + 生成），
   含真实 LLM 调用，会消耗 token，默认限制查询条数。

用法（backend/ 目录下，需先 docker compose up -d 起 pg 并已 seed 知识库）：
    uv run python -m scripts.bench_latency                       # 只测检索管线
    uv run python -m scripts.bench_latency --iterations 10        # 更多样本，分位更稳
    uv run python -m scripts.bench_latency --e2e --max-queries 5  # 加测端到端问答
    uv run python -m scripts.bench_latency --top-k 8              # 自定义检索 top_k

输出：终端打印分位摘要 + 写入 reports/bench-latency-<时间戳>.json。
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.db.seed_knowledge import seed_all_knowledge
from app.db.session import SessionLocal
from app.rag.embedding import embed_query
from app.rag.eval import load_eval_queries
from app.rag.rerank import rerank
from app.rag.retriever import (
    hybrid_search,
    keyword_search,
    retrieve,
    vector_search,
)

_EVAL_DATA = (
    Path(__file__).resolve().parents[1] / "tests" / "eval_data" / "rag_queries_v2.json"
)
_REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"

# 与 qa_agent 一致的检索条数（_question_from → retrieve(db, q, top_k=4)）
_DEFAULT_TOP_K = 4


def _percentile(sorted_vals: list[float], p: float) -> float:
    """最近秩法分位（无 numpy 依赖）。"""
    if not sorted_vals:
        return 0.0
    idx = max(0, int(round(p / 100 * len(sorted_vals))) - 1)
    return sorted_vals[idx]


def _summarize(name: str, values: list[float]) -> dict:
    """一组采样 → 分位摘要 dict。"""
    vals = sorted(values)
    return {
        "metric": name,
        "n": len(vals),
        "min_ms": round(min(vals), 2),
        "p50_ms": round(_percentile(vals, 50), 2),
        "p90_ms": round(_percentile(vals, 90), 2),
        "p95_ms": round(_percentile(vals, 95), 2),
        "p99_ms": round(_percentile(vals, 99), 2),
        "max_ms": round(max(vals), 2),
        "mean_ms": round(statistics.fmean(vals), 2),
    }


def _time_ms(fn, *args, **kwargs) -> tuple[object, float]:
    """执行 fn 并返回 (返回值, 耗时毫秒)。"""
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, (time.perf_counter() - start) * 1000


def _bench_retrieval(db, query: str, top_k: int) -> dict:
    """对单条 query 计时检索管线的各阶段（各阶段独立计时，不做相加）。

    rerank 走的是裸 httpx 单次调用（rerank.py 无重试），瞬时网络重置会抛
    异常；生产里的 ``retrieve()`` 对它本就有 RRF 降级，这里也单独隔离——
    rerank 失败只丢弃该阶段本次采样，不连累 retrieval_total。
    """
    stages: dict[str, float | None] = {}

    vec, stages["embedding"] = _time_ms(embed_query, query)
    _, stages["vector_search"] = _time_ms(vector_search, db, vec, top_k * 2)
    _, stages["bm25"] = _time_ms(keyword_search, db, query, top_k * 2)

    # rerank 需要候选：用 hybrid_search 现取一批（其自身耗时不计入 rerank 阶段）
    candidates = hybrid_search(db, query, top_k=top_k * 2)
    if candidates:
        try:
            _, stages["rerank"] = _time_ms(
                rerank, query, [c["content"] for c in candidates], top_n=top_k
            )
        except Exception:
            stages["rerank"] = None  # 瞬时失败，跳过该阶段本次采样
    else:
        stages["rerank"] = 0.0

    # 总管线：与 qa_agent 实际走的一模一样（hybrid_rerank，内部已带 RRF 降级）
    _, stages["retrieval_total"] = _time_ms(retrieve, db, query, top_k=top_k)
    return stages


def _measure_with_retry(fn, *args, retries: int = 3, **kwargs):
    """带指数退避地执行一次测量，处理 embedding/DB 等偶发瞬时失败。"""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 测量工具要尽量吞掉瞬时抖动
            last_exc = exc
            time.sleep(1.0 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _bench_e2e(db, query: str, top_k: int):
    """端到端跑一次 qa_agent 节点（含 LLM 自检 + 生成），返回耗时。"""
    from langchain_core.messages import HumanMessage

    from app.agents.qa_agent import make_qa_agent

    # qa_agent 内部自己开 SessionLocal 读知识库，这里传入的 db 仅用于占位一致；
    # 直接复用 make_qa_agent() 的节点函数（与图上执行等价，省掉 supervisor 路由）。
    qa = make_qa_agent()
    state = {
        "messages": [HumanMessage(query)],
        "task": f"回答知识问题：{query}",
        "hop_count": 1,
    }
    _, ms = _time_ms(qa, state)
    return ms


def main() -> None:
    parser = argparse.ArgumentParser(description="NutriLens RAG / 问答链路延迟压测")
    parser.add_argument("--iterations", type=int, default=5, help="每条 query 重复计时次数")
    parser.add_argument("--max-queries", type=int, default=0, help="最多测几条 query（0=全部）")
    parser.add_argument("--top-k", type=int, default=_DEFAULT_TOP_K, help="检索 top_k")
    parser.add_argument("--e2e", action="store_true", help="额外测端到端 qa_agent 延迟")
    parser.add_argument("--warmup", type=int, default=3, help="测量前预热次数（不计入统计）")
    parser.add_argument(
        "--eval-data",
        type=Path,
        default=_EVAL_DATA,
        help="评测集 JSON 路径（默认 rag_queries_v2.json）",
    )
    parser.add_argument("--no-seed", action="store_true", help="跳过知识库 seed（已 seed 时省时间）")
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        print("未配置 DASHSCOPE_API_KEY（embedding/rerank/LLM 都需要），无法真实测量。", file=sys.stderr)
        print("请在 backend/.env 填好 DASHSCOPE_API_KEY 后重试。", file=sys.stderr)
        sys.exit(1)

    if not args.no_seed:
        added = seed_all_knowledge()
        print(f"知识库 seed 完成：本次新增 {added} 条（未变化自动跳过）")

    queries = load_eval_queries(args.eval_data.resolve())
    query_texts = [q["query"] for q in queries]
    if args.max_queries > 0:
        query_texts = query_texts[: args.max_queries]
    print(f"评测集 {len(queries)} 条，本次测 {len(query_texts)} 条，每条 {args.iterations} 次。\n")

    # 预热：首轮含连接建立/单例初始化，不计入统计
    db = SessionLocal()
    try:
        _measure_with_retry(_bench_retrieval, db, query_texts[0], args.top_k)
        if args.e2e:
            _measure_with_retry(_bench_e2e, db, query_texts[0], args.top_k)
    finally:
        db.close()

    # 收集采样
    stage_samples: dict[str, list[float]] = {
        "embedding": [],
        "vector_search": [],
        "bm25": [],
        "rerank": [],
        "retrieval_total": [],
    }
    e2e_samples: list[float] = []
    skipped = 0  # 整条 query 采样失败被丢弃的次数

    db = SessionLocal()
    try:
        for _ in range(args.iterations):
            for q in query_texts:
                try:
                    stages = _measure_with_retry(_bench_retrieval, db, q, args.top_k)
                except Exception:
                    skipped += 1
                    continue
                for key in stage_samples:
                    val = stages[key]
                    if val is None:  # 该阶段本次采样失败（如 rerank 瞬时断开），单独跳过
                        continue
                    stage_samples[key].append(val)
                if args.e2e:
                    try:
                        e2e_samples.append(
                            _measure_with_retry(_bench_e2e, db, q, args.top_k)
                        )
                    except Exception:
                        pass
    finally:
        db.close()

    if skipped:
        print(f"提示：有 {skipped} 条采样因瞬时网络/DB 异常被丢弃。\n")

    summary = [_summarize(name, vals) for name, vals in stage_samples.items()]
    if args.e2e:
        summary.append(_summarize("qa_e2e", e2e_samples))

    # 打印可读摘要
    print("=" * 64)
    print("分位延迟（毫秒）")
    print("=" * 64)
    header = f"{'阶段':<16}{'n':>5}{'P50':>9}{'P95':>9}{'P99':>9}{'均值':>9}{'max':>9}"
    print(header)
    print("-" * 64)
    label = {
        "embedding": "embedding",
        "vector_search": "vector 检索",
        "bm25": "BM25 重建",
        "rerank": "rerank 精排",
        "retrieval_total": "检索管线(总)",
        "qa_e2e": "端到端问答",
    }
    for s in summary:
        print(
            f"{label[s['metric']]:<16}{s['n']:>5}{s['p50_ms']:>9.1f}"
            f"{s['p95_ms']:>9.1f}{s['p99_ms']:>9.1f}{s['mean_ms']:>9.1f}{s['max_ms']:>9.1f}"
        )
    print("=" * 64)
    print("环境：本地单机 · PostgreSQL+pgvector · DashScope(qwen/embedding/gte-rerank) · 无线上流量")

    # 落盘 JSON 报告（可复现）
    _REPORTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = _REPORTS_DIR / f"bench-latency-{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "eval_data": str(args.eval_data),
                "n_queries": len(query_texts),
                "iterations": args.iterations,
                "top_k": args.top_k,
                "e2e": args.e2e,
                "metrics": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n报告已写入：{out_path}")


if __name__ == "__main__":
    main()
