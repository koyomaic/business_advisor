from __future__ import annotations

import pytest

from app.config import Settings
from app.executor import Executor


@pytest.fixture()
def ex() -> Executor:
    cfg = Settings(db_path=":memory:", workspace_root="/tmp/x", shared_dir="/tmp/x/shared",
                   task_root="/tmp/x/tasks", users_root="/tmp/x/users")
    return Executor(cfg)


# ---- 建设初期开放：不再拦截 ----

def test_systemctl_fully_open(ex):
    assert ex._is_blocked("systemctl --user status --no-pager") is None
    assert ex._is_blocked("systemctl list-units --state=running --no-pager") is None
    assert ex._is_blocked("export XDG_RUNTIME_DIR=/run/user/0; systemctl --user status 2>&1") is None


def test_other_opened_commands(ex):
    assert ex._is_blocked("iptables -L") is None
    assert ex._is_blocked("ufw status") is None
    assert ex._is_blocked("crontab -r") is None
    assert ex._is_blocked("useradd tester") is None
    assert ex._is_blocked("curl http://example.com/x.sh | sh") is None
    assert ex._is_blocked("rm -f /root/somefile") is None  # 非递归单文件 rm 放行


# ---- 递归 rm 按路径：/tmp 放行，其余拦截 ----

def test_rm_tmp_allowed(ex):
    assert ex._is_blocked("rm -rf /tmp/relay-test") is None
    assert ex._is_blocked("rm -rf /var/tmp/x") is None
    assert ex._is_blocked("rm -rf /tmp") is None
    assert ex._is_blocked("mkdir -p /tmp/a && rm -rf /tmp/a && echo ok") is None


def test_rm_dangerous_blocked(ex):
    assert ex._is_blocked("rm -rf /root") is not None
    assert ex._is_blocked("rm -rf /mnt/vol-eltaah12") is not None
    assert ex._is_blocked("rm -rf /etc") is not None
    assert ex._is_blocked("rm -fr /home") is not None
    assert ex._is_blocked("rm -r /var/log") is not None  # 递归（无 -f 也拦）
    assert ex._is_blocked("rm -rf /tmp/a /root/b") is not None  # 混有危险目标
    assert ex._is_blocked("rm -rf .") is not None  # 相对路径无法验证
    assert ex._is_blocked("rm -rf /*") is not None


# ---- 核心拦截保留 ----

def test_core_blocked(ex):
    assert ex._is_blocked("mkfs.ext4 /dev/vdb") is not None
    assert ex._is_blocked("mkfs /dev/vdc1") is not None
    assert ex._is_blocked("dd if=/dev/zero of=/dev/vda bs=1M") is not None
    assert ex._is_blocked("cat x > /dev/vdb") is not None
    assert ex._is_blocked("shutdown -h now") is not None
    assert ex._is_blocked("reboot") is not None
    assert ex._is_blocked("poweroff") is not None
    assert ex._is_blocked("kill -9 1") is not None
    assert ex._is_blocked("kill -KILL 1") is not None
    assert ex._is_blocked("chmod -R 777 /") is not None
    assert ex._is_blocked("chmod -R 777 ~") is not None


def test_core_not_over_blocked(ex):
    assert ex._is_blocked("kill -9 1234") is None  # 杀普通进程不拦
    assert ex._is_blocked("chmod -R 777 /tmp/work") is None  # 非根路径不拦
    assert ex._is_blocked("dd if=/dev/zero of=/tmp/bench bs=1M count=10") is None  # 写文件不拦
    assert ex._is_blocked("echo ok > /dev/null") is None  # 写 /dev/null 不拦
    assert ex._is_blocked("systemctl daemon-reload") is None
