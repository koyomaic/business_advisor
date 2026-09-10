# 工作区约定（服务器任务 agent 必读）

## 动手前（共享知识检索顺序）

1. **优先权威源：jingboWiki**——用 `jingbowiki-api` 技能检索（快速检索 `POST /knowledge-search`；凭据 `shared/secrets/jingbowiki.env`，健康检查 `http://10.200.3.235:18082/health`）。团队知识以 jingboWiki 为准。
2. 本地兜底：`/mnt/vol-eltaah12/workspace/shared/knowledge/` 对应主题目录（《中转服务使用说明.md》《team-agent-relay-SKILL.md》等）；jingboWiki 不可达或未命中时再查。
3. 两处内容冲突时，以 jingboWiki 为准。有现成经验就用，不要重复摸索。

## 可用 CLI

- `dws`：钉钉工作套件（发消息/查通讯录/日程/表格/文档/审批/待办），用法与坑位见 dws skill
- `python3`
- 常规 shell 工具（bash、curl 等）

## GitHub 项目（"检查GitHub项目更新"即指它）

- 仓库 `koyomaic/business_advisor`（main）＝中转服务 relay 唯一真源；本地 git 工作区 `/mnt/vol-eltaah12/finaagent/relay-dev`
- 检查更新：`cd /mnt/vol-eltaah12/finaagent/relay-dev && git fetch origin && git log --oneline HEAD..origin/main`（无输出＝已最新；有输出＝汇报新提交后等指示）
- 任务里默认只检查/汇报；pull、部署、push、重启服务需任务明确要求（部署走 `/opt/team/relay-boot/boot.sh`，机队文档 `relay-dev/boot/INSTALL.md`）

## 共享区约定（shared/）

- `shared/` 是团队共享区，**不要静默覆盖他人文件**；改动已有共享文件前先保留原版本
- 任务产生的可复用经验写入 `shared/knowledge/` 对应主题目录
- **知识归档双写（硬性）**：凡归档进 `shared/knowledge/` 的知识文件（报告/文档/摘要/经验，无论任务产出还是用户上传），**必须在同一任务内经 `jingbowiki-api` 同步上传 jingboWiki**（权威源，全员可检索）。双写是归档动作的一部分，任务描述里"只改动 shared/knowledge/ 下文件""不要修改其他文件"之类范围限定**不豁免**本条；仅当任务明确写"不要上传 jingboWiki"时才跳过
- 上传**受理即成功**（不阻塞等解析，解析后台异步），在任务结果里报告 knowledge_id；需确认解析完成时用技能的 wait 子命令后查，不要长轮询

## 共享知识（取消隔离，个人上传即全员可用）

- `shared/skills/`：团队技能，已自动加载进你的技能列表，直接按技能名使用。其中**基础技能**（人为标记入库到 git 仓库 `skills/` 目录的；当前：jingbowiki-api、钉钉套件 dingtalk-*（安装位 `/root/.agents/skills`）、dws（`/opt/team/skills`）及 shared 内 dingtalk-* 技能；安装位由技能内 `.dest` 文件指定，缺省 shared/skills）以 git 为真源：改动务必提交回仓库，否则夜间体检（provision）会以仓库版覆盖本机改动（旧版备份 `*.bak-provision-*`）；未入库的本地/实验技能不受此限
- `shared/mcp/`：团队 MCP 工具服务器，已自动接入，把它们的工具当普通工具调用
- `shared/memory/`：团队记忆，已自动并入本 AGENTS.md
- 三类内容任何人上传后，下一个任务即全员生效，无需重启
- dws 凭证种子（`shared/secrets/dws-cli-seed/`）也**自动同步**进每个任务的 home，
  直接用 dws 即可，不用手动复制；报"登录态过期"时才走设备码流程

## 任务工作目录

你的工作目录 `tasks/<id>` 是一次性任务区，临时文件放这里即可，任务结束无需清理。

## 中转服务数据库

- 存储后端以 relay.env 的 `RELAY_DB` 为准：postgresql:// URL → PostgreSQL；缺省 → SQLite（workspace/relay.db）。
- 实时查证：`curl http://127.0.0.1:8787/health` 的 `db` 字段返回真实后端（postgresql/sqlite）。
- 若本机已切 PG，旧 `relay.db` 只是历史快照（存档、不再读写）——**不要**凭它存在就回答现役库是 SQLite。

## 临时文件清理（无需确认）

- **自己**在本次会话中创建的临时产物——如 `/tmp` 下的打包 zip、解压目录、中间文件、测试残留——直接删除即可，**不要向用户逐个征求确认**（用户要求：减少此类打扰）。
- 边界：仅限"本次会话自己生成的临时物"。用户的真实数据（workspace 业务数据、shared/ 共享区、他人文件、任务产出）不在免确认范围内，删除前必须说明并确认。

## 命令拦截边界（了解即可，正常干活别撞）

- `/tmp`、`/var/tmp` 下的清理（含 `rm -rf`）直接放行；systemctl、防火墙、cron、用户管理等均不拦。
- 会被拦的核心项：`mkfs`、写裸盘（`of=/dev/磁盘`、`> /dev/磁盘`）、`shutdown/reboot/poweroff/halt`、`kill -9 1`、`chmod -R 777 /` 或 `~`、**非 /tmp 路径的递归 rm**。
- 若任务确需执行会被拦的命令，如实说明并让用户在监控页审批，不要变着写法绕。
