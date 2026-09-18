# QA Agent 与 Agentic RAG

用户开始学习 `qa_agent.py`。

核心结论：

- `qa_agent` 是普通 LangGraph 节点，不是 ReAct 子图；检索迭代由代码显式控制，最多两轮。
- 流程为：Supervisor `task` → 混合检索（向量 + BM25）→ RRF 融合 → rerank → LLM 结构化自检 → 必要时 query rewrite 重检 → 带编号证据生成 → 出站引用清洗。
- `gen_llm` 负责最终回答，`check_llm.with_structured_output(QaSelfCheck)` 负责判断证据是否足够；职责分离提升可测性。
- `task` 优先于最后一条用户消息，延续 Supervisor 的指代消解成果。
- 无证据或自检仍不足时返回固定拒答，不调用生成模型，避免用通用知识补幻觉。
- `citations` 是后端结构化证据，统一用于回答编号、SSE、数据库历史和前端抽屉；正文实际使用的证据才进入最终目录。
- 当前引用校验只保证编号来自本轮召回候选，不能完全证明每个事实被证据蕴含；后续需要 entailment/评估集。
- 需要关注检索内容注入、LLM 自检误判、embedding/重排服务超时与降级、知识库版本和离线 RAG 评估。
