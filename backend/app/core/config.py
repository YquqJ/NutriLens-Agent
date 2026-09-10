"""
全局配置（pydantic-settings）。

设计决策：
- 所有配置集中一处、从环境变量/.env 读取，避免散落的 os.getenv 调用；
- 提供 `llm_settings` 单例延迟构建（ChatOpenAI 客户端在 agents 层使用），
  方便统一管理模型名与 DashScope 兼容端点。
"""

import logging
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """应用主配置。字段与 .env 文件一一对应。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 数据库 ----
    # 格式：postgresql+psycopg://user:password@host:port/dbname
    database_url: str = "postgresql+psycopg://nutrilens:nutrilens@localhost:5433/nutrilens"

    # ---- DashScope（LLM / Embedding / Rerank 统一走 OpenAI 兼容模式）----
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # 模型分工（刻意分离：便宜的模型做路由，强模型做内容生成）
    text_model: str = "qwen-plus"       # 文本理解 / Agent 推理
    vision_model: str = "qwen-vl-max"   # 食物图片识别（多模态）
    embedding_model: str = "text-embedding-v3"  # RAG 向量检索
    rerank_model: str = "gte-rerank-v2"         # 混合召回后的精排

    # ---- JWT ----
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24

    # ---- 阿里云 OSS ----
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_endpoint: str = ""
    oss_bucket_name: str = ""
    oss_public_base_url: str = ""

    # ---- 可观测（LangSmith，可选：开启后把整张图的执行轨迹 POST 到 LangSmith）----
    langsmith_tracing: bool = False   # 总开关
    langsmith_api_key: str = ""       # 为空则不开启
    langsmith_project: str = "nutrilens"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ---- 服务 ----
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """进程级单例。lru_cache 保证 .env 只解析一次。"""
    return Settings()


settings = get_settings()


def _apply_langsmith_env() -> None:
    """把 LangSmith 配置回填到 os.environ，供 langchain-core / langsmith 读取。

    必须在这里做、且要在任何 LLM/graph 调用之前（即本模块 import 时）：
    1. pydantic-settings 读 .env 只写进 Settings 字段、不污染 os.environ；
    2. langsmith 的 get_env_var 是 lru_cache（首次读取即缓存），且依次查
       LANGSMITH_ / LANGCHAIN_ 两个命名空间，晚设置会被缓存挡住。
    """
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return
    # TRACING 值必须是小写 "true"：langsmith.tracing_is_enabled() 用 `== "true"` 严格比较
    os.environ["LANGSMITH_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    logger.info("LangSmith 追踪已开启：project=%s", settings.langsmith_project)


_apply_langsmith_env()
