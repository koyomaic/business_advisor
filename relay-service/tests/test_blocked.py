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


# ---- 任务 HOME 沙箱内递归 rm：~/$HOME 展开后放行（凭证同步等合法操作不再误拦） ----

WORKDIR = "/mnt/ws/tasks/42"
THOME = WORKDIR + "/home"


def test_rm_task_home_allowed(ex):
    assert ex._is_blocked('rm -rf "$HOME/.local/share/dws-cli/dws-cli"', WORKDIR) is None
    assert ex._is_blocked("rm -rf $HOME/.cache", WORKDIR) is None
    assert ex._is_blocked("rm -rf ${HOME}/.cache", WORKDIR) is None
    assert ex._is_blocked("rm -rf ~/.local/share/dws-cli", WORKDIR) is None
    assert ex._is_blocked(f"rm -rf {THOME}/tmp-x", WORKDIR) is None
    assert ex._is_blocked("rm -rf $HOME", WORKDIR) is None  # 整个沙箱也是自己的


def test_rm_task_home_real_case(ex):
    # 任务 #9 被误拦的真实命令：同步 /root 新凭证进任务 HOME
    cmd = ('rm -rf "$HOME/.local/share/dws-cli/dws-cli" && '
           'cp /root/.local/share/dws-cli/auth-token.enc "$HOME/.local/share/dws-cli/" 2>&1; '
           'ls -la "$HOME/.local/share/dws-cli/"')
    assert ex._is_blocked(cmd, WORKDIR) is None


def test_rm_task_home_still_guarded(ex):
    assert ex._is_blocked("rm -rf $HOME/../../../../etc", WORKDIR) is not None  # .. 逃逸规范化后拦截
    assert ex._is_blocked("rm -rf /root", WORKDIR) is not None  # 系统路径照拦
    assert ex._is_blocked("rm -rf $HOME/x") is not None  # 无 workdir 上下文时保持旧行为
    assert ex._is_blocked('rm -rf "$DIR/x"', WORKDIR) is not None  # 其它变量无法展开
    assert ex._is_blocked("rm -rf ./cache", WORKDIR) is not None  # 相对路径照拦
    assert ex._is_blocked("rm -rf /tmp/a $HOME/../../shared/knowledge", WORKDIR) is not None  # 混有逃逸目标
