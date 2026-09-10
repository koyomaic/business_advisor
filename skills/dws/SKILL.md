---
name: dws
description: 钉钉工作套件（dws CLI）。当任务涉及钉钉发消息/查通讯录/日程/表格/文档/审批/待办等时使用。命令速查+坑位，避免逐个 --help 摸索。
---

# dws 钉钉工作套件

`dws` 装在 `/usr/bin/dws`，登录身份为 **中鲁经营利润运营大脑**（京博控股集团，user_id 37505774）。命令形如 `dws <服务> <子命令> [flags]`，`+` 开头的是封装好的快捷命令（自动解析姓名→userId），不带 `+` 的是原子命令。

## 认证

任何 dws 操作前先检查：

```bash
dws auth status
```

- `authenticated=true` 且 `token_valid=true` → 直接干活
- 未登录/失效 → 报告"**需管理员扫码授权**"，**不要自己尝试登录**（登录要扫码，无头环境做不到）

实测输出形态：

```json
{ "success": true, "authenticated": true, "token_valid": true, "corp_name": "京博控股集团", "user_id": "37505774", "user_name": "中鲁经营利润运营大脑" }
```

## 高频命令速查

发消息/写操作前先确认收件人（姓名多人同名时 CLI 会列候选，不要猜）。

| 场景 | 命令 |
|---|---|
| 发单聊（文本/Markdown） | `dws chat +dm --to 王洪彬 --content "内容" -y` |
| 发文件到单聊 | `dws chat conversation-file upload --user <userId> --file ./report.pdf -y` |
| 发群消息 | `dws chat +send-to-group`（参数看 `--help`） |
| 查人（要 userId/openDingTalkId） | `dws contact user search --query 王洪彬` |
| 看自己的资料 | `dws contact +me` |
| 今天/本周日程 | `dws calendar +today` ／ `dws calendar +week` |
| 约会议（按姓名拉参会人） | `dws calendar +book --title "周会" --start "2026-09-10T14:00:00+08:00" --end "2026-09-10T15:00:00+08:00" --with 张三,李四 -y` |
| 列出可访问的 AI 表格 | `dws aitable +base-list` |
| 按名称解析 baseId | `dws aitable +resolve-base --name 项目管理` |
| 搜索云文档 | `dws doc +find-doc --query 季度汇报` |
| 读文档内容（Markdown） | `dws doc read`（参数看 `--help`） |
| 我的待办 | `dws todo +get-my-tasks` ／ `dws todo +due-today` |
| 待我审批 | `dws oa +list-pending --start <epoch毫秒> --end <epoch毫秒> --page 1 --limit 20` |
| 最近访问/编辑的文档 | `dws drive +recent` |

输出默认 JSON（`-f json|table|pretty|...`），可用 `--jq`、`--fields` 过滤。

## 实测输出形态（2026-09-03 验证通过）

```bash
dws contact user search --query 王洪彬
# → {"result":[{"name":"王洪彬","userId":"18434","openDingTalkId":"DL1l...","title":"一级AIBP",...}],"success":true}
```

```bash
dws contact +me
# → {"data":{"dept":"ZLRN高管层","name":"中鲁经营利润运营大脑","org":"京博控股集团","userId":"37505774",...},"ok":true}
```

```bash
dws drive +recent
# → {"data":{"count":4,"hasMore":false,"items":[{"accessTime":"...","contentType":"ALIDOC","docUrl":"https://alidocs.dingtalk.com/...","name":"团队测试表","nodeId":"...","nodeType":"file"}]}, "ok":true}
```

```bash
dws calendar +today
# → {"data":{"complete":true,"count":0,"events":[]},"ok":true}   （今天无日程时 events 为空数组）
```

```bash
dws aitable +base-list
# → {"bases":[{"baseId":"mExel2BLV54XNaDOUpxE3qB6Wgk9rpMq","baseName":"团队测试表"}],"count":1}
```

```bash
dws todo +get-my-tasks
# → {"data":{"count":1,"todos":[{"dueTime":1788227905323,"priority":20,"subject":"...","taskId":"56679802634"}]},"ok":true}
```

## 坑位

1. **无头/非交互环境下所有写操作命令必须带 `-y`**，否则会挂在确认提示上。
2. **发文件到单聊**：`+dm` 只能发文本/Markdown，发不了文件。文件用 `dws chat conversation-file upload --user <userId> --file <相对路径>`（上传到会话文件空间，不自动发消息），需要时再用 `+dm` 通知对方。
3. **`dws api`（raw OpenAPI）需要自有应用的 ClientID/Secret**，MCP 默认凭证登录不支持，别用它绕。
4. **文件路径参数多为"工作目录内的相对路径"**（如 `--file ./a.pdf`），先把文件放进当前工作目录再用相对路径。
5. 查人参数是 **`--query` 不是 `--keyword`**（`dws contact user search --query 王洪彬`，任务描述里常见的 `--keyword` 写法不存在）。
6. `oa +list-pending` 的 `--start/--end` 是 **epoch 毫秒**（13 位），不是秒。
7. 姓名解析到多人时 CLI 返回候选列表，**不要猜**，向任务发起人确认后再发。

## 边界

- 高危操作（解散群 `chat +chat-dismiss`、清空会话消息 `chat +conversation-clear-messages`、删钉盘文件 `drive +delete`、删 Base `aitable +base-delete` 等）**执行前必须在总结里显式提示，由任务发起人确认后才执行**。
- 不代用户登录；不主动修改他人日程/文档/审批，除非任务明确要求。
- 拿不准命令参数时跑 `dws <path> --help` 或 `dws schema --cli-path "<path>" --compact`，不要凭记忆编参数。
