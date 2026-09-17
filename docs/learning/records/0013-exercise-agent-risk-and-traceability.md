# Exercise Agent：风险分级与可追溯性

用户继续通过 `exercise_agent` 对照学习 ReAct Worker。

核心结论：

- Exercise Agent 同样是 `create_react_agent` 子图，继承 AgentState 并加入 `remaining_steps`；通用骨架和 diet/plan worker 一致。
- 是否使用 HITL 取决于数据可信度与副作用风险，而非“所有写库都必须确认”。当前运动类型和时长通常由用户直述，因此不 interrupt；饮食克数多为估算，需要确认。
- MET 处理体现模型/工具/服务分层：Tool 优先查确定性表，未命中才提示 LLM 在有限范围估值并重试；Service 用 MET、体重和时长执行固定公式。
- 热量在写入时固化，防止用户后续更新体重导致历史运动记录漂移。
- 发现可优化点：ExerciseRecord 不保存 `met_source`，因此表命中和模型估计难以追溯；无 Profile 时默认 65kg 的假设应在用户侧明确披露；duration 入参应有更严格 Pydantic 范围校验。
- 面试要点：risk-based HITL、deterministic-first fallback、historical immutability、data provenance、runtime identity injection、service-layer facts。
