# Agent Memory 高频考点

## 四种东西不要混

| 名称 | 本项目承载 | 解决的问题 |
|---|---|---|
| 短期消息 | `AgentState.messages` | 当前轮、近期对话和工具观察 |
| 摘要记忆 | `AgentState.summary` | 长会话压缩、跨轮指代 |
| 运行时持久化 | Checkpointer | 跨请求恢复、HITL、图进度 |
| 长期业务记忆 | `UserProfile` / 业务表 | 跨会话用户事实 |

## 关键结论

- Checkpointer 会持久化 messages，但不会自动解决 token 无限增长。
- 摘要节点在进入 Supervisor 前运行：超过阈值，将旧消息折叠为 summary，保留近期 tail。
- `messages` 使用 `add_messages` reducer，删消息必须返回 `RemoveMessage(id=...)`，普通空列表不会覆盖历史。
- summary 用于 Supervisor 的路由和指代消解；Worker 应优先接收 Supervisor 改写后的 `task` 和近期 ToolMessage。
- UserProfile、饮食记录、权限、余额等应是权威事实；LLM summary 只能是辅助上下文。

## 当前实现参数

```text
MAX_MESSAGES = 24
KEEP_TAIL = 8
```

- 当前阈值按消息对象计数，不按 token 计数。
- Tool calling 会增加 AIMessage / ToolMessage，所以工具密集对话压缩更早。
- 摘要为滚动摘要：existing summary + 新旧消息 -> updated summary。

## 常见风险和改进

- 摘要可能丢失或扭曲历史，且误差会随滚动摘要累积。
- 按消息数不等于按成本；应考虑 token-aware trimming。
- 对摘要使用结构化 schema，区分事实、偏好、进行中任务、待办。
- 给摘要加来源范围、版本、时间，便于审计和重建。
- 对长久知识更适合采用 profile/业务表/检索式记忆，而不是无限增长的摘要。

## 面试一句话

“Memory 不是把所有聊天记录一直塞给模型。我把运行恢复、短期上下文、压缩摘要和长期业务事实分层；摘要用于语义连续性，业务表才是关键事实的唯一可信来源。”
