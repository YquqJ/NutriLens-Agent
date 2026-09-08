# DESIGN_NOTES — 设计决策与踩坑记录（ADR 风格，滚动追加）

> 规则（见 CLAUDE.md）：
> - 记录"决策与理由"，不记录"代码现在怎么跑"（那属于代码注释）；
> - 决策被推翻时**追加**"后续：改为 X"，不删原文；
> - 每条带日期，按时间倒序或正序均可，保持正序追加。

---

## 2026-09-08 决策：LLM 输出断言的容差设计（E2E 测试稳定性）

- **现象**：plan_agent E2E 间歇性挂——模型偶尔把 2055.6 写成"约 2056"或"2,055"，纯字符串匹配 `2055 in content` 失败。
- **规则**：对 LLM 生成内容的断言分两类处理——
  1. **行为类断言**（调了哪些工具、写没写库）：精确断言，这是确定性事实；
  2. **内容类断言**（引用了数字、提到了偏好）：做归一化（去逗号）+ 容差（精确值或 ±1 取整变体）+ 多次运行（3 轮全过才算稳定）。
- **教训**：LLM E2E 测试的 flaky 先看断言是否过严，再怀疑代码；断言挂了不要立刻改代码，先单独重跑定位是行为问题还是表述问题。

## 2026-09-08 踩坑：langgraph 与 langgraph-prebuilt 版本错配，import 直接崩

- **现象**：`from langgraph.prebuilt import create_react_agent` 报 `ModuleNotFoundError: No module named 'langgraph.stream'`。
- **原因**：`langgraph 0.4.10` 声明 `langgraph-prebuilt>=0.2.0` **无上界**，uv 解析到最新的 `1.1.0`（配套 langgraph 1.x 的新拆分包），新旧混装。
- **解决**：pyproject 显式 pin `langgraph-prebuilt>=0.2,<0.5`，解析回 0.2.3。
- **教训**：meta 包的依赖声明不总是带上界的，锁定主包版本时要把配套拆分包一起锁（`uv pip index` / `uv run --with` 可快速探测可解析版本）。

## 2026-09-08 踩坑：create_react_agent 的 callable prompt 返回字符串 → 模型失忆死循环

- **现象**：diet_agent 无限重复调用 `search_food`（同样的参数），直到触发 `GraphRecursionError`（25 轮上限）。加提示词"禁止重复查询"无效。
- **排查过程**（值得复用的方法论）：
  1. 先隔离模型：手工构造 [Human, AI(tool_call), Tool(result)] 消息序列直接 `bind_tools().invoke()`——模型行为完全正常，证明不是模型/提示词问题；
  2. 在 prompt callable 里加 spy 打印 state，发现消息历史在 state 中**累积正常**（id 配对无误）；
  3. 读 prebuilt 0.2.3 源码 `_get_prompt_runnable`：callable 的返回值会**整体作为模型输入**，而我返回的只是提示词字符串——**模型每轮只看到一句系统提示，看不到任何历史消息和工具结果**，于是每轮做同样的决定。
- **解决**：callable 返回 `[SystemMessage(人设+任务)] + state["messages"]` 全量列表。
- **教训**：Agent "无限重复同一工具调用"的第一怀疑对象不是提示词，而是**模型实际收到的输入**——用 spy 打出来看，别猜。另外 langgraph 各版本 prebuilt API 有差异，用法以当前安装版本源码为准。

## 2026-09-08 决策：qwen-plus 在空食物库上会反复重查（行为侧加固）

- **现象**：食物库未命中时 qwen-plus 倾向换 top_k 重查同一食物（即使历史里已有未命中结果）——在 callable prompt bug 修复后基本消失，但行为本身存在。
- **措施**：双层加固——diet_agent 系统提示词写明"每种食物最多查询一次"；`search_food` 未命中 hint 改为强指令（禁止重查、立即估算）。
- **后续**：M3.8 食物库 seed 后此场景出现率大幅下降，但防御性提示词保留。

## 2026-09-08 踩坑：本机 5432 端口被其他项目占用

- **现象**：`docker compose up` 报 `Bind for 0.0.0.0:5432 failed: port is already allocated`。
- **原因**：同机另一个项目（cookhero）的 postgres 容器随 Docker Desktop 自启动，占了 5432。
- **解决**：NutriLens 改用宿主机 5433（`docker-compose.yml` / `.env.example` / `config.py` 三处同步）。
- **教训**：多项目共用一台开发机时，compose 端口别都抢 5432 默认值；Navicat 连接时注意端口是 5433。

## 2026-09-08 踩坑：Git Bash 下 curl 传中文 JSON 解析失败

- **现象**：FastAPI 返回 `{"detail":"There was an error parsing the body"}`。
- **原因**：Windows Git Bash 的 `curl -d '中文'` 按 GBK 编码发出，服务端按 UTF-8 解析失败。
- **解决**：中文 body 写入 UTF-8 临时文件，用 `curl --data-binary @file` 发送。
- **教训**：Windows 下做接口联调，含非 ASCII 的请求体一律走文件；测试里用 TestClient（进程内）可完全绕开。

## 2026-09-08 踩坑：跨 Session 删除 ORM 父对象报错（fixture 清理）

- **现象**：测试 teardown 中 `db.delete(user)` 抛错（用户在另一个 SQLAlchemy Session 里被关联了 UserProfile）。
- **原因**：ORM 删父对象时会懒加载 relationship 子对象并尝试把子表外键置 NULL；`user_profiles.user_id` 是主键非空，置 NULL 失败。
- **解决**：清理时先显式删子行（profile）再删父行；或用 bulk delete（`query().delete()` 绕过 ORM 层，交给 DB 外键 ON DELETE CASCADE）。
- **教训**：多 Session 场景（Agent 工具每次调用独立 Session）下，测试清理不要依赖 ORM 级联感知。

## 2026-09-08 决策：饮食写库走 HITL，运动直接落库

- **背景**：两条写库路径一个用 `interrupt()` 请求人工确认，一个直接写。
- **理由**：HITL 的成本是打断交互，收益是拦住不可信数据。饮食克数由 VL 模型估算、误差大 → 值得拦；运动的"类型+时长"由用户亲口陈述、无估算环节 → 拦了纯添堵。
- **面试口径**：同一项目里两种策略并存，说明 human-in-the-loop 是按"数据可信度"做工程取舍，不是流程装饰。

## 2026-09-08 决策：档案更新业务逻辑从路由下沉到 service

- **背景**：M3.2 之前，"部分更新档案 + 重算 BMR/TDEE"写在 `api/users.py` 的 PUT 处理函数里。
- **理由**：Agent 工具（`tools/profile.py`）需要同一逻辑；按项目纪律 REST 与工具共用 service 层，于是先下沉再复用，路由变薄。
- **验证**：回归测试断言 REST 行为与下沉前的冒烟手算值完全一致（1648.8/2555.6/2055.6）。

## 2026-09-08 决策：数据库端口/凭据用默认值兜底，服务可裸跑

- **理由**：`config.py` 所有字段给了默认值（密钥为空串），无 `.env` 也能起服务——冒烟测试与单元测试不依赖外部凭据；只有调 LLM/OSS 的功能才需要真 key。

## 2026-09-08 踩坑：supervisor 返回注解 Command[RouteTarget] 导致图编译失败

- **现象**：`StateGraph.compile()` 抛 `ValueError: Found edge ending at unknown node FINISH`。
- **原因**：LangGraph 在 compile 时会解析节点函数返回注解里的字面量类型，作为 `Command` 的 goto 目标白名单做静态校验。`RouteTarget` 包含 `"FINISH"`（只是路由决策枚举值，真正跳转用的是 `END` 常量即 `"__end__"`），于是校验认为存在一条指向不存在节点的边。
- **解决**：supervisor 节点函数返回注解改为裸 `Command`（放弃静态 goto 校验，换取枚举与图节点名的解耦）。
- **教训**：`Command[Literal[...]]` 注解不是文档，是被运行时消费的约束；枚举值和图节点名要保持"同构但隔离"时，别让校验器看见枚举。

## 2026-09-08 踩坑：langgraph 0.4.10 + checkpoint-postgres 的 pending_sends 序列化崩溃

- **现象**：图用 PostgresSaver 编译运行正常，但 worker 子图（create_react_agent）一调工具就抛 `TypeError: Object of type Send is not JSON serializable`。
- **原因链**（排查了整条版本矩阵）：
  1. react 子图用 Send API 调度工具节点，`_apply_writes` 把 Send 对象放进 `checkpoint["pending_sends"]`（顶层字段，langgraph 0.4.x 的 v3 checkpoint 格式）；
  2. checkpoint-postgres 的 `put()` 把整个 checkpoint 用 psycopg 的原生 `json.dumps` 落 JSONB 列 —— Send 不可序列化，2.x/3.x 全线如此；
  3. 3.x 对 langgraph<0.5 的 DeprecationWarning 是版本号嗅探过于保守（实测 3.x 才是 0.4.10 的正确配对方向），但即使 3.x 也没修 put 路径；
  4. Send 另有一条落库通道（`put_writes` → `checkpoint_writes` 表，走 serde），但那只服务 v<4 的读迁移逻辑，**恢复执行（PUSH 任务重调度）依赖的是 checkpoint 里的 pending_sends 本身** —— 试过"写时剥离"，interrupt 恢复时 PUSH 任务丢失，agent 节点看到悬空 tool_calls 报 INVALID_CHAT_HISTORY。
- **解决**：`NutriLensPostgresSaver(PostgresSaver)` 补丁 —— put 时把 Send 编码成 JSON 安全结构（serde msgpack + base64），`_load_checkpoint_tuple` 时解码还原，保证与 MemorySaver 行为一致。依赖版本钉在 `langgraph-checkpoint-postgres>=3.0,<4.0`（2.x 连读迁移都没有，更不可用）。
- **验证**：全图 HITL（interrupt 挂起 → Command(resume) → 落库）E2E 测试固化在 tests/test_supervisor_graph.py。
- **面试口径**：这是"锁版本"策略的代价样本 —— 0.4.x 的 checkpoint 格式（v3/pending_sends）与 3.x saver 的预期格式（v4/通道化）之间有一个版本缝隙，官方没测的组合只能自己补桥。

## 2026-09-08 决策：turn_reset 入口节点 —— "轮内"状态每轮重置

- **背景**：hop_count/agent_trace/tool_calls 持久化在 checkpoint 里，但语义是"本轮"（防死循环计数/前端渲染轨迹）。
- **问题**：不重置时 hop_count 跨轮累积 —— 第一轮路由两次后，第二轮直接被防死循环守卫强制结束，worker 得不到任何执行机会（E2E 第二轮 invoke 无任何回复暴露了这点）。
- **方案**：图入口加 `turn_reset` 节点，每轮用户消息进来时重置这三个字段。`Command(resume=...)` 恢复中断不经过 START，不受影响。
- **对比过的替代方案**：由 API 层每次 invoke 传 `hop_count: 0` —— 可行但把不变式外包给了调用方，忘传即静默劣化；图自治（self-contained）更稳。

## 2026-09-09 踩坑：astream 走 async checkpointer 接口，同步 PostgresSaver 直接 NotImplementedError

- **现象**：SSE 端点用 `graph.astream(...)`，第一个请求即抛 `NotImplementedError`（langgraph/checkpoint/base 的 `aget_tuple`）。
- **原因**：`astream` 全链路调用 checkpointer 的 **async** 接口（`aget_tuple`/`aput`...），同步版 `PostgresSaver` 只实现了同步方法，基类 async 方法直接 raise。而 pending_sends 补丁打在同步类上，迁移 `AsyncPostgresSaver` 意味着补丁重写 + 连接管理重做。
- **解决**：生成器改为**同步** `graph.stream(...)`。starlette 的 StreamingResponse 原生支持同步迭代器（在 anyio 线程池里逐帧拉取），不必迁移异步版——一个同步迭代器的代价是流期间占用一个线程池线程，对当前规模可接受。
- **面试口径**：FastAPI 异步栈里跑同步阻塞迭代器是刻意取舍——异步化的收益（并发吞吐）远小于迁移成本（checkpointer 双实现 + 补丁重写），等出现真实并发瓶颈再还这笔债。

## 2026-09-09 决策：SSE 工具轨迹从节点 updates 差量配对提取，而非逐工具实时推送

- **背景**：tool_calls 事件需要 {name, args, result} 三元组；react 子图内部的工具调用默认不产生顶层节点更新。
- **方案**：worker 节点（子图整体）完成时的 updates 差量里，`AIMessage.tool_calls` 与 `ToolMessage` 按 `tool_call_id` 配对，一次性提取该 worker 本轮全部调用。
- **代价（已确认可接受）**：HITL 挂起发生在工具内部时，节点差量要等 resume 之后才产出——interrupt 之前已执行的工具（如 search_food）轨迹事件会在**恢复后补发**，顺序晚于 interrupt 事件。若未来要"每工具实时推"，需开 `subgraphs=True` 拿子图内部节点更新，chunk 会带 namespace 三元组，复杂度上一个台阶，目前不值。
- **顺带决策**：assistant 消息内容取自流结束后 `get_state()` 的最后一条 AI 消息（权威），token 拼接仅作兜底——多 hop 场景下拼接会把中间临场文本混进最终汇报。

## 2026-09-09 踩坑：元组排序平局回退比较 ORM 对象 —— 小数据集测不出来的 bug

- **现象**：食物库全量 seed（789 条）后，`search_foods` 抛 `TypeError: '<' not supported between instances of 'Food' and 'Food'`。
- **原因**：`sorted((match_rank(f), f) for f in rows)` 对 (rank, Food) 元组整体排序——rank 相同时 Python 回退比较元组第二项，ORM 对象没有定义 `<` 直接崩。之前不触发纯粹因为测试库数据少、rank 无平局。
- **解决**：`key=lambda t: t[0]` 只按 rank 键排序。
- **教训（面试口径）**：元组排序的平局回退是 Python 隐式行为，配自定义对象就是定时炸弹，且只有数据量上来才会引爆——"排序键要么唯一、要么显式给 key"。

## 2026-09-09 踩坑：测试断言编码了"环境为空"的假设，seed 后整体翻车

- **现象**：M3.8 灌入食物库后 `test_diet_agent_full_flow_with_hitl` 稳定失败（非偶发），断言所有条目 `confidence == "llm_estimate"`。
- **原因**：该测试写于食物库为空时，注释里明确写着"食物库当前为空（seed 在 M3.8），必然是 LLM 估算"——把环境快照当成了行为契约。seed 后"牛肉面"可查库精确命中，agent 正确改用 db_exact，旧断言反而把**正确行为**判为失败。
- **解决**：断言改为契约级——confidence 必须是三档枚举之一，不绑定具体哪档（哪一档取决于库里有没有该食物，那是环境）。
- **教训**：写"当前环境恰好如何"的断言时，在旁边标注触发条件翻转的里程碑（本次注释恰好标了 M3.8，看到失败就能立刻定位）；断言尽量对着接口契约写，别对着环境快照写。

## 2026-09-09 决策：qa_agent 用显式编排节点而非 react 循环

- **背景**：M4.5 的 qa_agent 检索流程是"检索 → 自检 → 改写重检（≤2 轮）"，SPEC 称 Agentic RAG。
- **理由**：检索迭代是有界的确定性流程，不需要模型即兴决定下一步；显式编排（普通节点函数）比 create_react_agent 更可控、可测、可解释——"Agentic"的关键在流程能自主迭代，不在是否用 react。diet/exercise worker 用 react 是因为工具调用序列真的开放；qa 的检索轮数有硬上界，写死更好。
- **代价与对齐**：检索轨迹不再是 react 工具调用的差量格式，通过 state["tool_calls"] 由节点 update 直接带回，chat.py 侧统一收集两路轨迹（react 差量配对 + 节点直带）——对 SSE 与落库保持同构。

## 2026-09-09 踩坑：embedding 不可逐位断言（远端非确定性）

- **现象**：embedding 分批顺序测试最初断言两次调用结果逐位相等，失败。
- **原因**：DashScope embedding 两次调用存在微小浮点差异（服务端非严格确定性），"逐位相等"是把环境属性当成了接口契约（与 M3.8 的"环境快照断言"同一类错误）。
- **解决**：改用余弦相似度断言（同文本高相似、异文本低相似）——检验的才是真正关心的契约：分批不乱序。
