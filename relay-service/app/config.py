from __future__ import annotations

import os
from dataclasses import dataclass, field


# 核心拦截（正则，对命令小写后匹配）：只拦"不可逆 / 会炸服务器 / 批量毁数据"。
# 建设初期开放优先：systemctl、iptables、ufw、crontab -r、useradd/userdel、
# curl|sh、wget|sh 一律放行；普通（非递归）rm 也放行。
# 递归 rm 由 executor._rm_violation 按路径单独判断：rm_safe_prefixes 下放行，其余拦截。
DEFAULT_BLOCKED_PATTERNS = [
    r"\bmkfs",                                      # 格式化文件系统（不可逆）
    r"\bof=/dev/(sd|vd|nvme|hd|xvd|dm-|md)\w*",     # dd 写裸盘
    r">\s*/dev/(sd|vd|nvme|hd|xvd|dm-|md)\w*",      # 重定向写裸盘
    r"\b(shutdown|reboot|poweroff|halt)\b",         # 服务器电源操作
    r"\bkill\s+(-9|-kill)\s+1(?!\d)",               # 杀 init（PID 1）
    r"\bchmod\s+-r\s+777\s+(?:~|/(?!\w))",          # 根/家目录递归 777
]
DEFAULT_RM_SAFE_PREFIXES = ["/tmp", "/var/tmp"]

# dws 消息发送二次确认门控的敏感接收人（executor._confirm_violation 精确字符串匹配）。
# "1" 是马韵升（董事局主席）的 userId，必须整 token 精确相等，绝不子串匹配
# （避免误伤 37505774 等含 1 的 userId）。
DEFAULT_CONFIRM_RECIPIENTS = ["马韵升", "1", "D3QFnNNkA4zsa6fEkz0vxWVZZG4c4SxTc"]


def _blocked_patterns_from_env() -> list[str]:
    raw = os.environ.get("RELAY_BLOCKED_PATTERNS", "").strip()
    if not raw:
        return list(DEFAULT_BLOCKED_PATTERNS)
    return [p.strip() for p in raw.split(",") if p.strip()]


def _rm_safe_prefixes_from_env() -> list[str]:
    raw = os.environ.get("RELAY_RM_SAFE_PREFIXES", "").strip()
    if not raw:
        return list(DEFAULT_RM_SAFE_PREFIXES)
    return [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]


def _confirm_recipients_from_env() -> list[str]:
    raw = os.environ.get("RELAY_CONFIRM_RECIPIENTS", "").strip()
    if not raw:
        return list(DEFAULT_CONFIRM_RECIPIENTS)
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass
class Settings:
    db_path: str
    workspace_root: str
    shared_dir: str
    task_root: str
    users_root: str
    admin_token: str = "change-me"
    max_concurrent: int = 3
    task_timeout: float = 1800.0
    engine: str = "opencode"  # opencode | claude
    agent_bin: str = ""
    model: str = ""
    log_path: str = ""
    xdg_config_home: str = ""
    dashboard_password: str = ""
    event_history_max: int = 500
    stale_timeout_hours: float = 24.0   # review/待审批 停留超时 → 自动 done
    sweep_interval_sec: float = 300.0   # 超时清扫周期
    blocked_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_PATTERNS))
    rm_safe_prefixes: list[str] = field(default_factory=lambda: list(DEFAULT_RM_SAFE_PREFIXES))
    confirm_recipients: list[str] = field(default_factory=lambda: list(DEFAULT_CONFIRM_RECIPIENTS))
    relay_exclude_providers: list[str] = field(default_factory=list)  # 任务配置中剔除的 provider（本地专用模型不进任务环境）
    boot_cmd: str = "/opt/team/relay-boot/boot.sh"  # bootloader 入口（POST /admin/update 触发）
    min_client_version: str = ""  # 要求的最低客户端版本（空=不校验；/health 透出，客户端软提醒）
    auth_legacy: bool = False     # 旧式 bearer token 认证（生产默认关：token 仅作一次性激活码；过渡需要时置 1）
    sign_window: int = 900        # 设备签名时间窗（秒），防重放；放宽以容忍成员机器时钟漂移

    @classmethod
    def from_env(cls) -> "Settings":
        root = os.environ.get("RELAY_WORKSPACE", "/mnt/vol-eltaah12/workspace")
        return cls(
            db_path=os.environ.get("RELAY_DB", f"{root}/relay.db"),
            workspace_root=root,
            shared_dir=os.environ.get("RELAY_SHARED", f"{root}/shared"),
            task_root=os.environ.get("RELAY_TASK_ROOT", f"{root}/tasks"),
            users_root=os.environ.get("RELAY_USERS", f"{root}/users"),
            admin_token=os.environ.get("RELAY_ADMIN_TOKEN", "change-me"),
            max_concurrent=int(os.environ.get("RELAY_MAX_CONCURRENT", "3")),
            task_timeout=float(os.environ.get("RELAY_TASK_TIMEOUT", "1800")),
            engine=os.environ.get("RELAY_ENGINE", "opencode"),
            agent_bin=os.environ.get("RELAY_AGENT_BIN", ""),
            model=os.environ.get("RELAY_MODEL", ""),
            log_path=os.environ.get("RELAY_LOG", f"{root}/relay.log"),
            xdg_config_home=os.environ.get("RELAY_XDG_CONFIG_HOME", ""),
            dashboard_password=os.environ.get("RELAY_DASHBOARD_PASSWORD", ""),
            stale_timeout_hours=float(os.environ.get("RELAY_STALE_TIMEOUT_HOURS", "24")),
            sweep_interval_sec=float(os.environ.get("RELAY_SWEEP_INTERVAL_SEC", "300")),
            blocked_patterns=_blocked_patterns_from_env(),
            rm_safe_prefixes=_rm_safe_prefixes_from_env(),
            confirm_recipients=_confirm_recipients_from_env(),
            relay_exclude_providers=[p.strip() for p in os.environ.get("RELAY_EXCLUDE_PROVIDERS", "").split(",") if p.strip()],
            boot_cmd=os.environ.get("RELAY_BOOT_CMD", "/opt/team/relay-boot/boot.sh"),
            min_client_version=os.environ.get("RELAY_MIN_CLIENT_VERSION", "").strip(),
            auth_legacy=os.environ.get("RELAY_AUTH_LEGACY", "0").strip().lower()
            in ("1", "true", "on", "yes"),
            sign_window=int(os.environ.get("RELAY_SIGN_WINDOW", "60")),
        )
