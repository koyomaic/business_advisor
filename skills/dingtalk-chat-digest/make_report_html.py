# -*- coding: utf-8 -*-
"""
钉钉聊天汇总报告生成器 · HTML 版 (dingtalk-chat-digest)
默认产物:单文件离线 HTML,手机友好。聊天气泡还原原文 + 总结卡片。
自带「自修改」能力(改字/一键导出为完整HTML)。

用法:
  python make_report_html.py \
    --title "我与<姓名>近三天单聊记录 · 原文与总结" \
    --meta  "2026-08-18 至 2026-08-20 ｜ 单聊 ｜ 5 条" \
    --messages messages.json \
    --summary  summary.json \
    --out "<输出目录>/<姓名>聊天汇总.html" \
    --self "<本人姓名或'我'>"

messages.json: dws +chat-messages 返回里的 messages 数组(或含 messages 键的完整返回)
summary.json : {"sections":[{"heading":..,"points":[..]}], "oneLine":.., "note":..}
"""
import argparse, json, html, re, base64, os, glob


def esc(s):
    return html.escape(str(s or '')).replace('\n', '<br>')


def norm_id(s):
    """归一化资源ID:去掉开头$,便于和落盘文件名/captions键匹配。"""
    return (s or '').lstrip('$').strip()


def extract_media_id(text):
    """从图片消息文本 [图片消息](mediaId=$xxx) 里抽出 mediaId(已去$)。"""
    m = re.search(r'mediaId=(\$?[^)\s]+)', text or '')
    return norm_id(m.group(1)) if m else None


def find_image_file(resdir, media_id):
    """在 resdir 里按 media_id 前缀找落盘图片(下载文件名=去$的resourceId+.ext)。"""
    if not resdir or not media_id:
        return None
    for ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        p = os.path.join(resdir, media_id + '.' + ext)
        if os.path.exists(p):
            return p
    # 兜底:前缀模糊匹配(资源ID较长,取前40字符)
    hits = glob.glob(os.path.join(resdir, media_id[:40] + '*'))
    return hits[0] if hits else None


def img_data_uri(path, max_bytes=1200000):
    """把图片读成 data URI 内嵌。超过 max_bytes 的大图仍内嵌(缩略靠CSS),
    返回 None 表示读失败。"""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        mime = 'image/jpeg' if ext in ('jpg', 'jpeg') else 'image/' + ext
        return 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode())
    except Exception:
        return None


def simplify(text):
    """把日程卡片/文件/图片/语音通话等噪音消息折叠成简洁标签,
    返回 (显示文本, 类型)。类型: 'text'|'schedule'|'file'|'image'|'call'。"""
    t = (text or '').strip()
    if '日程：' in t or 'meetingFromCalendar' in t or 'calendar_detail' in t:
        m = re.search(r'日程：([^\s]+(?:[^\n]*?))(?:\s+时间：|\s+时间:|$)', t)
        title = m.group(1).strip() if m else '日程'
        m2 = re.search(r'时间：([0-9]{4}-[0-9]{2}-[0-9]{2}[^\n]*?)(?:\s+地点|\s+入会|\s+日程|$)', t)
        when = ('　' + m2.group(1).strip()) if m2 else ''
        return ('📅 日程：' + title + when, 'schedule')
    if t.startswith('[文件]'):
        name = t.replace('[文件]', '').split('fileId')[0].strip()
        return ('📎 文件：' + name, 'file')
    if t.startswith('[图片消息]') or t.startswith('[图片]'):
        return ('🖼️ 图片', 'image')
    if '语音通话' in t or '普通电话' in t or '视频通话' in t:
        return ('📞 通话', 'call')
    return (t, 'text')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--title', required=True)
    ap.add_argument('--meta', default='')
    ap.add_argument('--messages', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--self', dest='selfname', default='我')
    ap.add_argument('--resdir', default='', help='--download-resources 的图片目录,内嵌图片用')
    ap.add_argument('--captions', default='', help='AI识图结果JSON: {"<mediaId去$>": "描述"}')
    args = ap.parse_args()

    with open(args.messages, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    msgs = raw.get('messages', raw) if isinstance(raw, dict) else raw
    with open(args.summary, 'r', encoding='utf-8') as f:
        summary = json.load(f)
    captions = {}
    if args.captions and os.path.exists(args.captions):
        with open(args.captions, 'r', encoding='utf-8') as f:
            captions = {norm_id(k): v for k, v in json.load(f).items()}

    def gettime(m):
        return m.get('time') or m.get('createTime') or ''
    norm = [{'time': gettime(m), 'sender': m.get('sender', ''),
             'text': m.get('text', '')} for m in msgs]
    norm.sort(key=lambda x: x['time'])

    # 聊天气泡
    bubbles = []
    last_day = None
    for m in norm:
        day = m['time'][:10]
        clock = m['time'][11:16]
        if day != last_day:
            bubbles.append(f'<div class="daysep"><span>{esc(day)}</span></div>')
            last_day = day
        is_self = args.selfname and args.selfname in m['sender']
        side = 'me' if is_self else 'other'
        disp, kind = simplify(m['text'])

        if kind == 'image':
            # 内嵌图片 + AI识图caption
            mid = extract_media_id(m['text'])
            uri = None
            if mid:
                fp = find_image_file(args.resdir, mid)
                if fp:
                    uri = img_data_uri(fp)
            cap = captions.get(mid, '') if mid else ''
            inner = ''
            if uri:
                inner += f'<img class="chatimg" src="{uri}" loading="lazy">'
            else:
                inner += '<span class="imgmiss">🖼️ 图片(未下载/私有域)</span>'
            if cap:
                inner += f'<div class="cap">🔎 {esc(cap)}</div>'
            body = f'<div class="bubble imgbubble">{inner}</div>'
        else:
            bcls = 'bubble' if kind == 'text' else 'bubble special'
            body = f'<div class="{bcls}">{esc(disp)}</div>'

        bubbles.append(
            f'<div class="row {side}">'
            f'<div class="meta"><span class="name">{esc(m["sender"])}</span>'
            f'<span class="clock">{esc(clock)}</span></div>'
            f'{body}'
            f'</div>'
        )
    chat_html = '\n'.join(bubbles)

    # 总结卡片
    sec_html = []
    for sec in summary.get('sections', []):
        pts = ''.join(f'<li>{esc(p)}</li>' for p in sec.get('points', []))
        sec_html.append(
            f'<div class="sumcard"><h3>{esc(sec.get("heading",""))}</h3>'
            f'<ul>{pts}</ul></div>'
        )
    sections_html = '\n'.join(sec_html)

    one = summary.get('oneLine', '')
    one_html = (f'<div class="oneline"><span class="tag">一句话</span>'
                f'<p>{esc(one)}</p></div>') if one else ''
    note = summary.get('note', '')
    note_html = (f'<div class="note"><b>※ 边界说明</b><p>{esc(note)}</p></div>'
                 ) if note else ''

    tpl = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--navy:#1f3a5f;--orange:#c05000;--bg:#f4f6f9;--me:#95ec69;--other:#fff;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:#222;line-height:1.6;}
.wrap{max-width:720px;margin:0 auto;padding:16px 14px 60px;}
header{text-align:center;padding:18px 8px 8px;}
header h1{font-size:19px;color:var(--navy);margin:0 0 6px;font-weight:800;}
header .meta{font-size:12px;color:#8a94a6;}
.bar{display:flex;gap:8px;justify-content:center;margin:14px 0;flex-wrap:wrap;}
.bar button{border:0;padding:8px 14px;border-radius:20px;font-size:13px;cursor:pointer;
background:#e6ebf2;color:var(--navy);font-weight:600;}
.bar button.primary{background:var(--navy);color:#fff;}
h2.sect{font-size:15px;color:var(--navy);margin:22px 4px 10px;padding-left:10px;
border-left:4px solid var(--orange);}
/* 聊天 */
.chat{background:#ebeef3;border-radius:14px;padding:14px 12px;}
.daysep{text-align:center;margin:12px 0;}
.daysep span{background:#c8cfda;color:#fff;font-size:11px;padding:2px 10px;border-radius:10px;}
.row{margin:10px 0;display:flex;flex-direction:column;max-width:82%;}
.row.other{align-items:flex-start;margin-right:auto;}
.row.me{align-items:flex-end;margin-left:auto;}
.row .meta{font-size:11px;color:#8a94a6;margin:0 4px 3px;}
.row .meta .name{font-weight:600;}
.row .meta .clock{margin-left:6px;}
.bubble{padding:9px 12px;border-radius:10px;font-size:14.5px;word-break:break-word;
box-shadow:0 1px 1px rgba(0,0,0,.05);}
.row.other .bubble{background:var(--other);border-top-left-radius:2px;}
.row.me .bubble{background:var(--me);border-top-right-radius:2px;}
.bubble.special{background:#eef1f6!important;color:#5a6472;font-size:13px;
border:1px dashed #c8d0dc;border-radius:8px;}
.imgbubble{padding:6px!important;background:#fff;}
.chatimg{max-width:220px;max-height:280px;border-radius:8px;display:block;cursor:zoom-in;}
.imgmiss{color:#8a94a6;font-size:13px;}
.cap{margin-top:6px;font-size:12px;color:#5a6472;background:#f4f7fb;
border-left:3px solid #4a90d9;padding:5px 8px;border-radius:4px;line-height:1.5;}
/* 总结 */
.sumcard{background:#fff;border-radius:12px;padding:12px 16px;margin:10px 0;
box-shadow:0 1px 3px rgba(0,0,0,.06);}
.sumcard h3{margin:0 0 6px;font-size:14px;color:var(--orange);}
.sumcard ul{margin:0;padding-left:18px;}
.sumcard li{margin:4px 0;font-size:14px;}
.oneline{background:var(--navy);color:#fff;border-radius:12px;padding:14px 16px;margin:12px 0;}
.oneline .tag{font-size:11px;background:rgba(255,255,255,.25);padding:2px 8px;border-radius:8px;}
.oneline p{margin:8px 0 0;font-size:15px;font-weight:600;}
.note{background:#fff4f0;border:1px solid #f3d3c6;border-radius:12px;padding:12px 16px;margin:12px 0;}
.note b{color:#b03030;font-size:13px;}
.note p{margin:6px 0 0;font-size:13px;color:#666;}
[contenteditable="true"]{outline:2px dashed #c05000;outline-offset:2px;background:#fffdf8;}
footer{text-align:center;color:#aab;font-size:11px;margin-top:20px;}
@media print{.bar{display:none;}body{background:#fff;}}
</style></head>
<body><div class="wrap" id="doc">
<header><h1>__TITLE__</h1><div class="meta">__META__</div></header>
<div class="bar">
<button class="primary" onclick="dl()">导出HTML</button>
<button onclick="ed()" id="edb">编辑</button>
<button onclick="window.print()">打印/PDF</button>
</div>
<h2 class="sect">💬 原文呈现</h2>
<div class="chat">
__CHAT__
</div>
<h2 class="sect">📌 内容总结</h2>
__SECTIONS__
__ONELINE__
__NOTE__
<footer>由 dingtalk-chat-digest 生成 · 原文逐字呈现,总结为AI归纳</footer>
</div>
<script>
function ed(){var d=document.getElementById('doc');var on=d.isContentEditable;
d.contentEditable=!on;document.getElementById('edb').textContent=on?'编辑':'完成';}
function dl(){var d=document.getElementById('doc');if(d.isContentEditable)ed();
var h='<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'+
'<meta name="viewport" content="width=device-width,initial-scale=1"><title>'+
document.title+'</title>'+document.querySelector('style').outerHTML+
'</head><body><div class="wrap">'+d.innerHTML+'</div></body></html>';
var b=new Blob([h],{type:'text/html'});var a=document.createElement('a');
a.href=URL.createObjectURL(b);a.download=document.title+'.html';a.click();}
</script>
</body></html>"""

    out_html = (tpl
                .replace('__TITLE__', esc(args.title))
                .replace('__META__', esc(args.meta))
                .replace('__CHAT__', chat_html)
                .replace('__SECTIONS__', sections_html)
                .replace('__ONELINE__', one_html)
                .replace('__NOTE__', note_html))

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(out_html)
    print(args.out)


if __name__ == '__main__':
    main()
