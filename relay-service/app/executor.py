from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import time
from dataclasses import dataclass, field

from . import shared_knowledge


@dataclass
class AgentResult:
    session_id: str = ""
    text: str = ""
    tokens: int = 0
    cost: float = 0.0
    error: str | None = None
    raw_tail: str = field(default="")
    blocked_cmd: str = ""


def _parse_opencode(line: str) -> dict | None:
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    part = ev.get("part") or {}
    sid = ev.get("sessionID") or part.get("sessionID") or ""
    out: dict = {}
    if sid:
        out["session_id"] = sid
    t = ev.get("type")
    if t == "text" and part.get("text"):
        out["text"] = part["text"]
        out["agent_event"] = {"kind": "text", "text": part["text"][:2000]}
    elif t == "tool_use":
        out["agent_event"] = {
            "kind": "tool",
            "tool": part.get("tool", ""),
            "title": part.get("title", ""),
        }
        if part.get("tool") == "bash":
            state = part.get("state") or {}
            inp = part.get("input") or state.get("input") or {}
            cmd = inp.get("command") or inp.get("cmd")
            if isinstance(cmd, str) and cmd.strip():
                out["tool_cmd"] = cmd
    elif t == "step_finish":
        tok = (part.get("tokens") or {}).get("total")
        if tok:
            out["tokens"] = int(tok)
        if part.get("cost"):
            out["cost"] = float(part["cost"])
    return out or None


def _parse_claude(line: str) -> dict | None:
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    out: dict = {}
    et = ev.get("type")
    if et == "system" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    elif et == "assistant":
        for block in (ev.get("message") or {}).get("content", []):
            if block.get("type") == "text" and block.get("text"):
                out["text"] = out.get("text", "") + block["text"]
                out["agent_event"] = {"kind": "text", "text": block["text"][:2000]}
            elif block.get("type") == "tool_use":
                out["agent_event"] = {"kind": "tool", "tool": block.get("name", "")}
                if str(block.get("name", "")).lower() == "bash":
                    inp = block.get("input") or {}
                    cmd = inp.get("command") or inp.get("cmd")
                    if isinstance(cmd, str) and cmd.strip():
                        out["tool_cmd"] = cmd
    elif et == "result":
        out["text"] = out.get("text", "") + (ev.get("result") or "")
        if ev.get("total_cost_usd"):
            out["cost"] = float(ev["total_cost_usd"])
        if ev.get("session_id"):
            out["session_id"] = ev["session_id"]
    return out or None


class Executor:
    """以无头方式驱动 agent CLI（opencode / claude），逐行解析 JSON 事件流。"""

    def __init__(self, cfg):
        self.cfg = cfg

    def _bin(self) -> str:
        if self.cfg.agent_bin:
            return self.cfg.agent_bin
        return "opencode" if self.cfg.engine == "opencode" else "claude"

    def build_cmd(self, workdir: str, prompt: str, resume_session: str | None) -> list[str]:
        if self.cfg.engine == "opencode":
            cmd = [self._bin(), "run", "--format", "json", "--auto", "--dir", workdir]
            if self.cfg.model:
                cmd += ["-m", self.cfg.model]
            if resume_session:
                cmd += ["-s", resume_session]
            cmd.append(prompt)
            return cmd
        cmd = [self._bin(), "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if resume_session:
            cmd += ["--resume", resume_session]
        return cmd

    def build_env(self, workdir: str, xdg_config: str | None = None) -> dict:
        env = dict(os.environ)
        env["HOME"] = os.path.join(workdir, "home")
        env["XDG_CONFIG_HOME"] = (xdg_config or self.cfg.xdg_config_home
                                  or os.path.expanduser("~/.config"))
        env["XDG_DATA_HOME"] = os.path.join(workdir, "data")
        return env

    async def run(self, *, task_id: int, workdir: str, prompt: str,
                  resume_session: str | None, data_dir: str | None,
                  cancel: asyncio.Event, publish,
                  exempt_cmd: str | None = None) -> AgentResult:
        cmd = self.build_cmd(workdir, prompt, resume_session)
        xdg = shared_knowledge.prepare_run(workdir, self.cfg)
        env = self.build_env(workdir, xdg)
        if data_dir:
            env["XDG_DATA_HOME"] = data_dir
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env=env,
            start_new_session=True,
        )
        parse = _parse_opencode if self.cfg.engine == "opencode" else _parse_claude
        res = AgentResult()
        deadline = time.monotonic() + self.cfg.task_timeout
        stderr_task = asyncio.create_task(proc.stderr.read())
        raw_tail: list[str] = []
        try:
            while True:
                if cancel.is_set():
                    self._kill(proc)
                    res.error = "cancelled"
                    return res
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._kill(proc)
                    res.error = f"timeout after {self.cfg.task_timeout:.0f}s"
                    return res
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=min(1.0, remaining))
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if not text:
                    continue
                raw_tail.append(text)
                if len(raw_tail) > 20:
                    raw_tail.pop(0)
                parsed = parse(text)
                if not parsed:
                    continue
                if parsed.get("session_id"):
                    res.session_id = parsed["session_id"]
                res.text += parsed.get("text", "")
                res.tokens += parsed.get("tokens", 0)
                res.cost += parsed.get("cost", 0.0)
                if parsed.get("agent_event"):
                    publish(task_id, t="agent", **parsed["agent_event"])
                cmd = parsed.get("tool_cmd")
                if cmd and self._is_blocked(cmd, workdir) and not self._exempt(cmd, exempt_cmd):
                    self._kill(proc)
                    res.blocked_cmd = cmd
                    res.error = f"blocked: {cmd[:200]}"
                    return res
        finally:
            if proc.returncode is None:
                self._kill(proc)
            await proc.wait()
            err = (await stderr_task).decode("utf-8", "replace")
        res.raw_tail = "\n".join(raw_tail[-5:])
        if res.error is None and proc.returncode != 0:
            tail = (err or res.raw_tail)[-800:]
            res.error = f"agent exited with code {proc.returncode}: {tail}"
        return res

    def _is_blocked(self, cmd: str, workdir: str = "") -> str | None:
        low = cmd.lower()
        for p in self.cfg.blocked_patterns:
            if not p:
                continue
            try:
                if re.search(p, low):
                    return p
            except re.error:
                if p.lower() in low:  # 非法正则退化为子串
                    return p
        return self._rm_violation(cmd, workdir)

    # ---- 递归 rm 按路径判断：rm_safe_prefixes 与任务自身 HOME 沙箱内放行，其余拦截 ----

    @staticmethod
    def _rm_targets(segment: str) -> tuple[bool, list[str]]:
        """从命令段中提取 rm 的参数。返回 (是否递归, 目标路径列表)。"""
        m = re.search(r"(?<![\w-])rm\b\s*([^\n;&|]*)", segment)
        if not m:
            return False, []
        recursive, paths = False, []
        for a in m.group(1).split():
            if a == "--recursive":
                recursive = True
            elif a.startswith("--"):
                continue
            elif a.startswith("-") and len(a) > 1:
                if "r" in a[1:].lower():
                    recursive = True
            else:
                paths.append(a)
        return recursive, paths

    @staticmethod
    def _resolve_rm_path(p: str, home: str) -> str:
        """去引号、把开头的 ~/$HOME/${HOME} 展开为任务真实 HOME，再规范化（防 .. 逃逸）。"""
        if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
            p = p[1:-1]
        if home:
            if p in ("~", "$HOME", "${HOME}"):
                p = home
            elif p.startswith("~/"):
                p = home + p[1:]
            elif p.startswith("$HOME/"):
                p = home + p[len("$HOME"):]
            elif p.startswith("${HOME}/"):
                p = home + p[len("${HOME}"):]
        return os.path.normpath(p) if p.startswith("/") else p

    def _rm_path_safe(self, p: str, home: str = "") -> bool:
        p = self._resolve_rm_path(p, home)
        if not p.startswith("/"):  # 相对路径/无法展开的变量：无法验证，拦截
            return False
        for root in self.cfg.rm_safe_prefixes:
            if p == root or p.startswith(root + "/"):
                return True
        if home and (p == home or p.startswith(home + "/")):
            return True  # 任务自身 HOME 沙箱（物理隔离），触不到共享区/系统目录
        return False

    def _rm_violation(self, cmd: str, workdir: str = "") -> str | None:
        home = os.path.join(workdir, "home") if workdir else ""
        for segment in re.split(r"[;&|\n]+", cmd):
            recursive, paths = self._rm_targets(segment)
            if not recursive:
                continue
            for p in paths:
                if not self._rm_path_safe(p, home):
                    return f"recursive rm outside safe dirs: {p}"
        return None

    @staticmethod
    def _exempt(cmd: str, exempt_cmd: str | None) -> bool:
        if not exempt_cmd:
            return False
        c, e = cmd.strip().lower(), exempt_cmd.strip().lower()
        return c == e or c.startswith(e)

    @staticmethod
    def _tree_pids(root_pid: int) -> list[int]:
        """root_pid 及其全部后代（agent 的工具子进程可能自成进程组，须整树杀）。"""
        children: dict[int, list[int]] = {}
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/stat", "rb") as f:
                    data = f.read().decode("ascii", "replace")
                ppid = int(data.rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            children.setdefault(ppid, []).append(int(d))
        out: list[int] = []
        stack = [root_pid]
        while stack:
            p = stack.pop()
            out.append(p)
            stack.extend(children.get(p, []))
        return out

    def _kill(self, proc: asyncio.subprocess.Process) -> None:
        pids = self._tree_pids(proc.pid)
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

        async def _escalate() -> None:
            await asyncio.sleep(5)
            for p in pids:
                try:
                    os.kill(p, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        try:
            asyncio.get_running_loop().create_task(_escalate())
        except RuntimeError:
            pass
