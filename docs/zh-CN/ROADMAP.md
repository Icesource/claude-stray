# Roadmap

已规划但还没落地的工作。把设计原由写下来，避免在 session 之间丢失。

完整设计文档见 [design/](design/)。

英文原版：[../ROADMAP.md](../ROADMAP.md)

| 条目 | 状态 | 文档 |
|---|---|---|
| P11.0 cache 并发锁 | Proposed（下方） | — |
| P11.1 CLI 子命令 | Proposed（下方） | — |
| P11.2 SKILL.md | Proposed（下方） | — |
| P14 AI Pipeline 重设计 | 已实施 | [DD-002](design/DD-002-ai-pipeline-redesign.md) |
| P15 卡片详情 + artifacts | Proposed | [DD-003](design/DD-003-card-detail-and-artifacts.md) |
| P16 Tips 小测验（间隔强化记忆） | Proposed（下方） | — |
| P17 Persona 累积（用户数字人 prompt） | Proposed（下方） | — |
| P13 (历史) 两段式分类 | Superseded | [DD-001](design/DD-001-two-pass-classification.md) |

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
   `raw.githubusercontent.com/Icesource/claude-stray/main/SKILL.md`）
   让别的机器一句话告诉主 Agent 就能安装

### 可选搭档：`SKILL.URL.txt`

单行文件包含 URL。让安装模式可以写成：

```
The mindmap SKILL lives at $(curl -s https://example.com/SKILL.URL.txt) .
```

## P16 — Tips 小测验（间隔强化记忆）

**为什么**：tips 气泡(DD-006、v0.5.0 之后)每轮播 20 条精选内容 —
唐诗宋词、词源、编程史、自然小知识等。用户最初提 tips 的初衷是
"扩充知识面",但当前 UX 完全是 ambient:一条 tip 显示 25 秒就转走,
没有任何复习闭环,看到的诗句和事实其实留不住。

本条 roadmap 加一个轻量的小测验/回忆层,让那些内容真的能"沉下来"。

### 设计草案

- **持久化所有曾经展示过的 tip** 到 `cache/derived/tips/history.jsonl`
  (append-only)。当前 `latest.json` 的 `history[]` 只保留最近
  `HISTORY_LIMIT` (6) 轮,小测验需要更长的尾巴。
- **每 N 天生成一次小测验**(可配,默认每周一次)。素材是过去 wisdom
  + curiosity 条目的抽样(work 和 rest 不算 — 不需要记忆)。AI 给每
  条选合适的题型:
  - **填空(cloze)**: 挖一个词/短语,让用户填。例如 "竹外桃花
    三两枝,___ 鸭先知。"
  - **选择题**: 作者是谁、出处是什么、词源。
  - **自由回忆**: "CC0 是什么意思?",揭示时给出答案 + 原 source
    URL。
- **测验入口**: sidebar 加一个 widget `📚 复习一下`,点开弹个小
  modal,一次一题。用户作答 → 看到正确答案 + 原始 source 链接 → 标
  记"记住了"/"忘了" → 反馈到 SuperMemo-2 风格的间隔曲线,忘了的会
  更早再出现。
- **source URL 是信任锚点**: 每道题的答案 reveal 时显示原 tip 的
  `↗` 来源链接。因为每个题都源自之前已经验证过来源的 tip,小测验
  本身不会进入幻觉空间。

### 待定设计问题(实施时再敲)

- 每周一次还是按需触发?默认每周 + 手动"再来一题"按钮。
- 小猫做什么反应?Pet sprite 可以在测验时切换姿势("教学模式")。
- 间隔重复状态的存储 schema:每个 tip 加 `next_review_at` /
  `interval_days` / `streak`。存哪里 — 跟 history.jsonl 放一起还是
  单独 `quiz_state.json`?
- 出题 prompt:中文诗词的 cloze 题型和英文 trivia 不一样,要分开处
  理。
- 成本:每周触发一次出题,Haiku 看 ~30 条 tip 作为 context,可忽略
  (~$0.02/轮),远小于 classify 一轮。

### 为什么先放 Roadmap 而非 DD

这是一个面向用户的特性,形态比较清晰(sidebar widget + 持久化历史
+ 周度调度),没有跨多文件 / schema 变更 / prompt 大改之前还到不
了 DD 门槛。落地时再升 DD。

## P17 — Persona 累积(用户的数字人 prompt)

**为什么**: 当前每次 Stop hook 触发 Layer 1 总结 session,服务于工
作 mindmap。同一个 hook 几乎零额外成本,可以同时蒸馏出**用户的工
作方式** — 语气、决策风格、惯用措辞、什么让他烦、什么会反复 double-
check、纠错时的句式。累积几百个 session 后,这份 persona 文件足够
丰富,可以作为"数字人" prompt — 一个能用用户语气、按用户思路做决
定的 AI agent。

### 草案

- **触发时机**: 蹭已有的 Layer 1 Stop-hook,或 Layer 2(看 cross-
  session 信号、不只一个 session)。新 prompt 输出 patch:
  ```yaml
  - trait: "倾向于代码尽量精简,除非主动要求不写注释"
    confidence: medium
    evidence: "session abc123 turn 4 显式说'别写注释'"
  - trait: "声明 'done' 前必跑测试"
    confidence: high
    evidence: "近 30 天 12 个 session 一致"
  ```
- **存储**: `cache/persona/traits.jsonl`(append-only),加一份周期
  性重新生成的 `cache/persona/digest.md` — 去重 + 按 confidence 排
  序的人类可读 persona 摘要。
- **衰减**: 若干周没被强化的 trait 会降 confidence(人会变化)。
  digest 只暴露超过 confidence 下限的 trait。
- **输出**: `claude-stray persona` CLI 子命令打印当前摘要,可选导
  出成 system-prompt 形态:
  ```
  $ claude-stray persona --as-system-prompt > /tmp/me.txt
  ```
  用户把这段贴进任何新 AI agent,就能种下自己的"语气基线"。

### 待定设计问题

- **隐私边界**: persona 文件高度个人化。放普通 `cache/`(已
  gitignore),还是独立放到 `~/.claude/persona/`(脱离项目)?是否
  静态加密?
- **漂移检测**: 怎么标记"这个 trait 以前是对的,但最近 20 个
  session 完全相反"?可能要 reinforcement score,遇到相反证据时
  衰减。
- **刻板化风险**: AI 总结一个人,容易偏向 caricature(脸谱化)。
  Mitigation: confidence 下限 + 必须有 evidence + 用户可以手动
  把某个 trait 标 `disputed`(有争议)。
- **AI 成本**: 蹭 Layer 1 的 prompt,每个 session 多输出 ~200
  token,约 $0.001/次。忽略不计。
- **可信度 UI**: dashboard 需要一个"AI 觉得我是个怎样的人"面板,
  让用户审计、编辑、或一键清空。

### 为什么先 Roadmap 而非 DD

隐私姿态、schema、dashboard 暴露面都需要真正的产品思考,这些没敲
定之前不要落 DD。先在这里记住,避免 session 之间丢失。

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
