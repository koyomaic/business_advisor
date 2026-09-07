from __future__ import annotations

import os
import time


class AuditLog:
    """任务级审计日志（谁/何时/什么事件/结果），追加写入。"""

    def __init__(self, path: str = ""):
        self._f = None
        self._path = path
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._f = open(path, "a", encoding="utf-8")

    def line(self, task_id: int, user: str, event: str, detail: str = "") -> None:
        if not self._f:
            return
        self._f.write(f"{time.time():.3f}\ttask={task_id}\tuser={user}\t{event}\t{detail}\n")
        self._f.flush()

    def tail(self, n: int = 10) -> list[str]:
        if not self._path:
            return []
        with open(self._path, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f if ln.strip()]
        return lines[-n:]

    def close(self) -> None:
        if self._f:
            self._f.close()
