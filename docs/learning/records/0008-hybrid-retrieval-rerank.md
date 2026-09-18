# Hybrid Retrieval 与 Rerank

用户开始导读 `rag/retriever.py`。

核心结论：

- 一条 `KnowledgeChunk` 同时保存检索正文、embedding 和来源元数据；来源元数据用于最终引用，不应只保存文本。
- 向量检索处理语义改写，pgvector 按余弦距离升序返回近邻；BM25 处理精确字面与专有词，本项目用中文字符二元组做零依赖分词。
- 两路原始分数不可比：余弦距离越小越好，BM25 越大越好。RRF 仅融合各自排名，避免脆弱的手工分数归一化和权重选择。
- `hybrid_search` 两路各取候选、RRF 融合；`retrieve` 先取更大的候选池（`top_k * 2`），再用 rerank 精排为最终 `top_k`。这对应 Recall 优先后再 Precision 优先。
- rerank 外部服务失败时退化到 RRF 顺序；当前 embedding 故障无法降级为 BM25，是可改进点。裸 `except Exception` 也应改为带日志、指标的精确错误处理。
- 面试关键词：embedding、pgvector、cosine distance、HNSW、BM25、中文分词、hybrid retrieval、RRF、recall、precision、rerank、fallback、retrieval evaluation。
