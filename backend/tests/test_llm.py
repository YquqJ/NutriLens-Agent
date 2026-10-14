"""LLM 客户端配置测试。"""

from app.agents.llm import get_judge_llm, get_text_llm, get_vision_llm
from app.core.config import settings


def test_llm_clients_have_finite_request_timeouts():
    """外部模型服务不可达时必须有退出边界，不能无限等待。"""
    get_text_llm.cache_clear()
    get_judge_llm.cache_clear()
    get_vision_llm.cache_clear()
    try:
        text_llm = get_text_llm()
        judge_llm = get_judge_llm()
        vision_llm = get_vision_llm()

        assert settings.llm_timeout_seconds == 60.0
        assert text_llm.request_timeout == settings.llm_timeout_seconds
        assert "stream_chunk_timeout" not in text_llm.model_kwargs
        assert text_llm.stream_usage is True
        assert judge_llm.request_timeout == settings.llm_timeout_seconds
        assert judge_llm.temperature == 0
        assert judge_llm.streaming is False
        assert vision_llm.request_timeout == settings.llm_timeout_seconds
    finally:
        # 其他测试不复用本测试构造的客户端实例，避免缓存污染。
        get_text_llm.cache_clear()
        get_judge_llm.cache_clear()
        get_vision_llm.cache_clear()
