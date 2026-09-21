"""端到端 QA Token 用量采集的离线测试。"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.agents.eval import TokenUsageCollector
from scripts.bench_latency import _summarize_tokens


def _response(*, usage_metadata=None, token_usage=None):
    """构造 callback 的最小 LLMResult 形态，不依赖真实模型。"""
    message = AIMessage(content="ok", usage_metadata=usage_metadata)
    return SimpleNamespace(
        generations=[[SimpleNamespace(message=message)]],
        llm_output={"token_usage": token_usage} if token_usage else {},
    )


def test_token_usage_collector_aggregates_usage_metadata_per_llm_call():
    """QA 自检和回答生成均应计入同一个 episode 的真实 Token 总量。"""
    collector = TokenUsageCollector()
    collector.on_llm_end(
        _response(
            usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
        )
    )
    collector.on_llm_end(
        _response(
            usage_metadata={"input_tokens": 240, "output_tokens": 60, "total_tokens": 300}
        )
    )

    assert collector.summary() == {
        "llm_calls": 2,
        "calls_without_usage": 0,
        "input_tokens": 360,
        "output_tokens": 90,
        "total_tokens": 450,
        "complete": True,
    }


def test_token_usage_collector_falls_back_to_openai_token_usage_and_marks_missing():
    """兼容响应缺 usage_metadata 时可回退；完全缺失不能伪造成 0 Token。"""
    collector = TokenUsageCollector()
    collector.on_llm_end(
        _response(
            token_usage={"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100}
        )
    )
    collector.on_llm_end(_response())

    assert collector.summary() == {
        "llm_calls": 2,
        "calls_without_usage": 1,
        "input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 100,
        "complete": False,
    }


def test_summarize_tokens_uses_token_units_and_keeps_all_complete_samples():
    """Token 分位摘要应使用 Token 字段，不能沿用延迟的毫秒字段。"""
    summary = _summarize_tokens("qa_total_tokens", [100, 200, 300])

    assert summary == {
        "metric": "qa_total_tokens",
        "n": 3,
        "min_tokens": 100,
        "p50_tokens": 200,
        "p90_tokens": 300,
        "p95_tokens": 300,
        "p99_tokens": 300,
        "max_tokens": 300,
        "mean_tokens": 200,
    }
