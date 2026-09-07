from __future__ import annotations

import base64

import httpx

MB = 1 * 1024 * 1024


def test_upload_download_roundtrip(member, relay):
    payload = "hello 团队".encode("utf-8") + b"\x00\x01\xff"
    r = member.post("/files", json={
        "path": "data/round.bin",
        "content_b64": base64.b64encode(payload).decode(),
    })
    assert r.status_code == 201, r.text
    assert r.json() == {"ok": True, "path": "data/round.bin", "size": len(payload)}
    r = member.get("/files", params={"path": "data/round.bin"})
    assert r.status_code == 200
    assert r.content == payload
    assert (relay["ws"] / "shared" / "data" / "round.bin").read_bytes() == payload


def test_upload_exactly_1mb_ok(member):
    exact = "y" * MB
    r = member.post("/files", json={
        "path": "exact.bin",
        "content_b64": base64.b64encode(exact.encode()).decode(),
    })
    assert r.status_code == 201, r.text
    assert r.json()["size"] == MB


def test_upload_over_1mb_rejected(member):
    big = "x" * (MB + 1)
    r = member.post("/files", json={
        "path": "big.txt",
        "content_b64": base64.b64encode(big.encode()).decode(),
    })
    assert r.status_code == 413


def test_download_over_1mb_rejected(member, relay):
    (relay["ws"] / "shared" / "big2.bin").write_bytes(b"z" * (MB + 1))
    r = member.get("/files", params={"path": "big2.bin"})
    assert r.status_code == 413


def test_path_traversal_blocked(member):
    for bad in ("../outside.txt", "/etc/passwd", "a/../../b.txt"):
        r = member.post("/files", json={
            "path": bad,
            "content_b64": base64.b64encode(b"x").decode(),
        })
        assert r.status_code == 400, bad
    r = member.get("/files", params={"path": "../outside.txt"})
    assert r.status_code == 400


def test_download_missing_file(member):
    r = member.get("/files", params={"path": "nope/missing.txt"})
    assert r.status_code == 404


def test_invalid_base64_rejected(member):
    r = member.post("/files", json={"path": "x.txt", "content_b64": "not-base64!!!"})
    assert r.status_code == 400


def test_files_require_auth(relay):
    r = httpx.get(relay["base"] + "/files", params={"path": "x"}, timeout=10)
    assert r.status_code == 401
    r = httpx.post(relay["base"] + "/files",
                   json={"path": "x.txt", "content_b64": "aGk="}, timeout=10)
    assert r.status_code == 401


# ---- secrets/ 凭证目录不经 files API 出入（凭证不出服务器） ----

def test_secrets_download_blocked(member, relay):
    d = relay["ws"] / "shared" / "secrets" / "dws-cli-seed" / "dws-cli"
    d.mkdir(parents=True, exist_ok=True)
    (d / "auth-token.enc").write_bytes(b"top-secret")
    r = member.get("/files", params={"path": "secrets/dws-cli-seed/dws-cli/auth-token.enc"})
    assert r.status_code == 403
    # 规范化绕路同样拦截
    r = member.get("/files", params={"path": "knowledge/../secrets/dws-cli-seed/dws-cli/auth-token.enc"})
    assert r.status_code == 403


def test_secrets_upload_blocked(member):
    r = member.post("/files", json={
        "path": "secrets/evil.txt",
        "content_b64": base64.b64encode(b"x").decode(),
    })
    assert r.status_code == 403


def test_secrets_symlink_escape_blocked(member, relay):
    import os
    shared = relay["ws"] / "shared"
    (shared / "secrets").mkdir(exist_ok=True)
    (shared / "secrets" / "cred.enc").write_bytes(b"top-secret")
    link = shared / "innocent"
    if not link.is_symlink():
        os.symlink(shared / "secrets", link)
    r = member.get("/files", params={"path": "innocent/cred.enc"})
    assert r.status_code == 403
