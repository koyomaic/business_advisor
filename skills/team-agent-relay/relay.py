#!/usr/bin/env python3
"""team-agent-relay 客户端（纯标准库，无第三方依赖）。

用法:
  python3 relay.py config [set TOKEN] [--server URL] [--profile 名称]
  python3 relay.py profiles                                # 列出全部 profile
  python3 relay.py version                                 # 客户端/服务端版本对照
  python3 relay.py run "任务描述" [-t a,b] [--urgent] [--resume N] [--force]
  python3 relay.py submit "任务描述" [-t a,b] [--urgent] [--resume N] [--force]
  python3 relay.py wait <id> [--timeout 900]
  python3 relay.py status <id>
  python3 relay.py tasks [--status S] [--limit N]
  python3 relay.py stream <id> [--timeout 600]
  python3 relay.py diff <id>
  python3 relay.py upload <本地文件> <共享区相对路径>     # 上传，≤1MB
  python3 relay.py download <共享区相对路径> [本地路径]   # 下载，≤1MB
  python3 relay.py cancel <id>
  python3 relay.py confirm <id> [--outcome done|conflict]

所有子命令支持 --profile <名称> 选择公司/服务器配置（缺省 default）。

输出均为单行 JSON。退出码: 0 正常; 2 目标重叠(409); 3 token失效(401)。
配置: 环境变量 TEAM_AGENT_SERVER/TEAM_AGENT_TOKEN/TEAM_AGENT_PROFILE 优先，
其次 ~/.team-agent/config（INI 多节，每节一组 SERVER=/TOKEN=，节名即 profile；
旧版无节平铺格式首次加载自动迁移为 [default] 并回写）。
连接: 默认 https://10.189.51.23:8788（中鲁），TLS 校验固定用本目录 ca.pem
（CA 缺失时退回系统默认校验）；历史默认地址（.23:8787 http、.29:8787 http）
首次加载时按 SERVER_MIGRATIONS 自动迁移并回写。.29 为新能源中转，
新能源成员用 --profile 新能源 --server https://10.189.51.29:8788 配置。
"""
from __future__ import annotations

import argparse
import base64
import configparser
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

__version__ = "1.2.0"

CFG_PATH = os.path.expanduser("~/.team-agent/config")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_PEM = os.path.join(SCRIPT_DIR, "ca.pem")
DEFAULT_SERVER = "https://10.189.51.23:8788"   # 中鲁（本团队默认）
# 历史默认地址 → 现地址（首载自动迁移回写；.29=新能源只做 http→https 原地升级，不跨机迁移）
SERVER_MIGRATIONS = {
    "http://10.189.51.23:8787": DEFAULT_SERVER,
    "http://10.189.51.29:8787": "https://10.189.51.29:8788",
}
TERMINAL = {"done", "review", "conflict", "failed", "cancelled"}
MAX_FILE_BYTES = 1 * 1024 * 1024  # 文件通道单文件上限 1MB


def _ssl_ctx(server: str):
    """https 返回 SSLContext（ca.pem 存在则固定校验），http 返回 None。"""
    if not server.startswith("https://"):
        return None
    ctx = ssl.create_default_context()
    if os.path.isfile(CA_PEM):
        ctx.load_verify_locations(CA_PEM)
    return ctx


def _new_cp() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.optionxform = str  # 保留 SERVER/TOKEN 大写键
    return cp


def _write_ini(cp: configparser.ConfigParser) -> None:
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        cp.write(f)
    os.chmod(CFG_PATH, 0o600)


def _read_ini() -> configparser.ConfigParser:
    """读多 profile 配置；旧平铺格式（无节头）自动迁移为 [default] 并回写。"""
    cp = _new_cp()
    if not os.path.isfile(CFG_PATH):
        return cp
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return cp
    try:
        cp.read_string(text)
    except configparser.MissingSectionHeaderError:
        cp = _new_cp()  # 旧平铺格式 → 迁移进 [default]
        flat = {}
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            flat[k.strip().upper()] = v.strip()
        cp.add_section("default")
        server = flat.get("SERVER", "")
        if server:
            cp.set("default", "SERVER", SERVER_MIGRATIONS.get(server, server))
        if flat.get("TOKEN"):
            cp.set("default", "TOKEN", flat["TOKEN"])
        _write_ini(cp)
        return cp
    except configparser.Error:
        return _new_cp()
    changed = False
    for name in cp.sections():  # 各节历史默认地址统一迁移
        old = cp.get(name, "SERVER", fallback="")
        if old in SERVER_MIGRATIONS:
            cp.set(name, "SERVER", SERVER_MIGRATIONS[old])
            changed = True
    if changed:
        _write_ini(cp)
    return cp


def load_cfg(profile: str = "") -> dict:
    profile = (profile or os.environ.get("TEAM_AGENT_PROFILE", "")
               or "default")
    cfg = {
        "profile": profile,
        "server": os.environ.get("TEAM_AGENT_SERVER", ""),
        "token": os.environ.get("TEAM_AGENT_TOKEN", ""),
    }
    cp = _read_ini()
    if cp.has_section(profile):
        if not cfg["server"]:
            cfg["server"] = cp.get(profile, "SERVER", fallback="")
        if not cfg["token"]:
            cfg["token"] = cp.get(profile, "TOKEN", fallback="")
    return cfg


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def req(method: str, cfg: dict, path: str, body=None):
    url = cfg["server"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + cfg["token"])
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60, context=_ssl_ctx(cfg["server"])) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"detail": raw[:300] or str(e)}
        return e.code, payload


def fail(code: int, status: int, payload) -> None:
    out({"error": True, "http": status, "detail": payload})
    sys.exit(code)


def req_bytes(cfg: dict, path: str):
    """GET 二进制内容，返回 (status, bytes)。"""
    url = cfg["server"].rstrip("/") + path
    r = urllib.request.Request(url, method="GET")
    r.add_header("Authorization", "Bearer " + cfg["token"])
    try:
        with urllib.request.urlopen(r, timeout=120, context=_ssl_ctx(cfg["server"])) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def need_cfg(cfg: dict) -> None:
    if not cfg["server"] or not cfg["token"]:
        out({"error": True, "detail": "CONFIG_MISSING",
             "profile": cfg["profile"]})
        sys.exit(4)


# ---- 命令 ----

def cmd_config(args, cfg):
    profile = cfg["profile"]
    if args.set_token:
        cp = _read_ini()
        if not cp.has_section(profile):
            cp.add_section(profile)
        server = (args.server
                  or cp.get(profile, "SERVER", fallback="")
                  or DEFAULT_SERVER)
        server = SERVER_MIGRATIONS.get(server, server)
        cp.set(profile, "SERVER", server)
        cp.set(profile, "TOKEN", args.set_token)
        _write_ini(cp)
        out({"saved": True, "profile": profile, "server": server,
             "path": CFG_PATH})
        return
    out({
        "configured": bool(cfg["server"] and cfg["token"]),
        "profile": profile,
        "server": cfg["server"] or None,
        "path": CFG_PATH,
    })


def cmd_profiles(args, cfg):
    cp = _read_ini()
    items = []
    for name in cp.sections():
        tok = cp.get(name, "TOKEN", fallback="")
        items.append({
            "name": name,
            "server": cp.get(name, "SERVER", fallback="") or None,
            "token": (tok[:6] + "…") if tok else None,
            "active": name == cfg["profile"],
        })
    out({"profiles": items, "active": cfg["profile"], "path": CFG_PATH})


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return (0,)


def cmd_version(args, cfg):
    server = cfg["server"] or DEFAULT_SERVER
    result = {"client": __version__, "profile": cfg["profile"],
              "server": None}
    try:
        with urllib.request.urlopen(server.rstrip("/") + "/health",
                                    timeout=10,
                                    context=_ssl_ctx(server)) as resp:
            health = json.loads(resp.read().decode("utf-8", "replace"))
        minv = health.get("min_client_version") or ""
        result["server"] = {
            "url": server,
            "version": health.get("version"),
            "min_client_version": minv or None,
        }
        result["upgrade_needed"] = bool(
            minv and _ver_tuple(__version__) < _ver_tuple(minv))
        if result["upgrade_needed"]:
            result["hint"] = (f"客户端 {__version__} 低于服务端要求 "
                              f"{minv}，请更新 team-agent-relay 技能")
    except Exception as e:  # 服务端不可达不阻塞版本查询
        result["detail"] = f"服务端不可达: {e}"
    out(result)


def _submit(cfg, description, targets, urgent, resume_from, force):
    body = {
        "description": description,
        "targets": [t.strip() for t in targets.split(",") if t.strip()],
        "priority": "urgent" if urgent else "normal",
        "force": force,
    }
    if resume_from is not None:
        body["resume_from"] = resume_from
    status, payload = req("POST", cfg, "/tasks", body)
    if status == 202:
        out(payload)
        return payload["task_id"]
    fail(2 if status == 409 else 1, status, payload)


def cmd_submit(args, cfg):
    _submit(cfg, args.description, args.targets, args.urgent,
            args.resume, args.force)


def cmd_wait(args, cfg):
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        status, payload = req("GET", cfg, f"/tasks/{args.id}")
        if status == 401:
            fail(3, status, payload)
        last = payload
        if payload.get("status") in TERMINAL:
            out(payload)
            return
        time.sleep(1.5)
    out({"error": True, "detail": "wait timeout", "last": last})
    sys.exit(1)


def cmd_run(args, cfg):
    tid = _submit(cfg, args.description, args.targets, args.urgent,
                  args.resume, args.force)
    out({"submitted": tid})
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        status, payload = req("GET", cfg, f"/tasks/{tid}")
        if status == 401:
            fail(3, status, payload)
        last = payload
        if payload.get("status") in TERMINAL:
            out(payload)
            return
        time.sleep(1.5)
    out({"error": True, "detail": "wait timeout", "last": last})
    sys.exit(1)


def cmd_status(args, cfg):
    status, payload = req("GET", cfg, f"/tasks/{args.id}")
    if status == 401:
        fail(3, status, payload)
    if status == 404:
        fail(1, status, payload)
    out(payload)


def cmd_tasks(args, cfg):
    path = "/tasks"
    q = []
    if args.status:
        q.append(f"status={args.status}")
    q.append(f"limit={args.limit}")
    status, payload = req("GET", cfg, path + "?" + "&".join(q))
    if status == 401:
        fail(3, status, payload)
    out(payload)


def cmd_stream(args, cfg):
    r = urllib.request.Request(cfg["server"].rstrip("/") + f"/tasks/{args.id}/stream")
    r.add_header("Authorization", "Bearer " + cfg["token"])
    deadline = time.time() + args.timeout
    try:
        resp = urllib.request.urlopen(r, timeout=60, context=_ssl_ctx(cfg["server"]))
    except urllib.error.HTTPError as e:
        fail(3 if e.code == 401 else 1, e.code, {"detail": str(e)})
    with resp:
        for raw in resp:
            if time.time() > deadline:
                out({"error": True, "detail": "stream timeout"})
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:])
            except ValueError:
                continue
            out(ev)
            if ev.get("t") == "status" and ev.get("s") in TERMINAL:
                return


def cmd_diff(args, cfg):
    status, payload = req("GET", cfg, f"/tasks/{args.id}/diff")
    if status == 401:
        fail(3, status, payload)
    out(payload)


def cmd_upload(args, cfg):
    if not os.path.isfile(args.local):
        out({"error": True, "detail": f"本地文件不存在: {args.local}"})
        sys.exit(1)
    size = os.path.getsize(args.local)
    if size > MAX_FILE_BYTES:
        out({"error": True, "detail": f"文件大小 {size} 字节超过 1MB 上限"})
        sys.exit(1)
    with open(args.local, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    status, payload = req("POST", cfg, "/files",
                          {"path": args.path, "content_b64": b64})
    if status == 401:
        fail(3, status, payload)
    if status == 201:
        out(payload)
        return
    fail(1, status, payload)


def cmd_download(args, cfg):
    status, data = req_bytes(cfg, "/files?path=" + urllib.parse.quote(args.path))
    if status == 401:
        fail(3, status, {"detail": "invalid token"})
    if status != 200:
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
        except ValueError:
            payload = {"detail": data[:300].decode("utf-8", "replace")}
        fail(1, status, payload)
    local = args.local or os.path.basename(args.path.rstrip("/")) or "download"
    os.makedirs(os.path.dirname(os.path.abspath(local)), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)
    out({"ok": True, "saved": local, "size": len(data)})


def cmd_cancel(args, cfg):
    status, payload = req("POST", cfg, f"/tasks/{args.id}/cancel")
    if status == 401:
        fail(3, status, payload)
    out(payload)


def cmd_confirm(args, cfg):
    status, payload = req("POST", cfg, f"/tasks/{args.id}/confirm",
                          {"outcome": args.outcome})
    if status == 401:
        fail(3, status, payload)
    out(payload)


def main() -> None:
    ap = argparse.ArgumentParser(prog="relay", description="团队中转服务客户端")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default="",
                        help="配置 profile 名（缺省 default；env TEAM_AGENT_PROFILE）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("config", parents=[common])
    p.add_argument("set_token", nargs="?", default="", help="写入 token")
    p.add_argument("--server", default="")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("profiles", parents=[common],
                       help="列出全部 profile（token 打码）")
    p.set_defaults(fn=cmd_profiles)

    p = sub.add_parser("version", parents=[common],
                       help="客户端/服务端版本对照")
    p.set_defaults(fn=cmd_version)

    def add_task_args(p, waitable=False):
        p.add_argument("-t", "--targets", default="",
                       help="逗号分隔，如 shared/reports/9月")
        p.add_argument("--urgent", action="store_true")
        p.add_argument("--resume", type=int, default=None)
        p.add_argument("--force", action="store_true")
        if waitable:
            p.add_argument("--timeout", type=int, default=1800)

    p = sub.add_parser("run", parents=[common], help="提交并等待终态（一步到位，最常用）")
    p.add_argument("description")
    add_task_args(p, waitable=True)
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("submit", parents=[common], help="仅提交，返回 task_id")
    p.add_argument("description")
    add_task_args(p)
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("wait", parents=[common])
    p.add_argument("id", type=int)
    p.add_argument("--timeout", type=int, default=1800)
    p.set_defaults(fn=cmd_wait)

    p = sub.add_parser("status", parents=[common])
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("tasks", parents=[common])
    p.add_argument("--status", default="")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_tasks)

    p = sub.add_parser("stream", parents=[common], help="SSE 实时流，逐行 JSON 到终态")
    p.add_argument("id", type=int)
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(fn=cmd_stream)

    p = sub.add_parser("diff", parents=[common])
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("upload", parents=[common], help="上传本地文件到共享区（单文件 ≤1MB）")
    p.add_argument("local", help="本地文件路径")
    p.add_argument("path", help="共享区相对路径，如 data/9月.xlsx")
    p.set_defaults(fn=cmd_upload)

    p = sub.add_parser("download", parents=[common], help="从共享区下载文件（单文件 ≤1MB）")
    p.add_argument("path", help="共享区相对路径")
    p.add_argument("local", nargs="?", default="", help="保存到本地路径（默认文件名）")
    p.set_defaults(fn=cmd_download)

    p = sub.add_parser("cancel", parents=[common])
    p.add_argument("id", type=int)
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("confirm", parents=[common])
    p.add_argument("id", type=int)
    p.add_argument("--outcome", choices=["done", "conflict"], default="done")
    p.set_defaults(fn=cmd_confirm)

    args = ap.parse_args()
    cfg = load_cfg(args.profile)
    if args.cmd not in ("config", "profiles", "version"):
        need_cfg(cfg)
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
