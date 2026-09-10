# dingtalk-chat-digest · 踩坑与参数化(按需加载)

只在命令报错、或需要处理边缘情况时读本文件。常规流程照 SKILL.md 四步即可。

## 命令踩坑(已校准)
- **时间参数**:无 `--since`;用 `--start-time/--end-time`,必须**成对**给,且 RFC3339 格式(`2026-08-18T00:00:00+08:00`,带 T 和 +08:00),否则被拒。
- **单聊读取入口**:`+chat-messages` **不认 `--chat-id`**,单聊也用 `--group` 传会话ID。
- **字段名**:`+chat-messages` 的 `--fields` 白名单里时间字段是 `createTime`(不是 `time`);报告脚本 gettime() 已兼容两者。
- **`--fields` 与 `--jq` 互斥,不要叠加**:同时给时 `--jq` 优先、`--fields` 失效(返回全字段)。裁字段→只用 `--fields`(脚本吃 `.messages`);自定义投影/取值→只用 `--jq`,且投影里写 `.createTime` 而非 `time`(否则 time 变 null)。
- **发送接收人**:`+messages-send --user` 要**通讯录 userId**(用 `dws contact get-self` 取当前账号的),不是 openDingTalkId;`--user` 传 openDingTalkId 会报"没有精确匹配的 userId"。
- **同名歧义**:通讯录可能有多个同名人;发本人优先直接投**单聊会话ID**(`--chat-id`),绕开歧义;工具按规则拒绝默认选第一个候选。
- **代理坑**:发文件前清 `unset HTTPS_PROXY HTTP_PROXY`(dtsend 已自动处理),否则企业OSS上传可能失败。

## 省token要点(复盘结论)
- 第1步定位会话ID:`--jq '[.messages[].conversationId]|unique'`,几十token拿到会话ID,别灌全量JSON(21条约4000token)。
- 第2步拉原文:`--fields createTime,sender,text` 去掉 reactions/resourceRefs/messageId 噪音。
- 群/长会话数据量大:先拿计数,>~50条就分时段/分批,先落盘 messages.json 再让脚本读,避免上下文膨胀。
- 报告排版在磁盘脚本里(make_report*.py),不进上下文;每次省~180行现写代码。
- **终端中文乱码不影响报告**:脚本以 UTF-8 读文件;要在终端核对原文用 `PYTHONIOENCODING=utf-8 python -c "...sys.stdout.reconfigure(encoding='utf-8')..."`。

## HTML噪音折叠(make_report_html.py 已内置 simplify())
日程卡片/文件/图片/语音通话会被折叠成灰色虚线小标签(📅日程/📎文件/🖼️图片/📞通话),丢弃超长 meetingFromCalendar/calendar_detail URL 和 fileId。实战验收发现:不折叠时日程/文件的长链接会铺满整屏、手机不可读。新增此类消息类型时,在 simplify() 里加分支。

## 图片/文档处理(实测硬约束)
- **图片(mediaId,`$iwE...`,钉钉OSS域):能下**。`--download-resources --output-dir <dir>` 落盘为 `<去$的resourceId>.jpg`。
- **文档(fileId,企业私有域,如 `xxx.your-corp.com`):可能下不了**,报"不受信任的下载地址"。只能保留文件名标注;要内容让用户在钉钉手动下载后给你。
- **图片内嵌+AI识图流程**:①`--download-resources` 下图(此时别用`--fields`,会丢resourceRefs);②用识图能力逐张看图,写`captions.json`(键=去$的mediaId,值=一句话描述);③`make_report_html.py --resdir <dir> --captions captions.json`,图片base64内嵌+显示🔎caption。
- 脚本函数:`extract_media_id()`从`[图片消息](mediaId=$xxx)`抽ID;`find_image_file()`按ID前缀在resdir找图;`img_data_uri()`转base64内嵌。
- ⚠️内嵌图使HTML体积暴涨(6MB图→8MB+ HTML);图多时只嵌关键几张。

## 参数化
- "近三天/近N天":今天回推 N 天(如今天 2026/08/20 → 近三天 = 08-18~08-20)。
- "发我" = 当前登录账号(userId 用 `dws contact get-self` 取);"发给XX"则第4步换成对应 userId 或单聊会话ID。
- 群汇总:第1步跳过,直接第2步用群 openConversationId(`+chat-search --query "<群名>"` 解析)。
- `--self`:报告里我方姓名,控制气泡左右分栏/着色,默认"我"。

## 产物选型
- 给人看 / 手机看 / 发钉钉 → HTML(`make_report_html.py`,默认)。
- 正式归档 / 打印 / 进公文流 → Word(`make_report.py`)。
- 拿不准 → HTML。
