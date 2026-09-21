"""开发环境启动脚本：端口占用时自动顺延到下一个可用端口。

用法（backend/ 目录下）：
    uv run python scripts/run_dev.py
    uv run python scripts/run_dev.py --port 9000

脚本会把实际监听端口写入 backend/.runtime-port，前端 Vite 启动时读取
该文件配置代理目标。生产环境仍应由进程管理器显式指定端口。
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNTIME_PORT_FILE = BACKEND_DIR / ".runtime-port"
DEFAULT_SCAN_LIMIT = 20


def is_port_available(host: str, port: int) -> bool:
    """检查本机端口能否监听。

    Windows 下指定地址和通配地址的 bind 探测结果可能不一致：例如已有进程
    绑定 127.0.0.1 时，探测 0.0.0.0 仍可能成功，但 Uvicorn 随后会因地址冲突
    启动失败。因此对 IPv4 同时检查目标地址与其对应的通配/回环地址。
    """
    probe_hosts = [host]
    if host == "0.0.0.0":
        probe_hosts.append("127.0.0.1")
    elif host == "127.0.0.1":
        probe_hosts.append("0.0.0.0")
    elif host == "::":
        probe_hosts.append("::1")
    elif host == "::1":
        probe_hosts.append("::")

    for probe_host in probe_hosts:
        with socket.socket(socket.AF_INET6 if ":" in probe_host else socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((probe_host, port))
            except OSError:
                return False
    return True


def find_available_port(host: str, start_port: int, scan_limit: int = DEFAULT_SCAN_LIMIT) -> int:
    """从 start_port 开始顺延查找可用端口。"""
    if start_port < 1 or start_port > 65535:
        raise ValueError("端口必须在 1 到 65535 之间")
    if scan_limit < 1:
        raise ValueError("scan_limit 必须大于 0")

    for port in range(start_port, min(start_port + scan_limit, 65536)):
        if is_port_available(host, port):
            return port
    raise RuntimeError(
        f"未找到可用端口：已检查 {start_port} 到 "
        f"{min(start_port + scan_limit - 1, 65535)}"
    )


def write_runtime_port(port: int, path: Path = RUNTIME_PORT_FILE) -> None:
    """原子写入实际端口，避免 Vite 读取到半截内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(f"{port}\n", encoding="ascii")
    temp_path.replace(path)


def remove_runtime_port(port: int, path: Path = RUNTIME_PORT_FILE) -> None:
    """仅在运行时文件仍属于当前进程时删除，避免误删新实例的端口。"""
    try:
        if path.read_text(encoding="ascii").strip() == str(port):
            path.unlink()
    except FileNotFoundError:
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 NutriLens 开发后端")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT)
    parser.add_argument("--no-reload", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    host = args.host or settings.host
    start_port = args.port if args.port is not None else settings.port
    port = find_available_port(host, start_port, args.scan_limit)
    write_runtime_port(port)
    print(f"NutriLens backend listening on http://localhost:{port}")
    print(f"Runtime port written to {RUNTIME_PORT_FILE}")

    # 脚本从 backend/ 目录启动时，app 可直接导入；从任意目录调用时也保持可用。
    import uvicorn

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=not args.no_reload,
            reload_dirs=[str(BACKEND_DIR / "app")] if not args.no_reload else None,
        )
    finally:
        remove_runtime_port(port)


if __name__ == "__main__":
    main()
