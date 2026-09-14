"""app/serve.py 监听形态选择（TLS 直听 / 明文回落）测试。"""
from __future__ import annotations

from app.serve import listen_plan


def test_listen_plan_tls(tmp_path):
    cert, key = tmp_path / "fullchain.pem", tmp_path / "server.key"
    cert.write_text("x"), key.write_text("y")
    p = listen_plan(str(tmp_path))
    assert p == {"host": "0.0.0.0", "port": 8788,
                 "ssl_certfile": str(cert), "ssl_keyfile": str(key)}


def test_listen_plan_plain_without_certs(tmp_path):
    # 无证书（非 HTTPS 主机）→ 明文 8787，维持原形态
    assert listen_plan(str(tmp_path)) == {"host": "0.0.0.0", "port": 8787}
    assert listen_plan("") == {"host": "0.0.0.0", "port": 8787}


def test_listen_plan_partial_certs(tmp_path):
    # 只有证书没有私钥 → 视为无 TLS，不半吊子起 https
    (tmp_path / "fullchain.pem").write_text("x")
    assert listen_plan(str(tmp_path)) == {"host": "0.0.0.0", "port": 8787}


def test_listen_plan_overrides(tmp_path):
    cert, key = tmp_path / "fullchain.pem", tmp_path / "server.key"
    cert.write_text("x"), key.write_text("y")
    p = listen_plan(str(tmp_path), host="127.0.0.1", port=9000)
    assert p["host"] == "127.0.0.1" and p["port"] == 9000 and "ssl_certfile" in p
