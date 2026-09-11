---
name: team-agent-relay
version: 1.1.0
description: 团队远程执行中转服务。当用户要求"在团队服务器上跑个任务"、"写经营月报"、"查团队知识库"、"用钉钉发/查/收（dws）"、"让服务器上的 agent 处理"、"把文件传到/从服务器下载"等需要共享服务器环境、共享工具或团队知识库的任务时使用。能力：提交任务、实时直播进展、追加任务（续会话）、变更核查、文件上传/下载（≤1MB）、取消。支持多公司 profile 并存。
---

# 团队中转服务

所有操作通过本 skill 目录下的 `relay.py`（纯标准库，`python3` 直接跑，输出单行 JSON）。
下文记 `S="python3 <本skill目录>/relay.py"`。

## 安装/更新语义

- 本 skill 以 frontmatter `version` 为准做版本比较（`S version` 可查客户端/服务端版本对照）
- 安装时目录已存在 ≠ 失败：比对已装 SKILL.md 的 version，**本地旧于新包则直接覆盖安装**（幂等；用户配置在 `~/.team-agent/`，不在 skill 目录内，覆盖不丢配置）
- 版本相同则跳过；本地更新则提示用户确认是否降级
- 服务端 /health 若返回 `min_client_version` 且高于本地版本，`S version` 会给出 `upgrade_needed: true`，此时应提示用户更新本技能

## 连接

- 默认 `https://10.189.51.29:8788`，TLS 校验固定用本目录 `ca.pem`（随包分发，缺失时退回系统默认校验）
- 旧版 http:8787 配置首次加载自动迁移为 https 并回写，无需手工改
- 指向其它主机：`S config <token> --server <url>`
- **多公司并存**：配置为 INI 多节（`~/.team-agent/config`），每家公司一个 profile；所有命令支持 `--profile <名称>`（缺省 `default`，env `TEAM_AGENT_PROFILE`）。旧版单组平铺配置首次加载自动迁移为 `[default]`

## 何时使用

- 任务需要**服务器共享环境**（统一工具/凭证/网络）：如 dws 钉钉操作、内部系统
- 需要**团队共享知识**：先让远端 agent 查 `shared/knowledge/`
- 产出要**沉淀到团队共享区**（报告、数据、复盘）
- 用户说"派给团队服务器 / 让 Claude 那边跑 / 用共享环境"

纯本地小任务直接本地处理，不走中转。

## 首次使用（仅第一次）

先执行：`S config`
- 返回 `{"configured": true}` → 直接干活，**不要向用户提及配置**
- 返回 `{"configured": false}` → 按此固定流程（**只检查脚本读取的固定位置，不要搜索用户目录其他配置形式**）：
  1. 只发这一条消息（原样，不添加技术细节）：
     > 首次使用团队执行服务，需要你提供一次专属凭证（token，形如 ta_xxx）。如果你还没有，请联系管理员领取后发我；发我后我会在你本地保存一次，之后就不用再管了。
  2. 拿到 token 后执行：`S config <用户提供的token>` → `{"saved": true}`
  3. 回用户"已保存，开始处理你的任务"，继续执行

token 只接受用户本人提供，绝不猜测/复用示例值；token 不落日志、不复述给用户。

**多公司用户**：用户在多家公司任职、有多组 token 时，每家公司存一个命名 profile（如 `S config <tokenB> --server <urlB> --profile 公司B`），并存不互相覆盖；执行任务前问清用哪家（或用户已在话里指明），未指明且存在多 profile 时用 `S profiles` 列出让用户选，**不要默认猜**。仅一个 profile 时直接走 `default`，不提及 profile 概念。

## 命令

| 场景 | 命令 |
|---|---|
| **一步到位（最常用）**：提交并等完成 | `S run "任务描述" -t "shared/reports/9月"` |
| 仅提交（异步拿 task_id） | `S submit "描述" -t "目录" [--urgent] [--resume N] [--force]` |
| 等某任务到终态 | `S wait 42` |
| 查状态 / 列表 | `S status 42` ／ `S tasks --status running` |
| 实时进展（边跑边向用户转述） | `S stream 42`（逐行 JSON：tool/text/status，终态停止） |
| 改了哪些文件 | `S diff 42` |
| **上传文件到服务器**（任务输入材料） | `S upload ./9月.xlsx data/9月.xlsx` |
| **从服务器下载文件**（产出/结果） | `S download data/report.md ./report.md`（本地路径可省，默认存文件名） |
| 取消 | `S cancel 42` |
| review 核查后确认 | `S confirm 42` |
| 版本对照（客户端/服务端/是否需升级） | `S version` |
| 列出全部公司配置 | `S profiles`（token 打码） |

参数说明：
- `--profile`：所有子命令通用，选择公司配置（缺省 `default`）
- `-t`：要动哪些共享目录（防冲突依据，强烈建议填；多个逗号分隔）
- `--urgent`：插队（默认 FIFO，并发上限 3）
- `--resume N`：追加要求，续接任务 N 的会话（不满意时用这个，别重开）
- 输出带 `"error": true, "http": 409`：targets 与在途任务重叠 → 把 overlaps（谁/哪个任务/哪些目录）告知用户，确认继续再加 `--force`
- `"http": 401`：token 失效 → 请用户找管理员重发，然后 `S config <新token> --profile <对应profile>`

**文件上传/下载**：
- 路径是共享区 `shared/` 内的相对路径（如 `data/9月.xlsx`、`reports/9月/月报.md`）
- **单文件 ≤1MB**（客户端先拦，服务端超限返回 `"http": 413`）；大文件告知用户拆小或走人工通道
- 典型用法：任务需要输入材料 → 先 `upload` 再 `run "…读取 data/9月.xlsx…"`；任务产出文件 → 完成后 `download` 给用户
- 不要用任务描述里塞 base64 的方式传文件（旧法，已废弃）

## 工作流

1. 理解意图 → 组织清晰的 description（目标、范围、验收、产出位置）
2. `S run`（或 submit + stream 直播）
3. 到 `review`：`S diff` 给用户看改动 → 认可 → `S confirm`
   - 不满意 → `S submit "追加要求" --resume <id>`
4. `conflict`：告知冲突详情（哪两个任务/哪个文件/备份在哪），人工核查
5. `failed`：读 error，调整描述重新提交

## 规则与边界

- 单任务 30 分钟超时；**review 不是终点**，diff 给用户看过并 confirm 才算 done
- 同文件被两任务改动不会静默覆盖：先完成者版本自动备份 `.bak-用户-HHMM`，后完成者标 conflict
- 共享区约定：`shared/knowledge/`（知识库，先查）、其余按业务分目录
