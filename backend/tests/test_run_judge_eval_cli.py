"""Judge 端到端评测 CLI 应输出可解析的 JSON 报告。"""

import json
import sys

import pytest

from app.rag import run_judge_eval as cli


def test_main_prints_json_report(monkeypatch, capsys, tmp_path):
    eval_data = tmp_path / "queries.json"
    eval_data.write_text('{"schema_version":"judge-test-v1"}', encoding="utf-8")
    monkeypatch.setattr(cli.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(cli, "load_eval_queries", lambda _path: [{"query": "测试问题"}])
    monkeypatch.setattr(cli, "seed_all_knowledge", lambda: 3)
    monkeypatch.setattr(
        cli,
        "run_qa_judge_eval",
        lambda queries, dataset_version: {
            "schema_version": "rag-qa-judge-v1",
            "dataset_version": dataset_version,
            "n_judged": len(queries),
            "n_failed": 0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_judge_eval", "--eval-data", str(eval_data), "--limit", "1"],
    )

    cli.main()

    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == "rag-qa-judge-v1"
    assert report["dataset_version"] == "judge-test-v1"
    assert report["metadata"]["seeded_chunks"] == 3
    assert report["metadata"]["generation_model"] == cli.settings.text_model


def test_main_returns_failure_when_any_case_failed(monkeypatch, capsys, tmp_path):
    eval_data = tmp_path / "queries.json"
    eval_data.write_text('{"schema_version":"judge-test-v1"}', encoding="utf-8")
    monkeypatch.setattr(cli.settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(cli, "load_eval_queries", lambda _path: [{"query": "测试问题"}])
    monkeypatch.setattr(cli, "seed_all_knowledge", lambda: 0)
    monkeypatch.setattr(
        cli,
        "run_qa_judge_eval",
        lambda *_args, **_kwargs: {
            "schema_version": "rag-qa-judge-v1",
            "n_judged": 1,
            "n_failed": 1,
        },
    )
    monkeypatch.setattr(sys, "argv", ["run_judge_eval", "--eval-data", str(eval_data)])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["n_failed"] == 1
