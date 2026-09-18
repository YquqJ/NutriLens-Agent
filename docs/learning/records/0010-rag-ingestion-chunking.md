# RAG 导入、切片与幂等更新

用户已进入 RAG 离线数据管道。

核心结论：

- RAG 由离线 ingestion 和在线 retrieval 共同构成；前者把原始文件转为可检索的 `KnowledgeChunk`，后者才根据用户问题召回。
- `document_loader.py` 负责确定性解析和切片，可离线单测；embedding、数据库写入在 `seed_knowledge.py` 执行，职责分离便于排错。
- 每个 chunk 保存正文、页码、章节、全局序号和内容 hash；章节前缀注入正文，保证片段独立召回时仍有语境。
- `_MAX_CHARS=600` 与 `_OVERLAP_CHARS=80` 是可调切片参数。当前 overlap 只用于超长单行，优先保持原始行结构。
- `KnowledgeDocument` 记录来源文件和文件 hash；同一文件未变化则跳过，变化时只删除该文档的旧 chunks 并重建，不影响其他文档。
- 文件 hash 判断“源文件是否变”，chunk content hash 标识“这段正文是否重复”。
- 实测内置 13 页 PDF 解析出 66 chunks，发现标题单独形成极短 chunk 的优化机会：可过滤最小正文长度或与后续段落合并。
- 切片是 RAG 质量上限，尺寸和 overlap 应通过 Recall@K、faithfulness 和人工抽样评估，而非迷信固定数值。
