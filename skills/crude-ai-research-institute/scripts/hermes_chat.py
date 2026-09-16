#!/usr/bin/env python3
"""hermes_chat.py — 正式环境 Hermes 原油AI研究院对话客户端.

把 Hermes 的 OpenAI 兼容 /v1/chat/completions 接口（SSE 流式）封装成
一次性 CLI 调用：内部聚合流式增量，输出完整回答文本。

凭证只从环境变量读取，不读任何 .env 文件：
  HERMES_API_TOKEN    Bearer token（必填）
  HERMES_BASE_URL     服务地址（必填，如 http://10.189.7.30:8642）
  HERMES_SESSION_KEY  会话密钥 / 用户标识（必填）
  HERMES_SESSION_ID   默认会话 ID（可选，不传则每次自动生成 uuid）
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_MODEL = "hermes-agent"


def load_env_value(key: str):
    val = os.environ.get(key)
    return val.strip() if val and val.strip() else None


def parse_sse_stream(resp):
    """逐行解析 SSE，聚合 delta.content；同时捕获 reasoning_content 与 usage。"""
    content_parts = []
    reasoning_parts = []
    usage = None
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if chunk.get("usage"):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning_parts.append(delta["reasoning_content"])
        msg = choice.get("message") or {}
        if msg.get("content") and not delta.get("content"):
            content_parts.append(msg["content"])
    return "".join(content_parts), "".join(reasoning_parts), usage


def call_hermes(args, payload):
    headers = {
        "Authorization": f"Bearer {args.token}",
        "X-Hermes-Session-Id": args.session_id,
        "X-Hermes-Session-Key": args.session_key,
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if payload.get("stream") else "application/json",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # Hermes 是内网服务，强制直连，无视 http_proxy/https_proxy 环境变量
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last_err = None
    for attempt in range(args.retries + 1):
        req = urllib.request.Request(args.base_url.rstrip("/") + "/v1/chat/completions",
                                     data=data, headers=headers, method="POST")
        try:
            resp = opener.open(req, timeout=args.timeout)
            with resp:
                if payload.get("stream"):
                    return parse_sse_stream(resp)
                body = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(body)
            choices = obj.get("choices") or []
            msg = (choices[0].get("message") or {}) if choices else {}
            return msg.get("content") or "", msg.get("reasoning_content") or "", obj.get("usage")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            hint = {401: "token 无效/过期，检查 HERMES_API_TOKEN",
                    403: "无权限，检查 HERMES_SESSION_KEY",
                    429: "触发限流，降低调用频率",
                    502: "网关上游不可用，Hermes 服务可能未启动，稍后再试",
                    504: "网关超时，Hermes 处理过久或服务异常"}.get(e.code, "")
            raise SystemExit(f"HTTP {e.code} from Hermes: {body} {hint}".strip())
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < args.retries:
                time.sleep(2 * (attempt + 1))
                continue
    raise SystemExit(f"无法连接 Hermes ({args.base_url})，已重试 {args.retries} 次: {last_err}")


def main():
    ap = argparse.ArgumentParser(description="调用正式环境 Hermes 原油AI研究院并返回完整回答")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--message", help="用户问题（单轮）")
    src.add_argument("--message-file", help="从文件读问题（长 prompt）")
    src.add_argument("--messages-json", help="完整 messages 数组 JSON（高级用法，覆盖 --message）")
    ap.add_argument("--session-id", default=None, help="会话 ID；不传自动生成，多轮追问时传回上一次的值")
    ap.add_argument("--session-key", default=None, help="会话密钥；默认读 HERMES_SESSION_KEY")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=None, help="服务地址；默认读环境变量 HERMES_BASE_URL（必填，无默认值）")
    ap.add_argument("--token", default=None, help="Bearer token；默认读 HERMES_API_TOKEN")
    ap.add_argument("--timeout", type=int, default=300, help="读超时秒数（agent 型后端较慢），默认 300")
    ap.add_argument("--retries", type=int, default=2, help="连接失败重试次数，默认 2")
    ap.add_argument("--no-stream", action="store_true", help="改用非流式请求")
    ap.add_argument("--format", default="text", choices=["text", "json"])
    args = ap.parse_args()

    args.token = args.token or load_env_value("HERMES_API_TOKEN")
    args.base_url = args.base_url or load_env_value("HERMES_BASE_URL")
    args.session_key = args.session_key or load_env_value("HERMES_SESSION_KEY")
    if not args.session_id:
        args.session_id = load_env_value("HERMES_SESSION_ID") or str(uuid.uuid4())

    if not args.token:
        raise SystemExit("缺少 HERMES_API_TOKEN：请设置环境变量")
    if not args.base_url:
        raise SystemExit("缺少 HERMES_BASE_URL：请设置环境变量（如 http://10.189.7.30:8642）")
    if not args.session_key:
        raise SystemExit("缺少 HERMES_SESSION_KEY：请设置环境变量")

    if args.messages_json:
        try:
            messages = json.loads(args.messages_json)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--messages-json 不是合法 JSON: {e}")
        if not isinstance(messages, list) or not messages:
            raise SystemExit("--messages-json 必须是非空 messages 数组")
    else:
        if args.message_file:
            text = pathlib.Path(args.message_file).read_text(encoding="utf-8")
        else:
            text = args.message
        messages = [{"role": "user", "content": text, "files": []}]

    payload = {"model": args.model, "messages": messages, "stream": not args.no_stream}

    t0 = time.time()
    content, reasoning, usage = call_hermes(args, payload)
    elapsed = round(time.time() - t0, 1)

    if args.format == "json":
        json.dump({"session_id": args.session_id, "content": content,
                   "reasoning": reasoning or None, "usage": usage, "elapsed_s": elapsed},
                  sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    elif not content.strip():
        raise SystemExit(f"Hermes 返回空内容（elapsed={elapsed}s, session_id={args.session_id}），"
                         "可用 --format json 查看 usage/reasoning 排查")
    else:
        sys.stdout.write(content.strip() + "\n")
        sys.stderr.write(f"[hermes] session_id={args.session_id} elapsed={elapsed}s "
                         f"(追问时传 --session-id {args.session_id} 可延续上下文)\n")


if __name__ == "__main__":
    main()
