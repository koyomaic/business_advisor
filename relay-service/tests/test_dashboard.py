from __future__ import annotations

import httpx
import pytest


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
