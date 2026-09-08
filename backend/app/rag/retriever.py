"""
混合检索（M4.2）：向量路 + 关键词路 → RRF 融合。

两路互补的失败模式（为什么必须混合）：
- 向量路（pgvector 余弦，HNSW 索引）擅长语义改写："怎么才能瘦" 能召回
  "减脂"主题切片；但对专有名词/精确字面（如"BM25""维生素 B12"）不敏感；
- 关键词路（rank_bm25 内存索引）正好相反：字面命中强，语义泛化弱。

融合用 Reciprocal Rank Fusion 而非分数加权：余弦距离和 BM25 分
的量纲不可比，任何加权都要拍脑袋定权；RRF 只看两路各自的排名
（score = Σ 1/(k + rank)，k=60 惯例值），天然免疫量纲问题。

中文分词：字符二元组（bigram）。不引 zhparser —— 需在 PG 里自编译
扩展、Windows 开发机不友好（SPEC 已排除），bigram 对常见营养/健身
词的召回足够，且纯 Python、零依赖。
BM25 索引每次查询时全量重建：知识库千级切片重建 <10ms，不值得
为省这点耗时引入增量索引的一致性复杂度——量级上来再换常驻缓存。
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeChunk
from app.rag.embedding import embed_query

# RRF 常数（惯例 60）：越大两路排名差异对融合分影响越平缓
RRF_K = 60


def _tokenize(text: str) -> list[str]:
    """字符二元组分词（中文无空格分界，二元组是零依赖的通用做法）。"""
    return [text[i : i + 2] for i in range(len(text) - 1)] or list(text)


def vector_search(db: Session, query_vec: list[float], k: int) -> list[KnowledgeChunk]:
    """向量路：pgvector 余弦距离最近邻（HNSW 索引生效）。"""
    dist = KnowledgeChunk.embedding.cosine_distance(query_vec)
    return list(db.scalars(select(KnowledgeChunk).order_by(dist).limit(k)).all())


def keyword_search(db: Session, query: str, k: int) -> list[KnowledgeChunk]:
    """关键词路：全量加载切片 → 内存 BM25 打分 → 取 top-k。"""
    from rank_bm25 import BM25Okapi

    chunks = list(db.scalars(select(KnowledgeChunk)).all())
    if not chunks:
        return []
    bm25 = BM25Okapi([_tokenize(c.content) for c in chunks])
    scores = bm25.get_scores(_tokenize(query))
    # 分数 >0 的按分降序；全 0（无字面命中）返回空
    ranked = sorted(
        (i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i]
    )
    return [chunks[i] for i in ranked[:k]]


def hybrid_search(db: Session, query: str, top_k: int = 5) -> list[dict]:
    """
    混合检索入口：两路各取 top（top_k*2 候选）→ RRF 融合 → 前 top_k。

    返回按融合分降序的 dict 列表（含切片正文与来源，供重排与生成用）。
    """
    query_vec = embed_query(query)
    vec_hits = vector_search(db, query_vec, top_k * 2)
    kw_hits = keyword_search(db, query, top_k * 2)

    # RRF：chunk_id → {chunk, score}；一路独占的条目也保留（另一路排名缺失按 0 分计）
    fused: dict[int, dict] = {}
    for hits in (vec_hits, kw_hits):
        for rank, chunk in enumerate(hits):
            entry = fused.setdefault(
                chunk.id, {"chunk": chunk, "score": 0.0, "ranked_by": []}
            )
            entry["score"] += 1.0 / (RRF_K + rank + 1)  # rank 从 0 起
            entry["ranked_by"].append("vector" if hits is vec_hits else "keyword")

    top = sorted(fused.values(), key=lambda e: -e["score"])[:top_k]
    return [
        {
            "id": e["chunk"].id,
            "content": e["chunk"].content,
            "source_title": e["chunk"].source_title,
            "topic": e["chunk"].topic,
            "rrf_score": round(e["score"], 6),
            "ranked_by": e["ranked_by"],  # 调试/轨迹用：该切片被哪几路召回
        }
        for e in top
    ]


def retrieve(db: Session, query: str, top_k: int = 5) -> list[dict]:
    """
    完整检索管线（M4.3 接线）：混合召回（求全）→ rerank 精排（求准）。

    降级策略：rerank 端点不可用（网络/限流）时回退 RRF 序截断——
    粗排结果可用总比整条问答链路报错好，rerank 顺序是锦上添花而非
    正确性依赖。失败静默降级但把 rrf_score 保留在结果里可追溯。
    """
    candidates = hybrid_search(db, query, top_k=top_k * 2)
    if not candidates:
        return []
    try:
        from app.rag.rerank import rerank

        pairs = rerank(query, [c["content"] for c in candidates], top_n=top_k)
        reranked = []
        for idx, score in pairs:
            item = dict(candidates[idx])
            item["relevance_score"] = score
            reranked.append(item)
        return reranked
    except Exception:
        return candidates[:top_k]
