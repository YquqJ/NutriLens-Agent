# Agent 应用开发 Resources

## Knowledge

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
  官方图 API 文档，覆盖 StateGraph、节点、边和 Command。用于理解 `graph.py` 的图定义与动态路由。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  官方持久化文档，解释 checkpointer、thread 和短期记忆。用于理解 `PostgresSaver` 与跨请求恢复。
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
  官方中断文档，解释 `interrupt()`、外部输入和 resume。用于理解 NutriLens 的 HITL 确认流程。
- [LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
  官方子图文档，解释 compiled subgraph 作为父图节点以及共享 state。用于理解 diet/exercise 等 worker。

## Wisdom

暂不安排社区学习；先通过项目代码、测试和面试模拟建立可验证能力。

## Gaps

- 后续需要补充 Agent 评测、成本监控、并发恢复和健康数据隐私的高质量资料。
