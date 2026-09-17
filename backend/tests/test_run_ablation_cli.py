"""消融实验 CLI 必须能把完成的评测结果序列化为 JSON。"""

import json
import sys
from types import SimpleNamespace

from app.rag import run_ablation as cli


def test_main_prints_json_report(monkeypatch, capsys):
    db = SimpleNamespace(close=lambda: None, scalar=lambda _statement: 32)
    loaded_paths = []

    def fake_load(path):
        loaded_paths.append(path)
        return [{"query": "q"}]

    monkeypatch.setattr(cli, "load_eval_queries", fake_load)
    monkeypatch.setattr(cli, "seed_all_knowledge", lambda split_mode: 0)
    monkeypatch.setattr(cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        cli,
        "run_ablation",
        lambda _db, _queries, top_k: {"schema_version": "test"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_ablation",
            "--eval-data",
            "tests/eval_data/rag_queries.json",
        ],
    )

    cli.main()

    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "test"
    assert report["metadata"]["split_mode"] == "section_aware"
    assert report["metadata"]["total_chunks"] == 32
    assert loaded_paths[0].name == "rag_queries.json"
