from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.workspace import Workspace


def _cfg(tmp_path, cleanup: bool) -> Settings:
    return Settings(
        db_path=str(tmp_path / "relay.db"),
        workspace_root=str(tmp_path),
        shared_dir=str(tmp_path / "shared"),
        task_root=str(tmp_path / "tasks"),
        users_root=str(tmp_path / "users"),
        admin_token="admin-test",
        cleanup_runtime=cleanup,
    )


def _seed_workdir(ws_dir, tid: int = 1) -> str:
    wd = os.path.join(ws_dir, str(tid))
    for sub in ("home", "data", ".result"):
        os.makedirs(os.path.join(wd, sub))
    with open(os.path.join(wd, ".baseline.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(wd, "home", "cache.bin"), "w") as f:
        f.write("x" * 1024)
    with open(os.path.join(wd, "data", "work.bin"), "w") as f:
        f.write("y" * 1024)
    with open(os.path.join(wd, ".result", "out.txt"), "w") as f:
        f.write("result")
    return wd


def test_cleanup_removes_runtime_keeps_result(tmp_path):
    cfg = _cfg(tmp_path, cleanup=True)
    ws = Workspace(cfg, None)
    wd = _seed_workdir(str(cfg.task_root))
    ws.cleanup_terminal({"id": 1, "workdir": wd})
    assert not os.path.exists(os.path.join(wd, "home"))
    assert not os.path.exists(os.path.join(wd, "data"))
    assert os.path.exists(os.path.join(wd, ".result", "out.txt"))
    assert os.path.exists(os.path.join(wd, ".baseline.json"))


def test_cleanup_disabled_keeps_everything(tmp_path):
    cfg = _cfg(tmp_path, cleanup=False)
    ws = Workspace(cfg, None)
    wd = _seed_workdir(str(cfg.task_root))
    ws.cleanup_terminal({"id": 1, "workdir": wd})
    assert os.path.exists(os.path.join(wd, "home", "cache.bin"))
    assert os.path.exists(os.path.join(wd, "data", "work.bin"))


def test_cleanup_without_workdir_key_falls_back_to_task_root(tmp_path):
    cfg = _cfg(tmp_path, cleanup=True)
    ws = Workspace(cfg, None)
    _seed_workdir(str(cfg.task_root), tid=7)
    ws.cleanup_terminal({"id": 7})  # 无 workdir 键 → task_root/7
    assert not os.path.exists(os.path.join(str(cfg.task_root), "7", "home"))


def test_cleanup_missing_workdir_noop(tmp_path):
    cfg = _cfg(tmp_path, cleanup=True)
    ws = Workspace(cfg, None)
    ws.cleanup_terminal({"id": 999, "workdir": str(tmp_path / "no-such-dir")})


def test_env_var_off_disables_cleanup(monkeypatch):
    monkeypatch.setenv("RELAY_CLEANUP_RUNTIME", "0")
    cfg = Settings.from_env()
    assert cfg.cleanup_runtime is False
    monkeypatch.setenv("RELAY_CLEANUP_RUNTIME", "1")
    assert Settings.from_env().cleanup_runtime is True
    monkeypatch.delenv("RELAY_CLEANUP_RUNTIME")
    assert Settings.from_env().cleanup_runtime is True
