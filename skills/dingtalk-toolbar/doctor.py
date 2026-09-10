#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dingtalk-toolbar 本机自检 / 自动适配脚本 (doctor)

新机器装完这个 skill 后,先跑一遍:
    python doctor.py

它做三件事:
  1) 检查  — 探测 OS / Python / dws / 登录状态 / 依赖
  2) 自动修 — 能自动配的当场配好(清代理规则、生成本机路径配置)
  3) 报告  — 配不了的(主要是"扫码登录")当场给出下一步命令

设计原则:能机器搞定的绝不麻烦人;必须人来的(登录、专属数据)只做"引导",不替你猜。
退出码: 0=全绿可用; 1=有阻塞项(通常是没登录/没装 dws)需按提示处理。
"""
import subprocess, json, sys, os, io, platform, shutil

# 统一 UTF-8 输出(Windows 控制台默认 GBK 会乱码)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
OK, WARN, BAD = '✅', '⚠️ ', '❌'
blockers = []   # 阻塞项(必须人处理)
notes = []      # 提示项(不阻塞)


def run(cmd, timeout=90):
    """跑命令,返回 (returncode, stdout+stderr)。"""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace',
                           timeout=timeout, shell=True)
        return p.returncode, (p.stdout or '') + (p.stderr or '')
    except Exception as e:
        return -1, str(e)


def section(t):
    print('\n' + '─' * 60)
    print('▍ ' + t)


# ── 1. 基础环境 ────────────────────────────────────────────
section('基础环境')
osname = platform.system()
print('%s OS       : %s %s' % (OK, osname, platform.release()))
print('%s Python   : %s (%s)' % (OK, platform.python_version(), sys.executable))
if sys.version_info < (3, 7):
    notes.append('Python 版本偏低(<3.7),建议升级到 3.8+')

# ── 2. dws CLI ─────────────────────────────────────────────
section('dws CLI (钉钉命令行 · 本 skill 的底座)')
dws_path = shutil.which('dws')
if not dws_path:
    print('%s 没找到 dws 命令。' % BAD)
    print('   这是本 skill 的硬依赖,必须先装。安装后重开终端再跑本脚本。')
    blockers.append('安装 dws CLI 并确保在 PATH 中')
else:
    print('%s dws 路径 : %s' % (OK, dws_path))
    rc, out = run(['dws', '--version'])
    ver = out.strip().splitlines()[0] if out.strip() else '(未知)'
    print('%s dws 版本 : %s' % (OK, ver))
    # 命令没改名校验:toolbar 依赖 `dws chat toolbar`
    rc, out = run(['dws', 'chat', 'toolbar', '--help'])
    if 'toolbar' in out.lower() and ('list' in out.lower() or 'create' in out.lower()):
        print('%s 子命令   : `dws chat toolbar` 可用(命令未改名)' % OK)
    else:
        print('%s 子命令   : `dws chat toolbar` 探测异常,可能改过名/未登录' % WARN)
        notes.append('`dws chat toolbar` 帮助异常,若下面登录正常仍报错,核对命令是否改名')

# ── 3. 登录状态(必须本人扫码,脚本不能代劳)────────────────
section('钉钉登录状态 (专属:必须用你自己的账号扫码)')
if dws_path:
    rc, out = run(['dws', 'auth', 'status', '--format', 'json'])
    try:
        s = out.find('{'); e = out.rfind('}')
        st = json.loads(out[s:e+1])
    except Exception:
        st = {}
    if st.get('authenticated') and st.get('token_valid'):
        print('%s 已登录   : %s / %s (userId=%s)' % (
            OK, st.get('corp_name'), st.get('user_name'), st.get('user_id')))
        print('   token 有效期至 %s' % st.get('expires_at', '?'))
    else:
        print('%s 未登录或 token 失效。' % BAD)
        print('   👉 这一步必须你本人操作(token 绑定你的钉钉账号),脚本无法代劳:')
        print('        dws auth login')
        print('   登录成功后重新跑一遍 doctor 即可。')
        blockers.append('执行 dws auth login 完成扫码登录')
else:
    print('%s 跳过(dws 未安装)' % WARN)

# ── 4. 代理规则(自动修:写进说明,脚本运行时已自动清理)──────
section('网络 / 代理')
proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
if proxy:
    print('%s 检测到系统代理: %s' % (WARN, proxy))
    print('   toolbar.py 运行时会自动清理代理并置 NO_PROXY=*(钉钉/OSS 直连),无需手动处理。')
else:
    print('%s 未检测到代理环境变量' % OK)

# ── 5. 路径自适配(自动修:本 skill 无硬编码用户路径,自定位)──
section('路径自适配')
print('%s skill 目录: %s' % (OK, SKILL_DIR))
tb = os.path.join(SKILL_DIR, 'toolbar.py')
if os.path.exists(tb):
    print('%s 辅助脚本 : toolbar.py 就位(调用时用本目录路径,不依赖固定盘符)' % OK)
    # 生成一份本机配置,供 SKILL.md 示例/其它入口引用,免得手改写死的用户目录
    cfg = {'skill_dir': SKILL_DIR,
           'toolbar_py': tb,
           'python': sys.executable}
    cfg_path = os.path.join(SKILL_DIR, 'local.config.json')
    try:
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print('%s 已生成   : local.config.json(本机实际路径,替代文档里写死的用户目录)' % OK)
    except Exception as ex:
        notes.append('写 local.config.json 失败: %s' % ex)
else:
    print('%s 没找到 toolbar.py,skill 包可能不完整' % BAD)
    blockers.append('toolbar.py 缺失,重新拉取完整 skill 包')

# ── 汇总 ───────────────────────────────────────────────────
section('结论')
if not blockers:
    print('%s 全部通过,skill 可以直接用了。' % OK)
    print('   自测: python toolbar.py list "你的某个群名"')
else:
    print('%s 还差 %d 项需要你处理:' % (BAD, len(blockers)))
    for i, b in enumerate(blockers, 1):
        print('   %d. %s' % (i, b))
if notes:
    print('\n提示(不阻塞):')
    for n in notes:
        print('   - ' + n)

sys.exit(1 if blockers else 0)
