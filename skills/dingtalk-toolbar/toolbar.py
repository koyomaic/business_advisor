#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
钉钉群「快捷栏」操作辅助脚本 (dingtalk-toolbar skill)

封装 dws chat toolbar 系列命令，省去手工处理：会话ID含'/'的转义、代理清理、
群名->openConversationId 解析、返回结果里中文乱码的 JSON 解析。

用法:
  python toolbar.py list   <群名|会话ID>
  python toolbar.py add     <群名|会话ID> --title 标题 --url 链接 [--pc-url 链接] [--icon 图标URL]
  python toolbar.py update  <群名|会话ID> --sid <shortcutId> --title 标题 --url 链接 [--pc-url ..] [--icon ..]
  python toolbar.py show    <群名|会话ID> <shortcutId>   # 移到可见区(隐藏区->可见区)
  python toolbar.py hide    <群名|会话ID> <shortcutId>   # 移到隐藏区
  python toolbar.py sort    <群名|会话ID> <id1,id2,id3>  # 可见区排序
  python toolbar.py rm      <群名|会话ID> <shortcutId>   # 删除自定义入口(不可逆)

说明:
- <群名|会话ID>: 传 openConversationId(以 cid 开头) 直接用; 否则当群名用 +chat-search 解析,
  多群命中会列出让你改用会话ID。
- create/update 若不传 --pc-url 默认同 --url; 不传 --icon 用内置默认图标。
- 所有 dws 调用走 cmd.exe(shell=True), 不加 MSYS_NO_PATHCONV(那是 Git Bash 才需要)。
"""
import subprocess, json, sys, os, io, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 清理影响钉钉/OSS 访问的代理变量
for k in ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy'):
    os.environ.pop(k, None)
os.environ['NO_PROXY'] = '*'

DEFAULT_ICON = "https://img.alicdn.com/imgextra/i1/O1CN01Nlbybe1FvhL5vhVQK_!!6000000000550-2-tps-96-96.png"

def dws(args):
    """执行 dws 命令, 返回 (dict_or_none, raw_str)。"""
    p = subprocess.run(['dws'] + args, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=90, shell=True)
    raw = (p.stdout or '') + (p.stderr or '')
    # 剔除升级器/嵌套skill告警行
    lines = [l for l in raw.splitlines()
             if not any(x in l for x in ('旧升级器', '嵌套 Skill', 'skill setup', '⚠'))]
    body = '\n'.join(lines).strip()
    try:
        # 抠出第一段完整 JSON
        s = body.find('{'); e = body.rfind('}')
        return json.loads(body[s:e+1]), body
    except Exception:
        return None, body

def resolve_cid(name_or_cid):
    """群名或会话ID -> openConversationId。"""
    if name_or_cid.startswith('cid'):
        return name_or_cid
    d, raw = dws(['chat', '+chat-search', '--keyword', name_or_cid, '--format', 'json'])
    chats = ((d or {}).get('chats')) or []
    if not chats:
        print('❌ 没搜到群「%s」，请确认群名或直接传 openConversationId' % name_or_cid)
        sys.exit(1)
    if len(chats) > 1:
        print('⚠ 群名「%s」命中 %d 个，请改用 openConversationId：' % (name_or_cid, len(chats)))
        for c in chats:
            print('  -', c.get('openConversationId'), '(成员%s人, 建于%s)' % (c.get('memberCount'), c.get('createAt')))
        sys.exit(1)
    return chats[0].get('openConversationId')

def print_list(cid):
    d, raw = dws(['chat', 'toolbar', 'list', '--conversation-id', cid, '--format', 'json'])
    # 空快捷栏时服务端返回 business_error(empty)，属正常"暂无自定义入口"
    if d and d.get('error'):
        if 'empty' in json.dumps(d, ensure_ascii=False):
            print('（该群快捷栏暂无自定义入口）'); return
        print('查询失败：', raw[:400]); return
    if not d:
        print('查询失败（无法解析返回）：', raw[:400]); return
    r = d.get('result', {})
    def show(title, arr):
        print('\n【%s】(%d)' % (title, len(arr)))
        for s in arr:
            tag = '自定义✎' if s.get('customLinkShortcut') else '系统'
            print('  %-18s id=%s  [%s]' % (s.get('name'), s.get('shortcutId'), tag))
    print('toolbarEnabled =', r.get('toolbarEnabled'))
    show('可见区 visible', r.get('visibleShortcuts', []))
    show('隐藏区 hidden', r.get('hiddenShortcuts', []))
    if r.get('disabledShortcuts'):
        show('停用 disabled', r.get('disabledShortcuts', []))

def do_create(cid, a):
    args = ['chat', 'toolbar', 'create-custom', '--conversation-id', cid,
            '--title', a.title, '--url', a.url,
            '--pc-url', a.pc_url or a.url, '--icon-url', a.icon or DEFAULT_ICON, '--format', 'json']
    if a.desc: args += ['--desc', a.desc]
    d, raw = dws(args)
    if d and d.get('success'):
        print('✅ 已在群快捷栏创建入口「%s」-> %s' % (a.title, a.url))
        print('   (可见区可能需要几秒刷新; 用 list 查看并拿 shortcutId)')
    else:
        print('创建失败：', raw[:400])

def do_update(cid, a):
    args = ['chat', 'toolbar', 'update-custom', '--conversation-id', cid,
            '--shortcut-id', str(a.sid), '--title', a.title, '--url', a.url,
            '--pc-url', a.pc_url or a.url, '--icon-url', a.icon or DEFAULT_ICON, '--format', 'json']
    if a.desc: args += ['--desc', a.desc]
    d, raw = dws(args)
    print('✅ 已更新入口 %s' % a.sid if (d and d.get('success')) else '更新失败：' + raw[:400])

def do_simple(cid, verb, sid):
    m = {'show': ('add', '--shortcut-ids'), 'hide': ('hide', '--shortcut-ids')}
    sub, flag = m[verb]
    d, raw = dws(['chat', 'toolbar', sub, '--conversation-id', cid, flag, str(sid), '--format', 'json'])
    print('✅ 完成 %s %s' % (verb, sid) if (d and d.get('success')) else '失败：' + raw[:400])

def do_sort(cid, ids):
    d, raw = dws(['chat', 'toolbar', 'sort', '--conversation-id', cid, '--sorted-ids', ids, '--format', 'json'])
    print('✅ 已排序：%s' % ids if (d and d.get('success')) else '排序失败：' + raw[:400])

def do_rm(cid, sid):
    d, raw = dws(['chat', 'toolbar', 'remove-custom', '--conversation-id', cid,
                  '--shortcut-id', str(sid), '--yes', '--format', 'json'])
    print('✅ 已删除入口 %s' % sid if (d and d.get('success')) else '删除失败：' + raw[:400])

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(0)
    verb = sys.argv[1]
    target = sys.argv[2]
    rest = sys.argv[3:]
    cid = resolve_cid(target)

    if verb == 'list':
        print_list(cid)
    elif verb in ('add', 'create', 'update'):
        ap = argparse.ArgumentParser()
        ap.add_argument('--title', required=True)
        ap.add_argument('--url', required=True)
        ap.add_argument('--pc-url', dest='pc_url', default=None)
        ap.add_argument('--icon', default=None)
        ap.add_argument('--desc', default=None)
        ap.add_argument('--sid', default=None)
        a = ap.parse_args(rest)
        if verb == 'update':
            if not a.sid:
                print('update 需要 --sid <shortcutId>'); sys.exit(1)
            do_update(cid, a)
        else:
            do_create(cid, a)
    elif verb in ('show', 'hide'):
        do_simple(cid, verb, rest[0])
    elif verb == 'sort':
        do_sort(cid, rest[0])
    elif verb == 'rm':
        do_rm(cid, rest[0])
    else:
        print('未知动作：', verb); print(__doc__)

if __name__ == '__main__':
    main()
