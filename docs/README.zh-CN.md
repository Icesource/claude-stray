# claude-stray

**Claude Code 的注意力驾驶舱。**

你在 Claude Code 里同时推进很多件事:有的在跑,有的在等*你*拍板,有的几小时前
就跑完了,有的你已经忘了。难的不是干活 —— 而是**一眼看清:谁在等我、每件事到
哪了、怎么近乎零成本地切回任意一件。**

`claude-stray` 是一个架在 Claude Code 之上的本地小面板,干的正是这件事:它读取你
的会话,让 AI 总结每条会话的进展、收集它产出的资源(MR、ISSUE、文档),并把它们
摆成**按注意力排序的卡片** —— 需要你 → 跑着 → 闲置 → 完成。点开任意一张卡看它到
哪了、看它的 MR/ISSUE 链接,或者**直接在卡片里开一个终端**把这件活接着干下去。

它**不是又一个 Agent**。真正的活复用 Claude Code 来做;它的全部职责是 triage +
handoff —— 帮你把注意力花在刀刃上。

一行安装。无需登录。除了生成总结时调 Anthropic,数据不出你的机器。首次启动自动
同步你已有的历史,之后在后台保持新鲜 —— 每条 Claude Code 会话一结束,对应卡片就
更新。

[English](../README.md) · [架构](ARCHITECTURE.md) · [路线图](ROADMAP.md) · [发布模型](RELEASE.md) · [更新日志](../CHANGELOG.md)

![dashboard preview](assets/screenshots/zh-CN/01-overview.png)

## 你会得到什么

一个 `http://127.0.0.1:9876/` 的面板,三个视图 —— **按注意力**、**按项目**、
**归档** —— 同一批卡片的不同看法:

- **实时的注意力分带。** 每件活被分进 **需要你 / 跑着 / 闲置 / 完成**,由 Claude
  Code hooks 的实时遥测驱动。正在生成的会话显示*跑着*;结束时卡在你这儿的显示
  *需要你*并带上具体那个问题。整块板子一眼尽收,先看哪儿心里有数。
- **每卡 AI 总结。** 每张卡带:一句*这是什么*、**最新进展**(自动保持更新)、
  三态任务(待办/完成/取消)、卡点、**下一步**,以及它产出的外部资源 —— **MR /
  PR / CR / ISSUE**。资源是"黏"的:一个 MR 上了卡就一直在,直到你移除;AI 不会
  悄悄丢链接。
- **原地切回去干。** 在驾驶舱内把某张卡的会话开成**内嵌终端**(`claude --resume`,
  不另开窗口),或跳到它的实时 pane。装了 `tmux`/`screen` 的话,终端连刷新页面都
  不丢。
- **AI 建议下一句。** 让某张卡给你 2–3 条可直接发送的下一句 —— 是结合你*所有*在
  飞工作的全局视角生成的,不只看这一条会话。
- **每周回顾**(每周五中午)+ **下一步建议**(取自你自己的数据,不是套话)。
- **暂停 / 恢复** 后台 AI,随时从横幅上切。

除了生成总结的 Anthropic 调用,数据不出你的机器。

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

纯 shell —— 安装过程不经过 Claude Code。脚本克隆到 `~/.claude-stray/`,装好
`/stray` 斜杠命令、`stray` shell 封装,以及保持面板新鲜的 Claude Code hooks。想先
读读:[`bin/quick-install.sh`](../bin/quick-install.sh)。

> **关于 `~/.claude-stray/`** —— 工具自己的家目录(类似 `~/.fzf`、`~/.nvm`)。
> 别手动 `mv`/`rm -rf` 它;斜杠命令、hooks、`stray` CLI 都持有指向它的绝对路径。
> 更新用 `cd ~/.claude-stray && git pull`(或重跑那条 curl)。要换位置,先
> `bin/uninstall.sh`,再用 `INSTALL_DIR=<路径>` 重装。

安装前可用环境变量覆盖默认:

```bash
INSTALL_DIR=~/code/claude-stray INSTALL_REF=stable LANG_CHOICE=zh-CN NO_SKILL=1 \
  curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

### 手动安装(完全透明)

```bash
git clone https://github.com/Icesource/claude-stray.git ~/.claude-stray
cd ~/.claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # 可选 —— 让 Claude Code 认识这个工具
```

### 依赖

- Python 3.9+
- `claude` CLI **已登录**(Claude Code Pro/Max 订阅即可,无需单独 API key)。
  后台分析没它跑不了。
- macOS 或 Linux(Windows 走 WSL)

**可选**(没有也能用,内嵌终端会优雅降级):

- `ttyd` —— 在卡片里嵌一个真终端(`brew install ttyd`)。
- `tmux`(或 `screen`,macOS 多预装)—— 让内嵌终端**跨页面刷新存活并重绘**
  (`brew install tmux`)。没有的话终端照样能用,只是刷新会重新 `resume`。
  (`abduco`/`dtach` **不行** —— 它们不重绘屏幕,TUI 重连后一片黑。)

## 首次运行(会发生什么)

```bash
stray --serve     # 面板在 http://127.0.0.1:9876/
```

- 首次在空缓存上启动时,面板会在后台分析你最近的会话(约 1–2 分钟)。页面显示
  **「首次同步中…」**,卡片陆续出现;若失败会直接告诉你原因(最常见是 `claude`
  没登录 —— 用 `claude -p hi` 验一下)。
- 会用一点 Haiku —— 几条会话大约 **$0.3–0.5**。
- 首次只同步**最近 48 小时**的会话(更老的在你回头看时懒加载)。要立刻把全部历史
  拉进来,跑 `stray --backfill`。

之后你什么都不用做:每结束一条 Claude Code 会话,它的卡片就在后台更新。

## 用法

```bash
stray --serve              # 面板(常用)
stray                      # 当前缓存的终端树(不调 AI)
stray --refresh            # 立即重新分类并渲染
stray --backfill           # 总结全部历史,不止最近 48h
stray --cost [month]       # 今日 + 近 7 天(或整月)花费
stray --diagnose [SID]     # 「为什么 X 会话没出现?」
stray --pause "原因"       # 暂停后台 AI …
stray --resume             #   … 再恢复
stray --weekly-report      # 上周回顾
stray --next-steps         # 接下来该看的 3 件事
stray --help               # 全部参数
```

在 Claude Code 里,`/stray` 把缓存的面板渲染进对话。面板右上角的 ⟳ 是日常「立即
刷新」。

### 在 Claude Code 对话里

跑过 `bin/install-skill.sh` 后,主 Claude Code agent 就认识 stray,可以回答「我这
周在做什么?」「给我看卡住的」「这个月花了多少?」之类,不用你显式打 `stray`。

## 花费

`claude-stray` 很懒 —— 只在会话结束或调度 tick 时调 API。Haiku-4.5 的典型单次:

| 任务 | 何时 | 单次花费 |
|---|---|---|
| 每会话总结 | 每条会话结束 | ~$0.04 |
| 跨会话分类 | 活跃时约 5 次/天 | ~$0.17 |
| 建议下一句 | 你点某张卡时 | ~$0.02 |
| 周报 | 周五 12:00 | $0.10–$0.50 |

护栏:分类有冷却、未变的会话跳过、每次调用都在每日预算上限内。用 `stray --cost`
实时看。

## 工作原理(简述)

Claude Code 已经写到 `~/.claude/projects/` 的会话,过一条懒管线:**extract**(读
新增的 transcript 字节)→ **summarize**(每会话一次 AI:进展/任务/资源/下一步)
→ **classify/装配**(把卡片摆进板子)→ **serve**(驾驶舱 + hooks 实时状态)。详细
设计见 [`docs/`](.),从 [ARCHITECTURE.md](ARCHITECTURE.md) 开始。

## 排查

1. **面板空 / 「同步失败」** —— 页面现在会写明原因,最常见是 `claude` 没登录
   (`claude -p hi`)。修好后 `stray --refresh`。
2. **某卡没更新** —— Claude Code hooks 可能漂了;`bash bin/install.sh` 安全重装。
3. **会话没出现** —— `stray --diagnose <sid>` 走一遍管线,告诉你哪步丢的。
4. **内嵌终端刷新后变黑** —— 装 `tmux`(`brew install tmux`)即可刷新不丢。

更多见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

## 卸载

```bash
bash bin/uninstall.sh           # 默认 —— 保留你的数据
bash bin/uninstall.sh --purge   # 连缓存 + transcript 也清(y/N 二次确认)
```

默认移除斜杠命令、`stray` CLI、可选 SKILL、`~/.claude/settings.json` 里的 hook
(先备份)。仓库源码、本地缓存、你的 Claude Code transcript 都留着 —— 那是你的数据。

## 许可

MIT —— 见 [LICENSE](../LICENSE)。
