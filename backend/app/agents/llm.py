"""
LLM 客户端统一构建。

所有 Qwen 调用统一走 DashScope 的 OpenAI 兼容模式（一个 base_url 搞定
chat / VL / embedding），langchain-openai 的 ChatOpenAI 直接复用：

模型分工（成本/能力权衡，面试口径）：
- qwen-plus     ：文本主力（Agent 推理、RAG 生成、计划生成）
- qwen-vl-max   ：仅图片识别（视觉能力强、价格高，只在 analyze_food_image 用）
- supervisor 路由：同样用 qwen-plus，但关闭流式（路由决策是一次结构化输出，
  流式无意义，反而多占一个流式连接）
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import settings


@lru_cache
def get_text_llm(streaming: bool = True) -> ChatOpenAI:
    """文本模型（qwen-plus）。streaming 参数只影响本客户端实例。"""
    return ChatOpenAI(
        model=settings.text_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        streaming=streaming,
        temperature=0.3,  # 健康建议需要一点表达多样性，但事实类回答不宜太发散
        max_retries=2,
        # timeout 传给 OpenAI 兼容客户端的 request_timeout；stream_chunk_timeout
        # 额外限制流式响应相邻 chunk 的等待，防止上游连接半开后永久卡住。
        timeout=settings.llm_timeout_seconds,
        stream_chunk_timeout=settings.llm_timeout_seconds,
    )


@lru_cache
def get_vision_llm() -> ChatOpenAI:
    """视觉模型（qwen-vl-max），仅图片识别使用。"""
    return ChatOpenAI(
        model=settings.vision_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=0,  # 识别任务要确定性，不做创造性发挥
        max_retries=2,
        timeout=settings.llm_timeout_seconds,
    )
