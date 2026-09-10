---
name: dingtalk-group-remark
description: "管理钉钉群的个人备注(仅自己可见)与个人群昵称。支持全量批量备注、增量检测新群并自动归类、单群备注、群昵称增删。用本地状态文件 group_state.json 记录已处理群,后续运行只对差集(新群)处理。当用户提到群备注、给群加备注、改群备注、批量备注、群昵称、检查新群、同步群备注、整理群列表等时触发。依赖 dws CLI。"
agent_created: true
metadata:
  type: tool
  requires:
    bins:
      - dws
---

# 钉钉群备注与群昵称管理 (DingTalk Group Remark)

给钉钉群设置**个人备注**(alias,只有自己可见)和**个人群昵称**(nick,群内可见),都是个人级设置,不影响群本身或其他成员。用 `dws chat` 系列命令操作,靠本地状态文件做增量同步。

> 首次使用前请先完成 dws 安装、登录,见随包 `README.md`。**状态文件 `group_state.json` 存的是你自己的真实群列表,不随包分发;首次运行会自动生成**。随包只提供 `group_state.example.json` 空模板作参考。

## 铁律
- **备注仅自己可见,群昵称群内可见** — 两者独立,别混。改前跟用户说清是哪个。
- **写操作前必确认**:批量备注先出建议表让用户确认;单群/删除也先说明目标+内容再执行。批量执行才加 `-y`。
- **批量单次 ≤ 30 条**,超出分批;逐条记成功/失败,末尾汇总。
- **`+chat-list-all` 有同步盲区**:刚建的群可能查不到 → 改用 `+chat-search --query "<群名>"` 单独搜。
- 群名多候选/零命中 → **停止并让用户消歧,不默认选第一个**。
- 命令一律加 `--format json` 按真实返回判断;Git Bash 手工跑且会话ID含 `/` 时前缀 `MSYS_NO_PATHCONV=1`。

## 核心命令(已校准到当前 dws)

| 能力 | 命令 |
|---|---|
| 全量拉群(一键翻页) | `dws chat +chat-list-all --page-all --format json` |
| 单独搜某群(建群盲区兜底) | `dws chat +chat-search --query "<群名>" --format json` |
| 设群备注 | `dws chat +chat-update-alias --group <openConversationId> --alias-title "<备注>" --format json` |
| 设群昵称 | `dws chat +chat-update-nick --group <openConversationId> --nick "<昵称>" --format json` |
| 清群昵称 | `dws chat +chat-update-nick --group <openConversationId> --format json`(不传 `--nick`) |

> `+chat-list-all --page-all` 自动沿 nextCursor 翻完所有群,无需手动循环 `--cursor`。群多可加 `--page-delay 200` 缓翻。

## 状态文件

增量检测依赖本地状态文件(与本 SKILL.md 同目录):

```
<本技能目录>/group_state.json
# 例如放在 ~/.claude/skills/dingtalk-group-remark/ 下时即该目录下的 group_state.json
```

结构:`{lastSyncAt, totalProcessed, groups:{ "<openConversationId>": {name, category, alias, remarkedAt} }}`(见同目录 `group_state.example.json`)。
规则:首次无文件→走模式一全量,完成后写文件;有文件→拉全量与已记录 ID 做差集,只处理新群;每批成功后**立即更新**避免中断丢进度;增量时顺带检测群名是否变化。

## 模式一 · 智能批量备注(首次/重整)
1. `+chat-list-all --page-all` 拉全量群,提取每条的 `openConversationId` + 群名。
2. **AI 智能分类**(见下方分类表),每群归一类,备注格式 `[分类] 简化群名`(去掉"群/讨论组"等冗余)。
3. 出**建议表**(序号｜当前群名｜分类｜建议备注｜openConversationId)+ 分类统计,给用户确认。
4. 用户确认/调整后,逐个 `+chat-update-alias ... -y`,单批 ≤30,记成功/失败。
5. 全部完成→写/更新 `group_state.json`,汇总成功失败数(提醒仅自己可见)。

### 分类表
| 分类 | 识别特征 | 前缀 |
|---|---|---|
| 项目类 | 项目名/版本号/迭代 | `[项目]` |
| 部门/团队类 | 部门名/团队/组别 | `[部门]` |
| 业务/工作类 | 业务线/产品线 | `[业务]` |
| 通知/公告类 | 通知/公告/播报 | `[通知]` |
| 社交/兴趣类 | 兴趣/活动/聚餐/运动 | `[社交]` |
| 外部/合作类 | 供应商/客户/合作方 | `[外部]` |
| 临时/讨论类 | 临时/讨论/测试 | `[临时]` |
| 其他 | 无法明确归类 | `[其他]` |

## 模式二 · 单群备注
群名先 `+chat-search --query "<关键词>"` 唯一解析(多候选→用户确认),展示"目标群+备注内容"确认后 `+chat-update-alias`。

## 模式三 · 群昵称
设:`+chat-update-nick --group <ID> --nick "<昵称>"`;清:同命令不传 `--nick`。

## 模式四 · 增量检测新群(日常推荐)
1. 读 `group_state.json`(无 → 提示先走模式一建基线)。
2. `+chat-list-all --page-all` 拉全量。
3. **差集对比**产三类:①新增群(有ID无记录)→分类+备注;②名称变更群(ID在但群名变)→展示新旧对比,问是否更新;③已退出群(记录在但列表无)→标记保留不处理。无新增无变更→告知"已是最新"。
4. 新群少(1~5个),默认**快速确认**批量执行;用户说"自动处理"则跳确认按建议直接执行。
5. 执行后更新状态:写新群、更新变更群 name/alias/remarkedAt、刷新 lastSyncAt/totalProcessed。
6. 汇总:新增X/变更X/已退出X/无变化X。

## 模式选择
| 用户意图 | 模式 |
|---|---|
| "整理所有群备注""批量加备注" | 一 |
| "检查新群""同步群备注" | 四 |
| "给XX群设备注""改那个群备注" | 二 |
| "改我群里昵称""设/清群昵称" | 三 |
| "重新整理全部群" | 一(忽略状态文件全量,完成后覆盖) |
| "清除状态""重置" | 删除 group_state.json |

## 踩坑(按需)
- `+chat-list-all` 建群盲区 → `+chat-search` 兜底(见铁律)。
- 多组织/账号:加 `--profile`(用 `dws profile list` 返回的 `corpId:userId`)。
- 状态文件只存 openConversationId/群名/分类/备注/时间,无敏感信息;但它是你自己的真实群列表,**分享/提交前请勿把它一起带出**。
- 旧笔记里的 `dws chat search` / `dws chat group update-alias` 仍可用,但**优先带完整性检查的 `+chat-search` / `+chat-update-alias`**。

相关:[[dingtalk-chat]](群解析/操作底座)、[[dingtalk-send]](发本人/发文件)、[[dingtalk-chat-digest]](聊天汇总报告)。
