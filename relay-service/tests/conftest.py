from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

OPENCODE_BIN = shutil.which("opencode") or "opencode"

TERMINAL = {"done", "conflict", "failed", "cancelled"}
# 执行结束（review 待人工确认、done 已完成，均视为执行结束）
EXEC_DONE = {"review", "done", "conflict", "failed", "cancelled"}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def relay_factory(tmp_path):
    servers: list[uvicorn.Server] = []

    def make(**overrides) -> dict:
        ws = tmp_path / f"workspace-{len(servers)}"
        (ws / "shared" / "knowledge").mkdir(parents=True)
        cfg = Settings(
            db_path=str(ws / "relay.db"),
            workspace_root=str(ws),
            shared_dir=str(ws / "shared"),
            task_root=str(ws / "tasks"),
            users_root=str(ws / "users"),
            admin_token="admin-test",
            max_concurrent=2,
            task_timeout=180.0,  # 生产默认 1800s；测试放宽以容忍模型延迟抖动
            engine="opencode",
            agent_bin=OPENCODE_BIN,
            log_path=str(ws / "relay.log"),
        )
        for k, v in overrides.items():
            setattr(cfg, k, v)
        app = create_app(cfg)
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="warning"))
        th = threading.Thread(target=server.run, daemon=True)
        th.start()
        servers.append(server)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    return {"base": base, "cfg": cfg, "ws": ws, "server": server}
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("relay server did not start")

    yield make

    for s in servers:
        s.should_exit = True
    time.sleep(0.5)


@pytest.fixture()
def relay(relay_factory) -> dict:
    return relay_factory()


@pytest.fixture()
def admin(relay) -> httpx.Client:
    c = httpx.Client(base_url=relay["base"], headers={"Authorization": "Bearer admin-test"},
                     timeout=30)
    yield c
    c.close()


@pytest.fixture()
def member(relay, admin) -> httpx.Client:
    r = admin.post("/users", json={"name": "tester"})
    assert r.status_code == 201, r.text
    tok = r.json()["token"]
    c = httpx.Client(base_url=relay["base"], headers={"Authorization": f"Bearer {tok}"},
                     timeout=30)
    yield c
    c.close()


def wait_task(base: str, token: str, task_id: int, timeout: float = 300.0,
              statuses=EXEC_DONE) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = httpx.get(f"{base}/tasks/{task_id}",
                      headers={"Authorization": f"Bearer {token}"}, timeout=10)
        assert r.status_code == 200
        last = r.json()
        if last["status"] in statuses:
            return last
        time.sleep(0.8)
    raise TimeoutError(f"task {task_id} not in {statuses} after {timeout}s, last={last}")


def audit_lines(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def submit(base: str, token: str, description: str, **kw) -> dict:
    body = {"description": description}
    body.update(kw)
    r = httpx.post(f"{base}/tasks", json=body,
                   headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert r.status_code == 202, r.text
    return r.json()
