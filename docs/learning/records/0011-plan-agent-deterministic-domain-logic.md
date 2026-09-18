# Plan Agent 与确定性业务逻辑

用户已进入 `plan_agent.py` 导读，并要求将 RAG 导入重要考点提炼为独立参考文档。

本轮新增 `reference/rag-ingestion-interview-cheatsheet.md`，集中记录 ingestion、chunking、hash、OCR、silent failure 和优化方向。

Plan Agent 核心：

- `plan_agent` 是 ReAct 子图，因为“读档、补档、只更新档案、生成计划”取决于用户当前请求和档案完整度。
- ReAct 的自由只用于选择受控工具与自然语言沟通；BMR/TDEE/热量目标等固定数学应由 profile service 纯函数计算。
- `get_profile` 和 `update_profile` 从运行时 config 得到当前 `user_id`，模型不拥有越权参数。
- `ProfileUpdate` 全字段可选；`model_dump(exclude_unset=True)` 提供 PATCH 语义，防止 LLM 只知道一个字段时抹掉其余档案。
- `recalc_profile_metrics` 在关键身体数据缺失时返回 None，拒绝产生无依据的精确数字。
- UserProfile 是跨会话长期业务记忆；AgentState/messages/checkpoint 是会话执行记忆，两者不应混为一谈。
- 代码审读发现：`tools/profile.py` 注释称工具与 qa_agent 共用，但当前实际 qa_agent 并未导入这些 tools，应以调用链而非注释为准。
