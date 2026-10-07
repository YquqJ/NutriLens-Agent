"""Request-level LLM usage collection for the chat stream.

The collector records provider-reported usage only. It never estimates token
counts from text length, because that would make the UI look precise while
being wrong for multilingual prompts, tool calls, and multimodal inputs.
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _normalize_usage(raw: Any) -> dict[str, int | None] | None:
    if not isinstance(raw, dict):
        return None

    input_tokens = _as_int(raw.get("input_tokens", raw.get("prompt_tokens")))
    output_tokens = _as_int(
        raw.get("output_tokens", raw.get("completion_tokens"))
    )
    total_tokens = _as_int(raw.get("total_tokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _usage_candidate(raw: Any) -> dict[str, int | None] | None:
    """Normalize either a usage dict or metadata wrapping one."""
    usage = _normalize_usage(raw)
    if usage is not None:
        return usage
    if isinstance(raw, dict):
        for nested in (raw.get("token_usage"), raw.get("usage")):
            usage = _normalize_usage(nested)
            if usage is not None:
                return usage
    return None


def _usage_from_response(response: Any) -> dict[str, int | None] | None:
    """Read usage from common LangChain/OpenAI-compatible response shapes."""
    for batch in getattr(response, "generations", []) or []:
        for generation in batch:
            message = getattr(generation, "message", None)
            candidates = (
                getattr(message, "usage_metadata", None),
                getattr(message, "response_metadata", None),
                getattr(generation, "generation_info", None),
            )
            for candidate in candidates:
                usage = _usage_candidate(candidate)
                if usage is not None:
                    return usage

    llm_output = getattr(response, "llm_output", None) or {}
    for candidate in (
        llm_output.get("token_usage"),
        llm_output.get("usage"),
    ):
        usage = _usage_candidate(candidate)
        if usage is not None:
            return usage
    return _usage_candidate(response)


def _sum_optional(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


def merge_usage_metrics(
    previous: dict[str, int | None] | None,
    current: dict[str, int | None] | None,
) -> dict[str, int | None]:
    """Merge request metrics across an interrupt/resume boundary."""
    previous = previous or {}
    current = current or {}
    input_tokens = _sum_optional(
        previous.get("input_tokens"), current.get("input_tokens")
    )
    output_tokens = _sum_optional(
        previous.get("output_tokens"), current.get("output_tokens")
    )
    previous_total = previous.get("total_tokens")
    if (
        previous_total is None
        and previous.get("input_tokens") is not None
        and previous.get("output_tokens") is not None
    ):
        previous_total = int(previous["input_tokens"]) + int(previous["output_tokens"])
    current_total = current.get("total_tokens")
    if (
        current_total is None
        and current.get("input_tokens") is not None
        and current.get("output_tokens") is not None
    ):
        current_total = int(current["input_tokens"]) + int(current["output_tokens"])
    total_tokens = _sum_optional(previous_total, current_total)
    return {
        "duration_ms": int(previous.get("duration_ms") or 0)
        + int(current.get("duration_ms") or 0),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


class TokenUsageCollector(BaseCallbackHandler):
    """Collect usage from every LLM call within one graph execution."""

    def __init__(self) -> None:
        super().__init__()
        self._active_runs: set[str] = set()
        self._counted_runs: set[str] = set()
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._total_tokens: int | None = None
        self._llm_calls = 0
        self._usage_calls = 0

    def _start(self, run_id: Any) -> None:
        self._active_runs.add(str(run_id))

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any) -> None:
        del serialized, prompts
        self._start(kwargs.get("run_id"))

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        del serialized, messages
        self._start(kwargs.get("run_id"))

    def _finish(self, run_id: Any, usage: dict[str, int | None] | None) -> None:
        key = str(run_id)
        if key in self._counted_runs:
            return
        self._counted_runs.add(key)
        self._active_runs.discard(key)
        self._llm_calls += 1
        if usage is None:
            return
        self._usage_calls += 1
        self._input_tokens = _sum_optional(
            self._input_tokens, usage.get("input_tokens")
        )
        self._output_tokens = _sum_optional(
            self._output_tokens, usage.get("output_tokens")
        )
        total = usage.get("total_tokens")
        if total is None:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if input_tokens is not None and output_tokens is not None:
                total = input_tokens + output_tokens
        self._total_tokens = _sum_optional(self._total_tokens, total)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self._finish(kwargs.get("run_id"), _usage_from_response(response))

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        del error
        self._finish(kwargs.get("run_id"), None)

    def summary(self) -> dict[str, int | None]:
        return {
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "total_tokens": self._total_tokens,
            "llm_calls": self._llm_calls,
            "usage_calls": self._usage_calls,
        }
