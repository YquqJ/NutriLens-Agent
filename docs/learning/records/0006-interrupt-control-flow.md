# Interrupt 控制流

用户已厘清 HITL 的三个阶段：

- 第一次 `/chat` 请求消费 `graph.stream`，遇到 `interrupt()` 后 LangGraph 保存 checkpoint，SSE 发出 `interrupt` 和 `done(interrupted=true)`，本次 HTTP 请求结束。
- 没有 Python 调用栈在服务器上持续等待用户；等待的是持久化 checkpoint。
- `/chat/resume` 使用同一 `thread_id` 和 `Command(resume=value)` 读取并恢复 checkpoint。
- 恢复不是从某一行精确跳回，而是从包含 interrupt 的节点开头重跑；重新执行到 `interrupt()` 时，运行时把 resume value 作为返回值，随后 Python 代码才走到 `if confirmed is False` 等后续分支。
- 恢复不会从整个图 `START` 重跑上游节点。
- `for` 迭代 `graph.stream` 事件，`yield` 增量发送一帧并暂停生成器；它不是无限循环。

Agent 工程重点：durable execution、事件协议、重放安全、幂等写入、不可信 resume 输入、不要吞掉 interrupt 特殊异常。

下一步：用 QA Agent 导读 RAG 检索、引用与评估。
