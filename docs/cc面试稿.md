# 面试稿 · NutriLens（费曼走读产出）

> 本文件由走读过程逐层累计：**简历 bullet（草稿）** + **追问防御点（概念）**。
> 走读方式：读一层代码 → 复述 → 纠缺口 → 压成下面一条。此为活的文档，后续逐层追加。

## 进度

| 状态 | 文件 |
|---|---|
| ✅ 已走读 | `graph.py` / `supervisor.py` / `state.py` / `diet_agent.py` / `tools/diet.py` / `api/chat.py` / `qa_agent.py` + `rag/` / `exercise_agent.py` + `plan_agent.py` / `services/profile.py` / `db/models.py` / `agents/llm.py` / `agents/memory.py` + `tools/context.py` / `core/security.py` + `core/deps.py` + `api/auth.py`（认证链）/ `api/records.py` + `api/conversations.py` + `main.py` + `core/config.py` + `db/session.py`（双表面） |
| ⏭ 待办   | 手写自测（8 个原子白板默写）与前端三悬案暂缓 |

---

## 一、简历项目段

> 分两层：**简历版**（投递用，短钩子、无私有符号）与**展开版**（面试追问用，被问时按「条 → 节」下钻到「二、追问防御点」）。

### 简历版（Claude Code版）

1. **多 Agent 编排（LangGraph）**：基于 LangGraph 搭建个人健康管理后端，Supervisor 星型路由统一调度饮食/运动/问答/计划四类子 Agent，结构化路由防死循环，worker 无直连、工具权限隔离。
2. **写库 HITL 与安全护栏**：饮食记录引入 human-in-the-loop，模型估算的克数须经用户确认/编辑后再落库；过敏风险用规则匹配而非模型判断、多层拦截，写库可控可解释。
3. **Agentic RAG 知识问答**：实现「检索→自检→不足改写重检」迭代，向量 + 关键词混合检索与重排，证据不足改拒答而非硬编；回答带章节/页码级引用、前端可点击溯源。
4. **确定性工程**：多模态识别只输出「看见什么」、营养值一律查库不走模型；BMR/TDEE 由服务层公式计算落库、LLM 只解读不算法术——确定性优先、估算打标兜底。

> 第 3 条可选追加量化结果：「建立 Recall/MRR/nDCG 检索评测，Recall@4 ≈ 0.91」——加分但会引来"怎么测的"追问，敢接住再放。

### 简历版（Codex版）

**【多 Agent 编排】**：基于 LangGraph 构建 Supervisor 星型架构，编排饮食、运动、知识问答、计划生成 4 类 Worker；使用 Pydantic 结构化路由和任务改写完成意图识别与指代消解，并通过路由次数限制、重复路由拦截和轮内状态重置避免 Agent 循环执行。

**【会话记忆管理】**：基于 PostgresSaver 持久化 AgentState，以 conversation_id 复用为 thread_id，实现跨请求上下文恢复与中断续跑；设计滚动摘要机制压缩长对话，在保留近期消息的同时支持跨轮指代消解，控制上下文持续膨胀。

**【HITL 安全写入】**：使用 interrupt() 在饮食记录落库前挂起图，将模型生成的食物和克数草稿通过 SSE 推送至前端；支持用户修改克数、删除食物或取消操作，再通过 Command(resume) 恢复执行，并结合确定性过敏规则与服务层校验保护写库边界。

**【Agentic RAG】**：构建包含 3 份 PDF、146 个切片的多文档知识库，实现章节感知切分、文件哈希幂等导入、pgvector 向量检索、BM25 关键词检索、RRF 融合和 Rerank 精排；加入检索充分性自检与 Query Rewrite，并支持文档、章节、页码和原文片段级引用溯源。

**【RAG 量化评测】**：建立包含 32 条正例、5 条领域外负例的 Golden Dataset，对 Vector、BM25、RRF、Rerank 进行消融实验；RRF 将 Recall@4 从 87.50% 提升至 96.88%，Recall@8 达到 98.44%，Rerank 将 MRR 从 86.62% 提升至 91.67%。

**【Agent 前端交互】**：基于 Vue 3、TypeScript 实现 Agent 产品界面，使用 fetch + ReadableStream 解析 POST SSE，实时展示模型回复、Agent 路由及工具调用轨迹；实现可编辑 HITL 确认卡片、图片识别、可点击引用抽屉、历史会话、记录管理和 ECharts 健康看板。


### 展开版（面试追问用 · 原 5 条；checkpointer 已从简历移除、留作"踩坑"追问素材）

1. **【LangGraph Supervisor 星型多 Agent 编排 + 结构化路由】**
   基于 LangGraph 实现 Supervisor 星型多 Agent：饮食/运动/问答/计划四类 worker 共享全局状态、经 Supervisor 统一路由、worker 间无直连（控制集中，隔离工具权限、避免 agent 间循环踢皮球）；Supervisor 用 Pydantic 钉死路由输出为 `{next_agent, task}`，结合历史做指代消解、把用户原话改写成脱离上下文可独立执行的子任务，配 hop_count 硬上限 + 同 agent 连续路由兜底防死循环。

2. **【checkpointer 持久化兼容性修复】**
   排查并修复 LangGraph 与 Postgres checkpointer 的版本兼容：`Send` 对象无法被原生 JSON 序列化导致 checkpoint 落库崩溃，通过 serde + base64 自定义编解码补全 pending_sends 的 JSONB 往返，使 Postgres 版与内存版 checkpointer 行为一致。

3. **【写库 HITL + 确定性安全护栏】**
   饮食写入用 `interrupt()` 做 human-in-the-loop：识别后先挂起整图、草稿经 SSE 推给前端确认/编辑，`Command(resume)` 后以编辑结果为准落库；过敏风险不交 LLM，用「档案过敏原 × 食物关键词」规则匹配 + 工具层两次确认 + 服务层兜底三层防护。HITL 的取舍统一为「数据是否估算」：模型估算的克数才确认、用户陈述的类型/时长直写。

4. **【Agentic RAG 混合检索 + 引用可追溯】**
   知识问答走「检索→自检→不足改写重检」迭代：pgvector 向量 + BM25 关键词两路召回经 RRF 融合（分别补语义/字面盲区），gte-rerank 精排、失败降级回粗排；出站对模型输出做确定性引用校验，只留正文实际引用的证据、剥掉幻觉 `[n]` 与自加"参考来源"。

5. **【确定性优先：感知/查询分离与数字走服务层】**
   多模态识别 VLM 只输出「看见什么」（名称/克数/视觉描述），营养值一律查库不走模型——可溯源事实不能交模型、否则幻觉无从校准，命中按 exact/prefix/fuzzy 分级连同 llm_estimate 落库透出前端；BMR/TDEE 由服务层公式算好落库、LLM 只读数不碰算术。与营养值查库、过敏规则匹配、引用校验同属一条原则：确定性优先、估算打标兜底。

---

## 二、追问防御点（按文件分层）

### graph.py
- **星型拓扑为什么**：只有 supervisor 用 `Command(goto=...)` 有选择权，其余节点被 `add_edge` 焊死；worker 干完强制回 supervisor。控制集中、worker 无直连、不互相踢皮球。
- **turn_reset 防什么**：checkpointer 持久化整个 state 但不区分"轮内/跨轮"。hop_count 不重置 → 第二轮第一次路由即顶到 2 被强制 FINISH、worker 全员罢工；agent_trace/tool_calls/citations 不重置 → 每轮重发旧轨迹。
- **pending_sends 补丁**：写 = Send 对象 → JSON 友好 dict；读 = dict → Send 对象。根因是 `json.dumps` 不认识 Send（**不是**"数据库不能存 dict"）。

### supervisor.py
- **为什么改写 task 而不是转发原话**：指代消解。例："那再记一笔，跟昨天一样的" → "查询昨天午餐并新建相同内容的今日午餐记录"。worker 不读历史也能独立执行。
- **防死循环两层**：hop_count≥2 强制 FINISH（代码硬约束，压在 prompt 软约束之上）+ 同 agent 连续路由兜底（用每轮清空的 agent_trace 判，不误杀跨轮同名）。
- **结构化输出**：`RouteDecision(BaseModel)` + `with_structured_output`，把路由钉死成两个字段。

### state.py
- **reducer**：`messages: Annotated[list, add_messages]` 是唯一"追加型"通道；其余字段默认覆盖。若不追加，后写节点覆盖先写，对话只剩最后一条。

### diet_agent.py
- **子图 vs 函数（正交）**：读 state 来自"是节点"，与"是不是子图"无关。三个 react worker 用 `create_react_agent` → 产出编译图 → 嵌外层只能 `add_node`；qa_agent 流程固定、无自主多步 → 普通函数。
- **interrupt 不需要子图**（曾过度概括，已纠正）：interrupt 任何节点都可用；子图只因 create_react_agent 返回图而必须。做子图 vs 手动 `.invoke()` 的界是"别另起独立运行时丢中断/丢共享状态"。
- **当前轮窗口过滤**：仅 diet 这么做（躲历史过敏结论干扰"已经吃了请记录"），exercise/plan 喂全量 messages。

### tools/diet.py
- **interrupt 从头重跑**：恢复时节点整体重跑，`interrupt` 之前必须是幂等/无副作用（这里 draft 组装是纯计算），否则写库会双跑。
- **过敏为什么不交 LLM**：模型可能因历史上下文拒绝记录已发生的饮食、也可能漏报；规则匹配（关键词表 + 纯函数可单测）保证确定性与可解释。
- **三层防御**：工具层第一次 interrupt 建卡展示风险 → 未勾知悉再 interrupt 一次 → service 层 `AllergyConfirmationRequired` 兜底（即使绕过工具直接调 service 也拦）。
- **落库条件是「无风险 或 已勾选」**（不是「且」）：体现"不阻止记录已发生的饮食"，只要明确知悉就能记现实。
- **删虾仍被要求勾知悉算不算 bug**：第二次 interrupt 触发条件用 draft 评估（`diet.py:166`），此刻取不到编辑后条目，体验边角但安全语义没错；是否成 bug 取决于前端是否在删光风险食物时自动置 `allergy_acknowledged=True`（待读前端）。

### api/chat.py

> 口述约定：这节对着面试官不要念 `tools/diet.py` / `create_diet_record` / `__interrupt__` / `intr.value` / `graph.get_state(cfg).next` 这些私有或内部符号，全部换通用词（对「讲述」做指代消解，与 supervisor 对「task」做的同一动作）。私有名 → 口述词：`create_diet_record`=饮食写入工具；`__interrupt__`=图挂起时状态流里带出的中断事件；`intr.value`=事件携带的待确认草稿；`Command(resume=…)`=恢复重启命令；`get_state(...).next`=当前挂起状态；`diet_service`=业务写入层。

- **HITL 完整闭环（口述版）**：Agent 生成记录草稿后，写入工具在落库前调 `interrupt()` 挂起整张图，把草稿（克数/营养值/过敏风险）经 SSE 推给前端渲染确认卡片，用户可编辑克数、删条目、或取消。前端确认后回传编辑结果，以 `Command(resume=用户答复)` 重启图：从挂起的工具重跑，`interrupt()` 这次直接返回用户答复，代码再以编辑后的最终条目落库。两道防御：恢复前用图状态接口确认「确实挂在等待输入」（否则对已结束会话写脏数据）；写入服务层兜底校验过敏知悉标记——未明确知悉绝不落库。
- **token 终稿替换**：流式 token 会混入 agent 的工具间过渡叙述（"先查一下…"），流结束时取最终 state 的完整回复在 `done` 帧下发，前端用它覆盖累积 token，用户只看到干净答案。
- **同步 stream 选型（待验真，暂不讲）**：不用 `astream` 是因同步版 PostgresSaver 异步接口未实现、且补丁打在同步类。低优先级 show 点，讲前先验真。

### qa_agent.py + rag/（Agentic RAG）

- **混合检索为什么**：向量路（语义泛化、怕专有名词/精确字面）+ BM25 关键词路（字面精确、怕同义改写），失败模式相反，两路拼起来各补盲区。
- **RRF 为什么不是加权**：余弦距离 vs BM25 分数量纲不可比，加权要拍脑袋定权；RRF 只认排名 `Σ 1/(60+rank+1)`，k=60 是原论文惯例平滑常数、对取值不敏感（k=0 会除零）。
- **一路独占怎么算**：只在召回它的那一路加分，另一路该项为 0（不是 rank=0）——两路共识 > 单边独占，不能给独占项虚加头部排名分。
- **rerank 位置 + 降级**：粗排求全 → 精排求准；rerank 端点失败回退 RRF 序截断（粗排可用总比整条链路报错好），走原生 API 因 OpenAI 协议无 rerank 端点。
- **迭代自检（Agentic）**：结构化输出判 sufficient，不足则改写 query 重检、按切片 id 合并去重、再自检；仍不足就明说"未找到"不硬编。生成路流式、自检路关流式（同 supervisor 路由理由）。
- **qa_agent 为什么是普通节点**：检索路线固定（≤2 轮），迭代写进流程而非交 react 模型即兴发挥，可控可测。
- **引用校验（不信模型文本）**：模型会乱写 `[n]`（页码/臆测号）、自加"参考来源"。口述版出站流水线：①定位串由检索结果的文档/章节/页码/片段号**确定性拼出**；②剥掉模型自加的"参考来源"目录（目录只由程序基于本轮证据唯一生成）；③正则扫正文所有 `[n]`，不在本轮证据集内的删除；④按正文**首次出现顺序**把实际引用的证据重编成连续号、同一证据共享号，**没用到的候选不进 SSE/库/前端抽屉**；⑤目录与前端抽屉都从"实际引用到的结构化证据"生成，UI 不反向回解析正文。核心：召回候选 ≠ 最终引用。

### rag/ 切片与导入（document_loader.py + seed_knowledge.py）

- **切片质量是选择不是算法**：结构感知切分（按"第X章 / X.Y 子节 / 附录"标题切，而非固定字符硬切）+ 切片自带语境（content 前拼 section 前缀，独立召回仍可知出处）+ 可追溯元数据（页码/章节/切片号 = 引用定位的数据基础）。chunk 600 字、普通按行累积不重叠，仅超长句 80 字滑动窗口重叠防硬截断。
- **提取/切片 与 向量化/入库 分层**：切片纯离线、确定性、可单测；embedding+写库才依赖外部服务。提取为空不做 OCR 兜底、直接 raise（不许把"空"静默当可用文档）。
- **幂等 + 精确重建**：源文件 SHA-256（流式 1MB 块读，防大文件全载内存）作幂等键——文件未变跳过、变了只删该文档旧切片重建（document/chunk 分表的用途落地）；批量向量化后校验条数一致，不一致 raise。

### exercise_agent + plan_agent（收齐 worker）

- **两种写库策略并存**：diet 克数是模型估算 → 写库前 interrupt 确认；exercise 类型/时长是用户陈述 → 直接落库。HITL 按「数据来源是否估算」取舍，不是无脑全局加。
- **MET 确定性优先、估算兜底**：met 不传先查内置表，未命中返回 met_not_found、提示模型按强度估（3/5/8）重试；估算值随记录落库、可追溯。
- **LLM 不做算术**：BMR/TDEE/calorie_target 在档案更新时由 service 层 Mifflin-St Jeor 算好落库，plan 只 get_profile 读数 + 解释 + 排方案；档案不全先补档再出计划。
- **update_profile 的部分更新**：`model_dump(exclude_unset=True)` 只吐 LLM 实际传的字段，没提的不覆盖；Pydantic Field 约束拦非法枚举。
- **「存疑不计算」的精确边界（硬输入 vs 软输入）**：`recalc_profile_metrics` 的门槛是 gender/weight_kg/height_cm/age 四个 BMR 因子，任缺一个即返 (None,None,None)——缺了公式前提硬凑默认会产出误导数字，宁可不算；而 activity_level / goal 是软输入，缺失不返 None、用保守默认（久坐 1.2 / 维持 0）兜底。「算不出」与「有安全默认值」是两回事。
- **档案 = 跨会话长期记忆**：身高体重/目标/过敏偏好存 UserProfile，agent 回答前先读档案个性化；diet 过敏检测读的 goal_note 就是这里来的。
- **exercise 小缺口（可防御）**：duration_minutes 必填但无 prompt 守护"缺失先追问、禁止编造时长"，对比 plan 的"先问再补"、diet 的置信度兜底，这里偏松。可补 prompt 纪律 + Field(gt=0, le=1440)。

### db/models.py + agents/llm.py（数据底座）

- **时区坑（naive vs aware）**：裸 `datetime.now()` 是 naive 本地时间，插 timestamptz 列被 Postgres 按 UTC 会话时区重解读——naive 值被**误当 UTC 存下**（不是 Postgres 加 8 小时），读回按 +8 渲染就跨天（9/10→9/11）。偏移量 = 应用本地时钟的 UTC offset（中国 +8，UTC 部署则偏移 0 不显现）。修法：`utcnow()` helper 统一写 aware 时间。
- **数值固化在 schema 层的落地**：bmr/tdee/calorie_target 三输出列可空 =「结果尚未产生」（四输入缺一即 NULL，对应 recalc 返 None）；ExerciseRecord 的 met/calories_burned 不可空 =「一产生就必有」。
- **conversation.id = thread_id（复用键）**：会话主键 UUID 直接当 checkpointer 的 thread_id（其接受任意字符串），免去「会话↔thread」映射表。
- **冗余总列（denormalize）**：看板按日聚合免 join items，代价是 service 层双写同步。
- **document/chunk 分表**：文档表存 source_key+content_hash 做幂等、可精确删旧切片重建；切片表只存 content+embedding（检索最小集）。
- **模型分工（llm.py）**：qwen-plus 文本主力 vs qwen-vl-max 仅图片识别（成本/能力权衡）；temperature 分任务——vision=0（识别确定性）、text=0.3（建议要多样性但事实不炮）；supervisor 路由与 qa 自检关流式（一次性结构化输出）。

### agents/memory.py + tools/context.py（记忆与上下文）

- **图的两条通道**：`state`（checkpoint、随时间累积、节点直读）vs `config`（每次 invoke 注入、不 checkpoint、身份/会话设定）。memory 管 state 里 messages 瘦身，context 从 config 的 configurable 取 user_id——两件"不写成工具参数"的事各走一条通道。
- **摘要压缩记忆**：messages 超 24 条 → 最旧 16 条折叠成**滚动摘要**写 summary（已有则合并、非从零压）+ `RemoveMessage` 裁掉，剩近 8 条；`≤24` 短路不调 LLM。summary（长期）+ 近窗口（短期）**只喂 supervisor** 做跨轮指代消解，worker 走 task 驱动只看近窗口。删除只能走 `RemoveMessage`（add_messages 是 append-only）。
- **工具上下文注入**：`@tool` 签名对 LLM 可见 → user_id/db 不能做工具参数；身份在 invoke 时注入 `configurable.user_id`，工具内 `ensure_config()`（langchain_core 公开低层工具、非废弃）从 contextvar 读当前运行 config 取回，取不到 `raise`（fail fast）。每次工具调用开短生命周期 DB Session。

### auth + 双表面（FastAPI/JWT 与 REST/SSE）

- **JWT 无状态凭证**：`header.payload.signature` 三段。payload 是 base64 明文 → 只放 `sub`=用户 id、`iss`=签发者、`exp`=过期，不放敏感信息；防篡改 = 服务端用密钥按 header+payload 重算签名、与第三段比对，改一个字就对不上。无状态 = 不存「谁登录了」、token 自证身份，代价是不能主动吊销、只靠 exp 过期。
- **密码只存 bcrypt 哈希**：单向 + 每次随机盐（同密码两次哈希不同、防彩虹表）。用 bcrypt 官方库而非 passlib——passlib 与 bcrypt≥4.0 有已知兼容问题、长期不维护。
- **401 与 403 语义**：401=未认证（还没证明你是谁）、403=无权限（证明了但没资格）。token 缺失/无效/过期都属「未认证」→ 统一 401；关掉框架默认的自动 403 改由依赖显式抛，语义更准。
- **依赖注入链 = 签名即鉴权**：端点 `Depends(get_current_user)` 一步完成「验 token + 开 DB 会话」，DB 会话用 generator（yield）做 setup/teardown、请求结束自动关；业务层拿到 `user` 时身份已天然校验完，不再自己判断「这人是谁」。
- **两处反枚举**：登录「用户不存在 / 密码错误」合并同一句文案；访问他人会话返回 404「会话不存在」而非 403——故意模糊「不存在 vs 无权限」，不让探测账号/会话是否真实存在。
- **双表面 = 同一 service 层两种 HTTP 暴露**：REST（表单手填/看板，JSON 一问一答）与 SSE（对话，长连接持续推帧）都落到同一批 `diet_service`/`exercise_service`，两条入口数据行为一致——「工具不碰 ORM、业务沉淀 service」的落地。
- **SSE 链三点**：①对话开场与中断恢复共用一份「跑图→分帧→落库」生成器，仅喂给图的输入不同（新一轮消息 vs 恢复命令）；②生成器内不持依赖注入的 DB 会话（流式发送生命周期与依赖 teardown 交错会踩坑），落库自开短会话；③同步 stream 而非异步——补丁打在同步版 checkpointer、流式框架原生支持同步迭代器，不必迁异步。
- **两个防御**：鉴权在流启动前完成（端点本身走依赖注入）；恢复前查「图确实处于挂起态」，否则对已结束会话灌恢复值会写脏 checkpoint、直接 400。

### 测试与评测（tests/ + rag/eval.py）

> 面试先分清两个词：**单元测试（unit test）测"代码对不对"，评测（evaluation）测"AI 好不好"。** 前者有唯一标准答案、可精确断言；后者无标准答案，只能靠人标 golden set + 指标逼近。AI 应用工程师被追问最多的是后者。

- **金字塔三层，项目全覆盖**：纯函数单测（毫秒、假数据断言精确值 → `test_eval_metrics.py` 测 Recall/MRR/nDCG 公式）→ 业务规则/集成（真 service+DB、测确定性逻辑 → `test_allergy_guard.py` 护栏、`test_retriever.py` 真 embedding）→ E2E 评测（真 LLM 全链路、锚点断言 → `test_qa_agent_rag.py`）。快的天天秒跑，慢的（真 key）用 `skipif(没配 key)` 隔离按需跑。
- **核心心法——测 LLM 别咬输出文本，测编排的确定性部分**：LLM 输出每次不同、没法精确断言；但"哪个分支走了/没走、citations 结构对不对、拒答不拒答"是确定的。例：无证据时 `assert generator.called is False`——断言"生成模型根本不该被调用"，而非断言它说了什么。
- **monkeypatch 是 Agent 单测的杀手锏**：把 LLM/检索临时换成假实现（测完自动还原），离线、免费、能精确测"编排逻辑是否走对"；真 LLM 的 E2E 另写、锚点断言只咬关键数值与结构字段（不全文比对）。
- **RAG 评测难点在评测集本身，不在指标**：尺子先用"能手工算清的例"校准（`test_eval_metrics.py` 锁死公式），再谈数字有无意义。活教材：第一轮 30 条直白 query Recall=1.0 是"题目太简单"而非"检索真好"，加难例+负例后 0.88 才可信；负例还暴露"库外问题被向量硬召回" → 判定拒答是 QA 层职责，检索层天生只会返"最像"。
- **golden 对齐用 content_hash 不用主键 id**：id 只在同一 DB 实例内稳定、跨 seed 会变；content_hash 由内容决定、跨环境可复现——顺带补上引用缺 stable chunk_id 的 P1 缺口。

---

## 三、手写基本功清单（白板可能考，暂不做自测）

> 这 7 个原子会默写 = 能手写任意 LangGraph agent 应用。括号是项目内范例。

1. `TypedDict` state + `messages: Annotated[list, add_messages]` — `state.py`
2. `StateGraph` + `add_node`/`add_edge`/`add_conditional_edges` + `.compile(checkpointer=...)` — `graph.py`
3. `@tool`（pydantic 参数） — `tools/diet.py`
4. `create_react_agent(llm, tools, prompt=..., state_schema=...)` — `diet_agent.py`
5. `interrupt(值)` 挂起 + `Command(resume=值)` 恢复 — `tools/diet.py` + `api/chat.py`
6. `class X(BaseModel)` + `llm.with_structured_output(X)` — `supervisor.py`
7. `graph.invoke(...)` / `graph.stream(..., stream_mode=["messages","updates"])` — `api/chat.py`
8. RRF 融合（`score += 1/(RRF_K + rank + 1)`，两路排名合成一个分）— `rag/retriever.py`