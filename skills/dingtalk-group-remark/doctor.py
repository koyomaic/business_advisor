#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dingtalk-group-remark 本机自检 / 自动适配脚本 (doctor)

新机器装完后先跑: python doctor.py
  检查 → 自动修 → 报告还差什么

本 skill 依赖:
  - dws CLI(钉钉命令行,硬依赖)+ 本人扫码登录
  - 无需 python 第三方库
说明:分发包里【不含】真实群数据,只带 group_state.example.json。
     首次体检会据此初始化一个空的 group_state.json(你自己的基线)。
     首次跑"批量备注"时会拉你自己的群把它填满。
"""
import subprocess, json, sys, os, io, platform, shutil

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(SKILL_DIR, 'group_state.json')
EXAMPLE = os.path.join(SKILL_DIR, 'group_state.example.json')
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
    rc, out = run(['dws', 'chat', '+chat-list-all', '--help'])
    if 'chat-list-all' in out.lower() or 'cursor' in out.lower() or 'page' in out.lower():
        print('%s 子命令   : `dws chat +chat-list-all` 可用(命令未改名)' % OK)
    else:
        notes.append('`dws chat +chat-list-all` 帮助异常,若登录正常仍报错,核对命令是否改名')
        print('%s 子命令   : +chat-list-all 探测异常,已记提示' % WARN)

# ── 3. 登录状态 ──
section('钉钉登录状态 (必须本人扫码)')
if dws_path:
    rc, out = run(['dws', 'auth', 'status', '--format', 'json'])
    try:
        s = out.find('{'); e = out.rfind('}'); st = json.loads(out[s:e+1])
    except Exception:
        st = {}
    if st.get('authenticated') and st.get('token_valid'):
        print('%s 已登录   : %s / %s' % (OK, st.get('corp_name'), st.get('user_name')))
    else:
        print('%s 未登录/失效 → 本人操作: dws auth login' % BAD)
        blockers.append('执行 dws auth login 完成扫码登录')
else:
    print('%s 跳过(dws 未安装)' % WARN)

# ── 4. 状态文件初始化(自动修:据 example 建空基线)──
section('状态文件 group_state.json (增量同步用)')
if os.path.exists(STATE):
    try:
        with open(STATE, 'r', encoding='utf-8') as f:
            n = len(json.load(f).get('groups', {}))
        print('%s 已有本机基线(%d 个群),沿用' % (OK, n))
    except Exception:
        print('%s 状态文件损坏,将重建为空基线' % WARN)
        _write_empty = True
    else:
        _write_empty = False
else:
    print('%s 首次运行,无状态文件 → 初始化空基线' % OK)
    _write_empty = True

if '_write_empty' in dir() and _write_empty:
    try:
        empty = {'lastSyncAt': None, 'totalProcessed': 0, 'baselineAt': None,
                 'note': 'initialized by doctor - run mode 1 to build your own baseline',
                 'groups': {}}
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(empty, f, ensure_ascii=False, indent=2)
        print('%s 已初始化空基线 group_state.json — 首次"批量备注"会拉你自己的群填充。' % OK)
        if os.path.exists(EXAMPLE):
            print('   (结构参考随包的 group_state.example.json)')
    except Exception as ex:
        print('%s 初始化失败: %s' % (BAD, ex))
        blockers.append('手动创建 group_state.json,内容 {"groups":{}}')

# ── 5. 代理 & 路径 ──
section('网络 / 代理')
proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
print(('%s 检测到代理 %s(dws 直连即可,如遇钉钉访问失败先清代理)' % (WARN, proxy)) if proxy else ('%s 未检测到代理' % OK))

section('路径')
print('%s skill 目录: %s' % (OK, SKILL_DIR))

# ── 汇总 ──
section('结论')
if not blockers:
    print('%s 全部通过,skill 可用。首次用: 让 Claude "批量给我的钉钉群加备注"' % OK)
else:
    print('%s 还差 %d 项:' % (BAD, len(blockers)))
    for i, b in enumerate(blockers, 1):
        print('   %d. %s' % (i, b))
if notes:
    print('\n提示(不阻塞):')
    for n in notes:
        print('   - ' + n)
sys.exit(1 if blockers else 0)
