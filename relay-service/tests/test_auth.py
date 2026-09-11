"""设备激活 + HMAC 签名认证（token 一次性激活码化）测试。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import httpx


def _sign(secret: str, dev_id: str, method: str, path: str, body: bytes = b"",
          ts: str | None = None, nonce: str | None = None) -> dict:
    ts = ts or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    digest = hashlib.sha256(body).hexdigest()
    msg = f"{ts}\n{method}\n{path}\n{digest}\n{nonce}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {"X-Device-Id": dev_id, "X-Timestamp": ts,
            "X-Nonce": nonce, "X-Signature": sig}


def _activate(base: str, token: str, device_id: str = "dev-test-1") -> dict:
    r = httpx.post(base + "/auth/activate",
                   json={"token": token, "device_id": device_id,
                         "device_name": "pytest"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()


def _make_user(admin: httpx.Client, name: str = "alice") -> str:
    r = admin.post("/users", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_activate_and_signed_request(relay, admin):
    base = relay["base"]
    token = _make_user(admin)
    # 测试基座开了过渡双轨（auth_legacy=True）：激活前 bearer 可用；
    # 生产默认硬切换（legacy=0）下该请求 401，见 test_legacy_off
    r = httpx.get(base + "/tasks", headers={"Authorization": f"Bearer {token}"},
                  timeout=10)
    assert r.status_code == 200
    # 激活：token 换设备凭证
    act = _activate(base, token)
    assert act["user"] == "alice" and act["device_secret"]
    secret, dev = act["device_secret"], act["device_id"]
    # 签名请求可用
    h = _sign(secret, dev, "GET", "/tasks")
    r = httpx.get(base + "/tasks", headers=h, timeout=10)
    assert r.status_code == 200
    # 激活后旧 token 作为 bearer 立即失效（已核销）
    r = httpx.get(base + "/tasks", headers={"Authorization": f"Bearer {token}"},
                  timeout=10)
    assert r.status_code == 401
    # 同一 token 二次激活 → 409（一次性）
    r = httpx.post(base + "/auth/activate",
                   json={"token": token, "device_id": "dev-other"}, timeout=10)
    assert r.status_code == 409


def test_signature_verification(relay, admin):
    base = relay["base"]
    act = _activate(base, _make_user(admin, "bob"))
    secret, dev = act["device_secret"], act["device_id"]
    # 错误签名
    h = _sign("wrong-secret", dev, "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
    # 过期时间戳（超出 900s 时间窗）
    h = _sign(secret, dev, "GET", "/tasks", ts=str(int(time.time()) - 1800))
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
    # 未知设备
    h = _sign(secret, "dev-ghost", "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
    # 重放：同 nonce 二次使用被拒
    h = _sign(secret, dev, "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 200
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
    # 篡改方法/路径签名不匹配
    h = _sign(secret, dev, "GET", "/users")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401


def test_signed_post_with_body(relay, admin):
    base = relay["base"]
    act = _activate(base, _make_user(admin, "carol"))
    secret, dev = act["device_secret"], act["device_id"]
    body = json.dumps({"description": "签名任务", "targets": []}).encode()
    h = _sign(secret, dev, "POST", "/tasks", body)
    h["Content-Type"] = "application/json"
    r = httpx.post(base + "/tasks", content=body, headers=h, timeout=10)
    assert r.status_code == 202, r.text
    # body 参与签名：同签名换 body → 401
    body2 = json.dumps({"description": "篡改", "targets": []}).encode()
    h2 = _sign(secret, dev, "POST", "/tasks", body)
    h2["Content-Type"] = "application/json"
    r = httpx.post(base + "/tasks", content=body2, headers=h2, timeout=10)
    assert r.status_code == 401


def test_signed_query_path(relay, admin):
    base = relay["base"]
    act = _activate(base, _make_user(admin, "dave"))
    secret, dev = act["device_secret"], act["device_id"]
    path = "/tasks?status=running&limit=5"
    h = _sign(secret, dev, "GET", path)
    r = httpx.get(base + path, headers=h, timeout=10)
    assert r.status_code == 200


def test_revoke_device(relay, admin):
    base = relay["base"]
    token = _make_user(admin, "frank")
    act = _activate(base, token)
    secret, dev = act["device_secret"], act["device_id"]
    h = _sign(secret, dev, "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 200
    r = admin.delete(f"/users/frank/devices/{dev}")
    assert r.status_code == 200
    h = _sign(secret, dev, "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
    # 设备列表可见已吊销
    devs = admin.get("/users/frank/devices").json()["devices"]
    assert any(d["device_id"] == dev and d["revoked_at"] for d in devs)


def test_reissue_token_multi_device(relay, admin):
    base = relay["base"]
    token = _make_user(admin, "grace")
    act1 = _activate(base, token, "dev-g1")
    # 补发新激活码（旧码已核销）
    r = admin.post("/users/grace/token")
    assert r.status_code == 201
    token2 = r.json()["token"]
    act2 = _activate(base, token2, "dev-g2")
    # 两台设备并存均可用
    for act, dev in ((act1, "dev-g1"), (act2, "dev-g2")):
        h = _sign(act["device_secret"], dev, "GET", "/tasks")
        assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 200
    # 吊销一台不影响另一台
    assert admin.delete("/users/grace/devices/dev-g1").status_code == 200
    h = _sign(act2["device_secret"], "dev-g2", "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 200


def test_legacy_off(relay_factory):
    relay = relay_factory(auth_legacy=False)
    base = relay["base"]
    r = httpx.post(base + "/users", json={"name": "heidi"},
                   headers={"Authorization": "Bearer admin-test"}, timeout=10)
    token = r.json()["token"]
    # legacy 关闭：未核销 token 的 bearer 也被拒
    r = httpx.get(base + "/tasks", headers={"Authorization": f"Bearer {token}"},
                  timeout=10)
    assert r.status_code == 401
    # 激活仍可用，签名请求正常
    act = _activate(base, token)
    h = _sign(act["device_secret"], act["device_id"], "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 200
    # health 透出开关
    assert httpx.get(base + "/health", timeout=5).json()["auth_legacy"] is False


def test_auth_legacy_default_off():
    """生产默认：旧式 bearer 认证关闭（硬切换），Settings 缺省即 False。"""
    from app.config import Settings
    assert Settings.__dataclass_fields__["auth_legacy"].default is False


def test_delete_user_revokes_devices(relay, admin):
    base = relay["base"]
    token = _make_user(admin, "ivan")
    act = _activate(base, token)
    assert admin.delete("/users/ivan").status_code == 200
    h = _sign(act["device_secret"], act["device_id"], "GET", "/tasks")
    assert httpx.get(base + "/tasks", headers=h, timeout=10).status_code == 401
