# Supervisor 速查：模型建议，程序裁决

## 一句话职责

Supervisor 不处理饮食、运动或 RAG 业务；它只做两件事：选择下一个 worker，并把用户原话改写成脱离历史也可执行的 `task`。

## 输入与输出

```text
输入：AgentState（messages、summary、图片识别结论、hop_count）
输出：Command(goto=..., update={next_agent, task, hop_count, agent_trace})
```

## 四层可靠性

1. `RouteDecision`：约束模型只能返回合法 worker 或 `FINISH`。
2. 系统提示词：告知 worker 职责、真实日期、任务改写和结束规则。
3. `MAX_HOPS`：达到上限时不调用模型，直接 `END`。
4. 同 worker 连续路由保护：模型没有识别任务已完成时，程序强制 `FINISH`。

## 关键分层

```text
LLM：提出 RouteDecision
Supervisor：核验/补充硬约束，生成 Command
LangGraph：按 Command 跳转并合并 update 到 State
Worker：执行任务
```

## 常见面试问答

问：为什么不用关键词 if/else 路由？

答：健康管理中存在口语、省略和跨轮指代，例如“那这个消耗多少卡”。LLM 更适合意图判断和任务改写；但其输出不可信，因此必须以结构化输出、目标白名单和 hop guard 把执行控制留在程序中。

问：为什么 worker 完成后还要回到 supervisor？

答：只有 supervisor 有全局调度权。它依据 worker 的结果决定结束还是极少数场景下继续分派，避免 worker 直接互相跳转造成耦合和循环。
