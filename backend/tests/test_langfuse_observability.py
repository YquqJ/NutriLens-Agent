"""Langfuse 可观测配置的单元测试。"""

from types import SimpleNamespace

from app.api import chat
from app.observability import langfuse


def test_add_langfuse_observability_leaves_config_unchanged_when_disabled(monkeypatch):
    monkeypatch.setattr(langfuse, "settings", SimpleNamespace(langfuse_enabled=False))
    base_config = {"configurable": {"thread_id": "conv-1", "user_id": 7}}

    result = langfuse.add_langfuse_observability(
        base_config,
        conversation_id="conv-1",
        user_id=7,
        entrypoint="chat",
    )

    assert result == base_config
    assert result is not base_config


def test_add_langfuse_observability_attaches_callback_and_session_metadata(monkeypatch):
    handler = object()
    monkeypatch.setattr(
        langfuse,
        "settings",
        SimpleNamespace(
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
        ),
    )
    monkeypatch.setattr(langfuse, "_create_callback_handler", lambda: handler)
    base_config = {
        "configurable": {"thread_id": "conv-1", "user_id": 7},
        "metadata": {"request_source": "api"},
    }

    result = langfuse.add_langfuse_observability(
        base_config,
        conversation_id="conv-1",
        user_id=7,
        entrypoint="resume",
    )

    assert result["configurable"] == base_config["configurable"]
    assert result["callbacks"] == [handler]
    assert result["run_name"] == "nutrilens.resume"
    assert result["metadata"] == {
        "request_source": "api",
        "langfuse_session_id": "conv-1",
        "langfuse_user_id": "7",
        "langfuse_tags": ["nutrilens", "resume"],
        "langfuse_trace_name": "nutrilens.resume",
        "conversation_id": "conv-1",
        "entrypoint": "resume",
    }


def test_create_callback_handler_supports_installed_langfuse_sdk(monkeypatch):
    from langfuse.langchain import CallbackHandler

    monkeypatch.setattr(
        langfuse,
        "settings",
        SimpleNamespace(
            langfuse_public_key="pk-lf-test",
            langfuse_secret_key="sk-lf-test",
            langfuse_host="https://cloud.langfuse.com",
        ),
    )

    handler = langfuse._create_callback_handler()

    assert isinstance(handler, CallbackHandler)


def test_chat_graph_config_uses_observability_wrapper(monkeypatch):
    captured: dict = {}

    def fake_add(config, **kwargs):
        captured["config"] = config
        captured.update(kwargs)
        return {"traced": True}

    monkeypatch.setattr(chat, "add_langfuse_observability", fake_add)

    result = chat._build_graph_config("conv-1", 7, "chat")

    assert result == {"traced": True}
    assert captured == {
        "config": {"configurable": {"thread_id": "conv-1", "user_id": 7}},
        "conversation_id": "conv-1",
        "user_id": 7,
        "entrypoint": "chat",
    }
