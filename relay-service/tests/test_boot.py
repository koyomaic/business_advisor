from __future__ import annotations

import os
import stat
import time

import httpx


def test_health_reports_version(relay):
    r = httpx.get(relay["base"] + "/health", timeout=10)
    assert r.status_code == 200
    v = r.json().get("version")
    assert isinstance(v, str) and v  # 开发树为 "dev"，git 部署后为 SHA


def test_admin_update_requires_admin(relay, member):
    r = member.post("/admin/update")
    assert r.status_code == 403


def test_admin_update_501_without_bootloader(relay_factory, tmp_path):
    relay = relay_factory(boot_cmd=str(tmp_path / "nonexistent-boot.sh"))
    r = httpx.post(relay["base"] + "/admin/update",
                   headers={"Authorization": "Bearer admin-test"}, timeout=10)
    assert r.status_code == 501


def test_admin_update_triggers_boot(relay_factory, tmp_path, monkeypatch):
    marker = tmp_path / "marker.txt"
    boot = tmp_path / "boot.sh"
    boot.write_text(f"#!/bin/bash\necho \"$1\" > {marker}\n", encoding="utf-8")
    boot.chmod(boot.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("RELAY_BOOT_NOSYSTEMD", "1")  # 测试走 detached 路径，不动真实 systemd
    relay = relay_factory(boot_cmd=str(boot))
    r = httpx.post(relay["base"] + "/admin/update",
                   headers={"Authorization": "Bearer admin-test"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["trigger"] == "detached"
    deadline = time.time() + 8
    while time.time() < deadline and not marker.is_file():
        time.sleep(0.2)
    assert marker.is_file(), "bootloader 未被触发"
    assert marker.read_text().strip() == "update"
    # 审计留痕
    with open(relay["ws"] / "relay.log", encoding="utf-8") as f:
        assert any("update_trigger" in ln for ln in f)
