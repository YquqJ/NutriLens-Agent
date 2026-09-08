# CLAUDE.md — NutriLens 开发守则

> 任何会话开始开发前必读本文件与 `docs/SPEC.md`。SPEC 是唯一施工图纸，按里程碑顺序推进，勿跳步、勿加 SPEC 之外的功能。

## 项目一句话

基于 LangGraph 多 Agent 的个人健康管理后端：饮食记录（拍照/文字）+ 运动记录 + 智能问答（Agentic RAG）+ 个性化计划 + 热量看板。

## 技术栈约定（已锁定，勿随意更换）

| 项 | 约定 |
|---|---|
| Python | 3.12（`requires-python >=3.12,<3.13`），包管理一律用 `uv` |
| Web | FastAPI + SQLAlchemy 2.0（`Mapped`/`mapped_column` 风格）+ psycopg |
| Agent | LangGraph **0.4.x**（interrupt/Command 为 0.2+ 语法，锁版本）+ PostgresSaver checkpointer |
| LLM | 阿里 Qwen，全走 DashScope OpenAI 兼容模式（`langchain-openai` 的 ChatOpenAI + base_url）；模型分工见 `app/agents/llm.py` |
| 检索 | pgvector（向量路）+ rank_bm25（内存关键词路，不用 zhparser）+ gte-rerank |
| 前端 | Vue3 + Vite + TS + Element Plus + ECharts（M6 才开始） |

## 目录结构

```
backend/app/
├── core/       配置 / JWT / 依赖注入
├── db/         SQLAlchemy 模型与会话
├── schemas/    API 请求/响应模型
├── services/   业务逻辑层（REST 与 Agent 工具共用，工具不直接操作 ORM）
├── agents/     LangGraph 多 Agent 编排 ★核心
├── tools/      @tool 工具集（Agent 的"手"，按业务域分文件）
├── rag/        Agentic RAG（知识库 / 混合检索 / 重排）
└── api/        路由（REST + SSE）
docs/
├── SPEC.md         里程碑与功能点清单（施工图纸）
└── DESIGN_NOTES.md 设计决策与踩坑记录（滚动追加）
```

## 代码风格

- **注释语言**：中文。每个模块头部 docstring 说明职责与设计决策；关键流程（interrupt 恢复、SSE 分帧、混合检索）写逐步行内注释。
- **工具层纪律**：`@tool` 函数只做编排与上下文提取，业务逻辑放 `services/`；工具参数不得包含 `user_id`/`db` 等调用方上下文（走 `app/tools/context.py` 的 `ensure_config`）。
- **数值落库**：所有计算结果（calories、bmr、met…）写入时固化，不随公式升级漂移（见 `app/db/models.py` 头部说明）。
- 外科手术式修改：只动与任务相关的代码，不顺手"改进"无关内容。

## 工作流约定

1. **小步开发**：每个功能点拆到"一次能看完"的粒度；动手前先说明 做什么 → 为什么 → 涉及哪些文件；完成后报告验证方式与结果。
2. **进度同步**：功能点完成（含验证）后，更新 `docs/SPEC.md` 的勾选状态，再做 git 提交（backend 仓库，提交信息中文、 imperative）。
3. **决策同步**：凡改动推翻了 `docs/DESIGN_NOTES.md` 中已记录的决策，必须在同一批修改中更新对应条目（追加"后续：改为 X"，不删原文）。
4. **踩坑记录**：开发中遇到真实问题（兼容性坑、调试过程、方案取舍），完成修复后立即在 `docs/DESIGN_NOTES.md` 追加一条（日期 + 问题 + 原因 + 解决）。
5. 面试素材（决策对比、踩坑）只进 DESIGN_NOTES.md，不塞进代码注释堆砌（代码注释只解释"为什么这样写"）。

## 常用命令（backend/ 下）

```bash
uv sync                              # 安装依赖
uv run python -m app.db.init_db      # 建表 + 向量索引
uv run uvicorn app.main:app --reload # 启动服务（需先 docker compose up -d 起 pg）
uv run pytest                        # 测试
```
