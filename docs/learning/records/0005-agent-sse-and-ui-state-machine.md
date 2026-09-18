# Agent SSE 协议与前端状态机

用户已继续到 Agent 产品的前后端运行时边界。

本课核心：

- 后端把 LangGraph 的 `messages` 与 `updates` 投影为 token、agent_trace、tool_calls、citations、interrupt、done、error 六类业务 SSE 事件。
- 前端按 `SseEvent` 判别联合类型处理事件；`ReadableStream` 的网络分片必须先 buffer，再按 SSE 空行分帧。
- `streaming` 与 `pendingMsg` 构成关键状态机；`busy = streaming || pendingMsg` 防止同一会话在图等待用户确认时发起并发执行。
- interrupt 时不落 assistant 消息；resume 完成且得到终稿后再落库。确认卡片与最终回答复用同一个 `live` assistant 消息对象。
- token 不是权威最终回答。后端在 done 中取最终 state 的最后一条 AIMessage，前端覆盖 token 累积文本；工具过程在 Tool Trace 单独显示。
- Agent 工程的重要安全发现：resume payload 是不可信输入。当前实现只在初始 tool call 上用 `DietItemIn` 校验，恢复后的 `confirmed["items"]` 仍应服务端再校验。更理想的协议只接收草稿 item id、grams 和 acknowledgement，由服务端重算营养值。
- 另一个产品完善方向：页面刷新后 checkpoint 仍有 pending interrupt，但前端没有查询/重建确认卡片的接口；生产系统应提供 pending state 恢复能力。

下一步：导读 QA Agent 的 RAG 检索链路，学习“检索、引用、幻觉约束、评估”这一条求职中非常高频的 Agent 技能线。
