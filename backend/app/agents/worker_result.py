"""Normalize worker outcomes and safely capture subgraph execution failures."""

from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphBubbleUp, GraphInterrupt

from app.agents.state import WorkerOutcome

READ_ONLY_TOOL_NAMES = frozenset(
    {
        "search_food",
        "get_daily_summary",
        "get_diet_records",
        "get_exercise_records",
        "get_profile",
        "retrieve_knowledge",
    }
)
MUTATING_TOOL_NAMES = frozenset(
    {
        "create_diet_record",
        "delete_diet_record",
        "create_exercise_record",
        "delete_exercise_record",
        "update_profile",
    }
)


def classify_worker_result(
    agent_name: str,
    messages: Sequence[Any],
    error: Exception | None = None,
) -> WorkerOutcome:
    """Classify failures conservatively; only known read-only work is retryable."""
    if error is not None:
        if agent_name == "qa_agent":
            return {
                "status": "retryable_error",
                "error_code": type(error).__name__,
                "retryable": True,
                "side_effect": "none",
            }
        return {
            "status": "fatal_error",
            "error_code": "side_effect_uncertain",
            "retryable": False,
            "side_effect": "unknown",
        }

    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    errors = [message for message in tool_messages if message.status == "error"]
    if not errors:
        return {
            "status": "success",
            "error_code": "",
            "retryable": False,
            "side_effect": (
                "committed"
                if any(
                    message.name in MUTATING_TOOL_NAMES
                    for message in tool_messages
                )
                else "none"
            ),
        }

    if any(
        message.name in MUTATING_TOOL_NAMES and message.status != "error"
        for message in tool_messages
    ):
        return {
            "status": "fatal_error",
            "error_code": "side_effect_committed",
            "retryable": False,
            "side_effect": "committed",
        }

    called_tools = {message.name for message in tool_messages}
    if called_tools and called_tools.issubset(READ_ONLY_TOOL_NAMES):
        return {
            "status": "retryable_error",
            "error_code": "read_tool_error",
            "retryable": True,
            "side_effect": "none",
        }
    return {
        "status": "fatal_error",
        "error_code": "side_effect_uncertain",
        "retryable": False,
        "side_effect": "unknown",
    }


def make_worker_node(agent_name: str, worker: Any):
    """Wrap a compiled worker subgraph while allowing LangGraph interrupts through."""

    def invoke_worker(
        state: dict[str, Any], config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        messages = state.get("messages") or []
        message_start = len(messages)
        try:
            # React workers are compiled subgraphs with ``invoke``; QA is a
            # regular node function. Normalize both execution shapes here so
            # Supervisor sees one consistent structured outcome.
            if hasattr(worker, "invoke"):
                result = worker.invoke(state, config=config)
                returns_full_state = True
            else:
                result = worker(state)
                returns_full_state = False
        except GraphBubbleUp:
            raise
        except Exception as exc:
            outcome = classify_worker_result(agent_name, (), error=exc)
            return {
                "worker_outcome": outcome,
                "worker_message_start": message_start,
                "worker_message_end": message_start,
            }

        updates = dict(result) if isinstance(result, Mapping) else {}
        # A manually invoked child returns pauses as a result key; re-raise them
        # so the parent graph persists and resumes the interruption normally.
        if "__interrupt__" in updates:
            raise GraphInterrupt(updates["__interrupt__"])
        returned_messages = updates.get("messages") or []
        if returns_full_state:
            result_messages = returned_messages or messages
            attempt_messages = result_messages[message_start:]
        else:
            # Ordinary LangGraph nodes return message deltas; combine them
            # only for classification/range bookkeeping and leave the delta
            # untouched in ``updates`` for the parent reducer.
            result_messages = [*messages, *returned_messages]
            attempt_messages = returned_messages
        outcome = classify_worker_result(
            agent_name, attempt_messages
        )
        updates["worker_outcome"] = outcome
        updates["worker_message_start"] = message_start
        updates["worker_message_end"] = len(result_messages)
        if outcome["status"] not in {"success", "needs_user_input"}:
            updates["worker_discarded_ranges"] = [
                *(state.get("worker_discarded_ranges") or []),
                {"start": message_start, "end": len(result_messages)},
            ]
        return updates

    return invoke_worker
