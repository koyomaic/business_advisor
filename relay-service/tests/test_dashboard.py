from __future__ import annotations

import time

import httpx
import pytest

import app.main as m
from app.config import Settings
from app.main import create_app


@pytest.fixture()
def relay_dash(relay_factory) -> dict:
    return relay_factory(dashboard_password="dash-test-pw")


def test_dashboard_disabled_without_password(relay):
    r = httpx.get(relay["base"] + "/", timeout=5)
    assert r.status_code == 404
    r = httpx.get(relay["base"] + "/dashboard/data", timeout=5)
    assert r.status_code == 404
    r = httpx.get(relay["base"] + "/dashboard/tokens", timeout=5)
    assert r.status_code == 404


def test_dashboard_login_page_and_data(relay_dash):
    c = httpx.Client(base_url=relay_dash["base"], timeout=10)
    try:
        r = c.get("/")
        assert r.status_code == 200
        assert "访问口令" in r.text

        r = c.post("/login", data={"password": "wrong"}, follow_redirects=False)
        assert r.status_code == 303
        assert "/?e=1" in r.headers["location"]

        r = c.post("/login", data={"password": "dash-test-pw"}, follow_redirects=False)
        assert r.status_code == 302
        assert "relay_dash" in c.cookies

        r = c.get("/")
        assert r.status_code == 200
        assert "调用情况" in r.text

        r = c.get("/dashboard/data")
        assert r.status_code == 200
        d = r.json()
        assert set(d) == {"metrics", "tasks", "report"}
        assert "active" in d["metrics"] and "by_user" in d["report"]

        r = httpx.get(relay_dash["base"] + "/dashboard/data", timeout=5)
        assert r.status_code == 401

        c.get("/logout", follow_redirects=False)
        assert c.get("/dashboard/data").status_code == 401
    finally:
        c.close()


def test_token_mgmt_crud(relay_dash):
    base = relay_dash["base"]
    c = httpx.Client(base_url=base, timeout=10)
    try:
        # 未登录 → 401
        assert c.get("/dashboard/tokens").status_code == 401
        r = c.post("/login", data={"password": "dash-test-pw"}, follow_redirects=False)
        assert r.status_code == 302 and "relay_dash" in c.cookies

        # 查：初始为空
        assert c.get("/dashboard/tokens").json() == {"users": []}

        # 增
        r = c.post("/dashboard/tokens", json={"name": "测试员"})
        assert r.status_code == 201, r.text
        tok1 = r.json()["token"]
        assert tok1.startswith("ta_")

        assert c.post("/dashboard/tokens", json={"name": "测试员"}).status_code == 409
        assert c.post("/dashboard/tokens", json={"name": "  "}).status_code == 422

        # 新 token 立即可用
        h1 = {"Authorization": f"Bearer {tok1}"}
        assert httpx.get(base + "/tasks", headers=h1, timeout=10).status_code == 200

        # 查：列表展示完整 token
        d = c.get("/dashboard/tokens").json()
        assert len(d["users"]) == 1
        u = d["users"][0]
        assert u["name"] == "测试员"
        assert u["token"] == tok1
        assert u["tasks_7d"] == 0 and u["done_7d"] == 0
        assert u["created_at"] > 0

        # 改（重置）：旧 token 立即失效，新 token 可用
        r = c.post("/dashboard/tokens/%E6%B5%8B%E8%AF%95%E5%91%98/regenerate")  # 测试员
        assert r.status_code == 200, r.text
        tok2 = r.json()["token"]
        assert tok2.startswith("ta_") and tok2 != tok1
        assert httpx.get(base + "/tasks", headers=h1, timeout=10).status_code == 401
        assert httpx.get(base + "/tasks",
                         headers={"Authorization": f"Bearer {tok2}"}, timeout=10).status_code == 200

        # 删
        assert c.delete("/dashboard/tokens/%E6%B5%8B%E8%AF%95%E5%91%98").json() == {"ok": True, "name": "测试员"}
        assert httpx.get(base + "/tasks",
                         headers={"Authorization": f"Bearer {tok2}"}, timeout=10).status_code == 401
        assert c.get("/dashboard/tokens").json() == {"users": []}
        assert c.delete("/dashboard/tokens/%E6%B5%8B%E8%AF%95%E5%91%98").status_code == 404
        assert c.post("/dashboard/tokens/%E6%B5%8B%E8%AF%95%E5%91%98/regenerate").status_code == 404
    finally:
        c.close()


# ---- 登录防爆破：窗口内同 IP 失败达上限 → 锁定；窗口过后自动解锁 ----

def test_login_rate_limit(relay_dash, monkeypatch):
    monkeypatch.setattr(m, "LOGIN_LOCK_SEC", 1.0)  # 测试用短窗口
    c = httpx.Client(base_url=relay_dash["base"], timeout=10)
    try:
        for _ in range(m.LOGIN_MAX_FAILS):
            r = c.post("/login", data={"password": "wrong"}, follow_redirects=False)
            assert r.status_code == 303 and "/?e=1" in r.headers["location"]
        # 锁定后即使口令正确也拒绝，且不发会话 cookie
        r = c.post("/login", data={"password": "dash-test-pw"}, follow_redirects=False)
        assert r.status_code == 303 and "/?e=2" in r.headers["location"]
        assert "relay_dash" not in c.cookies
        assert "尝试次数过多" in c.get("/?e=2").text
        # 窗口过后自动解锁
        time.sleep(1.1)
        r = c.post("/login", data={"password": "dash-test-pw"}, follow_redirects=False)
        assert r.status_code == 302 and "relay_dash" in c.cookies
        # 失败留审计痕迹（ip + 累计次数）
        log = (relay_dash["ws"] / "relay.log").read_text(encoding="utf-8")
        assert "login_fail" in log and "ip=127.0.0.1" in log
    finally:
        c.close()


def test_login_success_clears_fails(relay_dash):
    c = httpx.Client(base_url=relay_dash["base"], timeout=10)
    try:
        for _ in range(m.LOGIN_MAX_FAILS - 1):  # 差一次到上限
            c.post("/login", data={"password": "wrong"}, follow_redirects=False)
        r = c.post("/login", data={"password": "dash-test-pw"}, follow_redirects=False)
        assert r.status_code == 302 and "relay_dash" in c.cookies
        c.get("/logout", follow_redirects=False)
        # 成功已清零：再失败 MAX-1 次仍不锁
        for _ in range(m.LOGIN_MAX_FAILS - 1):
            r = c.post("/login", data={"password": "wrong"}, follow_redirects=False)
            assert "/?e=1" in r.headers["location"]
    finally:
        c.close()


# ---- 启动自检：admin_token 缺失/默认值拒绝启动（/admin/update 可触发部署） ----

def test_create_app_rejects_default_admin_token(tmp_path):
    for bad in ("change-me", ""):
        cfg = Settings(db_path=str(tmp_path / "relay.db"), workspace_root=str(tmp_path),
                       shared_dir=str(tmp_path / "shared"), task_root=str(tmp_path / "tasks"),
                       users_root=str(tmp_path / "users"), admin_token=bad)
        with pytest.raises(RuntimeError):
            create_app(cfg)
