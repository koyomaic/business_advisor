# claude-code-openai-proxy

让 **Claude Code** 使用任意 **OpenAI 兼容** 的大模型（例如 opencode 的默认模型）。

Claude Code 只会说 Anthropic Messages API，而很多自建 / 第三方模型端点（vLLM、new-api、one-api 等）只提供 OpenAI Chat Completions API。本项目是一个**零依赖**的本地转换代理，在两种协议之间做双向翻译，让 `claude` 命令直接用上这些模型。

> 一个 Node 文件，无需 `npm install`。支持流式、工具调用（function calling）、多轮 `tool_result` 回传。

---

## 工作原理

```
┌────────────┐   Anthropic Messages API    ┌───────────────┐   OpenAI Chat Completions   ┌──────────────┐
│ Claude Code │ ──────────────────────────> │  本代理 (:8790) │ ──────────────────────────> │  模型端点      │
│  (claude)   │ <────────────────────────── │  协议双向翻译    │ <────────────────────────── │ vLLM/new-api │
└────────────┘        Anthropic 格式         └───────────────┘        OpenAI 格式           └──────────────┘
```

代理负责：

| 方向 | 转换内容 |
| --- | --- |
| 请求 Anthropic → OpenAI | `system`（含 SDK 注入的多条 system，统一合并到最前）、`messages`、`tools` / `input_schema` → `functions`、`tool_use` → `tool_calls`、`tool_result` → `role:tool`、`stop_sequences`、`temperature` 等 |
| 响应 OpenAI → Anthropic | `choices[].message` → `content[]`（`text` / `tool_use`）、`finish_reason` → `stop_reason`、`usage` 字段映射 |
| 流式 SSE | OpenAI `chat.completion.chunk` → Anthropic `message_start` / `content_block_start` / `content_block_delta`（`text_delta`、`input_json_delta`）/ `message_delta` / `message_stop` |

---

## 环境要求

- Node.js ≥ 18（使用内置 `fetch`，无需任何第三方包）
- 一个 OpenAI 兼容的模型端点（`/v1/chat/completions`），且支持 function calling
- Linux + systemd（用于开机自启；也可手动前台运行）

---

## 快速开始

### 1. 配置

```bash
cp config.example.json config.json
chmod 600 config.json      # 里面有密钥，务必收紧权限
```

编辑 `config.json`：

```json
{
  "host": "127.0.0.1",
  "port": 8790,
  "baseURL": "http://your-endpoint/v1",
  "apiKey": "sk-xxxxxxxx",
  "model": "your-model-name"
}
```

也可以用环境变量覆盖（优先级：**环境变量 > config.json > 默认值**）：

| 环境变量 | 对应字段 | 默认 |
| --- | --- | --- |
| `PROXY_HOST` | `host` | `127.0.0.1` |
| `PROXY_PORT` | `port` | `8790` |
| `UPSTREAM_BASE_URL` | `baseURL` | —（必填） |
| `UPSTREAM_API_KEY` | `apiKey` | —（必填） |
| `UPSTREAM_MODEL` | `model` | —（必填） |
| `PROXY_DEBUG` | 打印每次请求的 role 序列并 dump 转换后的 body 到 `/tmp/claude_proxy_last.json` | 关闭 |

### 2. 运行

前台试跑：

```bash
node proxy.mjs
```

或用脚本装成 systemd 服务（开机自启、崩溃自动重启）：

```bash
sudo bash install.sh
```

### 3. 让 Claude Code 指向代理

编辑 `~/.claude/settings.json`，加入 `env`：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8790",
    "ANTHROPIC_AUTH_TOKEN": "dummy-proxy-ignores-it",
    "ANTHROPIC_MODEL": "your-model-name",
    "ANTHROPIC_SMALL_FAST_MODEL": "your-model-name",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "262144"
  }
}
```

说明：
- 代理**忽略**客户端传来的鉴权头，统一用 `config.json` 里的 `apiKey` 访问上游，所以 `ANTHROPIC_AUTH_TOKEN` 填任意非空值即可（用于避免 Claude Code 走 OAuth 登录）。
- 代理会把请求里的模型名**强制改写**为 `config.json` 的 `model`，因此 `ANTHROPIC_MODEL` 主要影响界面显示与 token 统计。
- `CLAUDE_CODE_MAX_CONTEXT_TOKENS` 设为模型真实上下文长度，可消除 “unrecognized model / 200k 假设” 的告警并让自动压缩更准确。

### 4. 验证

```bash
claude -p "Reply with exactly one word: pong"
```

---

## 手动 systemd（不用 install.sh）

```bash
sudo sed -e "s#__DIR__#$(pwd)#g" -e "s#__NODE__#$(command -v node)#g" \
  claude-proxy.service.example > /etc/systemd/system/claude-proxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now claude-proxy
```

管理命令：

```bash
systemctl status  claude-proxy      # 状态
systemctl restart claude-proxy      # 重启
journalctl -u claude-proxy -f       # 实时日志（或 tail -f proxy.log）
```

---

## 直接测试代理（不经过 Claude Code）

非流式：

```bash
curl -s http://127.0.0.1:8790/v1/messages \
  -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
  -d '{"model":"x","max_tokens":64,"messages":[{"role":"user","content":"say pong"}]}'
```

流式：

```bash
curl -sN http://127.0.0.1:8790/v1/messages \
  -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
  -d '{"model":"x","max_tokens":64,"stream":true,"messages":[{"role":"user","content":"count to 3"}]}'
```

工具调用：

```bash
curl -s http://127.0.0.1:8790/v1/messages \
  -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' \
  -d '{"model":"x","max_tokens":256,
       "tools":[{"name":"calculator","description":"multiply","input_schema":{"type":"object","properties":{"a":{"type":"number"},"b":{"type":"number"}},"required":["a","b"]}}],
       "messages":[{"role":"user","content":"Compute 23*7 with the calculator tool."}]}'
```

代理还实现了 `POST /v1/messages/count_tokens`（按字符数粗估）和 `GET /v1/models`（返回配置的模型），以满足 Claude Code 的辅助调用。

---

## 已知限制

- **思维链（reasoning）**：部分模型（如 Qwen 系）会把推理放在独立的 `reasoning` 字段。代理只转发正式回答 `content`，丢弃 `reasoning`，以避免与 Claude Code 的 extended-thinking（需要签名）冲突。
- **`unrecognized_model` 提示**：因为模型名不在 Claude Code 内置目录里，启动时会打印一行 `[claude-code:unrecognized_model]` 提示，属正常现象、不影响使用。
- **system 合并**：上游要求 system 只能在最前，故 SDK 在对话中途注入的 system 内容会被统一合并到开头的单条 system 消息。
- **图像**：`image` 内容块按 OpenAI `image_url`（base64 data URL 或 http URL）转发，具体是否生效取决于上游模型是否支持多模态。

---

## 安全

- `config.json` 含明文密钥，已在 `.gitignore` 中排除，**切勿提交**。
- 建议 `chmod 600 config.json`，并让代理只监听 `127.0.0.1`。

---

## License

MIT
