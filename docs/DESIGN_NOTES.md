# DESIGN_NOTES — 设计决策与踩坑记录（ADR 风格，滚动追加）

> 规则（见 CLAUDE.md）：
> - 记录"决策与理由"，不记录"代码现在怎么跑"（那属于代码注释）；
> - 决策被推翻时**追加**"后续：改为 X"，不删原文；
> - 每条带日期，按时间倒序或正序均可，保持正序追加。

## 2026-09-13 踩坑：HITL 中断时渲染空助手气泡

- **现象**：饮食确认卡片出现时，头像和 Agent 标签下方会多出一个空白圆角框，像“空气泡”。
- **原因**：SSE 收到 `interrupt` 后，助手消息仍保留 `content=""` 且 `streaming=false`；`ChatMessage` 无条件渲染气泡容器，只有内部文字/加载态被条件隐藏，导致边框和 padding 单独留下。
- **解决**：助手气泡仅在存在正文或仍处于流式状态时渲染；中断确认态保留头像、Agent 标签和 HITL 卡片，不再渲染空容器。
- **验证**：`npm run type-check` 与 `npm run build` 均通过。

## 2026-09-13 踩坑：记录接口非法日期冒泡为 500

- **现象**：记录与看板接口的 `date` 参数传入非法字符串时，`date.fromisoformat()` 抛出的 `ValueError` 会穿透 FastAPI 路由，测试客户端收到服务端异常而不是可读的参数错误。
- **原因**：日期解析 helper 只处理了缺省值，没有把标准库异常转换成 HTTP 层契约。
- **解决**：统一在 `api/records.py:_parse_date` 捕获 `ValueError`，返回 422 和“日期格式应为 YYYY-MM-DD”；新增 API 回归测试覆盖该边界。
- **教训**：任何来自 query/body 的标准库解析异常都必须在路由边界转换为明确的 4xx，不能让实现细节决定响应为 500。

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

## 2026-09-09 决策：前端设计系统"去 AI 味"（M6）

- **背景**：用户明确要求"界面不要太粗糙和一股 AI 味"。
- **原则**：暖纸白底（#F7F6F3）+ 墨色文字（#1A1D1A）+ 单一深绿主色（#0E7A5F）+ 细边框分隔，数字用 tabular-nums 等宽对齐。
- **刻意规避的"AI 味"**：大面积渐变、玻璃拟态、霓虹、emoji 当图标、"✨欢迎使用 XX"式空话——这些是当下 AI 生成前端的刻板印象，一出现就显廉价。卡片靠细边框而非阴影浮起；空态用可点击的示例问题（真实可用）而非空泛欢迎语。
- **落地**：Element Plus 通过 CSS 变量（--el-color-primary 等）整体拉进同一色板，不逐组件覆写；图标用 @element-plus/icons-vue 的线性 SVG，不用 emoji。ECharts 用 echarts/core 树摇 + 与色板对齐的克制色，避免默认鲜亮配色。

## 2026-09-09 决策：记录编辑用"线性重算"而非重查食物库（M6.6）

- **背景**：M6.6 需要编辑饮食克数/运动时长，后端原本只有 DELETE。
- **方案**：编辑营养值时按 `新克数 / 原克数` 线性缩放（热量/蛋白/脂肪/碳水同比例），运动消耗按 `新时长 / 原时长` 缩放——不重新查食物库、不重读用户体重。
- **理由**：编辑语义是"我要吃更多/更少、练更久"，不是"换食物/换体重"；且落库时营养值已按当时体重/食物库固化（见 models.py 头部说明），重查会引入新的取值源，反而破坏"历史记录不漂移"的承诺。线性缩放保持记录自洽，且纯本地计算无外部依赖。
- **代价**：改克数不重新做单位换算（如"半份"之类非均匀变化），但克数编辑是等比例缩放的自然模型，够用。


## 2026-09-09 踩坑：SSE 事件类型放 event: 行，前端却在 data JSON 里找 type（M6.3 回归修复）

- **现象**：对话页发消息后永远停在"正在思考…"，无 token、无 agent 徽章、无 HITL 卡片，也无报错。后端 curl 直连分帧完全正常（agent_trace/interrupt/done 齐全），数据库里 user 消息与 checkpoint 也都写了。
- **原因**：协议错位——后端 `_sse(event, data)` 把事件类型放在 SSE 标准的 `event:` 行，data JSON 本身不含 `type` 字段；前端 `handle()` 却 `switch (e.type)` 分发。`e.type` 恒为 `undefined`，switch 一个分支都不进；而分帧解析处的 `catch {}` 把这个静默失败吞掉，连报错都没有。另有一处：tool_calls 的 data 直接就是 `{name, args, result}`，前端却期望包在 `entry` 字段里。
- **排查路径**：curl 直连后端 ✅ → curl 走 Vite 代理 ✅（排除代理缓冲）→ 查 messages/checkpoints 表确认图确实跑到 diet_agent 并 interrupt（排除后端卡死）→ 缩到前端解析代码，对照 `types/index.ts` 的 SseEvent 定义发现 type 字段两边语义不同。
- **解决**：前端解析处一处改动：`event:` 行的名字在 `JSON.parse` 后补进对象再分发（tool_calls 包成 `{type, entry}`），不逐事件改后端六处 yield。
- **教训**：M6.3 验收只验了后端 curl 分帧，没有验前端渲染（SPEC 验收标准里写的是"SSE 收到 agent_trace/interrupt"——收到的主体含糊）。前后端各自定义协议契约（后端 chat.py docstring、前端 types/index.ts）但没有对照测试。跨端协议要么在共享类型里单一来源，要么至少写一个"前端解析逻辑跑真实后端流"的等价性验证（本次用 Node 脚本复刻分帧逻辑跑真流，26 token + interrupt + done 全部分发命中）。

## 2026-09-09 踩坑：HITL 编辑值落库正确但汇报错误（工具结果信息不足 + 三连坑）

- **现象**：用户在确认卡片把 450g 改成 350g，落库正确（350g/546kcal），但 assistant 汇报文本说"450克/702千卡"。
- **原因**：`create_diet_record` 工具的返回值只有 `{status, record_id, total_calories}`，不含确认后的条目明细。react 模型汇报时拿不到真实条目，就照抄自己草稿（interrupt 前的 450g 估算）。
- **解决**：工具结果带上 `items`（final_items，即用户确认后的值）。react 模型看到 350g/546 就如实汇报。
- **连带发现一（轨迹重放）**：resume 恢复时 react 子图的节点差量会整段重放（同一批 AIMessage/ToolMessage 再发一遍），chat.py 的 tool_calls 提取会翻倍（4 条里 2 条重复）。按内容键去重修复。DB 落库无重复（重放只是流事件层现象）。
- **连带发现二（重复路由）**：resume 后 supervisor 有概率把"已完成的任务"再当新任务派给同一 worker（多跑一轮模型、流里出现两段汇报）。hop_count 守卫兜住了但浪费一轮。强化提示词：对话尾部出现"已记录/已创建"完成态必须 FINISH。
- **连带发现三（Vue 响应性）**：前端 `live` 消息是普通对象 push 进 reactive 数组，SSE 事件里对原始引用的 mutate 不触发重渲染（绕过 proxy set 陷阱）——打字机效果实际从未生效，内容只在其它 ref 变化时一次性弹出。改 `reactive()` 包装。
- **已知未修的瑕疵**：下一轮对话的 tool_calls 事件会补发上一轮 resume 前的工具轨迹（LangGraph pending writes 的补发行为），跨轮轨迹有轻微"污染"（如运动消息的执行过程里混着上一轮的饮食工具）。纯展示层，暂不处理。
- **教训**：工具的返回值不只是给落库用的，也是模型下一轮的上下文——HITL 确认后的"事实"必须回流给模型，否则模型汇报的是自己的记忆而非世界现状。

## 2026-09-09 追加：工具结果带 items 仍不够，汇报纪律要写进提示词

- **现象**：工具结果已含确认后的 items（80g/200g/319.2kcal），模型汇报仍复述自己的草稿估算（100g/150g/297kcal）。牛肉面场景能对、早餐场景翻车——qwen 对"以工具结果为准"这件事不稳定。
- **原因**：上下文里同时存在两份"事实"——模型自己的草稿（原始 tool_call args）和工具返回的确认值，模型选哪份是概率行为。
- **解决**：diet_agent 系统提示词加【汇报纪律】：克数与营养值必须以 create_diet_record 返回结果为准，禁止复述估算草稿。复现验证：草稿 100/150 → 改 80/200 → 汇报为 80/200/319.2。
- **教训**：给模型两份相似信息时，"哪份是权威"必须显式声明，不能依赖模型自行判断（数据契约 vs 记忆，同 [[SSE type 协议错位]] 一类：上下文里有歧义时行为不稳定）。

## 2026-09-09 踩坑：supervisor 重复路由复发——prompt 软约束失效，改代码级硬兜底

- **现象**：用户一次提问"建议我之后该怎么吃"，回复里出现两段几乎一样的内容，且都带 RAG 引用 `[1]–[6]` 但引用编号不同（`[1][3][4][6][2]` vs `[3][6][4][5]`）。根因：qa_agent 被 supervisor 连续路由了两次——hop1 派 qa_agent 答一遍，hop2 的 qwen-plus 没识别出"已答完"又把 qa_agent 派了一遍；每次独立重新检索，所以两段引用编号不一样。
- **为什么之前的修复没兜住**：这是 09-09 HITL 三连坑里"连带发现二（重复路由）"的复发。当时只做了 prompt 强化（"对话尾部出现完成态必须 FINISH"），那是软约束、靠 LLM 自觉遵守，qwen-plus 这轮没听进去。
- **解决**：supervisor 加代码级硬兜底——同一轮内不允许把同一个 agent 连续路由两次：本次路由决策目标 == `agent_trace` 里上一个刚跑完的 agent 时，强制改成 FINISH。
- **两个必须想清楚的取舍（面试口径）**：
  1. 判重用 `agent_trace` 而非 `next_agent`：后者在 turn_reset 里没被重置、跨轮残留，会导致"新一轮首个 agent 恰好和上一轮相同"被误杀。
  2. 不能改成"看到 AI 回复就 FINISH"：那会误伤 diet→plan 这类跨 agent 复合请求（记录早餐后再出计划）。"同 agent 判重"只拦重复，不拦跨 agent 接力。
- **教训**：多 Agent 防重复回答，prompt 软约束是底线不是防线，关键不变量要在代码层兜底——"靠 LLM 自觉" vs "代码强制"，正是面试里"你如何保证 agent 不重复干活"这道题的标准答案分界线。

## 2026-09-10 踩坑：image_url 写进 state 后断链，图片识别从未接通（M6.4 起）

- **现象**：`/chat` 传了 `image_url`，但回复像完全没收到图片——文字只有"这是我昨天吃的午饭"（不含任何食物信息），模型也没调 `analyze_food_image`。
- **原因**：`image_url` 的消费链断在中途。`chat.py` 把它写进 `AgentState.image_url`，唯一消费它的 `analyze_food_image` 工具需要模型主动传 URL；而模型（diet_agent 的 qwen-plus 文本模型）从头到尾看不到这个 URL——supervisor 路由只看 `state["messages"]`（纯文本）、不读 `image_url` 字段，diet_agent 提示词却写着"图片 URL 会在任务里给出"——这句描述的是一条**从未接通的设想流程**。设计意图和实现之间隔了一整条没接的线。
- **解决**：在 `_diet_prompt` 里直接从 `state["image_url"]` 注入【图片】块（含 URL + "先 analyze_food_image 再 search_food"的指令），不再依赖 supervisor 把 URL 写进 task。理由：supervisor 是文本路由、本就不该理解图片；diet_agent 是唯一有图片工具的 worker，URL 就在它自己的 state 里，就地注入最直接。顺带把提示词规则 3 的"图片 URL 会在任务里给出"改成"系统提示的【图片】里给出"，与实现对齐。
- **教训**：一个字段"写进了 state"不等于"被消费了"。排查"某输入没生效"，先 grep 这个字段的所有消费点，看它有没有一条路通到真正用它的地方——中间只要有一环没读，就是静默断链，连报错都没有。

## 2026-09-10 踩坑：react agent 工具间叙述泄漏到前端，连系统提示词都被"返"回来

- **现象**：图片记录流里，assistant 回复把系统提示词原样返回了——【图片】指令、"现在我将逐一查询…"、工具返回的 JSON，全挤在最终消息里。
- **原因**：两层叠加。① qwen-plus 在调工具前/之间会"自言自语"，把 step-by-step 指令复述一遍（含【图片】块注入的"先 analyze_food_image 再 search_food"），这些文本是 AIMessage 的 `content`；② `chat.py` 的 "messages" 流模式把所有 AIMessageChunk 的 content 都当 token 推给前端，前端无脑 `live.content += e.content` 累积——叙述和最终汇报混在一起。
- **解决**：双管齐下——
  1. 软约束：diet_agent 提示词加【过程纪律】"调用工具前/之间不输出任何解释或过程文字，直接调用工具"；
  2. 硬兜底（关键）：`chat.py` 的 done 帧带上权威终稿 `content`（即 get_state 取的最后一条 AI 消息），前端收到 done 后用它**替换**累积的 token 文本、而非追加。这样无论模型多话，最终消息一定是干净的最终汇报。
- **教训**：react agent 的工具间叙述是"过程产物"，不是"答案"。流式渲染不能把过程产物当答案——要区分"过程 token"与"终稿"，终稿以图结束后最后一条 AI 消息为准。这是对 [[SSE 工具轨迹从节点 updates 差量配对提取]] 里"token 拼接仅作兜底"那条决策的后续：当时只在持久化层执行了，本次把前端实时视图也拉进同一个权威来源。

## 2026-09-10 踩坑：plan_agent 只输出承诺性开场白就结束，计划永远出不来

- **现象**：对话里输入"请为我制定饮食计划"，plan_agent 只回复一句"接下来我将为您制定一份符合减脂目标、避开禁忌食物、营养均衡的个性化饮食计划。"，之后无任何计划正文。
- **原因链**：
  1. plan_agent 是 react agent，qwen-plus 倾向先说一句"接下来我将…"的承诺性开场白再动手；如果这一句**不带 tool_call**（`create_react_agent` 收到纯文本 AI 消息就当作最终答案结束循环），循环直接终止，开场白就成了最终输出；
  2. 即便 supervisor 意识到任务没完成想再派 plan_agent 补做，也被"同 agent 判重"硬兜底（[[supervisor 重复路由复发]]里的防线）拦成 FINISH——这道防线本职是防重复回答，此处误伤了"没干完要继续干"的正当场景，但根因不在它；
  3. diet_agent 早在 [[react agent 工具间叙述泄漏到前端]] 就加了【过程纪律】规则 6，plan_agent 却一直漏加了这条——同类问题，只改了一个 worker。
- **解决**：plan_agent 系统提示词补两条纪律——【过程纪律】（调工具前/之间不输出解释或过程文字，直接 get_profile）＋【交付纪律】（档案齐全就一次性输出完整计划正文，禁止只说承诺性开场白就结束本轮，开场白之后正文必须跟上）。
- **教训**：同一形态的多个 worker（diet/exercise/plan 都是 create_react_agent），只要在其中一个发现并修复了一类模型行为 bug，就要**逐个排查其余 worker 是否漏了同一道防线**——这里 plan_agent 就是漏掉的。exercise_agent 同样没有【过程纪律】，是下一个可能的同款坑。

## 2026-09-10 踩坑："今天还剩多少热量缺口"错答成"尚未记录饮食"——工具意图不可发现 + 日期幻觉

- **现象**：问"我今天剩余多少热量缺口"，diet_agent 答"今日（2024-06-13）您尚未记录任何饮食"——既没答出缺口，日期还是编的。
- **原因（两层，都不是"缺计算"）**：
  1. 计算早已存在：`services/diet.py:get_daily_summary()` 返回 `remaining`(=目标−摄入+运动消耗) 等全量收支字段，且 `get_diet_records` 工具的返回值里就已带上 `daily_summary`。但该工具的 docstring 只写"查询饮食记录"，模型为答"热量缺口"去调它、看到 `records: []` 就停在"尚未记录"，忽略了手边现成的 `remaining`；diet_agent 提示词与 supervisor 的 AGENT_DUTIES 也都没把"热量缺口 / 剩余可摄入"写成一等意图 → **工具意图不可发现**。
  2. 日期幻觉：supervisor 与所有 worker 的提示词都只说"未说明日期默认今天"，但从没把真实日期注入提示词，qwen-plus 拿不到"今天"就瞎编 2024-06-13（工具内部 `date.today()` 其实是对的，错的只是模型嘴里说的日期）。
- **解决**：
  1. 新增专职工具 `get_daily_summary`（包装 `diet_service.get_daily_summary`），docstring 显式声明"还剩多少热量/热量缺口"意图与各字段含义，加入 diet_agent 工具集；diet_agent 提示词加【热量缺口】规则把它导向该工具；supervisor 的 AGENT_DUTIES 补"热量缺口/剩余可摄入热量"。
  2. `make_supervisor_node` 拼系统提示时注入 `date.today().isoformat()`（占位符 `{today}`），让指代消解把"今天"改写成真实日期。
  3. 【后续补丁，关键】日期只注入 supervisor 不够——最终回复文本由 worker 生成，worker 提示词里没有日期，模型照样固答 baked-in 的 "2024-06-13"。于是把 `【当前日期】{date.today()}` 直接注入 diet/exercise/plan 三个 react worker 的 `_xxx_prompt`（即"答案生产层"）。
- **教训**：
  1. 服务层"算好了"≠ 模型"够得着"。排查"agent 答不对"，先查两样：① 数据/计算到底有没有（grep service 层）；② 模型有没有一条明确的路径够到它——工具 docstring、worker 提示词意图、supervisor 路由职责，三处都要写明，缺一处答案就停在半路。
  2. "模型幻觉日期"这类问题，提示词注入要打在**产出那句话的层级**上：supervisor 改写 task 是一层，worker 生成终稿是另一层，只改前者挡不住后者。qwen-plus 对"今天"有 baked-in 默认值（本例恒为 2024-06-13），不给它真实日期它就固答这个。

## 2026-09-10 决策：可观测性引入 LangSmith（env 透传 + 进程启动早期回填）

- **背景**：curl 直连 SSE 观察 agent 流程偏繁琐，要一个"网页里按时间轴回看"的分布式 tracer。
- **方案**：LangSmith（langchain 官方追踪平台），零侵入——langchain-core 的 callback manager 检测到 `LANGSMITH_TRACING_V2=true` 后，每次 run 自动挂 `LangChainTracer`（supervisor 路由决策、react 每一轮工具、interrupt 挂起都在 trace 里，thread_id 即 conversation_id）。
- **关键实现点（踩坑）**：langchain 读的是 os.environ 里的 `LANGSMITH_*`，而 pydantic-settings 读 `.env` 只写进 Settings 字段、不碰 os.environ——直接把 key 写 `.env` 并不能让 langchain 看到。且 langsmith 的 `get_env_var` 是 lru_cache（首次读取即缓存）。因此必须在 `config.py` import 时（早于任何 LLM/graph 调用）把字段回填进 os.environ，且 TRACING 值必须是小写 "true"（`tracing_is_enabled()` 用 `== "true"` 严格比较，写 "True" 不生效）。
- **依赖**：langsmith 已是 langchain-core 的传递依赖（锁 0.12.2），无需新增；等要直接 import langsmith SDK 时再提升为直接依赖。
- **与自建可观测性的关系**：LangSmith 不替代现有 SSE agent_trace/tool_calls + messages.tool_trace 落库——前者是"回放式"分布式 tracer，后者是"产品内"实时/持久化观测，互补。

## 2026-09-10 踩坑：LangSmith 确认日志在启动时"消失"——import 期 logger.info 被丢弃

- **现象**：按上一条配好 `LANGSMITH_TRACING=true` + key 后重启，控制台看不到"LangSmith 追踪已开启"，据此误判追踪没开。
- **原因**：确认日志写在 `config.py` import 期（回填 os.environ 的必要条件，必须早于任何 LLM/graph 调用），此时 uvicorn 尚未接管日志、root logger 无 handler，logging 兜底 handler 只输出 WARNING+，`logger.info` 被静默丢弃。**追踪其实一直在工作**：`Client().list_projects()` 通 → key/网络没问题；`list_runs(project_name='nutrilens')` 能看到 supervisor/worker 的真实 trace——只是人看不到那条确认信息。
- **解决**：`_apply_langsmith_env` 发 info 前加 `if not logging.getLogger().handlers: logging.basicConfig(level=logging.INFO)`——仅在 root 尚无人配置时补 handler（pytest 已在 root 挂 handler，此处变 no-op，不影响测试）。
- **教训**：import 期日志是"三不管地带"，早于应用日志框架就位。凡"靠看日志确认启动状态"的开关，别假设 import 期的 `logger.info` 一定可见——要么就地补 handler，要么把确认挪到 lifespan/启动事件。可观测性开关本身就该自带可观测：给它一条**保证可见**的开机确认。

## 2026-09-10 踩坑：前端"执行过程"每轮越滚越大——react worker 工具轨迹跨轮累加

- **现象**：对话多轮后，每条 AI 回复的"执行过程"面板里工具越列越多（第 N 轮把前 N-1 轮的工具全带上，实测到 msg#89 已有 21 条工具）；预期应像"深度思考"那样，每条回复只挂自己这一轮的工具。
- **原因**：`chat.py:_extract_tool_calls` 从 worker 子图的 `update["messages"]` 里提炼工具调用，遍历的是**累积后的完整 messages**。react worker 每轮进入时，其 messages（`Annotated[list, add_messages]`）继承父图历轮历史，历轮的 `AIMessage.tool_calls + ToolMessage` 全都在列表里；直接遍历就等于每轮把历史工具重新提炼一遍。外层"每请求局部变量 `tool_trace=[]`"只能保证不跨请求累加，挡不住"本请求内数据源本身已累积"。此次曾据"局部变量已 reset"误判为"前端已按消息隔离、无 bug"，绕了弯路——只看了累加器，没看数据源。
- **解决**：`_extract_tool_calls` 以「最后一条 HumanMessage」为边界、只提炼其后的消息。理由：Human 消息总在每轮开头才追加，其后的工具必属本轮；resume 恢复中断不会新增 Human，本轮 interrupt 前已执行的工具仍被正确归入当前这一轮，HITL 单条消息的轨迹完整性不受影响。
- **教训**：排查"每轮累加"类问题别只盯"累加器是否 reset"，要追到"被遍历的数据源本身是不是 `add_messages` 这类累积通道"。LangGraph 里凡用 reducer 的 channel 跨轮都保留历史；从"状态差量"提炼本轮新增时，要么找累积分界（最后一条 Human / 快照比对），要么按 tool_call_id 去重。

## 2026-09-10 决策：会话自动命名——首条消息 qwen 语义概括 + 兜底截断

- **背景**：会话侧栏每个会话标题都是默认"新会话"，无法区分。
- **方案**：首条用户消息落库后，若 `title` 仍为默认"新会话"，用 qwen（复用 supervisor 同款 `get_text_llm(streaming=False)` 非流式实例）异步生成 4~10 字语义标题，只生成一次；LLM/网络异常时兜底为截取首条消息前 12 字，不阻断对话。
- **取舍**：标题只存语义（"早餐记录"），不把日期塞进 title——侧栏已有 `updated_at` 时间列（当天时分 / 过去 M/D），再塞"9.10"属冗余；语义标题 + 时间列 = 用户要的"日期+精简概括"。
- **为何首消息而非每轮**：首条消息通常已锁定主题，逐轮重命名徒增 LLM 调用与列表抖动（与 ChatGPT 一致）。

## 2026-09-10 踩坑：侧栏会话"当天显示成第二天"——naive datetime 写进 timestamptz 整体偏移

- **现象**：9/10 当天新建/活跃的会话，侧栏时间列显示"9/11"而非当天时分（如 17:50）。
- **原因**：`models.py` 里所有时间列都是 `DateTime(timezone=True)`（Postgres `timestamptz`），
  但默认值用 `datetime.now()`（naive 本地时间）。docker-compose 的 pg 容器没设 TZ、默认
  `Etc/UTC`，naive `17:50` 写进 timestamptz 时被 Postgres 当成 `17:50 UTC`，真实时刻偏移 +8h；
  读回 `.isoformat()` 变成 `...T17:50:00+00:00`，前端 `new Date` 再按浏览器时区(UTC+8)换算
  得 `9/11 01:50`。前端 `formatTime` 本身没错——错在存储的数据，不在显示。
- **解决**：新增 `db/models.py:utcnow()`（`datetime.now(timezone.utc)`）统一替换所有
  timestamptz 列的 `default`/`onupdate`；`chat.py` 手动刷 `updated_at` 处同步改 aware。
- **取舍/边界**：`date.today()`（服务本地日）仍用于饮食/运动记录的"归属哪一天"，这是两个
  不同语义的时钟——日历日归属 vs 时刻记录，前者故意用本地日、后者统一 UTC，不强求一致。
  存量错误行在下次发消息时 `updated_at` 被 aware now 刷新自然纠正，`created_at` 不显示故不追。
- **教训**：`DateTime(timezone=True)` 列必须喂 aware datetime；naive 值会被 DB 按会话时区
  重解读造成整体偏移，且这种偏移常要等前端展示才暴露——"显示层报的度，往往是存储层的病"。

## 2026-09-10 决策：记忆管理——摘要压缩（summary + 近窗口）防 messages 无限累积

- **背景**：会话 messages 是 `add_messages` 累积通道，长会话每轮把全量历史重喂给 supervisor
  与各 react worker，token/延迟线性增长、逼近上下文窗口。这是本次会话定位到的真正缺口
  （此前判断："会话列表"只是产品壳，不是上下文管理层，见其对应用户讨论）。
- **方案**：LangGraph 官方"摘要记忆"模式——
  1. `agents/memory.py` 新增 summarize 节点，插在 turn_reset 之后、supervisor 之前；
     当 `len(messages) > MAX_MESSAGES(24)` 时，把最旧 `KEEP_TAIL(8)` 之前的消息交给
     qwen 折叠成滚动摘要写入 `state.summary`（checkpoint 持久化、跨轮续上）；
  2. 用 `RemoveMessage(id=...)` 删被折叠的旧消息，messages 真正"瘦身"而非只少读；
  3. 摘要只喂 supervisor（指代消解需跨轮上下文）；worker 是 task 驱动、只看近窗口。
- **关键实现点（实验确认）**：裸 `HumanMessage(...).id` 是 None，但消息进图通道时会被
  LangGraph 补发 UUID id，所以 `RemoveMessage` 按 id 删除在真实链路可靠，无需手动补 id。
  短对话时 summarize 是 no-op（返回 `{}`），不多一次 LLM 调用。
- **取舍**：worker 不读 summary（task 已含指代消解）；长期事实（饮食/运动/档案）仍走工具
  查库而非塞进摘要——摘要负责"对话连续性与指代"，不是事实真值来源。阈值 24/保留 8 是
  面向 demo 的可信规模、非调优结论。

## 2026-09-10 踩坑：发图消息被识别成"上一轮记录的食物"——supervisor 指代消解幻觉覆盖了图片

- **现象**：用户前一轮刚记了"两根香肠"，下一轮发「这是我的晚饭」+ 食物照片，确认卡里
  出现的是"香肠"（111g），而不是图片里真实的 白切鸡/炒白菜/米饭/番茄蛋汤。
- **排查（黑盒对照，层层定位）**：
  1. 视觉模型直连 `analyze_food_image(该URL)` —— 结果正确（白切鸡150g/炒白菜/米饭/番茄蛋汤），
     感知层没坏；
  2. 新鲜会话复现同一条图消息 —— 链路正确；只有"带历史"的会话才错 → 锁定是历史上下文在作祟；
  3. 查该会话 checkpoint 的 `supervisor` task 字段 → 竟是
     `"将刚记录的两根香肠标记为晚餐"`。
- **根因**：supervisor 是纯文本路由、**看不到图片**。它把「这是我的晚饭」这个没有食物名词的
  文本，用指代消解关联到了最近一轮「我又吃了两根香肠」，于是改写出"把香肠改成晚餐"的错误
  task。diet_agent 拿到这个 task 后照做，尽管 `image_url` 其实就在 state 里、【图片】指令也
  注入了——**错误的 task 盖过了软性的【图片】指令**。后来我加的"带图时禁止臆测"软提示，
  qwen-plus 在强上下文（香肠刚被记录）下依旧无视，说明：**这类依赖"模型自主决定去调视觉
  工具"的链路，软提示靠不住**。
- **解决（感知与决策分离）**：新增 `analyze_image` 前置节点（插在 turn_reset 之后、supervisor
  之前），本条消息带图时**确定性**地先调 `analyze_food_image`，把结果写进新字段
  `recognized_foods`；再同时注入 supervisor（改写 task 时说"已识别出：白切鸡…，以此为准"）
  与 diet_agent（【图片识别结果】直接给出食物清单，无需也不应再调 analyze_food_image）。
  react agent 不再"记得"去看图，识别只发生一次、结果作为事实注入下游，幻觉空间被结构性消除。
- **教训**：多 Agent 编排里，「把感知/工具调用交给模型按提示自主决定」会被上下文干扰破坏——
  模型会忘调、漏调，或在强上下文下幻觉。**感知、检索、数值计算这类"确定性强、可预计算"的
  步骤，应从决策层剥离成图里的确定性前置/工具节点**，把结果作为事实注入，而不是靠软提示赌
  模型会照做。这跟 diet.py 里"感知(analyze_food_image)与查询(search_food)分离"是同一哲学，
  只是这次把它推到了图编排层：连"是否去看图"这个决策本身也不交给模型。

## 2026-09-11 决策：RAG 从 Python 手工常量切换为可追溯 PDF 导入

- **背景**：原知识库由 `knowledge_data.py` 中的 Python 字符串列表生成。它能验证向量检索，但不具备原始文档、页码、章节、版本或更新记录，回答中的“来源”实际只是人为起的分类名，无法证明知识的可追溯性。
- **方案**：以 `backend/data/knowledge/` 中注册的 PDF 作为正式知识源。新增 `knowledge_documents` 记录来源键、相对路径、SHA-256、解析器版本和页数；每个 `knowledge_chunks` 新增 `document_id`、页码、章节、切片序号和内容哈希。导入链路为：`PDF 文本层提取 → 按章节/页码切片 → 批量 embedding → pgvector + BM25 检索 → rerank → 带页码引用生成`。
- **更新策略**：不按单条正文“见过就跳过”，而是把源文件 SHA-256 作为幂等键。哈希一致且已有完整切片时跳过；哈希变化时，只删除该 document 的旧切片并重建。这样既能避免重复向量，又不会把文档修订和旧版本混在一起。
- **历史数据清理**：旧手工 seed 没有 `document_id`，因此首次 PDF 导入时仅删除 `document_id IS NULL` 的遗留知识切片。不会删除用户、会话、饮食、运动等业务表，也不应以“换知识源”为由清空整个 PostgreSQL 数据库。
- **边界与后续**：当前 PDF 有可提取文本层，适合直接用 `pypdf`；扫描件、复杂表格、图表型 PDF 不能静默按空文本入库，应进入 OCR、表格结构化和图表描述的独立分支。该 PDF 自身缺少发布机构和参考文献，适合作为项目导入样例而不是唯一权威医学依据；后续应补充官方指南，并在文档表中登记原始 URL、发布日期和版权信息。
- **面试讲述**：我没有把 RAG 停留在“把几段字符串写进 Python 再向量化”的 Demo 层，而是把知识源抽象成文档与切片两层。文档层用文件哈希管理版本，切片层保留页码和章节，既能实现幂等导入与局部重建，也能让模型回答回链到具体页面。替换数据源时只清理无文档归属的历史切片，而不是清空业务数据库，体现了数据迁移的最小破坏原则。对于扫描 PDF、表格和用户上传文档，我会把解析失败显式建模并走异步管线，而不是假装所有文件都能直接向量化。

## 2026-09-11 踩坑：把文档标题当作切片引用，导致 RAG 证据不可区分

- **现象**：同一份 PDF 被切为多个 chunk 后，工具轨迹仅展示 `source_title`。因为所有 chunk 都来自《通用营养与运动科学常识知识库》，用户看到的是多个一模一样的来源名，无法判断各条结果分别对应哪一段证据；即使回答写了 `[1][2]`，编号也没有稳定的可核验定位。
- **根因**：`source_title` 的语义是“文档级元数据”，不是“切片级定位符”。旧设计把它冗余存入 `knowledge_chunks`，再直接用于 UI 展示，既制造了数据重复，也混淆了“来源”和“证据位置”两个概念。
- **解决**：来源标题只保留在 `knowledge_documents`，`knowledge_chunks` 通过外键关联文档，并保存 `section`、`page_number`、`chunk_index`。检索结果统一生成 `《文档》· 章节 · 第 N 页 · 片段 M` 标签；工具轨迹、喂给 LLM 的上下文和回答末尾的“参考来源”对照表复用同一格式化函数。编号 `[1][2]` 因而既是回答内标记，也能在末尾定位到具体证据。
- **取舍**：`chunk_index` 不是用户最关心的自然语言位置，但同一章节同一页被切成多段时，它能消除歧义，因此作为最后一级定位保留。未来若加入 PDF 坐标（bounding box）或段落锚点，可再替换为更精细的页内定位。
- **面试讲述**：我发现 RAG 回答虽然“有来源”，但来源粒度其实不够：一份文档拆成几十个 chunk 后，文档标题完全无法区分证据。于是我把文档元数据和切片定位拆开，采用 document 外键保证标题单一真相，再用章节、页码和片段号生成确定性 citation label，并由程序而不是模型负责输出编号对照表。这样既避免了模型漏写参考，也让用户可以实际回查证据。

## 2026-09-11 决策：RAG 引用以结构化证据跨 SSE 与历史消息透传

- **背景**：回答中的 `[1][2]` 如果只是纯文本，前端只能从“参考来源”段落做正则反查；一旦模型遗漏、调整格式或历史消息缺字段，抽屉就无法拿到真实的切片正文。这会让“可点击引用”沦为脆弱的展示技巧，而不是可信的证据链。
- **方案**：QA 节点在生成回答的同时输出结构化 `citations`：`index`、文档/章节/页码/片段定位、标签和完整 chunk 正文。它进入 AgentState，在 SSE 中以独立 `citations` 事件推送，并持久化到 `messages.citations`，历史会话回放读取同一字段。前端只将 citations 中存在的 `[n]` 渲染成蓝色按钮；点击后右侧抽屉按同一回答的全部证据纵向展示，并自动滚到被点击的条目。
- **安全与一致性**：前端不使用 `v-html` 拼可点击链接，避免模型文本成为 HTML 注入面；它只把经过结构化 payload 校验的编号替换为按钮。引用编号、抽屉标签和正文由后端同一份结果生成，避免“页面显示 A、抽屉展示 B”的漂移。
- **面试讲述**：我把 RAG 引用从生成文本升级为结构化 UI 数据。模型只负责在结论旁标注 `[n]`，证据正文和定位由检索管线确定性产出；随后通过 AgentState、SSE、数据库消息表一路透传。这样新消息能实时打开证据抽屉，历史消息刷新后也能回放相同证据，前端不需要猜测或解析 LLM 的自然语言格式。

## 2026-09-11 踩坑：模型臆造引用编号，导致正文与参考来源目录错位

- **现象**：一次 RAG 回答只检索出 6 条证据，程序追加的“参考来源”是 `[1]` 到 `[6]`，但模型正文仍出现了 `[9]`、`[11]`、`[13]`。前端只会把结构化 citations 中存在的编号渲染为蓝色可点击按钮，因此这些错误编号以普通黑字残留，形成“正文编号与目录不对齐”的体验问题。
- **原因**：此前只靠 prompt 要求“不得编造编号”。生成模型会把切片里的页码、片段序号，或自己延续的脚注序列误写为 `[n]`；而“来源目录”是程序根据本轮检索结果确定性生成的，两者没有最后一道约束。
- **解决**：QA 节点生成结构化 citations 后，在最终回答出站前扫描所有纯数字 `[n]` 标记，仅保留 citations 载荷中真实存在的 index，再由程序追加来源目录。前端继续只依据同一份 citations 创建点击按钮，不把无效编号猜测映射到任何切片。
- **面试讲述**：RAG 的引用不能只靠模型“遵守格式”。我把模型输出视作不可信文本：模型可以决定在哪句话旁边放引用，但引用 ID 必须经过检索结果白名单校验；证据目录、抽屉正文和前端可点击标记全部来自结构化检索结果。这相当于把“语言模型生成”与“证据关联”分层，避免漂亮但不可核验的伪引用。

## 2026-09-11 踩坑：模型与程序同时输出来源目录，造成参考来源重复

- **现象**：回复正文后的“参考来源”列表完整出现两次。两份目录的内容看似相同，但会拉长回答，也让用户难以判断哪个才是系统可点击证据的权威来源。
- **原因**：虽然提示词要求模型不要输出目录，但模型仍可能生成 Markdown 标题或纯文本“参考来源：”；随后后端又按结构化 citations 确定性追加目录，形成重复。
- **解决**：最终出站前先移除模型回答末尾的“参考来源”段（兼容 `### 参考来源：` 与普通文本形式），再由 `citation_catalog` 追加唯一目录。程序保留正文中的有效 `[n]`，而目录、点击按钮和抽屉始终只信任结构化 citations。
- **面试讲述**：我把模型生成的引用目录与程序生成的证据目录明确区分：前者只是不可控文本，后者才是检索链路的产物。因此在出站层做规范化，让每个回答只有一份权威证据目录。这是生成式输出与确定性展示层之间的一个典型边界。

## 2026-09-11 踩坑：把检索候选当作最终参考来源，导致目录与正文错位

- **现象**：一条回答正文只使用了 `[1]`、`[3]`、`[4]`，下方“参考来源”却列出 `[1]` 到 `[6]`。其中 `[2]`、`[5]`、`[6]` 只是混合检索与重排阶段召回的候选切片，从未被正文引用；同一 `[1]` 在正文多次出现则是对同一证据的正常重复引用。
- **原因**：旧实现直接以 `retrieve()` 的完整 top-k 生成 citations 和目录，混淆了“候选证据集合”和“模型最终选择的引用集合”。编号也保持召回排序，造成正文出现跳号、目录含无落点条目。
- **解决**：在出站层扫描正文的有效 `[n]`，按首次出现顺序筛出实际使用的结构化 citations；重复出现的同一来源保持同一编号，未使用候选不进入来源目录、SSE、数据库或证据抽屉；对保留项重编为连续编号并同步替换正文标记。工具轨迹仍可展示完整召回结果，保留调试可观测性。
- **面试讲述**：我把 RAG 的“召回候选”与“最终引用”拆成两个数据层。候选集服务模型推理和调试，最终引用集只服务用户核验，并由回答文本中的引用标记驱动。这避免了把“模型看过但没有采纳的材料”误展示为结论依据，也让 UI 中的编号、抽屉和落库数据形成单一真相。

## 2026-09-11 踩坑：模型调用无超时，导致 LangSmith Trace 长期处于运行中

- **现象**：一条请求在 `qa_agent` 的 `ChatOpenAI` 调用处停住，LangSmith 瀑布图持续转圈；若开发时重启后端，旧进程无法补发结束事件，Trace 变成没有结束时间的孤儿记录。
- **原因**：LLM 工厂仅设置了 `max_retries`，但没有设置 OpenAI 兼容客户端的 HTTP 请求超时，也没有限制流式响应相邻 chunk 的等待时间。上游连接半开或服务端长时间无响应时，图执行没有自然退出边界。
- **解决**：新增可配置的 `LLM_TIMEOUT_SECONDS`（默认 60 秒），文本模型同时设置 `request_timeout` 与 `stream_chunk_timeout`，视觉模型和 embedding 客户端设置 HTTP timeout；聊天 SSE 捕获 OpenAI/httpx 超时并返回结构化 `llm_timeout` 错误。图以异常结束，追踪平台可以记录失败而不是永久运行。
- **取舍**：仍保留 2 次重试以应对短暂网络抖动，因此极端情况下总等待会长于单次 60 秒；如果生产环境更强调交互时延，可将重试次数下调并配置更短超时。
- **面试讲述**：我把外部模型调用当成不可靠 I/O，而不是普通函数调用：需要有超时、重试和面向用户的降级提示。这样故障不会把 Agent 图、SSE 连接和观测 Trace 一起拖入无终止状态，系统具备明确的失败边界。

## 2026-09-17 决策：计划生成先落在对话，结构化计划持久化后置

- **背景**：现有 `plan_agent` 会读取身体档案并生成自然语言建议，但数据库与 REST API 中尚无 `plans`、`plan_items` 或计划完成状态。若前端直接展示一份“我的计划”，只能依赖假数据，用户会误以为计划已保存并可追踪。
- **方案**：饮食计划页定位为计划工作流入口，而非持久化结果页。点击“生成饮食与运动计划”后跳转 `/chat?prompt=...`；对话页消费该参数，把提示词放入输入框并清理 URL，用户可补充偏好后再发送。饮食与运动保持在同一计划提示中，由现有 supervisor 决定是否交给 `plan_agent`、`exercise_agent` 等既有 worker，前端不改变多 Agent 编排。
- **后续接口边界**：计划确认与存储落地时，再新增 `Plan` 与 `PlanItem`（`kind=meal|exercise`）及可选完成记录；计划页只切换为读取真实计划 API。这样不会影响当前记录、档案和 SSE 对话链路，也不会让前端协议先于后端数据模型膨胀。

## 2026-09-17 调整：计划结果在 SSE 出站层自动归档

- **变化原因**：用户已经在 `/chat` 获得了计划，但原来的计划页只是跳转入口，生成内容没有可见的归宿。让模型额外调用一个“保存计划”工具会把数据一致性建立在模型是否遵守提示词上，也会对现有 Agent 工具链引入不必要的不确定性。
- **方案**：新增 `Plan` 业务模型与当前计划 API。聊天端取得 `plan_agent` 的权威最终内容后，若 supervisor 子任务明确包含“计划”，就在同一轮出站逻辑中保存为当前版本；新版本将旧版本标记为非当前。计划页只读 `/api/plans/current`，历史计划回复则保留手动同步按钮。
- **边界**：当前保存的是完整计划正文，饮食与运动保持为一份一致的 AI 交付；后续若需要按餐次或训练日打卡，再在此模型之下引入 `PlanItem`，而不是解析前端展示文本。supervisor 仍以原来的 star 拓扑路由，未发生职责变更。

## 2026-09-20 踩坑：复合饮食运动请求被单域 worker 误处理并覆盖回复

- **现象**：用户在一条消息中同时描述饮食和运动时，饮食记录与运动记录可能都已落库，但执行轨迹中出现 `exercise_agent is not a valid tool`，饮食 worker 还可能重复写入饮食；最终助手消息只显示最后一个运动汇报，看起来像运动结果覆盖了饮食结果。
- **根因**：supervisor 只负责选择下一个 worker，原始复合用户消息仍被完整注入 react 子图。饮食 worker 因而可能把另一个 agent 名称当成工具调用；同时 SSE 出站层用“最后一条 AIMessage”作为终稿，天然丢失前一个 worker 的完成汇报。
- **解决**：supervisor 提示词明确要求复合请求按领域拆成独立 task，并在 worker 之间继续路由未完成部分；diet/exercise worker 用 supervisor 的单域 task 替换当前轮原始用户文本，并加入任务边界约束；出站层按当前轮收集所有不带 tool_calls 的 worker 终态汇报，按执行顺序合并后再落库和推送。
- **边界**：仍保留最多两次路由，适配本项目当前的饮食 + 运动双域请求；若未来支持三个以上独立领域，应把“待处理子任务”从提示词约定升级为结构化状态字段，而不是继续依赖自然语言判断。
- **面试讲述**：多 Agent 系统中，“执行结果已落库”与“用户是否看到完整结果”是两个独立一致性问题。前者要靠 worker 任务边界和幂等写入保护，后者要靠出站层基于本轮事件聚合，而不是简单取最后一条消息。

## 2026-09-21 踩坑：Windows 通配地址端口探测漏掉 loopback 占用

- **现象**：开发启动脚本先用 `bind(0.0.0.0, port)` 检查端口；当另一个进程只监听 `127.0.0.1:port` 时，Windows 的探测仍可能返回成功，随后 Uvicorn 以通配地址启动，导致端口选择与实际本地访问行为不可靠。
- **原因**：Windows 对指定地址与通配地址的 socket 绑定语义不同于常见的 Linux 直觉，单独探测一个地址不能代表同端口上所有本地监听冲突。
- **解决**：启动脚本对 IPv4 的通配/回环地址成对检查：目标为 `0.0.0.0` 时额外检查 `127.0.0.1`，反向同理；新增真实 socket 回归测试。脚本实际选定端口后原子写入 `.runtime-port`，退出时只删除仍属于自己的端口记录，供 Vite 代理安全读取。

## 2026-09-21 决策：Agent 指标采用固定任务集的端到端离线评测

- **背景**：RAG 已有 Recall@K、MRR、nDCG 等“是否召回对证据”的指标，但它不能证明 supervisor 是否选对 worker、工具是否被正确调用、HITL 是否真的阻止了未经确认的写入，更不能证明复合饮食/运动请求能完整执行。因此不能拿 RAG 分数代替 Agent 可靠性，也不能凭主观 Demo 给简历填成功率。
- **方案**：新增 `agent-tasks-v1` 固定任务集（20 条），分为饮食记录/查询删除、运动记录/查询删除、混合意图、HITL 取消与过敏确认、档案与计划五类。每个 episode 以独立测试用户和随机 thread_id 运行真实 `qwen-plus` + 完整 LangGraph；checkpointer 使用 `MemorySaver`，避免污染生产会话；饮食确认完全复用前端的 `Command(resume=...)` 协议；结束后检查 `diet_records`、`exercise_records` 和档案是否符合预期，并删除测试用户。
- **指标口径**：
  1. **任务完成率**：一次 episode 只有同时满足预期 worker 已路由、必需工具齐全且无未允许/禁止工具、数据库副作用符合、HITL 结果符合，才记成功；公式为 `完成 episodes / 总 episodes`。
  2. **工具调用准确率**：按 episode 而非按工具调用计数，判定 `required_tools ⊆ actual_tools`、`actual_tools ⊆ allowed_tools` 且 `forbidden_tools ∩ actual_tools = ∅`。这样一个多工具任务不会因为调用次数多而虚高分数；禁止工具与未允许工具在失败明细中互斥归类，避免同一错误双计。
- **可复盘性**：每份 JSON 报告保留数据集版本、模型名、运行次数、分类得分、每条实际 agent 轨迹、工具参数与返回、数据库副作用和失败原因。报告目录 `backend/reports/` 被 git 忽略，数字可由 `uv run python scripts/run_agent_eval.py --repeats 3` 重跑，而不是写死在文档或代码里。
- **已验证基线**：在本机可用 PostgreSQL、食物库与 DashScope 凭据条件下，`qwen-plus` 对 20 条任务各跑 3 次，共 60 episodes；任务完成率 `100.00%`，工具调用准确率 `100.00%`，五个分类均为 `100.00%`，无执行异常。该结论只适用于该版本固定离线任务集，简历必须写“固定离线任务集”并同时给出任务数与重复次数，不能外推为线上真实用户准确率。
- **踩坑**：评测脚本的 `finally` 会正常清理测试用户；但在排查阶段强制终止一个重复启动的批跑时，进程来不及执行清理，留下了带 `agent_eval_` 前缀的用户。已删除并核验零残留。由此可见，隔离命名能把异常中断时的人工清理范围限制到确定集合；正式跑分应等待批跑自然结束，不并发启动重复任务。
- **面试讲述**：我把 Agent 成功定义为“路由、工具、HITL、持久化副作用”共同满足的端到端契约，而不是模型回复看起来像成功。RAG 的证据质量仍单独评估；对会产生业务写入的 Agent，则用固定任务集和数据库断言做黑盒验收。指标按 episode 计数，并保存失败轨迹，所以既能给出简历数字，也能定位是路由、工具选择、确认流程还是落库出了问题。

## 2026-09-21 踩坑：流式 QA 生成不返回 Token usage，端到端评测覆盖率为零

- **现象**：首次为 QA 端到端压测接入 Token 采集后，30 个 episode 共 60 次 LLM 调用全部被标记为缺失 usage，无法诚实地给出 Token 分位数。
- **排查**：直接调用非流式 `qwen-plus` 时，LangChain 回调中的 `AIMessage.usage_metadata` 和 `LLMResult.llm_output.token_usage` 都存在；沿 QA 链路逐次打印回调后发现，结构化自检（非流式）可返回 usage，而最终回答使用的流式 `ChatOpenAI` 默认回调只携带文本，不带 usage。因此问题位于客户端流式请求参数，而不是采集器的聚合逻辑。
- **解决**：在统一文本模型工厂显式设置 `stream_usage=True`；QA 节点支持仅供评测注入的 callback，并将同一采集器传给自检和最终生成。采集器优先读取标准 `usage_metadata`，再兼容 OpenAI `token_usage`；任何一次调用缺失 usage，整个 episode 都不会被当作 0 Token 参与分位数，而是计入 coverage。
- **验证**：固定 10 条 RAG 问题、每条重复 3 次，共 30 个端到端 episode；修复后 Token coverage 为 `30/30`，LLM 调用 coverage 为 `60/60`。总 Token P50 为 `2344`、P95 为 `2898`、P99 为 `2934`；端到端 QA 延迟 P50 为 `6098.3ms`、P95 为 `7796.6ms`。报告仅代表本机、当前模型版本和固定离线问题集，不外推为线上用户 Token 或延迟。
- **面试讲述**：Token 指标不能只数最终回答，也不能在上游未提供 usage 时填 0。我把它做成以 episode 为单位的可审计统计：覆盖自检和生成的全部模型调用，先报告 coverage，再报告分位数。排查时还发现流式接口和普通调用的 usage 返回形态不同，于是在模型工厂统一开启 stream usage，避免 SSE 用户路径与离线成本评测使用两套不一致的客户端行为。

## 2026-09-21 踩坑：严格 RAG 规则升级后，旧单测仍要求“部分证据也回答”

- **现象**：完整回归中 `test_qa_agent_rag.py` 的 fake self-check 构造了已删除的 `coverage="partial"` 字段，触发 Pydantic 校验错误；即使补齐字段，原测试仍期待模型用一条仅支持“有氧运动”的切片回答包含“是否需要力量训练”的复合问题。
- **原因**：测试写于宽松策略时期。当时“部分覆盖”允许模型只回答已覆盖部分；后来严格 RAG 改为 `QaSelfCheck.sufficient: bool`，要求证据不能直接覆盖完整问题时统一返回“未找到可靠信息”，并禁止生成模型以通用知识补齐。生产代码已切换，测试替身和断言没有同步。
- **解决**：把该用例改为 `sufficient=False`，断言返回固定拒答文案、citations 为空、生成模型未被调用。这样“无证据”与“仅擦边证据”两类路径都被锁定为拒答，严格模式不会在测试层被旧预期悄悄放宽。
- **教训**：提示词和数据模型的收紧属于行为契约变更，除了更新生产代码，也必须搜索 fake LLM、Pydantic 构造和旧的自然语言断言；否则测试不是在守护新规则，而是在要求代码退回旧规则。
