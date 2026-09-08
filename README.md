# business_advisor

经营智能体蜂群项目（设计方案见 [docs/蜂群设计方案.md](docs/蜂群设计方案.md)）。

核心组件：**团队中转服务** [relay-service/](relay-service/) —— 本地千问经 CLI 向服务器提交任务，
服务排队调度、无头驱动 agent、共享知识沉淀、并行防打架、审计与监控。

## bootloader（多机部署/自动更新/失败预警）

代码唯一真源 = 本仓库 **main 分支**；每台机器的密钥（`relay.env`）永不入库，
模板见 [relay-service/relay.env.example](relay-service/relay.env.example)。
每台机器的 bootloader 装在 `/opt/team/relay-boot/`，真源在本仓库 [boot/](boot/) 目录：
`boot.sh`（部署/守护/回滚脚本）+ `boot.env`（每机私有配置，模板 `boot.env.example`）
+ `relay-boot.service` / `relay-boot.timer`（systemd 单元）。

### 新机器一次性安装

```bash
sudo mkdir -p /opt/team/relay-boot
sudo cp boot/boot.sh /opt/team/relay-boot/                  # 之后由自更新机制保持与仓库一致
sudo cp boot/boot.env.example /opt/team/relay-boot/boot.env
sudo vi /opt/team/relay-boot/boot.env                       # 按该机改路径：RELEASE_ROOT/CURRENT_LINK/VENV/LOG/ALERT_TO 等
sudo cp boot/relay-boot.service boot/relay-boot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now relay-boot.timer
sudo /opt/team/relay-boot/boot.sh boot                      # 首次：clone → 部署 → 健康检查
```

前置：该机已有 git/curl/python3、`VENV` 指向的 venv、dws CLI（失败预警用）。

### 每日自动更新 + 守护

`relay-boot.timer` 每日 01:00（开机 2min 补跑，`Persistent=true`）执行 `boot.sh boot`：
检测远端 main SHA，与现役不同则走安全更新流——clone 到 `releases/<sha>/` → pip 依赖同步 →
快速测试门禁 → 写 VERSION → 符号链接原子切换 `CURRENT_LINK` → 重启 relay →
`/health` 校验 `version`==新 SHA → 失败自动回滚上一版并预警；无更新则做存活守护
（服务挂了/不健康自动拉起、重启）。日志见 `boot.env` 的 `LOG`（默认 `/var/log/relay-boot.log`）。
多机版本巡检：`curl http://<服务器>:8787/health` 比对各机 `version` 字段（git SHA）。

### 人工即时更新

```bash
curl -X POST http://<服务器>:8787/admin/update -H 'Authorization: Bearer <admin token>'  # 远程逐台触发
sudo /opt/team/relay-boot/boot.sh update                                                 # 或本机执行
```

### 失败钉钉预警

更新链路任何失败（远端不可达、依赖安装/测试门禁/健康检查失败、回滚后仍不健康）都会
`notify_failure`：用 dws 给 `boot.env` 里 `ALERT_TO`（默认王洪彬）发钉钉直聊，附主机名、
原因、当前版本与日志路径。dws 登录态走共享种子（`DWS_SEED` 可覆盖，默认
`/mnt/vol-eltaah12/workspace/shared/secrets/dws-cli-seed/dws-cli`）：临时 HOME 里**软链**
种子目录后直发，token 轮换直接发生在种子上（与 dws-renew 同一份登录态，无复制/回写竞态）；
种子不存在时退回本机 root 登录态直发。

### boot.sh 自更新

仓库 `boot/` 目录是 bootloader 的唯一真源。部署成功切换后（以及无更新的守护轮次里
release 已存在时），boot.sh 会比对 `releases/<sha>/boot/` 与本机：

- `boot.sh` 内容不同 → `cp` 到 `$BOOT_DIR/.boot.sh.new` 后 `mv -f` **原子替换**
  （运行中实例持旧 inode，不受影响）；
- `relay-boot.service` / `relay-boot.timer` 与 `/etc/systemd/system/` 不同 → 拷贝 +
  `systemctl daemon-reload`；
- `boot.env` 是每机私有配置，**永不覆盖**。

因此 bootloader 本身的改动也只需推 main，全 fleet 一日内自动跟随，无需逐台登录。

### 回滚与状态

```bash
sudo /opt/team/relay-boot/boot.sh rollback   # 切回最近一份 release 并重启，自动健康检查
sudo /opt/team/relay-boot/boot.sh status     # 远端/现役版本 + 健康状态 + 单元状态
```

## HTTPS（成员端不再提示"不安全地址"）

- `relay-tls-proxy.service`：socat 把 `https://<内网IP>:8788` TLS 终结后转发 `127.0.0.1:8787`。**全机只跑一个应用实例**（8787），代理无状态——避免双实例共享 relay.db 时重启恢复互相重复入队。
- 证书：内部 CA（`CN=Relay Internal CA`，10 年）签发，SAN 含本机内网 IP/主机名。CA 与服务器证书存 `workspace/shared/secrets/relay-tls/`（ca.key/server.key 600，绝不进 git）；`ca.pem` 公开，随 skill 分发给成员端做 CA 固定校验。
- 其它机器：安全通道拷贝 `ca.key/ca.pem` → `relay-service/scripts/tls-issue.sh <CA目录> <本机IP> [主机名]` 签发本机证书 → 安装 relay-tls-proxy.service（改证书路径）。
- 8787 http 保留兼容旧客户端；成员 skill（team-agent-relay）已默认 https:8788 且自动迁移旧配置。

## 发布流程

```bash
# 任一开发机：改代码 → 测试 → 推送
cd relay-service && python -m pytest -m "not integration" -q
git add -A && git commit -m "..." && git push origin main
# 全 fleet：次日 01:00 自动跟随；等不及就逐台 POST /admin/update
```
