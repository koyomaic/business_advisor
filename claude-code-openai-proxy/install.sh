#!/usr/bin/env bash
# Install the proxy as a systemd service and wire up Claude Code.
# Safe to re-run. Does NOT overwrite an existing config.json or settings.json.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE="$(command -v node)"
PORT="${PORT:-8790}"

echo "==> Install dir: $DIR"
echo "==> Node:        $NODE"

# 1) config.json
if [[ ! -f "$DIR/config.json" ]]; then
  cp "$DIR/config.example.json" "$DIR/config.json"
  chmod 600 "$DIR/config.json"
  echo "==> Created $DIR/config.json — EDIT IT with your baseURL / apiKey / model."
else
  echo "==> config.json already exists, leaving it untouched."
fi

# 2) systemd unit
UNIT=/etc/systemd/system/claude-proxy.service
sed -e "s#__DIR__#$DIR#g" -e "s#__NODE__#$NODE#g" \
  "$DIR/claude-proxy.service.example" > "$UNIT"
systemctl daemon-reload
systemctl enable --now claude-proxy.service
echo "==> systemd service 'claude-proxy' enabled + started."

# 3) Claude Code settings (printed, not auto-written, to avoid clobbering)
SETTINGS="$HOME/.claude/settings.json"
echo
echo "==> Add this \"env\" block to $SETTINGS (merge if it already exists):"
cat <<JSON
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:$PORT",
    "ANTHROPIC_AUTH_TOKEN": "dummy-proxy-ignores-it",
    "ANTHROPIC_MODEL": "<your-model-name>",
    "ANTHROPIC_SMALL_FAST_MODEL": "<your-model-name>"
  }
}
JSON
echo
echo "==> Verify:  systemctl status claude-proxy --no-highlight"
echo "==> Test:    claude -p 'say hi'"
