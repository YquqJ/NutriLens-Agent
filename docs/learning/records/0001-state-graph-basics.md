# State 与 Graph 的第一性理解

用户已理解 Supervisor 负责路由、Agent 输出具有不确定性、工具需要后端权威数据、HITL 用于确认和编辑、hop_count 用于防止循环。已纠正并建立的新知识是：`AgentState` 是图节点共享的数据契约；`PostgresSaver` 保存图状态与恢复位置，不等同于业务消息表或 LangSmith trace；`interrupt()` 首次暂停，`Command(resume=...)` 使用同一 thread_id 恢复，恢复时中断点之前的代码可能重跑，因此写库必须放在 interrupt 之后。

这为下一课从 `state.py` 和 `graph.py` 进入 Supervisor 路由、子图和 checkpoint 细节建立了基础。
