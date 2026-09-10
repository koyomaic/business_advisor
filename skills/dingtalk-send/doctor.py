#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dingtalk-send 本机自检 / 自动适配脚本 (doctor)

新机器装完后先跑: python doctor.py
  检查 → 自动修 → 报告还差什么

本 skill 依赖:
  - dws CLI(钉钉命令行,硬依赖)+ 本人扫码登录
  - 无需 python 第三方库
说明:本 skill 不写死任何人。"发我/本人" = 当前登录 dws 的账号。
     doctor 会验证能否用 `dws contact get-self` 取到你的身份,
     并把 userId 缓存到 identity.local.json(不随包分发)。
"""
import subprocess, json, sys, os, io, platform, shutil

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
IDENTITY = os.path.join(SKILL_DIR, 'identity.local.json')
OK, WARN, BAD = '✅', '⚠️ ', '❌'
blockers, notes = [], []


def run(cmd, timeout=90):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout, shell=True)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return -1, str(e)


def section(t):
    print('\n' + '─' * 60); print('▍ ' + t)


# ── 1. 基础环境 ──
section('基础环境')
print('%s OS       : %s %s' % (OK, platform.system(), platform.release()))
print('%s Python   : %s' % (OK, platform.python_version()))

# ── 2. dws CLI ──
section('dws CLI (钉钉命令行 · 底座)')
dws_path = shutil.which('dws')
if not dws_path:
    print('%s 没找到 dws 命令 — 硬依赖,先装并加 PATH,重开终端再跑。' % BAD)
    blockers.append('安装 dws CLI 并确保在 PATH 中')
else:
    print('%s dws 路径 : %s' % (OK, dws_path))
    rc, out = run(['dws', '--version'])
    print('%s dws 版本 : %s' % (OK, out.strip().splitlines()[0] if out.strip() else '(未知)'))

# ── 3. 登录状态 ──
section('钉钉登录状态 (必须本人扫码)')
authed = False
if dws_path:
    rc, out = run(['dws', 'auth', 'status', '--format', 'json'])
    try:
        s = out.find('{'); e = out.rfind('}'); st = json.loads(out[s:e+1])
    except Exception:
        st = {}
    if st.get('authenticated') and st.get('token_valid'):
        authed = True
        print('%s 已登录   : %s / %s' % (OK, st.get('corp_name'), st.get('user_name')))
    else:
        print('%s 未登录/失效 → 本人操作: dws auth login' % BAD)
        blockers.append('执行 dws auth login 完成扫码登录')
else:
    print('%s 跳过(dws 未安装)' % WARN)

# ── 4. 身份探测 + 缓存(自动修:取 userId 存 identity.local.json)──
section('本人身份 (发"我"时的收件人)')
if authed:
    rc, out = run(['dws', 'contact', 'get-self', '--format', 'json'])
    uid = None
    try:
        s = out.find('{'); e = out.rfind('}'); d = json.loads(out[s:e+1])
        r = (d.get('result') or [{}])
        r0 = r[0] if isinstance(r, list) and r else (r if isinstance(r, dict) else {})
        uid = r0.get('userId') or (r0.get('orgEmployeeModel') or {}).get('userId')
    except Exception:
        pass
    if uid:
        print('%s 已取到本人 userId = %s' % (OK, uid))
        try:
            with open(IDENTITY, 'w', encoding='utf-8') as f:
                json.dump({'userId': str(uid), 'source': 'dws contact get-self'}, f, ensure_ascii=False, indent=2)
            print('%s 已缓存到 identity.local.json(不随包分发)' % OK)
        except Exception as ex:
            notes.append('写 identity.local.json 失败: %s(不阻塞,运行时会再探测)' % ex)
    else:
        print('%s get-self 未取到 userId — 发纯文本给"我"时 skill 会自行再探测,不阻塞。' % WARN)
        notes.append('get-self 未解析到 userId;发富媒体给本人需 openDingTalkId,skill 运行时会用 aisearch 补取。')
else:
    print('%s 跳过(未登录)' % WARN)

# ── 5. 代理(自动:发文件前会清代理)──
section('网络 / 代理')
proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
if proxy:
    print('%s 检测到代理 %s — 发文件走企业 OSS,skill 发送前会清代理,无需手动处理。' % (WARN, proxy))
else:
    print('%s 未检测到代理' % OK)

section('路径')
print('%s skill 目录: %s' % (OK, SKILL_DIR))

# ── 汇总 ──
section('结论')
if not blockers:
    print('%s 全部通过,skill 可用。自测: 让 Claude "把某个文件发我"。' % OK)
else:
    print('%s 还差 %d 项:' % (BAD, len(blockers)))
    for i, b in enumerate(blockers, 1):
        print('   %d. %s' % (i, b))
if notes:
    print('\n提示(不阻塞):')
    for n in notes:
        print('   - ' + n)
sys.exit(1 if blockers else 0)
