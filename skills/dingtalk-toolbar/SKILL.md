---
name: dingtalk-toolbar
description: 管理钉钉群「快捷栏」入口(群聊顶部/底部的快捷入口)。收到"给群加快捷栏/群快捷入口/群顶部加个链接/把XX挂到群里/群快捷菜单/设置群快捷入口/快捷栏排序/删掉群快捷入口"等指令时,用本机 dws CLI 增删改查群自定义快捷栏入口。触发词：快捷栏、快捷入口、群快捷菜单、群里加链接、挂到群、群顶部入口、toolbar、快捷栏排序
metadata:
  type: tool
  requires:
    bins:
      - dws
      - python
---

# 钉钉群快捷栏 (DingTalk Group Toolbar)

管理钉钉群聊「快捷栏」——就是群里顶部/输入框上方那排一点就跳转的快捷入口。收到"给某群加个快捷入口/把某看板挂到群里/群快捷栏排个序/删掉那个入口"等指令,用本机 `dws chat toolbar` 系列命令操作。

> 首次使用前请先完成 dws 安装、登录,见随包 `README.md`。

## 铁律
- **删除自定义入口不可逆** — 执行 `rm` 前必须向用户确认删哪个,确认后再跑(脚本内已带 `--yes`)。
- **只能动"自定义链接入口"**(`customLinkShortcut=true`);系统自带入口只能 show/hide,不能删改。
- **群名多候选 → 停止让用户改用会话ID**,不默认选第一个。
- `create-custom`/`update-custom` 的 `--icon-url` **必填**(公网图片直链),脚本已内置默认图标兜底。
- 手工在 Git Bash 跑且会话ID含 `/` 时前缀 `MSYS_NO_PATHCONV=1`;走 toolbar.py(cmd.exe)则不要加。

**首选辅助脚本**（已封装群名解析、代理清理、中文乱码、会话ID转义），与本 SKILL.md 同目录:

```powershell
python <本技能目录>/toolbar.py <动作> <群名|会话ID> [参数]
# 例如放在 ~/.claude/skills/dingtalk-toolbar/ 下时:
python ~/.claude/skills/dingtalk-toolbar/toolbar.py list "<群名>"
```

## 能做什么 / 不能做什么

- ✅ **能**：增/删/改「自定义链接入口」(customLinkShortcut=true)——挂内部Web服务、外部网页、看板等,任意 URL。
- ✅ **能**：把系统自带入口在**可见区↔隐藏区**之间移动、给可见区入口**排序**。
- ❌ **不能**：删除或改动系统自带入口(群接龙/圈子/群日志/群抽签/群签到/看闲忙/Search Docs/Approval/Group Wiki 等 customLinkShortcut=false)——它们只能显示/隐藏。
- ❌ **不能**：改群公告、群相册这类"群设置"里的原生功能(不在 toolbar 范畴)。

## 常用动作（辅助脚本）

```powershell
# 查看某群快捷栏所有入口(可见区/隐藏区/自定义标记/shortcutId)
python toolbar.py list "<群名>"

# 加一个自定义入口(最常用)。不传 --pc-url 默认同 --url；不传 --icon 用内置默认图标
python toolbar.py add "<群名>" --title "<入口标题>" --url "https://<你的服务地址>:<端口>"
python toolbar.py add "<群名>" --title "<入口标题>" --url "https://<地址>" --pc-url "https://<地址>" --icon "https://<图标直链>"

# 改已有自定义入口(先 list 拿 shortcutId)
python toolbar.py update "<群名>" --sid <shortcutId> --title "<新标题>" --url "https://<新链接>"

# 入口在可见区↔隐藏区移动
python toolbar.py show "<群名>" <shortcutId>   # 隐藏区 -> 可见区
python toolbar.py hide "<群名>" <shortcutId>   # 可见区 -> 隐藏区

# 可见区排序(逗号分隔,按想要的顺序列 shortcutId)
python toolbar.py sort "<群名>" <shortcutId1>,<shortcutId2>

# 删除自定义入口(不可逆,脚本已内置 --yes)
python toolbar.py rm "<群名>" <shortcutId>
```

- `<群名|会话ID>`：以 `cid` 开头当会话ID直接用；否则当群名走 `+chat-search` 解析。**同名多群会停下并列出让你改用会话ID**。
- 删除是**不可逆**操作,执行前先向用户确认要删哪个入口,确认后再跑 `rm`(脚本内已带 `--yes`)。

## 底层命令（脚本不覆盖时回退）

辅助脚本封装的就是下面这些 `dws chat toolbar` 原子命令。**手工在 Git Bash 里跑时,会话ID含 `/`,命令前必须加 `MSYS_NO_PATHCONV=1`**；用 Python subprocess(shell=True 走 cmd.exe)则**不要**加。

| 命令 | 作用 | 关键参数 | 确认 |
|---|---|---|---|
| `chat toolbar list` | 查入口列表 | `--conversation-id` | 只读 |
| `chat toolbar create-custom` | 新建自定义入口 | `--conversation-id --title --url --pc-url --icon-url`(均必填) | 免确认 |
| `chat toolbar update-custom` | 改自定义入口 | 上述 + `--shortcut-id` | 免确认 |
| `chat toolbar add` | 隐藏区→可见区 | `--conversation-id --shortcut-ids`(逗号分隔) | 免确认 |
| `chat toolbar hide` | 可见区→隐藏区 | `--conversation-id --shortcut-ids` | 免确认 |
| `chat toolbar sort` | 可见区排序 | `--conversation-id --sorted-ids [--unsorted-ids]` | 免确认 |
| `chat toolbar remove-custom` | 删除自定义入口 | `--conversation-id --shortcut-id --yes` | **需确认** |

```bash
# Git Bash 手工示例(注意 MSYS_NO_PATHCONV=1)
MSYS_NO_PATHCONV=1 dws chat toolbar list --conversation-id "cid0/xxx==" --format json
MSYS_NO_PATHCONV=1 dws chat toolbar create-custom --conversation-id "cid0/xxx==" \
  --title "<入口标题>" --url "https://<地址>:<端口>" --pc-url "https://<地址>:<端口>" \
  --icon-url "https://<图标直链>" --format json
```

## 返回结构 & 坑

- `list` 返回 `result.{visibleShortcuts, hiddenShortcuts, disabledShortcuts, toolbarEnabled}`；每个入口有 `name / shortcutId / customLinkShortcut`。
- **`customLinkShortcut=true`** 才是自己建的、可改可删；`false` 是系统入口,只能 show/hide。
- **空快捷栏坑**：群里没有任何自定义入口时,`list` 会返回业务错误 `custom shortcut service returned empty`(server_error_code 1001),这是"暂无入口"的正常状态,不是故障。辅助脚本已识别为"（该群快捷栏暂无自定义入口）"。
- **create 不回传 shortcutId**：`create-custom` 成功只返回 `success:true`、result 为空,要拿新入口的 ID 得再 `list`。新入口默认进**可见区**。
- **图标必填**：`create-custom`/`update-custom` 的 `--icon-url` 是必填项,得是可公网访问的图片直链。脚本内置了一个默认图标兜底。
- 中文名在原始 JSON 里可能显示乱码(控制台 GBK),辅助脚本已用 UTF-8 处理,显示正常。

## 典型场景

- 把内部 Web 服务/看板挂到对应群,群成员一点直达(如各类进度看板、报表、答题系统等,填你自己的地址端口)。
- 群里高频用的外部网页/表单/文档,固定成快捷入口。

相关:[[dingtalk-chat]](群聊其它操作)、[[dingtalk-group-remark]](群备注/昵称)。
