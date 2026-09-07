#!/usr/bin/env python3
"""最小 MCP stdio 服务器：暴露 ping 工具，返回固定文本 MCP-PING-OK。

用于验证中转服务 shared/mcp 共享通道（stdio 换行分隔 JSON-RPC 2.0）。
"""
import json
import sys


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        mid = m.get("id")
        method = m.get("method", "")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": (m.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ping", "version": "0.1.0"},
            }})
        elif method in ("notifications/initialized", "initialized"):
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": "ping",
                 "description": "返回固定文本 MCP-PING-OK（共享 MCP 通道验证工具）",
                 "inputSchema": {"type": "object", "properties": {}}},
            ]}})
        elif method == "tools/call":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "MCP-PING-OK"}],
                "isError": False,
            }})
        elif method == "resources/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"resources": []}})
        elif method == "prompts/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"prompts": []}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "result": {}})


if __name__ == "__main__":
    main()
