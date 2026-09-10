---
name: dingtalk-chat-digest
description: 检索钉钉「和某个人的单聊」或「某个群」近N天的聊天内容,原文逐条呈现+AI总结,默认生成手机友好的HTML报告(可选Word)并发给本人(或指定人)。收到"调取/汇总/总结我和XX的聊天/单聊内容""汇总XX群的信息/群消息""把XX的对话做个报告发我"等指令时触发。触发词：调取聊天、汇总聊天、总结对话、我和某人的聊天、单聊内容、汇总群消息、群信息汇总、聊天报告、对话总结发我、群纪要
metadata:
  type: tool
  requires:
    bins:
      - dws
      - python
---

# 钉钉聊天汇总报告 (DingTalk Chat Digest)

「调取/汇总我和某人的单聊」或「汇总某个群」并**生成报告发我**时:`dws` CLI 检索对话级原文 → 逐条原文 + AI 总结 → HTML(默认)/Word → 发钉钉(默认本人)。依赖 python-docx(生成 Word 时)。

> 首次使用前请先完成 dws 安装、登录与 Python 依赖,见随包 `README.md`。本技能里的"我/本人"指**当前登录 dws 的账号**。

## 铁律
- **原文逐字呈现,不改写/裁剪**;总结与原文分区。
- **如实标注边界**:单聊里没有的内容(如"昨天在群里的讨论")不拼接、不臆测,说明并提示可补检索。
- 时间参数必须 RFC3339(`2026-08-18T00:00:00+08:00`)。

## 标准流程(4 步)

### 第 1 步 · 全局定位(找到目标会话ID)
按发送者+时间范围搜。**只需会话ID时用 `--jq` 直接取去重列表,别灌全量JSON**(省token关键):
```bash
dws chat +search-msg --sender-query "<姓名>" \
  --start-time "<起>T00:00:00+08:00" --end-time "<止>T23:59:59+08:00" \
  --page-all --jq '[.messages[].conversationId]|unique' --format json
```
- 返回形如 `["cidA/Bi...==","cidxjk...=="]`。单聊那个 `cid...==` 一般是一对一直接对话的会话。
- 拿不准哪个是单聊时,再补一条带 `--fields conversationId,sender,text` 的小范围搜确认,仍**不要**默认全字段。
- 群:已知群名直接 `dws chat +chat-search --query "<群名>"` 唯一解析 openConversationId,跳过本步。
- 多候选/零命中 → 停止并让用户消歧,**不默认选第一个**。

### 第 2 步 · 定向拉全原文(含双方/全员)
按会话ID拉时间范围内**全部**消息(单聊/群聊同命令,`--group` 传会话ID)。**用 `--fields` 只留报告要用的字段,去掉 reactions/resourceRefs/messageId 等噪音**(省token关键):
```bash
dws chat +chat-messages --group "<openConversationId>" \
  --start-time "<起>T00:00:00+08:00" --end-time "<止>T23:59:59+08:00" \
  --page-all --fields createTime,sender,text --format json > messages.json
```
- ⚠️ 字段名是 `createTime`(不是 `time`);报告脚本已兼容。**`--fields` 与 `--jq` 不能叠加**(同给则 `--jq` 优先、fields失效);裁字段就只用 `--fields`。
- 检查 `complete:true`、`hasMore:false`;partial 不得当完整。
- **群消息量大时**别一次性全灌上下文:先只跑一次拿计数,超过~50条就分时段/分批处理,或先 `--fields createTime,sender,text` 落盘再让脚本读,避免上下文膨胀。需要图片/文件再 `--download-resources`。

### 第 2.5 步 · 图片/文档处理(可选,聊天含图片时才做)
默认图片/文档只折叠成 📎📷 标签。**要在报告里看到图片内容+AI识图**时:
1. 拉消息时加 `--download-resources --output-dir <resdir>` 下载资源:
   ```bash
   dws chat +chat-messages --group "<会话ID>" --start-time ... --end-time ... \
     --page-all --download-resources --output-dir resdir --format json > messages.json
   ```
   (注:此时不能用 `--fields`,否则丢 resourceRefs;资源较多时按时段分批下)
2. **图片能下,企业私有域文档(fileId)可能下不了**——若下载报"不受信任的下载地址",文档只保留文件名标注。
3. 用识图能力逐张看 resdir 下的图片,把识别结果写进 `captions.json`:键=去掉开头`$`的mediaId(=落盘文件名去扩展名),值=一句话描述。
4. 第3步 HTML 生成加 `--resdir resdir --captions captions.json`,图片会 base64 内嵌+显示 🔎AI识图caption。
- ⚠️ 内嵌图片会让 HTML 变大(每张几MB→base64更大);图多时只内嵌关键几张,其余保持标签。
- 文档内容确实要:让用户在钉钉里手动下载后给你,再解析。

### 第 3 步 · 生成报告(原文+总结)
把第2步的 messages(JSON)喂给报告脚本。脚本按时间正序排原文,总结部分由 AI 根据原文归纳后填入。

**默认产 HTML**(手机友好:聊天气泡还原原文+总结卡片,自带编辑/导出/打印PDF按钮)。发钉钉、给人看,一律优先 HTML:
```bash
python "<本技能目录>/make_report_html.py" \
  --title "我与<姓名>近N天单聊记录 · 原文与总结" \
  --meta "<起> 至 <止> ｜ 单聊 ｜ N 条" \
  --messages messages.json --summary summary.json --self "<本人姓名或'我'>" \
  --out "<输出目录>/<姓名>聊天汇总-<起>至<止>.html"
  # 含图片时追加: --resdir resdir --captions captions.json (见第2.5步)
```

**需正式归档/进公文流/打印时**,才用 Word(make_report.py,参数同上,`--out ...docx`):
```bash
python "<本技能目录>/make_report.py" \
  --title "..." --meta "..." --messages messages.json --summary summary.json \
  --out "<输出目录>/<姓名>聊天汇总-<起>至<止>.docx"
```
选型:给人看/手机看 → HTML;存档/打印/流转 → Word。拿不准默认 HTML。

- `messages.json`:第2步返回里的 `messages` 数组(字段 `time`/`sender`/`text` 即可)。
- `summary.json`:AI 归纳的总结,格式见下方「总结JSON格式」。群汇总建议多分几段(讨论主题/关键结论/待办/风险)。
- `--self`:我方姓名,用于原文气泡左右分栏/着色(默认"我")。

### 第 4 步 · 发送(默认发本人)
发本人最稳:直接发到"我与对方的单聊会话ID",或按 [[dingtalk-send]] 发给当前登录账号。
```bash
# 或发到某个单聊会话(本人+对方都可见)
dws chat +messages-send --as user --chat-id "<单聊会话ID>" \
  --file "<相对路径docx/html>" --yes --format json
```
成功返回 `ok:true` + `openTaskId`。发给自己时,收件人 userId 用 `dws contact get-self` 取当前账号,不要写死。

## 总结 JSON 格式(summary.json)
```json
{
  "sections": [
    {"heading": "核心话题", "points": ["要点一", "要点二"]},
    {"heading": "关键结论", "points": ["..."]},
    {"heading": "待办/指令", "points": ["..."]}
  ],
  "oneLine": "一句话概括整段对话的实质。",
  "note": "边界说明:如'昨天的相关讨论在工作群,不在本单聊,可按需补检索'。留空则不显示。"
}
```

## 踩坑 / 参数化 / 选型(按需)
命令报错、群大数据量、同名歧义、"近N天"换算、产物选型等细节 → 读 `reference.md`(与本文件同目录)。常规四步不需要读。

相关:[[dingtalk-chat]](检索/发送底座)、[[dingtalk-send]](发本人)、[[self-editable-page]](HTML默认叠加自修改/导出)。
