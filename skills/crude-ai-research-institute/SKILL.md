---
name: crude-ai-research-institute
description: "调用正式环境原油AI研究院（OpenAI 兼容 chat/completions API，SSE 流式）。当下游业务 agent 需要原油综合研判类回答（如今日日报、交易建议、事件影响分析、历史类比、情景推演）或多轮追问时调用。自动处理流式聚合、会话保持、凭证从环境变量读取。"
---

# 原油AI研究院对话

把正式环境原油AI研究院（OpenAI 兼容 `/v1/chat/completions`，`model=hermes-agent`）封装为一次性 CLI 调用。服务地址由环境变量 `HERMES_BASE_URL` 指定。脚本内部解析 SSE 流式响应并聚合为完整回答，调用方无需处理流。

## 能力说明

可回答原油相关的综合研判问题：

- 完整日报 / 今日结论 / 报告章节 / 研判依据
- 单边行情、月差交易、裂解价差的交易建议（固定表格：方向/入场/目标/止损）
- 事件影响分析（地缘/制裁/OPEC+/和谈/天气 → 传导链 → 油价方向）
- 历史复盘 / 历史类比 / 预测复盘归因 / 反向思考
- 假设情景推演（"如果某事件发生会怎样"）
- 触发重跑（rerun：单 agent 约 3 分钟、全系统约 10 分钟，异步）

单点价格 / 指标 / 供需数据查询，本地已有 `oil-futures-price` / `eta-data-fetcher` / `crude-oil-pandas-analyzer` 可用时优先本地调用（秒级、近零成本；研究院单次约 15~30s、约 20 万 prompt tokens）。

响应特征：复杂研判可达分钟级（默认超时 300s）；回答自带 `[数据源 | 采集时间]` 标注，价格带具体合约号（如 Brent M1）。

详细能力清单与边界见 `references/capability.md`。

## 前置要求

调用前必须设置以下环境变量（脚本只从环境变量取，不读任何 .env 文件，与运行环境无关）：

```
HERMES_API_TOKEN=...      # Bearer token（必填）
HERMES_SESSION_KEY=...    # 会话密钥/用户标识（必填；默认发起用户一卡通号）
HERMES_BASE_URL=...       # 服务地址（必填，如 http://10.189.7.30:8642）
HERMES_SESSION_ID=...     # 默认会话 ID（可选，不传则每次自动生成 uuid）
HERMES_SESSION_MAP=...    # 可选：用户名→一卡通号 JSON 映射，配合 RELAY_TASK_USER 自动归属
```

也可用 CLI 参数覆盖：`--token` / `--session-key` / `--base-url` / `--session-id`。

relay 机队机器上，必填变量已通过 `workspace/relay.env`（systemd `EnvironmentFile`）预注入任务进程环境：relay 任务内无需手动 export，直接调用即可。凭据真值只存于各机 relay.env（600），不进 git。

**会话密钥按终端身份自动归属**：relay 执行器会向任务环境注入 `RELAY_TASK_USER`（=任务归属用户）；脚本解析顺序为 `--session-key` > `HERMES_SESSION_MAP[RELAY_TASK_USER]`（用户名→一卡通号映射，存于 relay.env）> `HERMES_SESSION_KEY`（本机默认发起用户一卡通号）。机器账号（如白露）无工号、不入映射，自动回落默认值；需临时指定归属时仍可用 `--session-key <一卡通号>` 覆盖。

## 命令

```bash
# 单轮提问（默认输出完整回答文本）
python3 {baseDir}/scripts/hermes_chat.py --message "今天原油怎么看"

# 长问题从文件读
python3 {baseDir}/scripts/hermes_chat.py --message-file /tmp/question.txt

# 结构化输出（含 session_id / usage / 耗时 / reasoning）
python3 {baseDir}/scripts/hermes_chat.py --message "..." --format json

# 多轮追问：传回上一轮输出的 session_id，延续研究院侧上下文
python3 {baseDir}/scripts/hermes_chat.py --message "再看看WTI呢" --session-id <上轮session_id>

# 完全自定义 messages 数组（高级用法）
python3 {baseDir}/scripts/hermes_chat.py --messages-json '[{"role":"user","content":"...","files":[]}]'
```

## 输出

- **text（默认）**：完整回答文本（stdout）。session_id 与耗时打到 stderr，不污染管道。
- **json**：`{session_id, content, reasoning?, usage?, elapsed_s}`。

## 注意事项

- **这是正式环境原油AI研究院**。下游 agent 应提出具体、完整的问题，一次问清，避免高频轮询和闲聊式多轮（每轮都是真实的 agent 运行成本）。
- **响应可能很慢**（研究院内部是完整 agent 链路），默认读超时 300s，可用 `--timeout` 调整；连接失败自动重试 2 次。
- **会话即上下文**：同一 `--session-id` 的多次调用共享研究院侧对话历史；不同业务 agent 请用不同 session-id 隔离，避免上下文串味。
- `files` 字段（传附件）暂未封装，如需支持先确认服务端的文件编码格式再扩展脚本。

## 故障排查

| 现象 | 原因与处理 |
|------|-----------|
| HTTP 401 | `HERMES_API_TOKEN` 无效/过期 |
| HTTP 403 | `HERMES_SESSION_KEY` 无权限 |
| HTTP 429 | 触发限流，降低调用频率，勿重试 |
| 连接失败 | 服务不可用或网络不通，脚本已重试 2 次 |
| 返回空内容 | 用 `--format json` 看 usage/reasoning；确认问题是否过于模糊 |
| 想看原始流 | 临时排查可用 curl 直连（见下） |

原始接口参考（排查用）：

```bash
curl --location --request POST "$HERMES_BASE_URL/v1/chat/completions" \
  --header "Authorization: Bearer $HERMES_API_TOKEN" \
  --header "X-Hermes-Session-Id: test-session" \
  --header "X-Hermes-Session-Key: $HERMES_SESSION_KEY" \
  --header "Content-Type: application/json" \
  --data-raw '{"model":"hermes-agent","messages":[{"role":"user","content":"ping","files":[]}],"stream":true}'
```
