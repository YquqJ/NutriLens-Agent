# RAG 导入高频考点

## 一句话链路

```text
原始 PDF/Markdown -> 解析 -> 清洗与切片 -> embedding -> KnowledgeDocument/KnowledgeChunk -> 在线检索
```

## 必答问题

### 为什么解析切片与 embedding 入库要分离？

- 解析、章节识别、切片是确定性本地逻辑，可离线测试。
- embedding 是调用外部 Embedding 模型服务，入库还包含数据库副作用。
- 分离后能定位失败来源：文件无文本层、切片策略、Embedding API、数据库。

注意：Embedding 使用的是向量模型，不是负责对话生成的 LLM。

### 为什么不能整份文档只生成一个向量？

- 多主题混杂，语义相似度不精确。
- 将整份文档送入 LLM 浪费上下文和成本。
- 无法定位引用到页码、章节和片段。
- Chunk 是检索、生成和引用的最小可控单位。

### Chunk 要保存哪些元数据？

```text
content / embedding / document_id / page_number / section / chunk_index / content_hash
```

- `content` 与 `embedding`：给检索使用。
- `page_number`、`section`、`chunk_index`：给用户引用、审计和调试使用。
- `document_id`：关联原始来源文件。
- `content_hash`：切片级内容身份与去重。

### 文件 hash 与 chunk hash 的区别？

- `file_sha256`：判断整份源文件是否变更。
- `content_hash`：标识单个切片正文是否重复或变化。

本项目当前策略：文件 hash 变化后，删除该文档所有旧 chunks，再全量重建。`content_hash` 已被存储并受唯一约束保护，但尚未实现只更新变更 chunk 的增量向量化。

### 为什么扫描 PDF 不能静默跳过？

- 扫描 PDF 常没有可提取文本层，PDF 解析器得到空字符串。
- 跳过页面会形成不完整知识库，却让导入表面上成功。
- 后续检索可能缺关键证据，造成错误回答、错误引用或不合理拒答。
- 正确策略：显式报错，或进入单独 OCR 流程。

这体现了工程原则：避免 silent failure（静默失败）。

### Chunk size 和 overlap 怎么解释？

- Chunk 太大：主题混杂、检索不准、上下文成本高。
- Chunk 太小：关键事实被拆散、缺上下文、候选数量上升。
- Overlap 降低关键句刚好跨边界被截断的风险。
- 固定参数不是标准答案，应通过 Recall@K、回答忠实度和人工抽样调优。

当前项目：优先按原始行/段落累计，最大 600 字符；只有单行过长时使用 80 字符重叠窗口。

## 当前项目可主动说的优化点

- 内置 PDF 实测会产生只有章节标题的极短 chunk；可与后续正文合并或做最小正文长度过滤。
- 文件更新目前全量重建该文档；大规模知识库可按 chunk hash 做增量 embedding。
- 为扫描 PDF 增加 OCR 分支、导入状态、失败详情与人工审核。
- 用离线评估集持续评估不同 chunk size/overlap 对检索和回答的影响。
