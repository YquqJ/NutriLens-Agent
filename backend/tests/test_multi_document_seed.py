"""多文档知识库导入应复用单文档幂等逻辑。"""

from pathlib import Path
from types import SimpleNamespace

from app.db import seed_knowledge as seed_module


def test_seed_all_knowledge_seeds_every_registered_source(monkeypatch):
    sources = (
        SimpleNamespace(source_key="a", source_title="A", path=Path("a.pdf")),
        SimpleNamespace(source_key="b", source_title="B", path=Path("b.pdf")),
    )
    calls = []

    def fake_seed(source_path, *, split_mode, source_key, source_title):
        calls.append((source_path, split_mode, source_key, source_title))
        return 3

    monkeypatch.setattr(seed_module, "KNOWLEDGE_SOURCES", sources)
    monkeypatch.setattr(seed_module, "seed_knowledge", fake_seed)

    added = seed_module.seed_all_knowledge(split_mode="fixed")

    assert added == 6
    assert calls == [
        (Path("a.pdf"), "fixed", "a", "A"),
        (Path("b.pdf"), "fixed", "b", "B"),
    ]
