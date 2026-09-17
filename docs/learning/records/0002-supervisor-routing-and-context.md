# Supervisor 路由与 Worker 上下文边界

用户已正确理解 `goto` 负责动态跳转、`update` 负责更新共享 State，以及 `hop_count` 用于限制多 Agent 循环。当前已补足两个关键边界：`FINISH` 是业务层结束标记、需映射到 LangGraph 的 `END`；`task` 用于明确 Worker 的目标，`messages` 用于保留本轮工具调用与工具结果，因此两者不能互相替代。

后续应继续用“模型提出建议、程序保存状态并执行约束”的框架理解 ReAct worker、工具和 HITL。
