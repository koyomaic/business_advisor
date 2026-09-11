#!/usr/bin/env bash
# pack.sh — 在中转服务器本机生成成员技能包：team-agent-relay-<dws认证大脑名>-<版本>-<日期>.zip
#
# 用法: pack.sh [大脑名] [服务器IP] [输出目录]
#   大脑名   缺省读本机 dws auth status 的 user_name（本技能所代表的 dws 认证大脑）
#   服务器IP 缺省 hostname -I 第一个内网 IP；成员包 server = https://<IP>:8788
#   ca.pem   优先 $WORKSPACE/shared/secrets/relay-tls/ca.pem，缺失时从本机 8788 TLS 链提取
#
# 打包动作：拷贝源模板 SKILL.md/relay.py，写入 PACKAGE_BRAIN/DEFAULT_SERVER、
# frontmatter name=team-agent-relay-<大脑名>、身份/服务器说明块，附 ca.pem 后压缩。
# 产物不含本脚本。源模板（仓库 skills/team-agent-relay）保持通用，不随打包改动。
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRAIN="${1:-$(dws auth status 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["user_name"])' 2>/dev/null || true)}"
IP="${2:-$(hostname -I | awk '{print $1}')}"
OUT_DIR="${3:-$(pwd)}"
[ -n "$BRAIN" ] || { echo "错误: 无法确定大脑名（dws 未登录？），请显式传第 1 参" >&2; exit 1; }
[ -n "$IP" ] && [ "$IP" != "127.0.0.1" ] || { echo "错误: 无法确定服务器 IP，请显式传第 2 参" >&2; exit 1; }
SERVER="https://$IP:8788"
CA="${RELAY_CA:-${WORKSPACE:-/mnt/vol-eltaah12/workspace}/shared/secrets/relay-tls/ca.pem}"
if [ ! -f "$CA" ]; then
  echo "本机 ca.pem 缺失，从 $SERVER TLS 链提取..." >&2
  CA="$(mktemp)"
  echo | timeout 10 openssl s_client -connect "$IP:8788" -showcerts 2>/dev/null \
    | awk '/-----BEGIN CERTIFICATE-----/{n++} n==2{print} /-----END CERTIFICATE-----/&&n==2{exit}' > "$CA"
  openssl x509 -in "$CA" -noout -subject >/dev/null 2>&1 || { echo "错误: CA 提取失败" >&2; exit 1; }
fi
BRAIN="$BRAIN" SERVER="$SERVER" CA="$CA" SRC="$SRC" OUT_DIR="$OUT_DIR" python3 <<'PYEOF'
import datetime, hashlib, os, re, zipfile

brain = os.environ["BRAIN"]; server = os.environ["SERVER"]
ca = os.environ["CA"]; src = os.environ["SRC"]; out_dir = os.environ["OUT_DIR"]

relay = open(os.path.join(src, "relay.py"), encoding="utf-8").read()
skill = open(os.path.join(src, "SKILL.md"), encoding="utf-8").read()

ver = re.search(r'^__version__ = "([^"]+)"', relay, re.M).group(1)
relay, n1 = re.subn(r'^PACKAGE_BRAIN = ""', f'PACKAGE_BRAIN = "{brain}"', relay, flags=re.M)
relay, n2 = re.subn(r'^DEFAULT_SERVER = "[^"]+"', f'DEFAULT_SERVER = "{server}"', relay, flags=re.M)
assert n1 == 1 and n2 == 1, "relay.py 打点位缺失"

skill, n3 = re.subn(r'^name: team-agent-relay$', f'name: team-agent-relay-{brain}', skill, flags=re.M)
skill, n4 = re.subn(r'^# 团队中转服务$', f'# 团队中转服务（{brain}）', skill, flags=re.M)
identity = (f'本技能代表 dws 认证大脑 **「{brain}」**：所有任务由「{brain}」所在服务器的 '
            f'agent 执行，钉钉（dws）操作以其身份发出。打包时已写入服务器与 CA，无需手配。')
skill, n5 = re.subn(r'<!-- PACK:IDENTITY-START -->.*?<!-- PACK:IDENTITY-END -->',
                    identity, skill, flags=re.S)
server_block = f'- 服务器：`{server}`（「{brain}」专属中转，打包时已写入，无需手配）'
skill, n6 = re.subn(r'<!-- PACK:SERVER-START -->.*?<!-- PACK:SERVER-END -->',
                    server_block, skill, flags=re.S)
assert n3 == 1 and n4 == 1 and n5 == 1 and n6 == 1, "SKILL.md 打点位缺失"

pkg_dir = f"team-agent-relay-{brain}"
out = os.path.join(out_dir, f"{pkg_dir}-{ver}-{datetime.date.today():%Y%m%d}.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr(f"{pkg_dir}/SKILL.md", skill)
    z.writestr(f"{pkg_dir}/relay.py", relay)
    z.write(ca, f"{pkg_dir}/ca.pem")
sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
print(f"已打包: {out}")
print(f"  大脑={brain}  服务器={server}  版本={ver}  大小={os.path.getsize(out)}B  sha256={sha[:16]}…")
PYEOF
