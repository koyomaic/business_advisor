#!/usr/bin/env bash
# tls-issue.sh — 用内部 CA 给其它机器签发中转服务服务器证书
#
# 用法:
#   scripts/tls-issue.sh <CA目录> <本机IP> [主机名] [输出目录]
# 示例:
#   scripts/tls-issue.sh /mnt/vol-eltaah12/workspace/shared/secrets/relay-tls 10.189.51.31 i-abc123 /etc/relay-tls
#
# CA目录需包含 ca.key + ca.pem（本服务器为 /mnt/vol-eltaah12/workspace/shared/secrets/relay-tls/）。
# 输出: <输出目录>/server.key (600) 和 server.pem (644)，SAN 含 本机IP/127.0.0.1/主机名/localhost，
#       供 relay-https.service 的 --ssl-keyfile/--ssl-certfile 使用。
#
# ⚠️ 安全须知:
#   - CA 私钥 (ca.key) 必须通过安全通道拷贝到签发机（scp 直连/加密介质），
#     绝不走共享区明文、聊天工具或邮件传播。
#   - ca.key / server.key 绝不进 git（仓库 .gitignore 已排除 *.key 与 relay-tls/），
#     签发完成后建议删除签发机上的 ca.key 副本。
#   - ca.pem 是公开文件，可随 skill 分发（客户端校验用）。
set -euo pipefail

CA_DIR="${1:?用法: tls-issue.sh <CA目录> <本机IP> [主机名] [输出目录]}"
HOST_IP="${2:?缺少本机IP}"
HOST_NAME="${3:-$(hostname)}"
OUT_DIR="${4:-.}"

[[ -f "$CA_DIR/ca.key" && -f "$CA_DIR/ca.pem" ]] || { echo "错误: $CA_DIR 下缺 ca.key/ca.pem" >&2; exit 1; }
mkdir -p "$OUT_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

openssl genrsa -out "$TMP/server.key" 2048 2>/dev/null
openssl req -new -key "$TMP/server.key" -subj "/CN=$HOST_NAME" -out "$TMP/server.csr"
cat > "$TMP/san.cnf" <<EOF
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$HOST_IP,IP:127.0.0.1,DNS:$HOST_NAME,DNS:localhost
EOF
openssl x509 -req -in "$TMP/server.csr" -CA "$CA_DIR/ca.pem" -CAkey "$CA_DIR/ca.key" \
  -CAcreateserial -days 3650 -sha256 -extfile "$TMP/san.cnf" -out "$TMP/server.pem" 2>/dev/null

install -m 600 "$TMP/server.key" "$OUT_DIR/server.key"
install -m 644 "$TMP/server.pem" "$OUT_DIR/server.pem"
openssl verify -CAfile "$CA_DIR/ca.pem" "$OUT_DIR/server.pem"
echo "已签发: $OUT_DIR/server.key (600), $OUT_DIR/server.pem (644), SAN=IP:$HOST_IP,IP:127.0.0.1,DNS:$HOST_NAME,DNS:localhost, 有效期 10 年"
