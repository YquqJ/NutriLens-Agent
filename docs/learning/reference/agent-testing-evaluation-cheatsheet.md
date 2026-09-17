# Agent Testing & Evaluation 速查

## 一句边界

```text
Test = 验证确定契约，通常二元 pass/fail
Eval = 用固定样本集衡量质量，观察分数、案例与回归
```

不要把“模型有随机性”误解成“Agent 无法测试”。模型的自由输出难以逐字断言，但 Agent 的控制流与副作用大多可以。

## NutriLens 四层

| 层级 | 项目例子 | 典型断言 | 是否适合作为 PR 门禁 |
|---|---|---|---|
| 纯函数 | `recall_at_k`、MRR、nDCG、热量公式 | 固定输入 -> 精确输出 | 是 |
| Tool / Service | 过敏拦截、用户归属、CRUD | 异常、落库结果、禁止副作用 | 是 |
| Graph 控制流 | supervisor、MemorySaver、hop guard | goto、State update、历史恢复 | 是 |
| Live E2E / Eval | embedding + pgvector + LLM | 基线指标、案例质量 | 否，独立/定期跑 |

## 断言优先级

```text
强断言：权限、数据库副作用、幂等性、数值公式、Pydantic 结构、路由目标、最大步数
中断言：必须调用 / 禁止调用的工具、引用集合、回复包含关键事实
弱断言：整段自然语言逐字相等（尽量避免）
```

## HITL 回归不变量

```text
首次 invoke:
  有 __interrupt__
  写操作尚未发生

相同 thread_id + Command(resume):
  从 checkpoint 恢复
  只写入一次预期业务记录

重复 resume / 网络重试:
  仍不产生重复记录（需要幂等设计）
```

## RAG 检索指标

| 指标 | 看什么 | 越高表示 |
|---|---|---|
| Recall@K | top K 覆盖了多少相关 chunk | 少漏资料 |
| MRR | 第一个相关 chunk 的排名倒数 | 第一个好结果更靠前 |
| nDCG@K | 多个相关 chunk 的整体排序 | 好资料整体更靠前 |

```text
相关集合 = {A, B}
检索排名 = [X, A, B]

Recall@2 = 1 / 2
Recall@3 = 2 / 2 = 1
MRR = 1 / 2
```

## Eval 要记录的元数据

- eval dataset 版本和每条样本的预期证据
- LLM / embedding / reranker 模型版本
- chunk 参数、索引和检索参数
- prompt / graph 版本
- 指标均值、逐题失败案例、相对上一次的 delta

## 当前项目的下一步

当前 `app/rag/eval.py` 已有检索层的 Recall@K、MRR、nDCG，以及库外负例观察。建议增加答案层评测：

- `faithfulness`：回答主张是否能由给出的上下文蕴含。
- `citation_correctness`：引用是否真的支持相应主张。
- `abstention_accuracy`：库外或证据不足时是否正确拒答/说明不确定。
- 写操作的 resume 幂等性：重复提交不会重复写库。

## 面试一句话

“我把 Agent 测试分为无模型的确定性契约测试和有 golden set 的质量评估：前者守住路由、权限和副作用，后者衡量检索与回答质量，并记录配置版本与回归差异。”
