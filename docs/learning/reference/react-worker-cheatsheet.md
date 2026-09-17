# ReAct Worker 速查：任务、工具、观察、再决策

## ReAct 循环

```text
任务 + 当前消息
  → LLM 选择工具（Action）
  → Tool 执行并返回结果（Observation）
  → LLM 读取结果并决定下一步
  → 最终自然语言汇报
```

在 NutriLens 中：

```text
diet_agent
  → search_food
  → 获得每 100g 营养数据
  → create_diet_record
  → interrupt 等待确认
  → resume 后写库
  → 汇报
```

## 三层职责

```text
Agent：决定调用哪个工具、组织最终表达
Tool：提取运行时上下文、组装业务流程、定义可见参数
Service：确定性业务规则、数据库读写、可被 REST 与 Tool 共用
```

## 两类状态

- `task`：Supervisor 已消解指代后的目标，例如“记录今日午餐：牛肉面一碗”。
- `messages`：Human/AI/Tool 消息序列。ReAct 必须读取 ToolMessage，才能知道上一个工具的结果。

## 必记安全原则

1. 感知、检索、数值计算、权限和写库前校验，不应只靠 prompt。
2. `interrupt()` 之前只能放可重复、无副作用的操作；恢复会从节点/工具起点重跑。
3. 最终写库必须走 service，不能只相信 Agent 已经“确认过”。

## 面试句式

> 我把模型自由度限制在工具选择和语言表达；识图、营养事实、过敏校验、持久化等确定性环节由节点、工具和 service 层接管，避免把关键业务正确性押在 prompt 上。
