# NutriLens 开发规格（施工图纸）

> 状态标记：`[x]` 已完成并验证 · `[~]` 进行中 · `[ ]` 未开始
> 每个功能点粒度控制在"一次提交能看完"。完成后勾选并 git 提交。

## 总体架构

```
用户消息（文字/图片）
      │
      ▼
┌───────────────┐   路由(改写子任务, 指代消解)   ┌──────────────┐
│   supervisor   │ ──────────────────────────▶ │ worker agent │
│  (qwen-plus)   │ ◀────────────────────────── │ ×4 见下      │
└───────────────┘        结果回传              └──────────────┘
      │                                                │
      │  interrupt(HITL) ◀── create_diet_record 等写库工具
      ▼
PostgresSaver checkpointer（thread_id = conversation_id）

worker 分工：
- diet_agent     饮食：图片识别/文字解析 → 食物库匹配 → HITL 确认 → 落库
- exercise_agent 运动：MET 查表 → 计算消耗 → 落库
- qa_agent       问答：Agentic RAG（混合检索 + 重排 + 迭代自检）
- plan_agent     计划：读身体档案 → BMR/TDEE → 生成饮食计划
```

## M0 基础设施 `[x]`（2026-09-08 完成）

- [x] docker-compose：PostgreSQL + pgvector 容器
- [x] `core/config.py`：pydantic-settings 统一读 .env
- [x] `db/session.py` + `db/init_db.py`：建表与向量索引
- [x] `main.py`：FastAPI 入口 + CORS

## M1 认证与用户 `[x]`（2026-09-08 完成）

- [x] `core/security.py`：bcrypt 密码哈希 + JWT 签发/校验
- [x] `api/auth.py`：注册/登录
- [x] `api/users.py` + `services/profile.py`：身体档案 CRUD，BMR/TDEE/目标热量缓存回填
- [x] `api/conversations.py`：会话列表/新建/历史/删除（id 即 thread_id）

## M2 记录与文件 `[x]`（2026-09-08 完成）

- [x] `services/diet.py`：食物检索（精确/前缀/模糊）、按克数换算营养、饮食记录 CRUD、每日汇总
- [x] `services/exercise.py`：MET 查表、消耗计算、记录 CRUD
- [x] `services/oss.py`：图片上传 OSS
- [x] `api/records.py` + `api/uploads.py`：REST 记录端点（查询/删除/看板，手动表单录入路径）

## M3 Agent 编排 ★核心 `[~]`

**已完成：**
- [x] `agents/state.py`：AgentState（messages reducer / HITL 草稿 / hop_count 防死循环）
- [x] `agents/llm.py`：模型工厂（qwen-plus 文本 / qwen-vl-max 视觉）
- [x] `tools/context.py`：ensure_config 取 user_id、独立 DB 会话
- [x] `tools/diet.py`：analyze_food_image / search_food / create_diet_record(interrupt HITL) / get_diet_records / delete_diet_record

**待开发（按序）：**
- [x] **M3.1** `tools/exercise.py`：create/get/delete_exercise_record 工具（复用 services/exercise）
      验收：单测 MET 计算 + 工具直调落库 ✅（tests/test_exercise_tools.py，6 用例全过：含 MET 未命中降级提示、越权删除校验）
- [x] **M3.2** `tools/profile.py`：get_profile / update_profile 工具（agent 读改身体档案与长期偏好）
      验收：工具直调读写 user_profiles ✅（tests/test_profile_tools.py，含部分更新语义、非法枚举拦截、REST 路由下沉后回归）
- [x] **M3.3** `agents/supervisor.py`：路由节点 —— 结构化输出 {next_agent, task}，hop_count≥2 强制结束
      验收：逻辑测试 4 用例通过（跳转/状态更新/防死循环/trace 追加）✅；真实 LLM 路由联调 3 用例已写，待配置 DASHSCOPE_API_KEY 后运行
- [x] **M3.4** `agents/diet_agent.py`：create_react_agent 绑定饮食工具 + 系统提示词（指代消解后的 task 驱动）
      验收：文字"我午饭吃了一碗牛肉面"全流程落库 ✅（E2E 真实 LLM+DB：interrupt 挂起→编辑克数恢复→落库断言；取消路径同样覆盖）
- [x] **M3.5** `agents/exercise_agent.py` + `agents/plan_agent.py`：同构 worker
      验收：各自域内指令正确落库/出计划 ✅（E2E：慢跑落库无 HITL + 计划引用档案数字与过敏偏好）
- [x] **M3.6** `agents/graph.py`：Supervisor 图组装 + PostgresSaver checkpointer 接线
      验收：同一 thread_id 二次 invoke 能续上历史 ✅（tests/test_supervisor_graph.py：E2E 真实 LLM+PostgresSaver 二轮 invoke，第二轮基于第一轮落库记录回答追问；全图 HITL interrupt→resume→落库 也已覆盖。附带：qa_agent 占位形态接入图；turn_reset 入口节点修 hop_count 跨轮累积；NutriLensPostgresSaver 补丁修 pending_sends JSONB 往返 —— 细节见 DESIGN_NOTES）
- [x] **M3.7** `api/chat.py`：SSE 流式端点（token/agent_trace/tool_calls/interrupt 四类事件分帧）+ `Command(resume=...)` 恢复端点 + 消息落库 messages 表
      验收：curl 联调——发消息→收到 interrupt→确认→落库→看板可见 ✅（tests/test_chat_api.py E2E：SSE 收到 agent_trace/interrupt→resume 确认→DietRecord 落库→messages 表 user/assistant 各一条、assistant 带 agent_name 与 tool_trace；另含无挂起中断 resume 返回 400 的守卫用例。SSE 验证方式为 TestClient 流式断言，等价于 curl 链路）
- [x] **M3.8** 食物库 seed 脚本：导入中国食物成分表数据 ~800-1000 条（含 alias）
      验收：search_food("西红柿") 命中并带别名"番茄" ✅（foods_data.py 整理 789 条（17 大类：主食/面点/餐食/肉类/水产/豆类/蔬菜/菌藻/水果/坚果/奶类/饮品/零食/调味/菜肴等），seed_foods.py 幂等导入（按 name 去重不覆盖）；tests/test_food_seed.py 覆盖幂等性 + 别名双向命中 + 规模断言。附带修复：search_foods 元组排序平局时比较 Food 对象的 TypeError——全量 seed 后平局常见才暴露）

## M4 Agentic RAG `[ ]`

- [x] **M4.1** `rag/embedding.py`：text-embedding-v3 客户端 + 批量入库
- [x] **M4.2** `rag/retriever.py`：混合检索（pgvector 余弦 + rank_bm25 内存索引）→ RRF 融合
- [x] **M4.3** `rag/rerank.py`：gte-rerank 重排（DashScope 原生 API，非 OpenAI 兼容模式）
- [x] **M4.4** 知识库 seed：营养/健身知识文档切片入库
- [x] **M4.5** `agents/qa_agent.py`：迭代自检（检索结果不足 → 改写 query 重检，≤2 轮）
      验收：问"减脂期每天吃多少蛋白质"，回答带来源且检索轨迹可见

## M5 热量看板 API `[x]`（2026-09-08 完成，冒烟验证）

- [x] **M5.1** 看板端点（实现在 `api/records.py`，未单独拆 dashboard.py）：当日热量收支（摄入-消耗-目标差）、宏量营养素占比、7 日趋势（无记录日期补零）
      验收：冒烟测试通过——summary 的 calorie_target/remaining 与档案计算一致，trend 序列按日补零 ✅

## M6 前端 `[ ]`

- [x] **M6.1** 项目脚手架：Vue3 + Vite + TS + Element Plus + Pinia + axios 拦截器（JWT）
- [x] **M6.2** 登录/注册 + 身体档案表单
- [ ] **M6.3** 对话页：SSE 渲染（打字机 + agent 徽章 + 工具轨迹折叠面板）+ HITL 确认卡片（可编辑克数）
- [ ] **M6.4** 拍照记录：图片上传 → 触发对话消息携带 image_url
- [ ] **M6.5** 看板页：ECharts 热量收支 + 宏量营养素环图 + 7 日趋势折线
- [ ] **M6.6** 记录管理：饮食/运动记录列表、编辑、删除

## 附：`agents/qa_agent.py` 图谱位置说明

qa_agent 在 M3.4-M3.6 阶段先以"直连 LLM + 无工具"的占位形态接入图（保证 supervisor 路由可用），M4 再替换为完整 Agentic RAG 实现。
