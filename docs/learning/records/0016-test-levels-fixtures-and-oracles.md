# 测试层级、Fixture 与预期答案

用户已掌握 AAA 基础。本节继续建立阅读项目测试所需的结构：

- Unit 测一个函数，尽量无外部依赖；Integration 测多个模块与数据库协作；E2E 测入口到最终结果的完整链路。
- `test_service_blocks_agent_write_without_explicit_ack` 是 Service + DB 集成测试：`pytest.raises` 验证异常，后续查询验证没有副作用，`finally` 关闭会话。
- Fixture 是可复用的测试准备与清理函数；`allergy_user` 自动创建带过敏档案的用户并在结束后删除。
- Stub 返回预先指定结果，Mock 还可记录调用；Supervisor 使用 Stub 是为了隔离 LLM，只测图控制流。
- 测试预期要有独立来源，不能复制生产实现；要覆盖反例，并可用临时故障思维验证测试确实能抓错。
- 测试金字塔：Unit 多、快；Integration 适量；E2E 少量但覆盖关键链路。真实 LLM 更适合独立 Eval。
