from __future__ import annotations

import json
import os
import re
import shutil

SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,49}$")


def slug_valid(name: str) -> bool:
    return bool(SKILL_NAME_RE.match(name or ""))


def strip_jsonc(text: str) -> str:
    """去掉 // 与 /* */ 注释（感知字符串，不伤 URL），并清理 } ] 前的尾逗号。"""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = esc = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    s = "".join(out)
    return re.sub(r",(\s*[}\]])", r"\1", s)


def load_jsonc(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.loads(strip_jsonc(f.read()))
    except (OSError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def mcp_entry_from_file(name: str, obj: object) -> dict:
    """shared/mcp/<name>.json 的内容：条目本身（{"type":"local",...}）
    或 {name: 条目} / {任意单键: 条目} 包装形式。"""
    if not isinstance(obj, dict):
        return {}
    if set(obj) == {name}:
        v = obj[name]
        return v if isinstance(v, dict) else {}
    if len(obj) == 1:
        v = next(iter(obj.values()))
        return v if isinstance(v, dict) else {}
    return obj


def load_shared_mcp(shared_dir: str) -> dict:
    """读取 shared/mcp/*.json → {server_name: mcp条目}。"""
    root = os.path.join(shared_dir, "mcp")
    out: dict = {}
    if not os.path.isdir(root):
        return out
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        try:
            with open(os.path.join(root, fn), encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, ValueError):
            continue
        entry = mcp_entry_from_file(name, obj)
        if entry:
            out[name] = entry
    return out


def shared_memory_text(shared_dir: str) -> str | None:
    """拼接 shared/memory/*.md；为空返回 None。"""
    root = os.path.join(shared_dir, "memory")
    if not os.path.isdir(root):
        return None
    parts: list[str] = []
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(root, fn)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                body = f.read().strip()
        except OSError:
            continue
        if body:
            parts.append(f"## [{fn}]\n{body}")
    if not parts:
        return None
    return ("# 团队共享记忆（来自 shared/memory/，全员 agent 自动加载，上传即生效）\n\n"
            + "\n\n".join(parts))


def _sync_symlink(dst: str, src: str) -> None:
    if os.path.islink(dst):
        if os.readlink(dst) == src:
            return
        os.unlink(dst)
    elif os.path.exists(dst):
        if os.path.isdir(dst) and not os.path.islink(dst):
            shutil.rmtree(dst, ignore_errors=True)
        try:
            os.unlink(dst)
        except OSError:
            pass
    if os.path.exists(src):
        os.symlink(src, dst)


def _symlink_dws_seed(workdir: str, shared_dir: str) -> None:
    """把任务 HOME 的 dws 凭证目录软链到共享种子，所有会话共用同一份活凭证。

    单一登录态 lineage：dws 刷新 token 会轮换 refresh token，软链让轮换原地
    发生在种子上（服务器 dws-renew 定时器从种子续期并回写种子），杜绝复制
    副本分叉后互相失效、被迫人工浏览器重新授权。

    - 种子不存在（shared/secrets/dws-cli-seed/dws-cli/）则静默跳过，不影响任务
    - dst 已存在（旧复制模式的真实目录或旧软链）则删除后重建软链；
      任务目录是临时的，无需备份
    """
    seed = os.path.join(shared_dir, "secrets", "dws-cli-seed", "dws-cli")
    if not os.path.isdir(seed):
        return
    share = os.path.join(workdir, "home", ".local", "share")
    dst = os.path.join(share, "dws-cli")
    try:
        os.makedirs(share, exist_ok=True)
        if os.path.islink(dst) or os.path.exists(dst):
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            else:
                os.unlink(dst)
        os.symlink(os.path.abspath(seed), dst)
    except OSError:
        pass


def prepare_run(workdir: str, cfg) -> str:
    """为本次运行生成隔离的 XDG 配置目录（共享知识注入点），返回新 XDG_CONFIG_HOME。

    - opencode.json = 全局基线配置 + skills.paths 追加 shared/skills + mcp 合并 shared/mcp
    - 全局配置目录里的 node_modules/package*.json 等以符号链接复用（不重装依赖）
    - shared/memory/*.md 拼成 AGENTS.md 写入 workdir 与 home 全局位（双保险加载）
    - dws 凭证种子软链进任务 HOME（全会话共用一份活凭证；种子缺失则跳过）
    """
    base_xdg = cfg.xdg_config_home or os.path.expanduser("~/.config")
    base_pkg = os.path.join(base_xdg, "opencode")
    xdg = os.path.join(workdir, ".xdg")
    pkg = os.path.join(xdg, "opencode")
    os.makedirs(pkg, exist_ok=True)

    base_cfg: dict = {}
    for fn in ("opencode.json", "opencode.jsonc"):
        p = os.path.join(base_pkg, fn)
        if os.path.isfile(p):
            base_cfg = load_jsonc(p)
            break

    # 剔除本地专用 provider（如本地才用的模型），但默认模型所在的 provider 永不剔除
    exclude = {str(p).strip() for p in getattr(cfg, "relay_exclude_providers", []) if str(p).strip()}
    default_model = str(base_cfg.get("model") or "")
    if "/" in default_model:
        exclude.discard(default_model.split("/", 1)[0])
    if exclude:
        provs = base_cfg.get("provider")
        if isinstance(provs, dict):
            for name in list(provs.keys()):
                if name in exclude:
                    del provs[name]

    skills = dict(base_cfg.get("skills") or {})
    paths = skills.get("paths")
    if not isinstance(paths, list):
        paths = []
    skills_root = os.path.join(cfg.shared_dir, "skills")
    if skills_root not in paths:
        paths.append(skills_root)
    skills["paths"] = paths
    base_cfg["skills"] = skills

    mcp = dict(base_cfg.get("mcp") or {})
    mcp.update(load_shared_mcp(cfg.shared_dir))
    if mcp:
        base_cfg["mcp"] = mcp

    with open(os.path.join(pkg, "opencode.json"), "w", encoding="utf-8") as f:
        json.dump(base_cfg, f, ensure_ascii=False, indent=2)

    if os.path.isdir(base_pkg):
        for entry in os.listdir(base_pkg):
            if entry in ("opencode.json", "opencode.jsonc"):
                continue
            _sync_symlink(os.path.join(pkg, entry), os.path.join(base_pkg, entry))

    _symlink_dws_seed(workdir, cfg.shared_dir)

    mem = shared_memory_text(cfg.shared_dir)
    if mem:
        for p in (os.path.join(workdir, "AGENTS.md"),
                  os.path.join(workdir, "home", ".config", "opencode", "AGENTS.md")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(mem + "\n")
    return xdg
