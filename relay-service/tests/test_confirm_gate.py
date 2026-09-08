from __future__ import annotations

import pytest

from app.config import DEFAULT_CONFIRM_RECIPIENTS, Settings
from app.executor import Executor


@pytest.fixture()
def ex() -> Executor:
    cfg = Settings(db_path=":memory:", workspace_root="/tmp/x", shared_dir="/tmp/x/shared",
                   task_root="/tmp/x/tasks", users_root="/tmp/x/users")
    return Executor(cfg)


# ---- 马韵升（董事局主席）：姓名 / userId "1" / openDingTalkId 全命中 ----

def test_dm_to_chairman_blocked(ex):
    cmd = "dws chat +dm --to 马韵升 --content x --yes"
    reason = ex._is_blocked(cmd)
    assert reason is not None and "二次确认" in reason and "马韵升" in reason
    assert ex._confirm_violation(cmd) == reason


def test_dm_to_chairman_by_userid_blocked(ex):
    reason = ex._is_blocked("dws chat +dm --to 1 --content x --yes")
    assert reason is not None and "二次确认" in reason
    # 原子命令形态同样拦
    assert ex._is_blocked("dws chat message send --user 1 --content x") is not None
    assert ex._is_blocked("dws chat +messages-send --as user --user 1 --text x") is not None


def test_dm_to_chairman_by_opendingtalkid_blocked(ex):
    odid = "D3QFnNNkA4zsa6fEkz0vxWVZZG4c4SxTc"
    assert ex._is_blocked(f"dws chat +dm --to {odid} --content x --yes") is not None
    assert ex._is_blocked(f"dws chat message send --open-dingtalk-id {odid} --content x") is not None
    assert ex._is_blocked(f"dws chat +messages-send --open-dingtalk-id {odid} --text x") is not None
    assert ex._is_blocked(f"dws chat +messages-send-card --receiver-open-dingtalk-id {odid} --content x") is not None


# ---- 单发普通人：不拦；userId 精确匹配，无子串误伤 ----

def test_dm_to_ordinary_person_allowed(ex):
    assert ex._is_blocked("dws chat +dm --to 王洪彬 --content x --yes") is None
    assert ex._is_blocked("dws chat message send --user 37505774 --content x") is None
    assert ex._is_blocked("dws chat +messages-send --as user --user-query 王洪彬 --text x") is None
    assert ex._is_blocked("dws chat +messages-send-card --receiver 37505774 --content x") is None


def test_userid_no_substring_false_positive(ex):
    # "1" 是敏感 userId，但绝不能子串命中含 1 的其他 userId
    for uid in ("10", "37505774", "12345", "118785", "21", "100"):
        assert ex._is_blocked(f"dws chat +dm --to {uid} --content x --yes") is None, uid
        assert ex._is_blocked(f"dws chat message send --user {uid} --content x") is None, uid


# ---- 多接收人（逗号分隔 / 重复 flag / 批量命令）：拦 ----

def test_multi_recipients_blocked(ex):
    cases = [
        'dws chat +broadcast --to "张三,李四" --content x',
        "dws chat +broadcast --to 张三 --to 李四 --content x",
        "dws chat +broadcast --to 张三,李四,王五 --content x --yes",
        "dws chat +messages-send --as bot --robot-code r --users 37505774,12345 --text x",
        "dws chat +messages-batch-send-by-bot --robot-code r --users 37505774,12345 --title t --content x",
        "dws chat message send-by-bot --robot-code r --users 37505774,12345 --title t --text x",
        "dws ding message send --robot-code r --users 37505774,12345 --content x",
        "dws ding message send-personal --users odidA,odidB --content x",
        "dws ding +send-personal --users odidA,odidB --content x",
    ]
    for cmd in cases:
        reason = ex._is_blocked(cmd)
        assert reason is not None and "二次确认" in reason, cmd


def test_multi_recipients_including_chairman_blocked(ex):
    reason = ex._is_blocked("dws chat +broadcast --to 王洪彬,马韵升 --content x")
    assert reason is not None and "二次确认" in reason


# ---- 群聊 / 会话目标：拦 ----

def test_group_send_blocked(ex):
    cases = [
        "dws chat +send-to-group --group 项目冲刺 --content x",
        "dws chat +send-to-group --group cidAbc123== --content x --yes",
        "dws chat +messages-send --as user --chat-id cidAbc123== --markdown '## 周报'",
        "dws chat +messages-send --as user --chat-query 项目冲刺 --text x",
        "dws chat +messages-send --as bot --robot-code r --groups cid1,cid2 --text x",
        "dws chat +messages-send-by-bot --robot-code r --group cid1 --title t --content x",
        "dws chat +messages-send-by-webhook --token tok123 --title t --content x",
        "dws chat message send --conversation-id cidAbc123== --content x",
        "dws chat message send-by-webhook --token tok123 --title t --content x",
        "dws chat +messages-send-card --group cid1 --content x",
        "dws chat +messages-reply --group cid1 --message-id m1 --content 收到",
        "dws chat +messages-forward --src-conversation-id cidS --msg-id m1 --dest-conversation-id cidD",
        "dws chat +messages-combine-forward --src-conversation-id cidS --msg-ids m1,m2 --dest-conversation-id cidD",
    ]
    for cmd in cases:
        reason = ex._is_blocked(cmd)
        assert reason is not None and "二次确认" in reason, cmd


# ---- DING：敏感人拦、单发普通人放、源会话 --group 不算目标 ----

def test_ding_gate(ex):
    assert ex._is_blocked("dws ding +send-personal --users D3QFnNNkA4zsa6fEkz0vxWVZZG4c4SxTc --content x") is not None
    assert ex._is_blocked("dws ding message send --robot-code r --users 1 --content x") is not None
    assert ex._is_blocked("dws ding message send --robot-code r --users 37505774 --content x") is None
    assert ex._is_blocked("dws ding message send-personal --users odidOrdinary --content x") is None
    # send-by-message 的 --group 是源会话，接收人看 --users：单发普通人不拦
    assert ex._is_blocked("dws ding message send-by-message --group cidSrc --message-id m1 --users 37505774") is None
    assert ex._is_blocked("dws ding message send-by-message --group cidSrc --message-id m1 --users 1") is not None


# ---- 只读 / 非发送命令：即使含敏感名字也不拦 ----

def test_readonly_commands_allowed(ex):
    cases = [
        "dws auth status",
        "dws contact user search --keyword 马韵升",
        "dws contact user get --user-id 1",
        "dws chat +chat-list",
        "dws chat +chat-messages --group 项目冲刺",
        "dws chat +search-msg --keyword 马韵升",
        "dws chat +chat-members-list --group 项目冲刺",
        "dws chat message list --conversation-id cidAbc123==",
        "dws chat +chat-search --query 马韵升粉丝群",
        "dws ding +list",
        "dws ding message receiver-status --users 1",
        "dws chat +bot-find --keyword 机器人",
        "dws aisearch person --query 马韵升",
    ]
    for cmd in cases:
        assert ex._is_blocked(cmd) is None, cmd


def test_dws_substring_paths_not_confused(ex):
    # 路径里带 "dws" 字的普通文件操作不受门控影响（递归 rm 规则照旧独立判定）
    assert ex._is_blocked('rm -rf "$HOME/.local/share/dws-cli/dws-cli"', "/mnt/ws/tasks/42") is None
    assert ex._is_blocked("cat /root/.local/share/dws-cli/auth-token.enc") is None


# ---- 引号 / 等号 / 链式 / 嵌套变体 ----

def test_quote_and_equals_variants_blocked(ex):
    assert ex._is_blocked('dws chat +dm --to "马韵升" --content x --yes') is not None
    assert ex._is_blocked("dws chat +dm --to '马韵升' --content x --yes") is not None
    assert ex._is_blocked("dws chat +dm --to=马韵升 --content=x --yes") is not None
    assert ex._is_blocked('dws chat message send --user "1" --content x') is not None
    assert ex._is_blocked("dws chat +dm --to '1' --content x") is not None


def test_chained_and_nested_blocked(ex):
    assert ex._is_blocked("dws contact user search --keyword 马韵升 && dws chat +dm --to 马韵升 --content x") is not None
    assert ex._is_blocked('bash -c "dws chat +dm --to 马韵升 --content x"') is not None
    assert ex._is_blocked("cd /tmp; dws chat +send-to-group --group 项目冲刺 --content x") is not None
    # 链上只有只读命令时不拦
    assert ex._is_blocked("dws auth status && dws contact user search --keyword 马韵升") is None


# ---- 审批豁免：approve 后 resume 带 exempt_cmd 放行同一命令 ----

def test_exempt_after_approval(ex):
    cmd = "dws chat +dm --to 马韵升 --content x --yes"
    assert ex._is_blocked(cmd) is not None          # 首跑拦截
    assert Executor._exempt(cmd, cmd) is True       # 审批后同命令豁免
    assert Executor._exempt(cmd, None) is False     # 未审批不豁免
    gcmd = "dws chat +send-to-group --group 项目冲刺 --content x"
    assert Executor._exempt(gcmd, gcmd) is True


# ---- 配置：默认清单 / 环境变量覆盖 / 自定义清单生效 ----

def test_config_defaults_and_env(monkeypatch):
    cfg = Settings(db_path=":memory:", workspace_root="/tmp/x", shared_dir="/tmp/x/shared",
                   task_root="/tmp/x/tasks", users_root="/tmp/x/users")
    assert cfg.confirm_recipients == DEFAULT_CONFIRM_RECIPIENTS == \
        ["马韵升", "1", "D3QFnNNkA4zsa6fEkz0vxWVZZG4c4SxTc"]

    monkeypatch.setenv("RELAY_CONFIRM_RECIPIENTS", "马韵升,1,D3QFnNNkA4zsa6fEkz0vxWVZZG4c4SxTc")
    assert Settings.from_env().confirm_recipients == DEFAULT_CONFIRM_RECIPIENTS

    monkeypatch.setenv("RELAY_CONFIRM_RECIPIENTS", "张三, 42 ")
    s = Settings.from_env()
    assert s.confirm_recipients == ["张三", "42"]
    ex2 = Executor(s)
    assert ex2._is_blocked("dws chat +dm --to 张三 --content x") is not None
    assert ex2._is_blocked("dws chat +dm --to 42 --content x") is not None
    assert ex2._is_blocked("dws chat +dm --to 马韵升 --content x") is None  # 自定义清单已不含
    assert ex2._is_blocked("dws chat +dm --to 421 --content x") is None     # 仍无子串误伤

    monkeypatch.delenv("RELAY_CONFIRM_RECIPIENTS")
    assert Settings.from_env().confirm_recipients == DEFAULT_CONFIRM_RECIPIENTS
