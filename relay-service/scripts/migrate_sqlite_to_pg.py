#!/usr/bin/env python3
"""SQLite → PostgreSQL 一次性数据迁移（users + tasks，保留任务 id 与序列值）。

用法:
  python migrate_sqlite_to_pg.py <sqlite_path> <pg_url> [--force]

- 目标库表结构自动创建（与 app.db 同一 schema）
- 目标库已有数据时默认拒绝；--force 清空后重迁
- 迁移后核对两库行数，不一致则退出码 1
"""
from __future__ import annotations

import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import psycopg2  # noqa: E402

from app.db import DB  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    sqlite_path, pg_url = args
    if not os.path.isfile(sqlite_path):
        print(f"FAIL: sqlite 文件不存在: {sqlite_path}")
        return 1

    db = DB(pg_url)  # 自动建表
    db.close()

    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row
    pconn = psycopg2.connect(pg_url, connect_timeout=10)
    pcur = pconn.cursor()

    pcur.execute("SELECT count(*) FROM users")
    n_users = pcur.fetchone()[0]
    pcur.execute("SELECT count(*) FROM tasks")
    n_tasks = pcur.fetchone()[0]
    if (n_users or n_tasks) and not force:
        print(f"FAIL: 目标库非空（users={n_users} tasks={n_tasks}），确认要清空重迁请加 --force")
        return 1
    if n_users or n_tasks:
        pcur.execute("TRUNCATE tasks RESTART IDENTITY")
        pcur.execute("TRUNCATE users")
        pconn.commit()
        print(f"已清空目标库（原 users={n_users} tasks={n_tasks}）")

    for r in sconn.execute("SELECT token, name, created_at FROM users"):
        pcur.execute("INSERT INTO users(token, name, created_at) VALUES(%s,%s,%s)"
                     " ON CONFLICT (token) DO NOTHING",
                     (r["token"], r["name"], r["created_at"]))
    users_migrated = sconn.execute("SELECT count(*) FROM users").fetchone()[0]

    cols = [r[1] for r in sconn.execute("PRAGMA table_info(tasks)")]
    collist = ",".join('"user"' if c == "user" else c for c in cols)
    ph = ",".join(["%s"] * len(cols))
    tasks_migrated = 0
    for r in sconn.execute(f"SELECT {collist} FROM tasks ORDER BY id"):
        pcur.execute(f"INSERT INTO tasks({collist}) VALUES({ph})", tuple(r[c] for c in cols))
        tasks_migrated += 1
    pcur.execute("SELECT setval(pg_get_serial_sequence('tasks','id'),"
                 " COALESCE((SELECT MAX(id) FROM tasks), 1))")
    pconn.commit()

    pcur.execute("SELECT count(*) FROM users")
    pg_users = pcur.fetchone()[0]
    pcur.execute("SELECT count(*) FROM tasks")
    pg_tasks = pcur.fetchone()[0]
    pcur.execute("SELECT count(*) FROM tasks t JOIN users u ON t.\"user\" = u.name")
    orphan = tasks_migrated - pcur.fetchone()[0]

    print(f"users: sqlite={users_migrated} pg={pg_users}")
    print(f"tasks: sqlite={tasks_migrated} pg={pg_tasks}")
    if pg_users != users_migrated or pg_tasks != tasks_migrated:
        print("FAIL: 行数不一致")
        return 1
    if orphan:
        print(f"WARN: {orphan} 个任务的 user 不在 users 表（历史已删成员），不影响迁移")
    print("OK: 迁移完成，序列已对齐")
    pconn.close()
    sconn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
