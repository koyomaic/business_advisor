#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dingtalk-chat-digest 本机自检 / 自动适配脚本 (doctor)

新机器装完后先跑: python doctor.py
  检查 → 自动修 → 报告还差什么

本 skill 依赖:
  - dws CLI(钉钉命令行,硬依赖)+ 本人扫码登录
  - python
  - python-docx(仅 make_report.py 出 Word 时需要;HTML 报告不需要)
"""
import subprocess, json, sys, os, io, platform, shutil, importlib.util

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
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
if sys.version_info < (3, 7):
    notes.append('Python <3.7,建议升级到 3.8+')

# ── 2. dws CLI ──
section('dws CLI (钉钉命令行 · 底座)')
dws_path = shutil.which('dws')
if not dws_path:
    print('%s 没找到 dws 命令 — 本 skill 硬依赖,必须先装并加入 PATH,重开终端再跑。' % BAD)
    blockers.append('安装 dws CLI 并确保在 PATH 中')
else:
    print('%s dws 路径 : %s' % (OK, dws_path))
    rc, out = run(['dws', '--version'])
    print('%s dws 版本 : %s' % (OK, out.strip().splitlines()[0] if out.strip() else '(未知)'))
    rc, out = run(['dws', 'chat', '+search-msg', '--help'])
    if 'search-msg' in out.lower() or 'sender' in out.lower():
        print('%s 子命令   : `dws chat +search-msg` 可用(命令未改名)' % OK)
    else:
        notes.append('`dws chat +search-msg` 帮助异常,若登录正常仍报错,核对命令是否改名(记忆:search 曾并入 big-search)')
        print('%s 子命令   : +search-msg 探测异常,已记提示' % WARN)

# ── 3. 登录状态 ──
section('钉钉登录状态 (专属:必须本人扫码)')
if dws_path:
    rc, out = run(['dws', 'auth', 'status', '--format', 'json'])
    try:
        s = out.find('{'); e = out.rfind('}'); st = json.loads(out[s:e+1])
    except Exception:
        st = {}
    if st.get('authenticated') and st.get('token_valid'):
        print('%s 已登录   : %s / %s (userId=%s)' % (OK, st.get('corp_name'), st.get('user_name'), st.get('user_id')))
    else:
        print('%s 未登录/失效 → 本人操作: dws auth login (脚本无法代劳,token 绑你的账号)' % BAD)
        blockers.append('执行 dws auth login 完成扫码登录')
else:
    print('%s 跳过(dws 未安装)' % WARN)

# ── 4. python-docx(自动修:可自动 pip 装)──
section('Python 依赖 · python-docx (仅出 Word 报告需要)')
if importlib.util.find_spec('docx'):
    print('%s python-docx 已安装(可出 Word 报告)' % OK)
else:
    print('%s python-docx 未安装 — HTML 报告不受影响;要出 Word 才需要。尝试自动安装...' % WARN)
    rc, out = run([sys.executable, '-m', 'pip', 'install', 'python-docx', '-q'])
    if rc == 0 and importlib.util.find_spec('docx'):
        print('%s 已自动安装 python-docx' % OK)
    else:
        notes.append('自动装 python-docx 失败,要出 Word 请手动: pip install python-docx(HTML 报告不受影响)')
        print('%s 自动安装失败,已记提示(不阻塞:HTML 报告仍可用)' % WARN)

# ── 5. 代理 ──
section('网络 / 代理')
proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
if proxy:
    print('%s 检测到代理 %s — 脚本运行时会自动清代理直连钉钉/OSS,无需手动处理。' % (WARN, proxy))
else:
    print('%s 未检测到代理' % OK)

# ── 6. 路径 & 脚本就位 ──
section('路径自适配 & 脚本完整性')
print('%s skill 目录: %s' % (OK, SKILL_DIR))
missing = [f for f in ('make_report.py', 'make_report_html.py') if not os.path.exists(os.path.join(SKILL_DIR, f))]
if missing:
    print('%s 缺脚本   : %s — skill 包不完整' % (BAD, ', '.join(missing)))
    blockers.append('缺失 %s,重新拉取完整 skill 包' % ', '.join(missing))
else:
    print('%s 报告脚本 : make_report.py / make_report_html.py 就位' % OK)
    try:
        with open(os.path.join(SKILL_DIR, 'local.config.json'), 'w', encoding='utf-8') as f:
            json.dump({'skill_dir': SKILL_DIR, 'python': sys.executable}, f, ensure_ascii=False, indent=2)
        print('%s 已生成   : local.config.json(本机实际路径)' % OK)
    except Exception as ex:
        notes.append('写 local.config.json 失败: %s' % ex)

# ── 汇总 ──
section('结论')
if not blockers:
    print('%s 全部通过,skill 可用。自测: 让 Claude "汇总我和某人近三天的单聊发我"' % OK)
else:
    print('%s 还差 %d 项:' % (BAD, len(blockers)))
    for i, b in enumerate(blockers, 1):
        print('   %d. %s' % (i, b))
if notes:
    print('\n提示(不阻塞):')
    for n in notes:
        print('   - ' + n)
sys.exit(1 if blockers else 0)
