from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from conftest import submit, wait_task  # noqa: E402

from app.main import create_app  # noqa: E402


def _start_app(cfg, port: int) -> uvicorn.Server:
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1",
                                           port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(base + "/health", timeout=1).status_code == 200:
                return server
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("second relay server did not start")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.integration
def test_restart_recovery_reruns_orphans(relay_factory):
    """进程重启后，原 queued/running 任务必须被重新排队执行（不再变孤儿）。"""
    r1 = relay_factory()
    base1, cfg = r1["base"], r1["cfg"]
    admin = httpx.Client(base_url=base1, headers={"Authorization": "Bearer admin-test"},
                         timeout=30)
    tok = admin.post("/users", json={"name": "rec"}).json()["token"]
    t1 = submit(base1, tok, "只回复 ok，不要使用任何工具。")["task_id"]
    time.sleep(1.0)
    # 直接停掉第一个服务（模拟崩溃/重启，任务可能停在 running 或 queued）
    r1["server"].should_exit = True
    time.sleep(2.0)

    port2 = _free_port()
    server2 = _start_app(cfg, port2)
    base2 = f"http://127.0.0.1:{port2}"
    try:
        t = wait_task(base2, tok, t1, timeout=300)
        assert t["status"] in ("done", "review"), t
    finally:
        server2.should_exit = True
        admin.close()
