"""
全局配置（pydantic-settings）。

设计决策：
- 所有配置集中一处、从环境变量/.env 读取，避免散落的 os.getenv 调用；
- 提供 `llm_settings` 单例延迟构建（ChatOpenAI 客户端在 agents 层使用），
  方便统一管理模型名与 DashScope 兼容端点。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ---- 服务 ----
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """进程级单例。lru_cache 保证 .env 只解析一次。"""
    return Settings()


settings = get_settings()
