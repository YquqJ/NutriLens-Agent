# Agent Testing 与 Eval：可靠性和质量分层

用户进入 NutriLens 的测试与评估模块，目标是能够从工程视角说明 Agent 项目如何避免“能演示但不可验证”。

核心结论：

- Test 是确定契约的二元验证；Eval 是固定数据集上的质量测量，两者不能混为一谈。
- 项目已体现四层分离：纯函数（RAG 指标）、Service/Tool（过敏写库防线）、Graph 控制流（stub router、MemorySaver、hop guard）、真实模型与检索 E2E（`pytest.mark.eval`）。
- Stub router 不是假测试：它隔离 LLM，只验证 Supervisor 已拿到路由决策后是否正确 `goto`、更新 `hop_count` 和 trace。
- LLM 自然语言不宜整段逐字断言；应断言 schema、必需工具调用、禁止副作用、引用、关键事实、数值范围、权限和数据库结果。
- HITL 的重要不变量：首次 interrupt 后不得写库；相同 thread_id 的 resume 后恰好写入一次。下一步可用幂等键或消费标记防御 resume 重放导致重复写入。
- RAG 评测集以 `content_hash` 标识相关证据，跨 seed/数据库更稳定；现有检索指标为 Recall@K、MRR、nDCG。
- 项目现有 Eval 偏检索层；可扩展回答层 faithfulness、citation correctness、abstention accuracy，并持久化数据集/模型/prompt/index 配置与指标 delta。

下一步：让用户先回答自测题，再结合其答案选择深入“端到端可观测性与线上追踪”或“把当前测试补成一份面试级质量方案”。
