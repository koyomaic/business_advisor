from __future__ import annotations

import hashlib
import json
import os
import shutil
import time

SKIP_DIRS = {".baseline", ".result", "home", "data", ".git", "node_modules", "__pycache__"}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snap(root: str, base: str) -> dict[str, tuple[int, int, str]]:
    """快照 root 下所有文件：{工作区相对路径: (mtime_ns, size, sha256)}。"""
    out: dict[str, tuple[int, int, str]] = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, base)
            try:
                st = os.stat(p)
                out[rel] = (st.st_mtime_ns, st.st_size, _sha(p))
            except OSError:
                continue
    return out


class Workspace:
    """每任务独立工作目录 + 共享区基线快照 + 完成扫描 + 冲突备份。"""

    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db

    def resolve(self, target: str) -> str:
        t = target.strip().strip("/")
        if t.startswith("/"):
            return t
        return os.path.join(self.cfg.workspace_root, t)

    def prepare(self, task: dict, reuse_workdir: str | None = None) -> str:
        workdir = reuse_workdir or os.path.join(self.cfg.task_root, str(task["id"]))
        os.makedirs(workdir, exist_ok=True)
        os.makedirs(os.path.join(workdir, "home"), exist_ok=True)
        if not reuse_workdir:
            os.makedirs(os.path.join(workdir, "data"), exist_ok=True)
        baseline: dict = {}
        baseline.update(_snap(self.cfg.shared_dir, self.cfg.workspace_root))
        for t in task["targets"]:
            baseline.update(_snap(self.resolve(t), self.cfg.workspace_root))
        with open(os.path.join(workdir, ".baseline.json"), "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False)
        if not task.get("workdir"):
            self.db.set(task["id"], workdir=workdir)
        return workdir

    def scan(self, task: dict) -> dict:
        """任务结束后的变更扫描（事后兜底）。"""
        workdir = task["workdir"]
        with open(os.path.join(workdir, ".baseline.json"), encoding="utf-8") as f:
            baseline = json.load(f)
        cur: dict = {}
        cur.update(_snap(self.cfg.shared_dir, self.cfg.workspace_root))
        for t in task["targets"]:
            cur.update(_snap(self.resolve(t), self.cfg.workspace_root))

        created, modified, deleted = [], [], []
        for rel, meta in cur.items():
            if rel not in baseline:
                created.append(rel)
            elif baseline[rel][2] != meta[2]:  # 仅按内容哈希判定，避免同内容重写的误报
                modified.append(rel)
        for rel in baseline:
            if rel not in cur:
                deleted.append(rel)
        created.sort(); modified.sort(); deleted.sort()

        for rel in created + modified:
            src = os.path.join(self.cfg.workspace_root, rel)
            dst = os.path.join(workdir, ".result", rel)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        all_changed = sorted(set(created) | set(modified) | set(deleted))
        self.db.set(task["id"], changed_files=all_changed)
        return {"created": created, "modified": modified, "deleted": deleted, "all": all_changed}

    def backup_version(self, other_task: dict, rel_file: str) -> str | None:
        """把 other_task 产出的 rel_file 版本备份为 <文件>.bak-<用户>-HHMM，绝不静默覆盖。"""
        src = os.path.join(other_task["workdir"], ".result", rel_file)
        if not os.path.isfile(src):
            return None
        dst_file = os.path.join(self.cfg.workspace_root, rel_file)
        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
        hm = time.strftime("%H%M", time.localtime(other_task["finished_at"] or time.time()))
        dst = f"{dst_file}.bak-{other_task['user']}-{hm}"
        shutil.copy2(src, dst)
        return dst
