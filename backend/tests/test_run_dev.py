"""开发后端自动选端口的单元测试。"""

from pathlib import Path

import pytest

from scripts.run_dev import (
    find_available_port,
    is_port_available,
    parse_args,
    remove_runtime_port,
    write_runtime_port,
)


def test_find_available_port_skips_occupied_port(monkeypatch):
    occupied = {8000}

    monkeypatch.setattr(
        "scripts.run_dev.is_port_available",
        lambda _host, port: port not in occupied,
    )

    assert find_available_port("127.0.0.1", 8000, scan_limit=3) == 8001


def test_is_port_available_detects_loopback_listener_when_host_is_wildcard():
    """Windows 下通配地址探测不能漏掉已有的 loopback listener。"""
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        assert is_port_available("0.0.0.0", port) is False
    finally:
        listener.close()


def test_find_available_port_reports_exhausted_range(monkeypatch):
    monkeypatch.setattr("scripts.run_dev.is_port_available", lambda *_args: False)

    with pytest.raises(RuntimeError, match="未找到可用端口"):
        find_available_port("127.0.0.1", 8000, scan_limit=2)


def test_write_runtime_port_replaces_previous_value(tmp_path: Path):
    runtime_file = tmp_path / ".runtime-port"

    write_runtime_port(8001, runtime_file)
    write_runtime_port(8002, runtime_file)

    assert runtime_file.read_text(encoding="ascii") == "8002\n"


def test_remove_runtime_port_only_removes_its_own_port(tmp_path: Path):
    runtime_file = tmp_path / ".runtime-port"
    write_runtime_port(8001, runtime_file)

    remove_runtime_port(8000, runtime_file)
    assert runtime_file.exists()

    remove_runtime_port(8001, runtime_file)
    assert not runtime_file.exists()


def test_parse_args_keeps_host_and_port_unset_without_cli_override():
    args = parse_args([])

    assert args.host is None
    assert args.port is None
