#!/usr/bin/env bash
# dws 凭证自动续期：独立 HOME 从种子初始化 -> dws auth status 静默续期 -> 回写种子（回写前备份旧种子）
# 由 dws-renew.timer 每 6 小时触发一次；也可手动执行本脚本。
set -u

WORKSPACE="/mnt/vol-eltaah12/workspace"
SEED_DIR="$WORKSPACE/shared/secrets/dws-cli-seed"
SEED="$SEED_DIR/dws-cli"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG="$SEED_DIR/dws-renew.log"

log() {
  local line="[$(date '+%F %T')] $*"
  echo "$line"
  { echo "$line"; } >> "$LOG" 2>/dev/null || true
}

if ! command -v dws >/dev/null 2>&1; then
  log "dws binary not found, skip"
  exit 1
fi

if [[ ! -d "$SEED" ]]; then
  log "seed missing, skip: $SEED"
  exit 0
fi

# 独立 HOME（每次全新，用完即删自己的临时目录）
WORK="$(mktemp -d /tmp/dws-renew-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
export HOME="$WORK/home"
export XDG_DATA_HOME="$WORK/data"
mkdir -p "$HOME/.local/share"

cp -a "$SEED" "$HOME/.local/share/dws-cli"
chmod 700 "$HOME/.local/share/dws-cli"

OUT="$(dws auth status 2>&1)"
RC=$?
if (( RC != 0 )) || ! grep -q '"authenticated": true' <<<"$OUT"; then
  log "renew FAILED (rc=$RC), seed NOT updated: $(head -c 300 <<<"$OUT" | tr '\n' ' ')"
  exit 1
fi

# 备份旧种子（全量保留，不删除）
cp -a "$SEED" "$SEED_DIR/dws-cli.bak-$STAMP"

# 回写：覆盖同名文件，不删除种子内其他文件
cp -a "$HOME/.local/share/dws-cli/." "$SEED/"
chmod 700 "$SEED"
find "$SEED" -maxdepth 1 -type f -exec chmod 600 {} +

EXPIRES="$(grep -o '"expires_at": "[^"]*"' <<<"$OUT" | head -1)"
log "renew OK, seed updated (backup: dws-cli.bak-$STAMP) $EXPIRES"
