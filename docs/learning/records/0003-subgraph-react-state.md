# Subgraph 与 ReAct 状态边界

用户已掌握：`diet_agent` 不是普通函数，而是通过 `create_react_agent` 构造的编译子图，并作为节点加入外层 supervisor 图。

核心模型：

- 外层循环是 `supervisor -> worker -> supervisor`，由 `hop_count` 限制。
- 内层循环是 `agent -> tools -> agent`，由 `remaining_steps` 限制。
- ReAct 的观察结果以 `ToolMessage` 追加到 `messages`，所以 worker 不需要完整跨轮历史，但必须拿到本轮消息和工具结果。
- 子图会产生共享状态更新，尤其是 `messages`；模型本身不直接修改 Python state，而是节点返回 update，由 LangGraph 合并。
- 数据库写入是工具/服务的外部副作用，不等于 AgentState 字段更新。

下一步：导读 `create_diet_record` 的 HITL 中断、resume 重放与写库顺序。
