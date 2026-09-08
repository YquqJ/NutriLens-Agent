# NutriLens 健康管理智能助手

> 基于 AI Agent 的个人健康管理应用 —— 饮食管理 + 运动记录 + 智能问答三位一体，帮助用户实现热量收支平衡。

## 功能

- 📷 **拍照记录饮食**：上传食物照片 → qwen-vl-max 识别 → 食物库匹配营养数据 → 人工确认后落库（Human-in-the-loop）
- ⌨️ **文字描述录入**："我午饭吃了一碗牛肉面" → Agent 解析并自动记录
- 🏃 **运动记录**：MET 公式计算运动消耗
- 💬 **智能问答**：营养/健身咨询（Agentic RAG：混合检索 + 重排 + 迭代自检）
- 🎯 **个性化计划**：BMR/TDEE 计算 + 按目标（减脂/增肌/维持）生成饮食计划
- 📊 **热量看板**：每日收支、宏量营养素、7 日趋势

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph（Supervisor 多 Agent、interrupt HITL、PostgresSaver checkpointer） |
| 模型 | 阿里 Qwen（qwen-plus / qwen-vl-max / text-embedding-v3 / gte-rerank，DashScope 兼容模式） |
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 · SSE 流式 |
| 数据 | PostgreSQL + pgvector · 阿里云 OSS |
| 前端 | Vue 3 · Vite · TypeScript · Element Plus · ECharts · Pinia |

## 架构

```
（待补充：Supervisor 多 Agent 架构图）
```

## 快速开始

```bash
# 1. 启动 PostgreSQL（含 pgvector）
docker compose up -d

# 2. 后端
cd backend
cp ../.env.example .env          # 填入 DASHSCOPE_API_KEY / OSS 配置
uv sync                          # 首次安装依赖（固定 Python 3.12）
uv run python -m app.db.init_db  # 建表 + 向量索引
uv run uvicorn app.main:app --reload

# 3. 前端（M6 后提供）
cd frontend && npm install && npm run dev
```

## 项目结构

```
backend/app/
├── core/       配置 / JWT / 依赖注入
├── db/         SQLAlchemy 模型与会话
├── schemas/    API 请求/响应模型
├── services/   业务逻辑层（REST 与 Agent 工具共用）
├── agents/     LangGraph 多 Agent 编排 ★核心
├── tools/      @tool 工具集（Agent 的"手"）
├── rag/        Agentic RAG（知识库 / 混合检索 / 重排）
└── api/        路由（REST + SSE）
```

> 详细注释贯穿全码：每个模块头部 docstring 说明职责与设计决策，关键流程（interrupt 恢复、SSE 分帧、混合检索）有逐步行内注释。
