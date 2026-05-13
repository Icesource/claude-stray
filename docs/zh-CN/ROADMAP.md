# Roadmap

已规划但还没落地的工作。把设计原由写下来，避免在 session 之间丢失。

完整设计文档见 [design/](design/)。

英文原版：[../ROADMAP.md](../ROADMAP.md)

| 条目 | 状态 | 文档 |
|---|---|---|
| P11.0 cache 并发锁 | Proposed（下方） | — |
| P11.1 CLI 子命令 | Proposed（下方） | — |
| P11.2 SKILL.md | Proposed（下方） | — |
| P13 两段式分类 | Proposed | [DD-001](design/DD-001-two-pass-classification.md) |

## P11.0 — cache 写入的并发锁

**为什么**：多个写者可能同时操作同一 cache 文件。当下：

| 写者 | 文件 |
|---|---|
| `refresh.sh` apply-overrides 阶段 | `mindmap.json`、`user_overrides.json`（读 + 清空） |
| `serve.py /api/save` | `user_overrides.json`、`deleted_ids.json`、`cache/archive/<ws>/*.json` |
| `record-location.py` | `session_locations.json` |
| （未来）CLI `mindmap card/task ...` | 同 `/api/save` |

`refresh.sh` 已经有全局 `mkdir cache/refresh.lock.d` 串行化 refresh，
但**不覆盖** `/api/save` 或规划中的 CLI。最危险的竞争是 **CLI/UI
在 `user_overrides.json` 上做读-改-写，同时另一个写者也碰这个文件**。

### 设计

加 `bin/_cache_lock.py`，导出一个 context manager：

```python
from contextlib import contextmanager
import fcntl
from pathlib import Path

@contextmanager
def cache_lock(name: str = "overrides"):
    """在 cache/.locks/<name>.lock 上拿 POSIX advisory 排他锁。
    阻塞（非自旋）直到拿到。退出 context 时释放。"""
    lock_dir = Path(__file__).resolve().parent.parent / "cache" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    with open(lock_path, "w") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
```

所有写 `user_overrides.json` / `deleted_ids.json` / archive 目录的
路径都用 `cache_lock("overrides")`。锁名空间和 refresh 锁分开，
小的 CLI 写不会排队等 AI 跑完。

### 落地清单

- [ ] 建 `bin/_cache_lock.py`
- [ ] `serve.py /api/save` 包在 `cache_lock("overrides")` 里
- [ ] `refresh.sh` apply-overrides Python 块用同名锁
- [ ] CLI 命令（P11.1）用同名锁
- [ ] `mindmap.json` 最终写入用原子 `tmp + rename`，并发 reader 永远
      看不到半写状态

### 范围之外

- 跨主机并发。仅 loopback。
- 锁超时。操作 <100ms，阻塞没问题。

## P11.1 — CLI 子命令

**为什么**：终端优先的用户想要和 HTML UI 平价的 shell 接口。也是
P11.2（SKILL）的前提：SKILL Agent 可以直接 shell out 到 `mindmap`
CLI，不用学 HTTP API。

### 子命令清单

```
mindmap ls [--status active|paused|done|archived|all]
mindmap show <init-id 或 name 前缀>
mindmap card add                       # 交互式向导
mindmap card archive <init-id>
mindmap card unarchive <init-id>
mindmap card delete <init-id>
mindmap task done <init-id> <title>
mindmap task undone <init-id> <title>
mindmap task add <init-id> <title>
mindmap task del <init-id> <title>
```

所有写命令用 P11.0 的 `cache_lock("overrides")`。

### "创建 initiative" 的语义

用 **overrides 占位** 策略：
- `mindmap card add` 直接往 `mindmap.json` 写一个 stub initiative
  （status=`active`、无 sessions、用户提供 summary/progress/tasks）
- 同时给 `user_overrides.json` 加一个 marker，让 refresh 时的合并
  知道保留这个人造节点
- 下次 AI refresh 在 PRIOR_MINDMAP 看到占位节点；按连续性规则保留
  id+name，只在证据出现时充实 metadata

### 实现说明

- 子命令 dispatcher 在 `bin/mindmap`（bash）里路由到
  `bin/cli_commands.py`（Python）
- Python 端镜像 `effectiveStatus()` 逻辑
- Initiative id 支持 prefix 或 name 子串模糊匹配，用户不用记 id
- bonus：zsh/bash 的 `_mindmap_completion` tab 补全

## P11.2 — Agent 一行安装 SKILL.md

**为什么**：用户给的目标模式：

```
Read https://<url>/SKILL.md and register on the platform.
```

把 SKILL.md 装到 `~/.claude/skills/mindmap/`，主 Agent 自动知道
mindmap 工具——不用每次 session 手动教它。

### 交付物

1. 仓库根（或 `skill/`）下一份 `SKILL.md`，遵循
   [Anthropic SKILL 规范](https://docs.claude.com/en/docs/claude-code/skills)。
   frontmatter 声明：
   - `name: mindmap`
   - `description`：何时激活（用户问当前工作、项目全貌、上次停在哪、
     在做什么）
   - `arguments`：不需要；SKILL 描述如何调 CLI

2. SKILL 正文段落：
   - **What it does** — 一段话讲 mindmap 工具
   - **Commands** — `mindmap` 子命令对照表 + 使用场景
     （"用户问'我在做什么' → `mindmap ls`"）
   - **How it works** — 三阶段 pipeline（extract → aggregate →
     AI classify）、连续性模型、override 流向
   - **Troubleshooting** — 镜像 `mindmap --diagnose` 输出的决策树，
     Agent 不跑 diagnose 也能给用户讲 cooldown / extract / 分类问题
   - **Examples** — 典型用户提问 + Agent 应该跑什么

3. `bin/install-skill.sh`：复制 `SKILL.md` → `~/.claude/skills/mindmap/`
   让当前机器立即生效

4. Hosted URL：发布在稳定 raw URL（GitHub Pages 或
   `raw.githubusercontent.com/Icesource/claude-code-worktree/main/SKILL.md`）
   让别的机器一句话告诉主 Agent 就能安装

### 可选搭档：`SKILL.URL.txt`

单行文件包含 URL。让安装模式可以写成：

```
The mindmap SKILL lives at $(curl -s https://example.com/SKILL.URL.txt) .
```

## 不在 Roadmap 内

这些考虑过，暂时不做：

- **增量 AI**（只把新 session 喂给 AI）。打破"AI 看到全部、自己判
  断"的模型，失去跨 session 分类能力。Haiku + prompt cache 成本本来
  就很低。

- **活跃度感知 cooldown**（发现 N 个新 session 就缩短 cooldown）。
  边际收益不抵实现复杂度。用户可以在 shell 里覆盖
  `CLAUDE_WORKTREE_COOLDOWN_SECS`。

- **服务端权威状态**（overrides 搬到 server，client 发 delta）。当前
  "client 持有完整状态、server 是哑存储"模型更简单，竞争窗口对单
  用户场景太短不值得修。

- **自定义 URL scheme**（如 `claude-mindmap://resume/<id>`）做跨进
  程跳转。仅 macOS、配置复杂；`/focus` 和 `/newpane` HTTP endpoint
  已经覆盖实际需求。
