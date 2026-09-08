"""
NutriLens 健康管理智能助手 — 后端服务入口包。

架构总览（详见仓库根 README.md）：
    app/
    ├── core/       配置、JWT 安全、依赖注入
    ├── db/         SQLAlchemy 模型与会话管理
    ├── schemas/    API 层 Pydantic 模型（请求/响应）
    ├── services/   业务逻辑层（REST 与 Agent 工具共用，保证两条写入路径行为一致）
    ├── agents/     LangGraph 多 Agent 编排（supervisor + 4 个专职 agent）
    ├── tools/      LangGraph @tool 工具集（LLM 的"手"）
    ├── rag/        Agentic RAG：知识库文档、混合检索、重排
    ├── api/        FastAPI 路由（REST + SSE 流式）
    └── scripts/    一次性运维脚本（知识库入库、食物数据导入）
"""
