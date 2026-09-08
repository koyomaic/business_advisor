#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="/mnt/vol-eltaah12/workspace"
BACKUP_DIR="/mnt/vol-eltaah12/backup"
KEEP=3

STAMP="$(date +%Y%m%d-%H%M)"
DEST="$BACKUP_DIR/relay-backup-$STAMP.tar.gz"
STAGE="$(mktemp -d /tmp/relay-backup-stage-XXXXXX)"

trap 'rm -rf "$STAGE"' EXIT
trap 'rc=$?; printf "{\"ok\":false,\"error\":\"backup failed at line $LINENO (exit $rc)\"}\n"; exit "$rc"' ERR

fail() {
  printf '{"ok":false,"error":"%s"}\n' "$1"
  exit 1
}

[[ -d "$WORKSPACE" ]] || fail "workspace not found: $WORKSPACE"

# DB 模式：relay.env 的 RELAY_DB 为 postgresql:// URL 时走 pg_dump，否则/缺省走 SQLite 快照
# RELAY_BACKUP_SKIP_DB=1：DB 备份由外部负责（如云管理部门统一备份 PG），本机只备工作区文件
RELAY_DB="$(sed -n 's/^RELAY_DB=//p' "$WORKSPACE/relay.env" 2>/dev/null | tail -1 || true)"
SKIP_DB="$(sed -n 's/^RELAY_BACKUP_SKIP_DB=//p' "$WORKSPACE/relay.env" 2>/dev/null | tail -1 || true)"

mkdir -p "$BACKUP_DIR"

WARNING=""
DB_ARGS=()
DB_MODE="sqlite"
if [[ "$SKIP_DB" == "1" ]]; then
  # 不做 DB 快照；历史 SQLite 文件若仍在则一并归档（本地文件，非外部备份范围）
  DB_MODE="skipped(external)"
  if [[ -f "$WORKSPACE/relay.db" ]]; then
    DB_ARGS+=(-C "$WORKSPACE" relay.db)
  fi
elif [[ "$RELAY_DB" == postgres*://* ]]; then
  DB_MODE="pg_dump"
  command -v pg_dump >/dev/null 2>&1 || fail "pg_dump not found (install postgresql-client)"
  pg_dump --dbname="$RELAY_DB" -Fc -f "$STAGE/relay.pg.dump" || fail "pg_dump failed"
  pg_restore --list "$STAGE/relay.pg.dump" >/dev/null 2>&1 || fail "pg_dump archive verification failed"
  DB_ARGS+=(-C "$STAGE" relay.pg.dump)
  # 历史 SQLite 库若仍在，一并归档（切换 PG 前的旧数据）
  if [[ -f "$WORKSPACE/relay.db" ]]; then
    DB_ARGS+=(-C "$WORKSPACE" relay.db)
  fi
else
  [[ -f "$WORKSPACE/relay.db" ]] || fail "relay.db not found in $WORKSPACE"
  # relay.db: consistent snapshot via sqlite3 .backup when available, else cp (with warning)
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$WORKSPACE/relay.db" ".backup $STAGE/relay.db"
  else
    WARNING="sqlite3 CLI not found; relay.db copied with cp (snapshot may not be consistent)"
    cp "$WORKSPACE/relay.db" "$STAGE/relay.db"
    printf '%s\n' "WARNING: $WARNING" >&2
  fi
  DB_ARGS+=(-C "$STAGE" relay.db)
fi

# package: shared/ + relay.log + relay.env from workspace, DB snapshot from staging
# （RELAY_BACKUP_SKIP_DB=1 时 DB_ARGS 可能为空，仅工作区文件）
if (( ${#DB_ARGS[@]} )); then
  tar -czf "$DEST" -C "$WORKSPACE" shared relay.log relay.env "${DB_ARGS[@]}"
else
  tar -czf "$DEST" -C "$WORKSPACE" shared relay.log relay.env
fi
chmod 600 "$DEST"

# verify archive is readable
if ! tar -tzf "$DEST" >/dev/null; then
  mv "$DEST" "$DEST.failed"
  fail "tar verification failed: $DEST"
fi

# retention: keep newest KEEP archives (by filename); failed .failed archives count too
mapfile -t ALL < <(find "$BACKUP_DIR" -maxdepth 1 -name 'relay-backup-*.tar.gz*' -printf '%f\n' | sort)
TOTAL="${#ALL[@]}"
DELETED=0
if (( TOTAL > KEEP )); then
  for f in "${ALL[@]:0:$(( TOTAL - KEEP ))}"; do
    rm -f "$BACKUP_DIR/$f"
    DELETED=$(( DELETED + 1 ))
  done
fi
KEPT=$(( TOTAL - DELETED ))

SIZE="$(stat -c %s "$DEST")"
if [[ -n "$WARNING" ]]; then
  printf '{"ok":true,"file":"%s","size_bytes":%s,"kept":%s,"db":"%s","warning":"%s"}\n' "$DEST" "$SIZE" "$KEPT" "$DB_MODE" "$WARNING"
else
  printf '{"ok":true,"file":"%s","size_bytes":%s,"kept":%s,"db":"%s"}\n' "$DEST" "$SIZE" "$KEPT" "$DB_MODE"
fi
