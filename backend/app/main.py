"""
FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, conversations, records, uploads, users

app = FastAPI(
    title="NutriLens API",
    description="健康管理智能助手后端 —— LangGraph 多 Agent + Agentic RAG",
    version="0.1.0",
)

# 开发期 CORS 全开（前后端分端口本地联调）；生产部署应收紧 origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["meta"])
def health():
    """存活探针（部署健康检查用）。"""
    return {"status": "ok", "service": "nutrilens"}


# ---- 路由注册 ----
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(uploads.router)
app.include_router(records.router)
app.include_router(conversations.router)
# chat（SSE 流式 Agent 端点）在 M2 LangGraph 图就绪后注册：
# app.include_router(chat.router)
