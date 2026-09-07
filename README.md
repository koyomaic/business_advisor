# business_advisor

经营智能体蜂群项目（设计方案见 [docs/蜂群设计方案.md](docs/蜂群设计方案.md)）。

核心组件：**团队中转服务** [relay-service/](relay-service/) —— 本地千问经 CLI 向服务器提交任务，
服务排队调度、无头驱动 agent、共享知识沉淀、并行防打架、审计与监控。

## 多机部署（bootloader 机制）

- 代码唯一真源 = 本仓库 **main 分支**；每台机器的密钥（`relay.env`）永不入库，
  模板见 [relay-service/relay.env.example](relay-service/relay.env.example)
- 每台机器安装 bootloader `/opt/team/relay-boot/boot.sh`（仓库外分发）+ `boot.env`（本机路径配置）
- **两种更新触发路径**：
  1. **定时**：`relay-boot.timer` 每日 01:00 检测 git 更新并部署，兼作服务存活守护；
  2. **人工即时**：`POST /admin/update`（admin token，可远程逐台触发）或本机执行 `boot.sh update`
- **安全更新流**：fetch → `releases/<sha>/` 检出 → 依赖同步 → 快速测试门禁 →
  符号链接原子切换 → 重启 → `/health` 检查（`version`==新 SHA）→ 失败自动回滚上一版
- **多机版本巡检**：`curl http://<服务器>:8787/health` 比对各机 `version` 字段（git SHA）

## 发布流程

```bash
# 任一开发机：改代码 → 测试 → 推送
cd relay-service && python -m pytest -m "not integration" -q
git add -A && git commit -m "..." && git push origin main
# 全 fleet：次日 01:00 自动跟随；等不及就逐台 POST /admin/update
```
