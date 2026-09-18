# 摘要记忆与上下文工程

用户已导读 `memory.py`。

核心结论：

- Checkpointer 持久化 state，但不自动控制长会话 token 成本；`summary` 节点负责压缩 `messages`。
- 当前策略：`MAX_MESSAGES=24`，超过后把最旧消息折叠为滚动摘要，借助 `RemoveMessage` 删除旧原文，只保留 `KEEP_TAIL=8` 条近期消息。
- 计数单位是消息对象，不是轮数也不是 token；ReAct 产生 AI/Tool 消息，因此工具密集会话更早压缩。
- 摘要位于 `analyze_image` 后、Supervisor 前。Supervisor 注入 summary 做跨轮指代消解；Worker 主要依赖 task 与近期工具上下文，不直接消费 summary。
- 业务 `messages` 表仍保存产品历史回放；AgentState 内被裁剪的 messages 是运行时上下文窗口。
- 摘要存在信息丢失与滚动误差风险，不能作为过敏、权限、金额等关键事实唯一来源；这些应落 UserProfile 与业务表。
- 已新增 `reference/agent-memory-interview-cheatsheet.md`。
