from __future__ import annotations

import json
import sqlite3
import threading
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  token TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user TEXT NOT NULL,
  description TEXT NOT NULL,
  project TEXT NOT NULL DEFAULT '',
  targets TEXT NOT NULL DEFAULT '[]',
  priority TEXT NOT NULL DEFAULT 'normal',
  status TEXT NOT NULL DEFAULT 'queued',
  session_id TEXT NOT NULL DEFAULT '',
  workdir TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  changed_files TEXT NOT NULL DEFAULT '[]',
  conflicts TEXT NOT NULL DEFAULT '[]',
  tokens INTEGER NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,
  resume_from INTEGER,
  blocked_cmd TEXT NOT NULL DEFAULT '',
  resume_hint TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  started_at REAL,
  finished_at REAL
);
"""

TASK_FIELDS = {
    "user", "description", "project", "targets", "priority", "status",
    "session_id", "workdir", "result", "error", "changed_files",
    "conflicts", "tokens", "cost", "resume_from", "blocked_cmd", "resume_hint",
    "started_at", "finished_at",
}


def _row_to_task(row: sqlite3.Row) -> dict:
    t = dict(row)
    for k in ("targets", "changed_files", "conflicts"):
        try:
            t[k] = json.loads(t[k])
        except (TypeError, ValueError):
            t[k] = []
    return t


class DB:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tasks)")}
            for name, decl in (("blocked_cmd", "TEXT NOT NULL DEFAULT ''"),
                               ("resume_hint", "TEXT NOT NULL DEFAULT ''")):
                if name not in cols:
                    self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {name} {decl}")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _q(self, sql: str, args: tuple = (), one: bool = False):
        with self._lock:
            cur = self._conn.execute(sql, args)
            rows = cur.fetchall()
            self._conn.commit()
            return (rows[0] if rows else None) if one else rows

    # ---- users ----

    def create_user(self, name: str, token: str) -> None:
        self._q("INSERT INTO users(token, name, created_at) VALUES(?, ?, ?)",
                (token, name, time.time()))

    def user_by_token(self, token: str) -> dict:
        row = self._q("SELECT * FROM users WHERE token = ?", (token,), one=True)
        return dict(row) if row else {}

    def user_by_name(self, name: str) -> dict:
        row = self._q("SELECT * FROM users WHERE name = ?", (name,), one=True)
        return dict(row) if row else {}

    def delete_user(self, name: str) -> None:
        self._q("DELETE FROM users WHERE name = ?", (name,))

    def list_users(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT token, name, created_at FROM users ORDER BY name")]

    # ---- tasks ----

    def create_task(self, *, user: str, description: str, project: str = "",
                    targets: list[str] | None = None, priority: str = "normal",
                    resume_from: int | None = None) -> int:
        row = self._q(
            "INSERT INTO tasks(user, description, project, targets, priority, resume_from, created_at)"
            " VALUES(?, ?, ?, ?, ?, ?, ?)",
            (user, description, project, json.dumps(targets or [], ensure_ascii=False),
             priority, resume_from, time.time()),
        )
        cur = self._conn.execute("SELECT last_insert_rowid() AS id")
        return cur.fetchone()["id"]

    def task(self, task_id: int) -> dict | None:
        row = self._q("SELECT * FROM tasks WHERE id = ?", (task_id,), one=True)
        return _row_to_task(row) if row else None

    def set(self, task_id: int, **fields) -> None:
        fields = {k: v for k, v in fields.items() if k in TASK_FIELDS}
        if not fields:
            return
        if "targets" in fields:
            fields["targets"] = json.dumps(fields["targets"], ensure_ascii=False)
        if "changed_files" in fields and isinstance(fields["changed_files"], list):
            fields["changed_files"] = json.dumps(fields["changed_files"], ensure_ascii=False)
        if "conflicts" in fields and isinstance(fields["conflicts"], list):
            fields["conflicts"] = json.dumps(fields["conflicts"], ensure_ascii=False)
        sql = "UPDATE tasks SET {} WHERE id = ?".format(
            ", ".join(f"{k} = ?" for k in fields))
        self._q(sql, (*fields.values(), task_id))

    def list_tasks(self, limit: int = 50, status: str | None = None) -> list[dict]:
        if status:
            rows = self._q("SELECT * FROM tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
                           (status, limit))
        else:
            rows = self._q("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
        return [_row_to_task(r) for r in rows]

    def active_tasks(self) -> list[dict]:
        rows = self._q("SELECT * FROM tasks WHERE status IN ('queued', 'running', 'pending_approval') ORDER BY id")
        return [_row_to_task(r) for r in rows]

    def tasks_with_file(self, rel_file: str, exclude: int) -> list[dict]:
        rows = self._q("SELECT * FROM tasks WHERE id != ? AND changed_files != '[]'", (exclude,))
        out = []
        for r in rows:
            t = _row_to_task(r)
            if rel_file in t["changed_files"]:
                out.append(t)
        return out

    def status_counts(self) -> dict[str, int]:
        rows = self._q("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    def period_stats(self, since: float) -> dict:
        rows = self._q("SELECT status, COUNT(*) AS c FROM tasks WHERE created_at >= ? GROUP BY status",
                       (since,))
        counts = {r["status"]: r["c"] for r in rows}
        total = sum(counts.values())
        return {"submitted": total,
                "done_rate": round(counts.get("done", 0) / total, 3) if total else 0.0}

    def recent_task_ids(self, minutes: int = 60, limit: int = 20) -> list[int]:
        rows = self._q("SELECT id FROM tasks WHERE created_at >= ? ORDER BY id DESC LIMIT ?",
                       (time.time() - minutes * 60, limit))
        return [r["id"] for r in rows]

    def stale_tasks(self, states: list[str], cutoff: float) -> list[dict]:
        """created_at 早于 cutoff 且仍处于指定状态的任务（用于超时清扫）。"""
        ph = ",".join("?" * len(states))
        rows = self._q(f"SELECT * FROM tasks WHERE status IN ({ph}) AND created_at < ? ORDER BY created_at",
                       (*states, cutoff))
        return [_row_to_task(r) for r in rows]

    def mark_stale_done(self, task_id: int, marker: str) -> bool:
        """原子地把仍处于 review/pending_approval 的任务置为 done。返回是否更新。"""
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='done', error=?, finished_at=COALESCE(finished_at, ?)"
                " WHERE id=? AND status IN ('review','pending_approval')",
                (marker, now, task_id))
            self._conn.commit()
            return cur.rowcount > 0

    def report(self, days: int = 7) -> dict:
        rows = [dict(r) for r in self._q(
            "SELECT user, status, tokens, created_at, blocked_cmd FROM tasks WHERE created_at >= ?",
            (time.time() - days * 86400,))]
        by_day: dict[str, dict[str, int]] = {}
        by_user: dict[str, dict] = {}
        conflicts = blocked = 0
        for r in rows:
            day = time.strftime("%Y-%m-%d", time.localtime(r["created_at"]))
            d = by_day.setdefault(day, {"submitted": 0, "done": 0, "failed": 0,
                                        "conflict": 0, "cancelled": 0, "pending_approval": 0})
            d["submitted"] += 1
            if r["status"] in d:
                d[r["status"]] += 1
            u = by_user.setdefault(r["user"],
                                   {"user": r["user"], "tasks": 0, "done": 0, "tokens": 0})
            u["tasks"] += 1
            u["tokens"] += r["tokens"] or 0
            if r["status"] == "done":
                u["done"] += 1
            if r["status"] == "conflict":
                conflicts += 1
            if r["blocked_cmd"]:
                blocked += 1
        for u in by_user.values():
            u["done_rate"] = round(u["done"] / u["tasks"], 3) if u["tasks"] else 0.0
        return {
            "days": days,
            "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
            "by_user": sorted(by_user.values(), key=lambda x: x["user"]),
            "conflicts": conflicts,
            "blocked": blocked,
        }
