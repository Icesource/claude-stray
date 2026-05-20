# claude-stray

Claude Code 的本地工作伙伴：把你的会话历史转成 AI 自动分类的卡片式
工作台 —— 卡片、任务、周报、成本追踪，外加一只走来走去的像素小猫给你
念诗。

[English](../README.md) · [架构](zh-CN/ARCHITECTURE.md) · [Roadmap](zh-CN/ROADMAP.md) · [Release 模型](zh-CN/RELEASE.md) · [Changelog](../CHANGELOG.md)

![dashboard 截图](assets/dashboard-preview.png)
<!-- 截图缺失的话，dashboard 在 http://127.0.0.1:9876/ -->

## 它能干什么

`claude-stray` 监听 `~/.claude/projects/*.jsonl` 会话文件，走三层 Haiku
pipeline（extract → 单 session 总结 → 跨 session 分类），产出：

- **Dashboard** 在 `http://127.0.0.1:9876/`，每个 initiative 一张卡：
  summary / progress / tasks（三态：pending / done / cancelled）/
  blockers / artifacts（CR / MR / PR / issue / branch）/ 工作区
  sidebar / 状态过滤 / 搜索。
- **周报**，每周五正午自动生成。
- **下一步建议** —— 基于数据的 3 条聚焦推荐。
- **Tips 气泡** —— 每批 20 条精选内容（诗句、词源、编程史），每条带
  source URL 可点击核验。每 25 秒切换，气泡可拖到任意位置。
- **成本追踪** —— `stray --cost` 按层/日/周/月分项 token 开销。
- **生命周期 pause/resume** —— dashboard 顶栏一键 kill switch，
  demo / 专注时段不让 AI 在后台跑。

除了走 Anthropic API 的网络调用，所有数据留在你自己的机器上。

## 安装

### 方式 A —— 一行命令安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

纯 shell,不经过 Claude Code。脚本会做依赖检查 → clone 到
`~/Code/claude-stray`(`INSTALL_DIR=<path>` 可改)→ 跑 `bin/install.sh`
→ 安装 SKILL 到 `~/.claude/skills/stray/`。

想先看脚本再 pipe?
[`bin/quick-install.sh`](../bin/quick-install.sh) 是源。

支持的环境变量(放在 pipe 前面):

```bash
INSTALL_DIR=~/dev/claude-stray \
INSTALL_REF=v0.6.0 \
LANG_CHOICE=en \
NO_SKILL=1 \
  curl -fsSL https://raw.githubusercontent.com/Icesource/claude-stray/main/bin/quick-install.sh | bash
```

### 方式 B —— 手动,完全透明

```bash
git clone https://github.com/Icesource/claude-stray.git ~/Code/claude-stray
cd ~/Code/claude-stray
bash bin/install.sh
bash bin/install-skill.sh    # 可选 — 装 SKILL 让主 agent 自动调 stray
```

`bin/install.sh` 配置：

- Slash 命令 `/stray` 与 `/stray-refresh`（附 `/mindmap*` 老别名，
  v0.7 会移除）
- `~/.local/bin/stray` shell wrapper（附 `mindmap` 别名）
- Claude Code 的 `Stop` + `SessionStart` hook 写入
  `~/.claude/settings.json`

### 安装后

```
/stray-refresh          # 在 Claude Code 里跑,首次约 30-120s
stray --serve           # 终端启动,自动开 http://127.0.0.1:9876/
```

首次 refresh 之后,每个 session 都通过 hook 自动更新;in-process 调
度器负责 tips(每 2h)和周报(周五 12:00)。

> **关于"让 Claude Code 帮我装"这条路。** README 早期版本曾建议在
> Claude Code 里粘贴 `Read <SKILL URL> and install it`。Claude Code
> (正确地)把这种模式当作 prompt 注入向量,会拒绝。安装必须走 shell;
> SKILL 的作用是**装完之后**让主 Claude Code agent 知道这个工具,不是
> 用来当安装入口。

### 依赖

- Python 3.9+
- 已登录的 `claude` CLI（Claude Code Pro/Max 订阅即可，不需要单独
  API key）
- macOS 或 Linux（Windows 走 WSL）

## 使用

### CLI

```bash
stray --serve              # dashboard 在 http://127.0.0.1:9876/（推荐）
stray                      # 终端树视图，零 AI 调用
stray --refresh            # 强制重新分类后渲染
stray --cost               # 今天 + 近 7 天成本表
stray --cost month         # 整月分项
stray --diagnose [SID]     # 为什么 session X 没出现？
stray --pause "demo 备战"  # kill switch
stray --resume             # 释放 kill switch
stray --weekly-report      # 生成上周周报
stray --next-steps         # 下一步 3 条建议
stray --help               # 全部 flag
```

`mindmap` 是 `stray` 的兼容别名，参数完全一致。

### Slash 命令

```
/stray              # 渲染缓存 dashboard 到聊天里
/stray-refresh      # 强制 refresh 后渲染
```

### 在 Claude Code 里对话

SKILL（见上文 [方式 A](#方式-a--一行命令通过-skill-安装推荐)）让主
Claude Code agent 知道 stray 存在。装完后可以直接问：

- "我这周在搞什么？"
- "这个月在 Claude 上花了多少钱？"
- "现在哪些卡住了？"
- "继续我周二做 HSF MR 清理那次的 session"

不用显式调 `stray`。

## 成本

三层 pipeline 懒执行 —— 只在 hook 触发或 dashboard 调度器到点时跑。
Haiku-4.5 下每层单次典型开销：

| 层 | 何时 | 单次 |
|---|---|---|
| Layer 1 总结 | 每个 session 的 Stop hook | ~$0.04 |
| Layer 2 分类 | 合并触发，活跃使用约 5 次/天 | ~$0.17 |
| Tips | `--serve` 时每 2 h | ~$0.08 |
| 周报 | 周五 12:00 | $0.10–$0.50 |
| Next-steps | 每次 classify 后 | ~$0.05 |
| Wellness | 蹭 tips 的 tick；命中信号才 AI 调用 | 最多 ~$0.02 |

硬约束：classify 15 分钟冷却、dirty-tracking 跳过未变 session、
每个 `claude -p` 调用都带 `--max-budget-usd` 日预算上限。

实时查看：`stray --cost`（默认：今天 + 7 天表）或 `stray --cost month`。

可调参：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `CLAUDE_WORKTREE_MODEL` | `claude-haiku-4-5-20251001` | Layer 2 模型 |
| `CLAUDE_WORKTREE_COOLDOWN_SECS` | `900` | classify 间最小间隔 |
| `CLAUDE_WORKTREE_TIMEOUT` | `600` | `claude -p` 超时 |

## 数据模型

Initiatives → sessions → tasks。完整 schema 和背后的设计决策见
[`docs/design/`](design/)。近期重要里程碑：

- [DD-002](design/DD-002-ai-pipeline-redesign.md) —— 三层 pipeline 架构
- [DD-005](design/DD-005-lifecycle.md) —— opt-in pause/resume
- [DD-006](design/DD-006-card-derived-ai-features.md) —— 周报 / next-steps / tips / wellness
- [DD-011](design/DD-011-task-model-final.md) —— 三态 task 模型，单存储，无归档目录

## 排错

绝大多数问题是下面 4 类之一：

1. **Dashboard 空** —— 跑一次 `stray --refresh`
2. **卡片没更新** —— hook 可能丢失，重跑 `bin/install.sh`
3. **某个 session 不在** —— `stray --diagnose <sid>` 走完整个 pipeline
   告诉你哪一步丢了
4. **感觉花得贵** —— `stray --cost month` 看分层细分，常见原因记录
   在 [TROUBLESHOOTING.md](zh-CN/TROUBLESHOOTING.md)

SKILL（[`SKILL.md`](../SKILL.md)）内嵌了完整决策树，Claude Code 不用
跑 `--diagnose` 也能引导用户排查。

## 卸载

```bash
bash bin/uninstall.sh           # 默认 — 保留用户数据
bash bin/uninstall.sh --purge   # 顺手清掉 cache + session 历史(y/N 确认)
```

默认清理我们装到你机器上的 5 件东西:slash 命令、CLI wrapper、
`~/.claude/skills/stray/` 的 SKILL、`~/.claude/settings.json` 里的
hook 配置(先备份成 `.bak.<时间戳>`)、残留的 macOS launchd plist。
**保留的**:repo 源码、本地 cache、`~/.claude/projects/...` 下的
Claude Code 会话 jsonl —— 那些是你自己的数据。

`--purge` 额外清掉 `cache/` 并提示 y/N 是否删除 session 历史。脚本
退出时会打印手动 `rm -rf` 的命令删 repo 源码本身(脚本不能自删)。

## License

MIT —— 见 [LICENSE](../LICENSE)。
