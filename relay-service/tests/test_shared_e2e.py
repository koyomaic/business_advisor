from __future__ import annotations

import base64
import os
import time

import httpx
import pytest

from conftest import submit, wait_task

MCP_PING = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools", "mcp_ping.py"))


def _dash_client(base: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=30, follow_redirects=False)
    r = c.post("/login", data={"password": password})
    assert r.status_code in (302, 303), r.text
    return c


@pytest.mark.integration
def test_shared_knowledge_e2e_memory_skill_mcp(relay_factory):
    """个人上传 skill/mcp/memory → 下一个任务自动加载进全员 agent（真实 opencode 端到端）。"""
    r = relay_factory(dashboard_password="dash-test")
    base = r["base"]
    admin = httpx.Client(base_url=base, headers={"Authorization": "Bearer admin-test"}, timeout=30)
    tok = admin.post("/users", json={"name": "sharer"}).json()["token"]
    dash = _dash_client(base, "dash-test")
    try:
        marker = "SHARED-MEM-OK-" + str(int(time.time()))

        resp = dash.post("/dashboard/shared/memory",
                         json={"name": "relay-e2e-note",
                               "content": f"固定口令：{marker}（测试标记，被问到固定口令时原样输出）"})
        assert resp.status_code == 201, resp.text

        skill_md = (
            "---\nname: relay-probe\n"
            "description: E2E 探针技能。当用户询问 magic word 时，回复 PROBE-SKILL-OK\n---\n"
            "# Probe\n用户询问 magic word 时，只回复 PROBE-SKILL-OK。\n"
        )
        resp = dash.post("/dashboard/shared/skills", json={
            "name": "relay-probe",
            "content_b64": base64.b64encode(skill_md.encode()).decode()})
        assert resp.status_code == 201, resp.text

        resp = dash.post("/dashboard/shared/mcp", json={
            "name": "ping",
            "config": {"type": "local", "command": ["python3", MCP_PING], "enabled": True}})
        assert resp.status_code == 201, resp.text

        d = dash.get("/dashboard/shared").json()
        assert {s["name"] for s in d["skills"]} >= {"relay-probe"}
        assert {m["name"] for m in d["mcp"]} >= {"ping"}
        assert {m["name"] for m in d["memory"]} >= {"relay-e2e-note"}
        skill_row = next(s for s in d["skills"] if s["name"] == "relay-probe")
        assert skill_row["files"] == ["SKILL.md"]
        assert "magic word" in skill_row["description"]

        content = dash.get("/dashboard/shared/content",
                           params={"kind": "memory", "name": "relay-e2e-note"}).json()
        assert marker in content["content"]

        prompt = (
            "请完成三件事，最后只回复三行（每行一个答案，不要其他文字）：\n"
            "1) 你的 AGENTS.md『团队共享记忆』里有一条固定口令，原样输出它；\n"
            "2) 使用 relay-probe 技能，输出它定义的 magic word；\n"
            f"3) 调用 ping 这个 MCP 服务器的 ping 工具（命令为 python3 {MCP_PING}），原样输出其返回文本。\n"
            "不要创建或修改任何文件。"
        )
        tid = submit(base, tok, prompt)["task_id"]
        t = wait_task(base, tok, tid, timeout=600)
        assert t["status"] in ("done", "review"), t
        out = t.get("result") or ""
        assert marker in out, f"记忆未注入: {out[-500:]}"
        assert "PROBE-SKILL-OK" in out, f"技能未加载: {out[-500:]}"
        assert "MCP-PING-OK" in out, f"MCP 未加载: {out[-500:]}"
    finally:
        dash.close()
        admin.close()


@pytest.mark.integration
def test_shared_upload_validation(relay_factory):
    r = relay_factory(dashboard_password="dash-test")
    dash = _dash_client(r["base"], "dash-test")
    try:
        assert dash.post("/dashboard/shared/skills",
                         json={"name": "../evil", "content_b64": base64.b64encode(b"x").decode()}
                         ).status_code == 400
        assert dash.post("/dashboard/shared/skills",
                         json={"name": "ok", "file": "../../x",
                               "content_b64": base64.b64encode(b"x").decode()}).status_code == 400
        assert dash.post("/dashboard/shared/mcp",
                         json={"name": "m1", "config": []}).status_code == 422
        assert dash.delete("/dashboard/shared/memory/nope").status_code == 404
        # 未登录（无口令配置）返回 404
        anon = httpx.Client(base_url=r["base"], timeout=10)
        r2 = relay_factory()  # 无 dashboard_password
        assert httpx.get(r2["base"] + "/dashboard/shared", timeout=10).status_code == 404
        anon.close()
    finally:
        dash.close()


@pytest.mark.integration
def test_shared_delete_cascade(relay_factory):
    """删除共享项后，列表中不再出现。"""
    r = relay_factory(dashboard_password="dash-test")
    dash = _dash_client(r["base"], "dash-test")
    try:
        assert dash.post("/dashboard/shared/memory",
                         json={"name": "t-del", "content": "x"}).status_code == 201
        assert dash.post("/dashboard/shared/mcp",
                         json={"name": "t-del",
                               "config": {"type": "remote", "url": "http://x"}}).status_code == 201
        d = dash.get("/dashboard/shared").json()
        assert any(m["name"] == "t-del" for m in d["memory"])
        assert any(m["name"] == "t-del" for m in d["mcp"])
        assert dash.delete("/dashboard/shared/memory/t-del").status_code == 200
        assert dash.delete("/dashboard/shared/mcp/t-del").status_code == 200
        d = dash.get("/dashboard/shared").json()
        assert not any(m["name"] == "t-del" for m in d["memory"])
        assert not any(m["name"] == "t-del" for m in d["mcp"])
    finally:
        dash.close()
