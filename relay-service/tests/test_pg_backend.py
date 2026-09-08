"""PostgreSQL 后端测试：RELAY_TEST_PG_URL 指向真实 PG 服务器（在其上建临时库，测完即删）。

未设置 RELAY_TEST_PG_URL 时整体跳过（部署门禁 -m "not integration and not pg" 也不跑本文件）。
本地执行：
  RELAY_TEST_PG_URL='postgresql://USER:PASS@HOST:5432/postgres' \
    .venv/bin/python -m pytest -q -m pg
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

from app.db import DB, is_pg_url

PG_URL = os.environ.get("RELAY_TEST_PG_URL", "")

pytestmark = pytest.mark.pg


@pytest.fixture(scope="module")
def pg_url() -> str:
    if not PG_URL:
        pytest.skip("RELAY_TEST_PG_URL 未设置")
    import psycopg2
    admin = psycopg2.connect(PG_URL, connect_timeout=10)
    admin.autocommit = True
    dbname = f"relay_test_{uuid.uuid4().hex[:8]}"
    try:
        admin.cursor().execute(f'CREATE DATABASE "{dbname}"')
    except Exception as e:  # 无建库权限等
        admin.close()
        pytest.skip(f"无法创建测试库: {e!r}")
    admin.close()
    url = PG_URL.rsplit("/", 1)[0] + "/" + dbname
    yield url
    admin = psycopg2.connect(PG_URL, connect_timeout=10)
    admin.autocommit = True
    admin.cursor().execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
    admin.close()


@pytest.fixture()
def db(pg_url):
    d = DB(pg_url)
    d._run("TRUNCATE tasks RESTART IDENTITY")
    d._run("TRUNCATE users")
    yield d
    d.close()


def test_is_pg_url():
    assert is_pg_url("postgresql://u:p@h:5432/db")
    assert is_pg_url("postgres://u:p@h/db")
    assert not is_pg_url("/mnt/vol-eltaah12/workspace/relay.db")


def test_schema_created(db):
    rows, _ = db._run("SELECT table_name FROM information_schema.tables"
                      " WHERE table_schema='public' AND table_name IN ('users','tasks')")
    assert {r["table_name"] for r in rows} == {"users", "tasks"}


def test_users_crud(db):
    db.create_user("张三", "tok-zs")
    db.create_user("李四", "tok-ls")
    assert db.user_by_token("tok-zs")["name"] == "张三"
    assert db.user_by_name("李四")["token"] == "tok-ls"
    assert db.user_by_token("nope") == {}
    names = [u["name"] for u in db.list_users()]
    assert names == sorted(names) and set(names) == {"张三", "李四"}
    db.delete_user("李四")
    assert db.user_by_name("李四") == {}


def test_task_lifecycle(db):
    tid = db.create_task(user="王五", description="测试任务：中文/emoji🚀",
                         project="proj", targets=["a.md", "b/c.md"], priority="high")
    assert tid > 0
    t = db.task(tid)
    assert t["user"] == "王五"
    assert t["description"] == "测试任务：中文/emoji🚀"
    assert t["targets"] == ["a.md", "b/c.md"]
    assert t["status"] == "queued" and t["priority"] == "high"
    assert t["resume_from"] is None

    db.set(tid, status="running", started_at=time.time(), session_id="ses-1")
    db.set(tid, status="review", result="完成", tokens=123, cost=0.5,
           changed_files=["a.md"], finished_at=time.time())
    t = db.task(tid)
    assert t["status"] == "review" and t["session_id"] == "ses-1"
    assert t["tokens"] == 123 and abs(t["cost"] - 0.5) < 1e-9
    assert t["changed_files"] == ["a.md"]

    assert [x["id"] for x in db.list_tasks(limit=10)] == [tid]
    assert [x["id"] for x in db.list_tasks(limit=10, status="review")] == [tid]
    assert db.list_tasks(limit=10, status="done") == []
    assert db.status_counts() == {"review": 1}
    stats = db.period_stats(time.time() - 60)
    assert stats["submitted"] == 1 and stats["done_rate"] == 0.0
    assert db.recent_task_ids(minutes=5) == [tid]
    assert db.tasks_with_file("a.md", exclude=tid + 100) and \
           db.tasks_with_file("a.md", exclude=tid) == []


def test_active_and_stale(db):
    t1 = db.create_task(user="u1", description="d1")
    t2 = db.create_task(user="u2", description="d2")
    db.set(t2, status="done", finished_at=time.time())
    assert [t["id"] for t in db.active_tasks()] == [t1]

    db.set(t1, status="review")
    db._run("UPDATE tasks SET created_at=? WHERE id=?", (time.time() - 48 * 3600, t1))
    stale = db.stale_tasks(["review", "pending_approval"], time.time() - 24 * 3600)
    assert [t["id"] for t in stale] == [t1]
    assert db.mark_stale_done(t1, "超时自动done") is True
    assert db.task(t1)["status"] == "done"
    assert db.task(t1)["error"] == "超时自动done"
    assert db.mark_stale_done(t1, "again") is False


def test_report(db):
    t1 = db.create_task(user="甲", description="x")
    db.set(t1, status="done", tokens=10, finished_at=time.time())
    t2 = db.create_task(user="乙", description="y")
    db.set(t2, status="failed", blocked_cmd="rm -rf /")
    r = db.report(days=7)
    assert r["blocked"] == 1
    by_user = {u["user"]: u for u in r["by_user"]}
    assert by_user["甲"]["done"] == 1 and by_user["甲"]["done_rate"] == 1.0
    assert by_user["乙"]["tokens"] == 0
    assert sum(d["submitted"] for d in r["by_day"]) == 2


def test_reconnect_after_conn_close(db):
    db.create_user("重连测试", "tok-re")
    db._conn.close()  # 模拟网络断连/服务端重启
    assert db.user_by_name("重连测试")["token"] == "tok-re"
    tid = db.create_task(user="重连测试", description="断线后写入")
    assert db.task(tid)["description"] == "断线后写入"


def test_concurrent_writes(db):
    import threading
    ids: list[int] = []
    lock = threading.Lock()

    def worker(n: int):
        for i in range(5):
            tid = db.create_task(user=f"并发-{n}", description=f"task {n}-{i}")
            with lock:
                ids.append(tid)

    ths = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert len(set(ids)) == 20
    assert db.status_counts()["queued"] == 20


def test_app_e2e(pg_url, tmp_path):
    """FastAPI 全栈跑在 PG 后端：建成员→token 鉴权→建任务→查询→dashboard 统计。"""
    import httpx
    from app.config import Settings
    from app.main import create_app

    ws = tmp_path / "ws"
    (ws / "shared" / "knowledge").mkdir(parents=True)
    cleaner = DB(pg_url)
    cleaner._run("TRUNCATE tasks RESTART IDENTITY")
    cleaner._run("TRUNCATE users")
    cleaner.close()
    cfg = Settings(
        db_path=pg_url,
        workspace_root=str(ws),
        shared_dir=str(ws / "shared"),
        task_root=str(ws / "tasks"),
        users_root=str(ws / "users"),
        admin_token="admin-pg",
        max_concurrent=1,
        engine="opencode",
        agent_bin="/bin/true",
        log_path=str(ws / "relay.log"),
    )
    import threading
    import uvicorn
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if httpx.get(base + "/health", timeout=1).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        admin = httpx.Client(base_url=base, headers={"Authorization": "Bearer admin-pg"}, timeout=15)
        r = admin.post("/users", json={"name": "pg成员"})
        assert r.status_code == 201, r.text
        tok = r.json()["token"]
        member = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        assert member.get("/tasks").status_code == 200
        assert admin.get("/users").json()["users"][0]["name"] == "pg成员"
        # 直接经 DB 建任务（不经调度器，避免真实执行），验证 API 序列化
        db = DB(pg_url)
        tid = db.create_task(user="pg成员", description="序列化验证", targets=["x.md"])
        db.set(tid, status="done", result="ok", changed_files=["x.md"],
               conflicts=[], finished_at=time.time())
        db.close()
        r = member.get(f"/tasks/{tid}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done" and body["targets"] == ["x.md"]
        assert body["changed_files"] == ["x.md"]
        assert httpx.get(base + "/health", timeout=5).json()["ok"] is True
    finally:
        server.should_exit = True
        time.sleep(0.5)
