# claude-stray

AI 驱动的终端工作树 — 自动将 Claude Code 会话分类为项目并追踪进度。

[English](../README.md)

## 效果

读取你的 Claude Code 会话历史,用 AI 自动分类,直接在终端渲染工作全景:

```
Claude Code Worktree  (generated 2m ago)
────────────────────────────────────────────────────────────
├── my-saas-app  [● active]  4m ago  6 sessions
│   ~/code/my-saas-app
│   构建用户认证和仪表盘功能。
│   progress: OAuth 集成已完成,正在实现管理面板的
│             基于角色的访问控制。
│   tasks:
│     ├─ ✓ 搭建 OAuth2 登录流程
│     ├─ ✓ 设计仪表盘布局
│     ├─ ○ 实现管理面板 RBAC
│     └─ ○ 添加认证中间件单元测试
│
├── data-pipeline  [● active]  2h ago  8 sessions
│   ~/code/data-pipeline
│   从 Kafka 处理分析事件的 ETL 管道。
│   progress: Kafka 消费者和转换阶段已完成,
│             正在编写 BigQuery 输出连接器。
│   tasks:
│     ├─ ✓ 带偏移追踪的 Kafka 消费者
│     ├─ ✓ JSON schema 校验阶段
│     ├─ ○ BigQuery 输出连接器
│     └─ ○ 死信队列处理
│
└── archived (2)
    ├─ dotfiles (shell 配置清理)    (10d ago, 2s)
    └─ scratch-pad (临时实验)       (21d ago, 5s)
```

## 安装

```bash
git clone https://github.com/Icesource/claude-stray.git ~/code/claude-stray
cd ~/code/claude-stray
bash bin/install.sh
```

一条命令完成所有事:安装 slash 命令、CLI 封装、Claude Code hooks 和
macOS 定时任务(如适用)。安装过程不会触发模型调用。

然后打开 Claude Code,运行:

```
/mindmap-refresh
```

首次运行会调用 AI 分类(约 30-120 秒),你可以实时看到模型的分类过程。
此后工作树会在后台自动刷新,随时用 `mindmap` 或 `/mindmap` 查看即可。

### 环境要求

- Python 3.9+
- `claude` CLI 已安装且已登录
- Claude Code 有效订阅(Pro/Max)— 复用现有额度,无需单独 API Key
- macOS 或 Linux(Windows 通过 WSL)

## 使用

### 终端(即时,零模型开销)

```bash
mindmap              # 渲染缓存的树形图
mindmap --refresh    # 先刷新再渲染
```

在 Claude Code 中,用 `!` 前缀获得同样的即时输出:

```
!mindmap
!mindmap --refresh
```

### Slash 命令(支持 Tab 补全,经过模型)

```
/mindmap             # 显示缓存的树形图
/mindmap-refresh     # 强制刷新后显示
```

## 自动刷新

工作树自动保持新鲜,正常使用无需手动刷新:

- **每次 Claude Code 响应后** — `Stop` hook 触发后台刷新
- **会话启动时** — `SessionStart` hook 确保数据最新
- **每 2 小时** — macOS LaunchAgent 兜底(Linux 可配置 cron,见安装输出)

所有刷新在后台运行,不会阻塞你的工作。

## 成本与性能

分类默认使用 **Haiku** 模型,快速且便宜。三层保护防止不必要的开销:

1. **冷却期**(15 分钟)— 上次刷新后短时间内跳过 AI 调用
2. **哈希跳过** — 会话数据未变化时跳过 AI 调用
3. **增量提取** — 只读取 session 文件中的新增字节

| 场景 | 花费 |
|------|------|
| 冷却期内 | **$0**(跳过 AI 调用) |
| 会话数据未变化 | **$0**(哈希跳过) |
| 典型刷新(~100 个会话) | ~$0.01–0.05 |

每次 AI 调用在日志中记录 token 用量:

```
[refresh] usage: in=18200 (+0 cache-create) out=1500 cost=$0.0234 prompt=42KB elapsed=15s
```

可通过环境变量覆盖默认值:

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLAUDE_WORKTREE_COOLDOWN_SECS` | `900`(15 分钟) | AI 调用最小间隔 |
| `CLAUDE_WORKTREE_MODEL` | `claude-haiku-4-5-20251001` | 分类用模型 |
| `CLAUDE_WORKTREE_TIMEOUT` | `600`(10 分钟) | `claude -p` 超时 |

## 项目状态

| 状态 | 图标 | 条件 |
|------|------|------|
| active | `●` | 3 天内有活动 |
| paused | `◐` | 3-14 天空闲,或有恢复信号 |
| done | `✓` | 明确完成 |
| archived | `▪` | 超过 14 天空闲且无恢复信号 |

## 工作原理

1. **`extract.py`** — 增量读取 `~/.claude/projects/**/*.jsonl`,生成结构化摘要。
2. **`aggregate.py`** — 过滤噪声,按时间排序,输出紧凑 JSON。
3. **`refresh.sh`** — 将会话数据 + 分类提示词喂给 `claude -p`,生成 `mindmap.json`。
4. **`render.py`** — 用 Python 标准库渲染彩色 ANSI 树形图(无需 pip install)。

## 故障排除

- **"No mindmap cache found"** — 运行 `mindmap --refresh`。
- **后台刷新未触发** — 用 `jq .hooks ~/.claude/settings.json` 确认 hook 已安装。
  Hook 仅对安装后新启动的会话生效。
- **"Not logged in"** — 运行 `claude /login`。
- **数据过时** — 运行 `mindmap --refresh`,查看日志了解原因。

## 卸载

```bash
bash bin/uninstall.sh
```

会移除 slash 命令、CLI 封装、Claude Code hooks 和 macOS LaunchAgent。
仓库本身不会被删除。

## 许可证

MIT
