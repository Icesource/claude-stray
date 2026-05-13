# 故障排查

我们实际遇到过的故障模式决策树。第一站永远是：

```bash
mindmap --diagnose [session_id]    # 省略参数则自动挑最近活跃的
```

它会逐阶段走 pipeline 告诉你哪一步丢了 session。本文档大部分内容
是"根据 diagnose 输出该做什么"。

英文原版：[../TROUBLESHOOTING.md](../TROUBLESHOOTING.md)

## "我新提交的任务/修复/决定没出现在脑图"

### Step 1: 找到你的 session id

在你做工作的那个 Zellij pane 里：

```bash
mindmap --diagnose
```

它会挑最近修改的 jsonl。确认 session id 和首条 prompt 看起来是你的。
不是的话手动找：

```bash
ls -lt ~/.claude/projects/$(pwd | sed 's|/|-|g')/*.jsonl | head
```

### Step 2: 读 diagnose 输出

| `--diagnose` 报告 | 可能原因 | 修复 |
|---|---|---|
| Stage 1 (extract) `summary missing` | hook 没跑过、或 extract 没被调用 | `python3 bin/extract.py` |
| Stage 2 (aggregate) 不在列表，`is_automation=true` | session 首条 prompt 是分类器 prompt 本身（罕见，自我引用） | 等下次 session，或手动删 `cache/sessions/<sid>.json` 重新 extract |
| Stage 2 (aggregate) 不在列表，`user_message_count<1` | 纯工具调用 session，没用户消息 | 预期行为。脑图特意排除 |
| Stage 3 (mindmap) `session_id NOT in any initiative` 且 last AI run < session 活跃时间 | session extract 之后 AI 还没跑过 | `mindmap --refresh` |
| Stage 3 说 session 已分类但卡片内容滞后 | extract 的压缩遮住了最新内容 | 见 ["卡片内容滞后实际工作"](#卡片内容滞后实际工作) |
| Stage 5 `in cooldown` | 最近真实 AI 跑过；下一次 hook 触发被闸门拦住 | 等，或 `mindmap --refresh` 强制 |

### Step 3: 强制跑一次

```bash
mindmap --refresh    # refresh.sh 内部置 CLAUDE_WORKTREE_FORCE=1
```

观察日志：

```bash
tail -f ~/Library/Logs/claude-code-worktree.log              # macOS
tail -f ~/.local/state/claude-code-worktree/refresh.log       # Linux
```

成功跑完会以 `[refresh] wrote ... N workspaces, M initiatives` 加一段
`DIFF vs prior` 摘要结尾。

## 卡片内容滞后实际工作

症状：卡片存在，session_id 也在里面，但 progress 文本/task 仍反映
**旧**状态。

根因：`extract.py` 把每个 session 硬压缩到 ~1.5KB 才给 AI 看。
长 session 或最后一轮是套话开场（"好问题，让我想想"）的 session
会丢失真正的内容。

### 临时方案

- 暂时提高信号上限（env var 尚未实现；要改 `extract.py` 常量后重新
  extract 该 session）。当前限制：`RECENT_PROMPT_LIMIT=5`,
  `SUMMARY_TRIM=1500`, `PROMPT_TRIM=400`
- 强制重新 extract 单个 session：
  ```bash
  rm cache/sessions/<sid>.json
  python3 -c "
  import json
  s = json.load(open('cache/state.json'))
  key = '/Users/.../<sid>.jsonl'
  s.pop(key, None)
  json.dump(s, open('cache/state.json','w'), indent=2)"
  python3 bin/extract.py
  mindmap --refresh
  ```

### 结构性修复

这正是 [DD-001](design/DD-001-two-pass-classification.md) 要解决的
问题：用每 session 一次 AI summary 替代硬压缩。

## "Hook 在触发但什么都没变"

症状：`tail -f` 日志看到 `[hook] ... refresh-bg fired` 但
mindmap.json 的 mtime/内容不动。

### 诊断

```bash
mindmap --diagnose
# 看 [5] "Last real AI run" 和 [6] "Recent hook outcomes"
```

| `[6]` 显示 | 意思 |
|---|---|
| `OK ran AI`（带 DIFF） | AI 这一轮真跑了 |
| `SKIP cooldown` | last_ai_run.epoch 太近（默认 300s 窗口） |
| `skip hash-same` | aggregate_input.json 没变；AI 正常跳过 |
| `skip locked` | 另一次 refresh 还在跑；第二次进入直接退出 |
| `skip no-sessions` | aggregate_input.json 空（罕见） |
| `FAIL` | `claude -p` 失败或超时；日志找 `claude -p failed` |

### 历史 bug：假性 cooldown

commit `9f01447` 之前的 cooldown 用 `mindmap.json` mtime。
apply-overrides 阶段会写这个文件，所以用户任何 UI 编辑都假性重置
clock，让 AI 永远跑不起来。如果你看到这个症状但仓库没拉新代码，
pull 后重装。

## "UI 上勾完成的 task 刷新后又回来了"

不应该发生——apply-overrides 阶段在 AI 看 PRIOR_MINDMAP 之前就把翻
转烤进 mindmap.json，且 prompt 有严格 done-monotone 规则。

如果真发生：

1. 点击后立刻看 `cache/user_overrides.json` ——你的翻转应该在里面
2. 等一次 hook 驱动 refresh，再看——文件应该清空（已消费），
   `cache/mindmap.json` 应该显示 task 完成
3. 如果 refresh 后 task 又回到未完成：
   - 要么 `apply-overrides` 没跑（日志看 `applied N task toggles`）
   - 要么 AI 不顾单调规则覆盖了（日志看 `DIFF vs prior`；如果有
     `done 1→0` 报 bug）

## "归档的卡片刷新后又出现"

通过 UI 归档的不应该出现这种情况——它们被物理移出 `mindmap.json`，
数据存活在 `cache/archive/<ws>/<id>.json`。`render-html.py` 重读
这个目录，所以归档区始终能看到。

如果归档后又作为普通 initiative 出现：

1. 检查 `cache/archive/<ws>/<id>.json` 存在
2. 检查 `cache/mindmap.json` 在所有 workspace 下都**没有**这个 id
3. 如果两点都对但 workspace 还显示该卡片，重启 server（HTML 可能被
   浏览器缓存）。`mindmap --serve` 在 GET / 时检测 mindmap.json 比
   mindmap.html 新就会自动重生成 HTML

## "`mindmap --serve` Ctrl-C 关不掉"

commit `9f01447` 已修。旧代码在 SIGINT handler 里同步调
`httpd.shutdown()`，和主线程的 `serve_forever()` 死锁。新代码用
worker thread 调 shutdown + `daemon_threads=True`。还是老行为就 pull。

## 日志在哪

| 平台 | 路径 |
|---|---|
| macOS | `~/Library/Logs/claude-code-worktree.log` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/claude-code-worktree/refresh.log` |

每条 `[hook] <ISO timestamp>` 开启一次 invocation；到下一条 `[hook]`
之前的所有输出都属于这次 invocation。

## 死活不行：清空重刷

```bash
rm -rf cache/sessions/ cache/state.json cache/last_input.sha256 \
       cache/last_ai_run.epoch
mindmap --refresh
```

保留用户编辑（`user_overrides.json`、archive 目录、deleted_ids、
session_locations）。把 extract+AI pipeline 从头重建一遍。
代价一次 Haiku 调用（~$0.20）。
