# NutriLens Agent State / Graph 速查

## 核心心智模型

```text
State = 共享工作台
Node = 读 State、做一件事、返回局部更新
Edge = 固定流程连接
Command = 节点提出动态跳转 + 状态更新
Checkpoint = 某个 thread 的图状态与执行位置快照
interrupt = 暂停图并等待外部输入
resume = 用同一个 thread 恢复
```

## 本项目主链路

```text
START → turn_reset → analyze_image → summarize → supervisor
                                             ↓
                     diet/exercise/qa/plan → supervisor → END
```

## 必记字段

- `messages`：带 `add_messages` reducer 的累积消息通道。
- `task`：Supervisor 改写后的独立任务。
- `next_agent`：路由结果。
- `hop_count`：业务层死循环保护。
- `agent_trace/tool_calls/citations`：前端和历史回放所需元数据。

## 面试句式

> 模型负责提出路由和工具调用建议，LangGraph 负责状态、流程和恢复，工具/服务层负责确定性业务规则与副作用。

## 官方资料

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
