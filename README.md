# NutriLens 健康管理智能助手

NutriLens 是一个面向个人用户的 AI 健康管理应用，围绕饮食记录、运动记录、健康知识问答和个性化计划组织日常健康管理流程。项目采用 Vue 3 + FastAPI，使用 LangGraph 编排多 Agent，并通过 PostgreSQL、pgvector 与对象存储持久化业务数据和知识库。

## 功能概览

- **饮食记录**：通过文字或食物照片记录饮食；图片识别结果经过营养信息补全和用户确认后再写入记录。
- **运动记录**：记录运动类型与时长，根据运动 MET 值和用户资料估算消耗热量。
- **健康问答**：针对营养、饮食和运动问题检索知识库，生成带证据引用的回答。
- **个性化计划**：基于个人资料、BMR/TDEE 和健康目标生成饮食计划。
- **健康看板**：查看每日热量收支、宏量营养素和阶段趋势。
- **会话体验**：支持 SSE 流式回复、工具轨迹、Citation 回查、HITL 确认，以及回复耗时和 Token 用量展示。

## 技术栈

| 层次 | 技术 |
|---|---|
| Web 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、ECharts |
| API 服务 | Python 3.12、FastAPI、SQLAlchemy 2、SSE |
| Agent 编排 | LangGraph、LangChain；Supervisor 调度领域 Worker，PostgresSaver 持久化对话状态 |
| 模型服务 | 阿里云 DashScope：Qwen 文本/视觉模型、text-embedding-v3、gte-rerank |
| 数据存储 | PostgreSQL、pgvector、阿里云 OSS |
| 检索 | pgvector 向量检索、BM25 关键词检索、RRF 融合、Rerank 精排 |

## 系统架构

```mermaid
flowchart LR
    UI[Vue 3 Web 客户端] -->|REST / SSE| API[FastAPI]
    API --> GRAPH[LangGraph Supervisor]
    GRAPH --> IMG[图片识别与上下文整理]
    IMG --> SUP[Supervisor 路由]
    SUP --> DIET[饮食 Agent]
    SUP --> EXERCISE[运动 Agent]
    SUP --> QA[健康问答 Agent]
    SUP --> PLAN[计划 Agent]
    DIET --> SUP
    EXERCISE --> SUP
    QA --> SUP
    PLAN --> SUP
    API --> DB[(PostgreSQL)]
    GRAPH --> CP[(PostgresSaver Checkpoints)]
    QA --> RAG[检索与证据组装]
    RAG --> VEC[(pgvector)]
    RAG --> BM25[BM25 + RRF + Rerank]
    API --> OSS[(对象存储 OSS)]
```

Supervisor 是唯一调度中枢，饮食、运动、问答和计划 Agent 分别负责领域任务。Worker 完成后回到 Supervisor，由其决定是否继续处理复合请求或结束本轮。图状态通过 PostgreSQL checkpoint 保存；饮食图片识别采用人工确认后写入（HITL），避免未经用户确认地保存估算数据。

问答链路会进行知识检索和证据组装；当首轮结果被判定不足时，可改写查询并再次检索。生成回答时将检索片段作为上下文，Citation 提供文档、章节、页码和原文片段定位。

## 本地运行

### 环境要求

- Python 3.12 和 [uv](https://docs.astral.sh/uv/)
- Node.js 与 npm
- Docker Desktop / Docker Engine
- DashScope API Key
- OSS 配置用于食物图片上传与访问；如只验证不涉及图片上传的流程，可按需配置

### 1. 启动数据库

在项目根目录执行：

```powershell
docker compose up -d
```

Compose 会启动 PostgreSQL 16 + pgvector，默认映射到宿主机 `15433` 端口。

### 2. 配置并启动后端

```powershell
Copy-Item .env.example backend/.env
```

编辑 `backend/.env`，至少配置数据库连接和 `DASHSCOPE_API_KEY`。数据库地址默认应与 Compose 端口一致：

```dotenv
DATABASE_URL=postgresql+psycopg://nutrilens:nutrilens@localhost:15433/nutrilens
DASHSCOPE_API_KEY=你的DashScope_API_Key
```

然后初始化数据库、导入知识文档并启动 API：

```powershell
Set-Location backend
uv sync
uv run python -m app.db.init_db
uv run python -m app.db.seed_knowledge
uv run python scripts/run_dev.py
```

开发启动脚本默认从 `8000` 端口开始，若端口被占用会自动顺延，并将实际端口写入 `backend/.runtime-port`。

### 3. 启动前端

在另一个终端窗口从项目根目录执行：

```powershell
Set-Location frontend
npm install
npm run dev
```

Vite 默认运行于 `http://localhost:5173`。开发服务器会读取后端运行端口并代理 `/api` 请求；也可通过 `BACKEND_PORT` 临时指定代理端口：

```powershell
$env:BACKEND_PORT = "8000"
npm run dev
```

## RAG 知识库与评测

知识文档位于 `backend/data/knowledge/`。`app/rag/document_loader.py` 中的 `KNOWLEDGE_SOURCES` 是导入注册表；新增 PDF 后需登记稳定的 `source_key`、标题和文件路径，再运行 seed 命令。导入流程会提取 PDF 文本、按章节感知策略切分、生成 embedding 并写入 PostgreSQL/pgvector。源文件未变化时会按哈希跳过重复导入。

检索模式包括：

- `vector`：单轮 pgvector 向量检索，作为检索基线。
- `bm25`：基于中文字符 bigram 的 BM25 关键词检索。
- `hybrid_rrf`：融合向量与 BM25 的候选结果。
- `hybrid_rerank`：在混合召回候选上使用 Rerank 调整排序；服务不可用时回退到 RRF 结果。

真实检索消融评测需要 PostgreSQL 中已导入对应知识源，并配置 DashScope API Key。在 `backend/` 目录运行：

```powershell
# 100-query comparison: retrieval metrics + QA LLM-as-Judge
uv run python -m app.rag.run_full_eval
```

默认评测集 `tests/eval_data/rag_queries_v3.json` 含 100 条唯一 query，覆盖 8 份知识 PDF，并包含 5 条领域外负例。脚本对比 Vector、BM25、RRF、Hybrid+Rerank 的检索指标，并对 Vector 与 Hybrid+Rerank 分别运行 QA 和 LLM-as-Judge，比较 Faithfulness、Answer Relevancy。报告包含 Recall@4、Recall@8、MRR、nDCG@4、两项生成质量均分、相对 Vector 基线的绝对/相对变化及逐 query 明细，默认写入 `backend/reports/rag-eval-v3.json`。

完整评测会产生较多模型调用；可用 `--limit 5` 先做小批量冒烟评测，或通过 `--output` 指定报告位置。页码与证据文本用于锚定 gold evidence，不依赖固定 chunk hash；新增 PDF 需补充并人工核对 query 与 gold evidence。Judge 分数用于定位问题和版本间对比，不是绝对真值或线上质量门槛，应对健康安全等用例抽样人工复核。

## 测试与质量检查

后端单元与集成测试（在 `backend/` 目录）：

```powershell
uv run pytest
```

真实检索评测也可通过 pytest 显式运行：

```powershell
uv run pytest -m eval -s
```

前端检查（在 `frontend/` 目录）：

```powershell
npm run type-check
npm run test
npm run build
```

## 项目结构

```text
backend/
├── app/
│   ├── agents/       LangGraph Supervisor、领域 Agent、状态与记忆
│   ├── api/          FastAPI 路由与 SSE 对话接口
│   ├── core/         配置、认证与依赖注入
│   ├── db/           SQLAlchemy 模型、初始化、seed 与 checkpoint 集成
│   ├── observability/调用指标与可观测性集成
│   ├── rag/          PDF 解析、切分、检索、Rerank、Citation 与评测
│   ├── services/     业务服务层
│   └── tools/        Agent 可调用工具
├── data/knowledge/   已登记的知识 PDF
├── scripts/          开发与评测辅助脚本
└── tests/            后端测试与 RAG 评测集
frontend/
├── src/api/          后端 API 客户端
├── src/components/   对话、轨迹、引用及表单组件
├── src/stores/       Pinia 状态
├── src/types/        TypeScript 类型
├── src/utils/        前端工具函数
└── src/views/        页面视图
```

## 可选可观测性

项目支持按需启用 Langfuse 或 LangSmith，用于观察 Agent 路由、工具和模型调用。相关环境变量及配置说明见 [`.env.example`](.env.example)。不要将包含 API Key、JWT Secret 或 OSS 凭据的 `.env` 文件提交到版本库。
