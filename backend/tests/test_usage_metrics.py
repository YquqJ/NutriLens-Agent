"""请求级模型用量统计测试。"""

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.usage import TokenUsageCollector, merge_usage_metrics


def _response(*, usage_metadata=None, token_usage=None):
    message = AIMessage(content="ok", usage_metadata=usage_metadata)
    return LLMResult(
        generations=[[ChatGeneration(message=message)]],
        llm_output={"token_usage": token_usage} if token_usage else {},
    )


def test_collector_aggregates_multiple_llm_calls_and_provider_formats():
    collector = TokenUsageCollector()

    collector.on_llm_start({"name": "qwen-plus"}, ["prompt"], run_id="run-1")
    collector.on_llm_end(
        _response(
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
            }
        ),
        run_id="run-1",
    )
    collector.on_llm_start({"name": "qwen-plus"}, ["prompt"], run_id="run-2")
    collector.on_llm_end(
        _response(
            token_usage={
                "prompt_tokens": 240,
                "completion_tokens": 60,
                "total_tokens": 300,
            }
        ),
        run_id="run-2",
    )

    assert collector.summary() == {
        "input_tokens": 360,
        "output_tokens": 90,
        "total_tokens": 450,
        "llm_calls": 2,
        "usage_calls": 2,
    }


def test_collector_does_not_fabricate_usage_when_provider_omits_it():
    collector = TokenUsageCollector()
    collector.on_llm_start({"name": "qwen-plus"}, ["prompt"], run_id="run-1")
    collector.on_llm_end(_response(), run_id="run-1")

    assert collector.summary() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "llm_calls": 1,
        "usage_calls": 0,
    }


def test_merge_usage_metrics_keeps_partial_hitl_metrics():
    assert merge_usage_metrics(
        {"duration_ms": 1200, "input_tokens": 100, "output_tokens": 20},
        {"duration_ms": 800, "input_tokens": 40, "output_tokens": 10},
    ) == {
        "duration_ms": 2000,
        "input_tokens": 140,
        "output_tokens": 30,
        "total_tokens": 170,
    }


def test_merge_usage_metrics_derives_missing_total_per_phase_before_summing():
    assert merge_usage_metrics(
        {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        {"input_tokens": 40, "output_tokens": 10, "total_tokens": None},
    )["total_tokens"] == 170
