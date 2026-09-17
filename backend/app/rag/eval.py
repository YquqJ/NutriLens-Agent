"""RAG 检索质量量化评测：指标函数（纯函数）+ 真实后端跑分入口。

要回答"怎么证明检索效果好"，得有一份 golden 评测集 + 可复现的指标。本模块：
- `recall_at_k` / `mrr` / `ndcg_at_k` 是纯函数，离线可单测、锁死指标口径；
- `run_eval` 走真实 embedding + pgvector（由 `tests/test_rag_eval.py` 以
  `pytest -m eval` 触发，未配 DASHSCOPE_API_KEY 时自动跳过）——假向量测出的
  指标是假数字，证明不了真实语义召回质量；
- golden 用“页码 + 证据文本”对齐当前切分下的 chunk，避免固定切分与章节
  切分产生不同 content_hash 后无法公平比较；旧 `relevant_hashes` 仍兼容。
"""

import json
import math
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.db.models import KnowledgeChunk
from app.rag.retriever import hybrid_search, retrieve, retrieve_by_mode


def _normalize_evidence_text(text: str) -> str:
    """消除 PDF 换行和连续空白，避免证据锚点依赖排版细节。"""
    return re.sub(r"\s+", " ", text).strip()


def _load_eval_dataset(path: Path, stack: tuple[Path, ...] = ()) -> dict:
    path = path.resolve()
    if path in stack:
        chain = " -> ".join(str(item) for item in (*stack, path))
        raise ValueError(f"评测集 includes 出现循环引用：{chain}")

    data = json.loads(path.read_text(encoding="utf-8"))
    evidence = {}
    queries = []
    next_stack = (*stack, path)

    for include in data.get("includes", []):
        included = _load_eval_dataset(path.parent / include, next_stack)
        for evidence_id, item in included["evidence"].items():
            if evidence_id in evidence and evidence[evidence_id] != item:
                raise ValueError(f"重复 evidence id 内容不一致：{evidence_id}")
            evidence[evidence_id] = item
        queries.extend(included["queries"])

    default_source_key = data.get("default_source_key")
    for evidence_id, raw_item in data.get("evidence", {}).items():
        item = dict(raw_item)
        if default_source_key is not None:
            item.setdefault("source_key", default_source_key)
        if evidence_id in evidence and evidence[evidence_id] != item:
            raise ValueError(f"重复 evidence id 内容不一致：{evidence_id}")
        evidence[evidence_id] = item
    queries.extend(data.get("queries", []))
    return {"evidence": evidence, "queries": queries}


def load_eval_queries(path: Path) -> list[dict]:
    """加载可组合评测集，并把稳定 evidence id 展开为证据锚点。"""
    data = _load_eval_dataset(path)
    evidence = data.get("evidence", {})
    queries = []

    for raw_query in data["queries"]:
        query = dict(raw_query)
        evidence_ids = query.get("relevant_evidence_ids")
        if evidence_ids is not None:
            missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence]
            if missing:
                raise ValueError(
                    f"评测问题引用了不存在的 evidence id：{query['query']} -> {missing}"
                )
            query["relevant_evidence"] = [evidence[evidence_id] for evidence_id in evidence_ids]
        else:
            query.setdefault("relevant_evidence", [])
        queries.append(query)

    return queries


def resolve_relevant_ids(chunks, query: dict) -> set[int]:
    """将稳定证据锚点解析为当前知识库切分策略下的相关 chunk id。"""
    evidence_items = query.get("relevant_evidence")
    if evidence_items:
        relevant_ids: set[int] = set()
        for evidence in evidence_items:
            expected_source = evidence.get("source_key")
            expected_page = evidence["page_number"]
            expected_text = _normalize_evidence_text(evidence["text"])
            matches = {
                chunk.id
                for chunk in chunks
                if chunk.page_number == expected_page
                and (
                    expected_source is None
                    or getattr(chunk, "source_key", None)
                    == expected_source
                    or getattr(getattr(chunk, "document", None), "source_key", None)
                    == expected_source
                )
                and expected_text in _normalize_evidence_text(chunk.content)
            }
            if not matches:
                raise ValueError(
                    "评测集与数据库不一致：相关证据无法解析 "
                    f"-> {query['query']} / source {expected_source} "
                    f"/ page {expected_page} / {expected_text}"
                )
            relevant_ids.update(matches)
        return relevant_ids

    hashes = query.get("relevant_hashes") or []
    hash_to_id = {chunk.content_hash: chunk.id for chunk in chunks if chunk.content_hash}
    return {hash_to_id[content_hash] for content_hash in hashes if content_hash in hash_to_id}


def _is_positive_query(query: dict) -> bool:
    return bool(query.get("relevant_evidence") or query.get("relevant_hashes"))


def recall_at_k(pred_ids: list[int], relevant_ids: set[int], k: int) -> float:
    """Recall@K = 检索 top-K 中命中的相关切片 / 全部相关切片。"""
    if not relevant_ids:
        return 0.0
    return len(set(pred_ids[:k]) & set(relevant_ids)) / len(set(relevant_ids))


def mrr(pred_ids: list[int], relevant_ids: set[int]) -> float:
    """MRR = 第一个相关切片排名的倒数（1-based）；无相关记 0。"""
    for i, pid in enumerate(pred_ids):
        if pid in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(pred_ids: list[int], relevant_ids: set[int], k: int) -> float:
    """nDCG@K：二值相关（命中=1），排名越靠前权重越高，除以理想排序的 DCG 归一。"""
    if not relevant_ids:
        return 0.0
    top = pred_ids[:k]
    dcg = sum(
        1.0 / math.log2(i + 2) for i, pid in enumerate(top) if pid in relevant_ids
    )
    ideal_len = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_len))
    return dcg / idcg if idcg else 0.0


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _run_mode_eval(
    db,
    queries: list[dict],
    *,
    mode: str,
    top_k: int,
) -> dict:
    """对单一检索模式跑一份可比较的评测报告。"""
    chunks = db.scalars(
        select(KnowledgeChunk).options(joinedload(KnowledgeChunk.document))
    ).all()
    report = {"recall@4": [], "recall@8": [], "mrr": [], "ndcg@4": []}
    per_query = []
    negatives = []
    positive_top1_scores = []

    for q in queries:
        query = q["query"]
        relevant_ids = resolve_relevant_ids(chunks, q)
        hits = retrieve_by_mode(db, query, top_k=top_k, mode=mode)
        ids = [h["id"] for h in hits]
        top1_score = float(
            hits[0].get("relevance_score", hits[0].get("rrf_score", 0.0))
            if hits
            else 0.0
        )

        if _is_positive_query(q):
            if not relevant_ids:
                raise ValueError(f"评测集与数据库不一致：相关切片无法解析 -> {query}")
            values = {
                "recall@4": recall_at_k(ids, relevant_ids, 4),
                "recall@8": recall_at_k(ids, relevant_ids, 8),
                "mrr": mrr(ids, relevant_ids),
                "ndcg@4": ndcg_at_k(ids, relevant_ids, 4),
            }
            for key, value in values.items():
                report[key].append(value)
            positive_top1_scores.append(top1_score)
            per_query.append(
                {
                    "query": query,
                    "metrics": values,
                    "relevant_ids": sorted(relevant_ids),
                    "retrieved_ids": ids,
                    "top1_score": top1_score,
                }
            )
        else:
            negatives.append(
                {
                    "query": query,
                    "top1_score": top1_score,
                    "top_titles": [
                        {
                            "title": h.get("source_title"),
                            "section": h.get("section"),
                            "score": h.get("relevance_score", h.get("rrf_score", 0.0)),
                        }
                        for h in hits[:3]
                    ],
                }
            )

    return {
        "mode": mode,
        "n_queries": len(queries),
        "n_positive": len(per_query),
        "n_negative": len(negatives),
        "metrics": {key: _mean(values) for key, values in report.items()},
        "positive_top1_score": _mean(positive_top1_scores),
        "negative_top1_score": _mean([n["top1_score"] for n in negatives]),
        "per_query": per_query,
        "negatives": negatives,
    }


def run_ablation(
    db,
    queries: list[dict],
    *,
    modes: list[str] | tuple[str, ...] = (
        "vector",
        "bm25",
        "hybrid_rrf",
        "hybrid_rerank",
    ),
    top_k: int = 8,
) -> dict:
    """对多个检索模式跑统一口径的消融报告。"""
    return {
        "schema_version": "rag-ablation-v1",
        "top_k": top_k,
        "modes": list(modes),
        "results": {
            mode: run_eval(db, queries, mode=mode, top_k=top_k)
            for mode in modes
        },
    }


def run_eval(
    db,
    queries: list[dict],
    hybrid_top_k: int = 8,
    retrieve_top_k: int = 4,
    *,
    mode: str | None = None,
    top_k: int | None = None,
) -> dict:
    """对评测集跑真实检索，返回平均指标与逐条明细。

    queries 条目的 `relevant_evidence`（或旧 `relevant_hashes`）二义：
    - 非空：正例，算 Recall@K / MRR / nDCG；
    - 空列表：负例（拒答场景），不算召回指标，只记录 top-K 头部与其分数，
      供人工观察“库外问题是否被强误命中”（检索层不负责拒答，这里只给信号）。
    """
    if mode is not None:
        return _run_mode_eval(db, queries, mode=mode, top_k=top_k or hybrid_top_k)

    chunks = db.scalars(
        select(KnowledgeChunk).options(joinedload(KnowledgeChunk.document))
    ).all()
    hybrid_report = {"recall@4": [], "recall@8": [], "mrr": [], "ndcg@4": []}
    retrieve_report = {"recall@4": [], "mrr": [], "ndcg@4": []}
    per_query = []
    negatives = []
    positive_top1_scores = []

    for q in queries:
        query = q["query"]
        relevant_ids = resolve_relevant_ids(chunks, q)

        hybrid_hits = hybrid_search(db, query, top_k=hybrid_top_k)
        retrieve_hits = retrieve(db, query, top_k=retrieve_top_k)
        hybrid_ids = [h["id"] for h in hybrid_hits]
        retrieve_ids = [h["id"] for h in retrieve_hits]
        top1_rrf = hybrid_hits[0]["rrf_score"] if hybrid_hits else 0.0

        if _is_positive_query(q):  # 正例
            if not relevant_ids:
                raise ValueError(f"评测集与数据库不一致：相关切片无法解析 -> {query}")
            hyb = {
                "recall@4": recall_at_k(hybrid_ids, relevant_ids, 4),
                "recall@8": recall_at_k(hybrid_ids, relevant_ids, 8),
                "mrr": mrr(hybrid_ids, relevant_ids),
                "ndcg@4": ndcg_at_k(hybrid_ids, relevant_ids, 4),
            }
            ret = {
                "recall@4": recall_at_k(retrieve_ids, relevant_ids, 4),
                "mrr": mrr(retrieve_ids, relevant_ids),
                "ndcg@4": ndcg_at_k(retrieve_ids, relevant_ids, 4),
            }
            for key, val in hyb.items():
                hybrid_report[key].append(val)
            for key, val in ret.items():
                retrieve_report[key].append(val)
            positive_top1_scores.append(top1_rrf)
            per_query.append(
                {
                    "query": query,
                    "hybrid": hyb,
                    "retrieve": ret,
                    "relevant_ids": sorted(relevant_ids),
                    "retrieved_ids": retrieve_ids,
                    "top1_rrf": top1_rrf,
                }
            )
        else:  # 负例（拒答）：只观察 top-K 是否误命中库内无关内容
            negatives.append(
                {
                    "query": query,
                    "top1_rrf": top1_rrf,
                    "top_titles": [
                        {
                            "title": h["source_title"],
                            "section": h["section"],
                            "rrf_score": h["rrf_score"],
                        }
                        for h in hybrid_hits[:3]
                    ],
                }
            )

    return {
        "n_queries": len(queries),
        "n_positive": len(per_query),
        "n_negative": len(negatives),
        "hybrid_search": {k: _mean(v) for k, v in hybrid_report.items()},
        "retrieve": {k: _mean(v) for k, v in retrieve_report.items()},
        "positive_top1_rrf": _mean(positive_top1_scores),
        "negative_top1_rrf": _mean([n["top1_rrf"] for n in negatives]),
        "per_query": per_query,
        "negatives": negatives,
    }
