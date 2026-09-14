"""生产入口：按证书存在性自动选择监听形态（systemd relay.service 调用）。

- 有证书（RELAY_TLS_DIR 下 fullchain.pem+server.key）：0.0.0.0:8788 TLS 直听。
  应用直接终结 TLS → request.client.host 为真实客户端 IP（审计/登录限频不失真），
  且不再对外暴露明文端口。本机回环明文健康检查口（127.0.0.1:8787 → 8788）
  由 relay-tls-proxy.service（socat）提供，仅 loopback 可达。
- 无证书（非 HTTPS 主机）：0.0.0.0:8787 明文，维持原形态。

覆盖项：RELAY_HOST / RELAY_PORT（显式指定端口时不再按证书推断）。
"""
from __future__ import annotations

import os


def listen_plan(tls_dir: str, host: str = "", port: int = 0) -> dict:
    """返回 uvicorn 监听参数：{"host","port","ssl_certfile","ssl_keyfile"}。"""
    cert = os.path.join(tls_dir, "fullchain.pem") if tls_dir else ""
    key = os.path.join(tls_dir, "server.key") if tls_dir else ""
    tls = bool(tls_dir) and os.path.isfile(cert) and os.path.isfile(key)
    plan: dict = {"host": host or "0.0.0.0", "port": port or (8788 if tls else 8787)}
    if tls:
        plan["ssl_certfile"] = cert
        plan["ssl_keyfile"] = key
    return plan


def main() -> None:
    import uvicorn
    plan = listen_plan(os.environ.get("RELAY_TLS_DIR", ""),
                       os.environ.get("RELAY_HOST", ""),
                       int(os.environ.get("RELAY_PORT", "0") or 0))
    uvicorn.run("app.entry:app", **plan)


if __name__ == "__main__":
    main()
