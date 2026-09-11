from __future__ import annotations

import os

import httpx
import pytest

from conftest import submit, wait_task


def test_health_open(relay):
    r = httpx.get(relay["base"] + "/health", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["engine"] == "opencode"
    assert body["db"] == "sqlite"  # 测试环境用临时 SQLite；生产 PG 时返回 postgresql
    assert body["max_concurrent"] == 2
    assert body["min_client_version"] is None  # 默认不启用客户端最低版本校验


def test_health_min_client_version(relay_factory):
    relay = relay_factory(min_client_version="1.1.0")
    r = httpx.get(relay["base"] + "/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["min_client_version"] == "1.1.0"


def test_missing_token_401(relay):
    r = httpx.get(relay["base"] + "/tasks", timeout=5)
    assert r.status_code == 401


def test_bad_token_401(relay):
    r = httpx.get(relay["base"] + "/tasks",
                  headers={"Authorization": "Bearer nope"}, timeout=5)
    assert r.status_code == 401


def test_user_management(relay, admin, member):
    # 非 admin 不能管理用户
    r = member.post("/users", json={"name": "hacker"})
    assert r.status_code == 403

    r = admin.post("/users", json={"name": "zhang"})
    assert r.status_code == 201
    assert r.json()["token"].startswith("ta_")

    # 重名冲突
    r = admin.post("/users", json={"name": "zhang"})
    assert r.status_code == 409

    names = [u["name"] for u in admin.get("/users").json()["users"]]
    assert "zhang" in names and "tester" in names

    # 记录 token 以便吊销后验证失效
    ztok = admin.post("/users", json={"name": "tmp2"}).json()["token"]
    assert httpx.get(relay["base"] + "/tasks",
                     headers={"Authorization": f"Bearer {ztok}"}, timeout=5).status_code == 200
    r = admin.delete("/users/tmp2")
    assert r.status_code == 200
    # 吊销后 token 立即失效
    assert httpx.get(relay["base"] + "/tasks",
                     headers={"Authorization": f"Bearer {ztok}"}, timeout=5).status_code == 401
    r3 = admin.delete("/users/tmp2")
    assert r3.status_code == 404


def test_get_task_not_found(relay, member):
    r = member.get("/tasks/99999")
    assert r.status_code == 404


def test_task_lifecycle_and_diff(relay, member):
    """真实 opencode 全流程：提交 → running → review → diff → confirm → done。"""
    shared = relay["cfg"].shared_dir
    tok = member.headers["Authorization"].split()[1]
    target = os.path.relpath(os.path.join(shared, "lifecycle.txt"),
                             relay["cfg"].workspace_root)
    out = submit(relay["base"], tok,
                 f"用 write 工具在 {os.path.join(shared, 'lifecycle.txt')} 写入内容 hello-lifecycle。完成后只回复 done。",
                 targets=[target])
    tid = out["task_id"]
    # 立刻能查到 queued
    t = member.get(f"/tasks/{tid}").json()
    assert t["status"] in ("queued", "running")
    assert t["user"] == "tester"

    t = wait_task(relay["base"], tok, tid, timeout=240)
    assert t["status"] == "review", t
    assert t["session_id"], "应记录 agent 会话 id"
    assert t["result"].strip(), "应有结果文本"
    assert target in t["changed_files"]
    assert open(os.path.join(shared, "lifecycle.txt")).read() == "hello-lifecycle"

    # diff 接口
    d = member.get(f"/tasks/{tid}/diff").json()
    assert target in d["changed_files"]
    assert d["conflicts"] == []

    # confirm → done
    r = member.post(f"/tasks/{tid}/confirm", json={"outcome": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"

    # done 之后不能再 confirm
    r = member.post(f"/tasks/{tid}/confirm", json={"outcome": "done"})
    assert r.status_code == 409


def test_cancel_queued(relay, member):
    # 占满执行池
    shared = relay["cfg"].shared_dir
    tok = member.headers["Authorization"].split()[1]
    a = submit(relay["base"], tok, "用 bash 工具执行 sleep 20，然后只回复 done。")
    b = submit(relay["base"], tok, "用 bash 工具执行 sleep 20，然后只回复 done。")
    c = submit(relay["base"], tok, "只回复 ok，不要使用任何工具。")
    try:
        import time
        deadline = time.time() + 30
        while time.time() < deadline:
            ta = member.get(f"/tasks/{a['task_id']}").json()
            if ta["status"] == "running":
                break
            time.sleep(0.5)
        assert ta["status"] == "running"
        # c 应排队中
        tc = member.get(f"/tasks/{c['task_id']}").json()
        assert tc["status"] == "queued"
        r = member.post(f"/tasks/{c['task_id']}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "cancelled"
        tc = member.get(f"/tasks/{c['task_id']}").json()
        assert tc["status"] == "cancelled"
    finally:
        member.post(f"/tasks/{a['task_id']}/cancel")
        member.post(f"/tasks/{b['task_id']}/cancel")


def test_overlap_409_then_force(relay, member):
    shared = relay["cfg"].shared_dir
    tok = member.headers["Authorization"].split()[1]
    a = submit(relay["base"], tok, "用 bash 工具执行 sleep 15，然后只回复 done。",
               targets=["shared/rep"])
    import time
    deadline = time.time() + 30
    while time.time() < deadline:
        if member.get(f"/tasks/{a['task_id']}").json()["status"] == "running":
            break
        time.sleep(0.5)
    # 子目录重叠 → 409
    r = member.post("/tasks", json={
        "description": "只回复 ok，不要使用任何工具。",
        "targets": ["shared/rep/9月"],
    })
    assert r.status_code == 409
    det = r.json()["detail"]
    assert det["overlaps"][0]["task_id"] == a["task_id"]
    assert det["overlaps"][0]["user"] == "tester"

    # 无重叠 → 放行
    r = member.post("/tasks", json={
        "description": "只回复 ok，不要使用任何工具。",
        "targets": ["shared/other"],
    })
    assert r.status_code == 202

    # force → 放行（带 warnings）
    r = member.post("/tasks", json={
        "description": "只回复 ok，不要使用任何工具。",
        "targets": ["shared/rep/9月"],
        "force": True,
    })
    assert r.status_code == 202
    assert r.json()["warnings"]

    # 纯读（显式 read_only 字段，客户端 ≥1.5.0）→ 重叠也放行，无 warnings
    r = member.post("/tasks", json={
        "description": "只回复 ok，不要使用任何工具。",
        "targets": ["shared/rep/9月"],
        "read_only": True,
    })
    assert r.status_code == 202
    assert not r.json()["warnings"]
    assert member.get(f"/tasks/{r.json()['task_id']}").json()["read_only"] is True

    # 纯读（描述带「只读」标记，存量 1.4.0 客户端零改动）→ 同样放行并落库
    r = member.post("/tasks", json={
        "description": "只读查询：只回复 ok，不要使用任何工具。",
        "targets": ["shared/rep/9月"],
    })
    assert r.status_code == 202
    assert member.get(f"/tasks/{r.json()['task_id']}").json()["read_only"] is True

    member.post(f"/tasks/{a['task_id']}/cancel")
