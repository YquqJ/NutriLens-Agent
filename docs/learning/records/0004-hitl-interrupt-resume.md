# HITL interrupt 与 resume

用户正在学习 `create_diet_record` 的人工确认闭环。

关键结论：

- `interrupt_payload` 是给前端的确认请求值，不是通过 reducer 写入 `AgentState` 的普通字段。
- `interrupt()` 会暂停整张图；checkpointer 保存 state、执行位置和待恢复信息。
- resume 必须使用原 `thread_id`（本项目即 `conversation_id`），否则找不到原来的暂停点。
- interrupt 前只能做可重复、无副作用的工作；数据库写入必须放在确认之后。
- `Command(resume=False)` 表示取消，工具返回 `cancelled`，不落库。
- 确认后的 `confirmed["items"]` 是事实来源，必须覆盖模型最初草稿，避免用户改克数后仍汇报旧值。
- 过敏风险在确认前提示，在确认后按最终条目复核；service 层还要做防绕过校验。

下一步：导读 `chat.py` 的 SSE 事件协议，以及前端如何渲染和提交确认卡片。
