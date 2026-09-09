#!/usr/bin/env bash
# dws 登录态每小时刷新：直接在共享种子上操作（软链进临时 HOME，
# token 轮换原地发生在种子上，与 boot.sh notify_failure 同一份登录态，无复制/回写竞态）
# 输出：/var/log/dws-refresh.log（只记状态，不记令牌）
set -uo pipefail
LOG=/var/log/dws-refresh.log
SEED=/mnt/vol-eltaah12/workspace/shared/secrets/dws-cli-seed/dws-cli
OUT="$(mktemp /tmp/dws-refresh-out.XXXX)"
trap 'rm -f "$OUT"' EXIT

if [ -d "$SEED" ]; then
  work="$(mktemp -d /tmp/dws-refresh-XXXXXX)"
  mkdir -p "$work/.local/share"
  ln -s "$SEED" "$work/.local/share/dws-cli"
  HOME="$work" timeout 60 /usr/bin/dws auth status >"$OUT" 2>&1
  rc=$?
  rm -rf "$work"
else
  HOME=/root timeout 60 /usr/bin/dws auth status >"$OUT" 2>&1
  rc=$?
fi

ts="$(date '+%F %T')"
if [ "$rc" -eq 0 ] && grep -q '"authenticated"[[:space:]]*:[[:space:]]*true' "$OUT"; then
  uid="$(grep -o '"user_id"[[:space:]]*:[[:space:]]*"[^"]*"' "$OUT" | head -1 | cut -d'"' -f4)"
  exp="$(grep -o '"refresh_expires_at"[[:space:]]*:[[:space:]]*"[^"]*"' "$OUT" | head -1 | cut -d'"' -f4)"
  echo "[$ts] OK user=$uid refresh_expires=$exp" >>"$LOG"
  exit 0
else
  echo "[$ts] FAIL rc=$rc $(tr '\n' ' ' <"$OUT" | head -c 300)" >>"$LOG"
  exit 1
fi
