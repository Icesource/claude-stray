# DD-002: AI Pipeline 重设计

**Status**: Proposed
**Author**: bby
**Date**: 2026-05-14
**Supersedes**: DD-001（两段式分类）—— DD-002 是其完整版

英文原版：[../../design/DD-002-ai-pipeline-redesign.md](../../design/DD-002-ai-pipeline-redesign.md)

> 整合 P13 系列讨论的完整设计。涵盖：核心抽象、文件布局、三层架构、
> mtime dirty tracking、冷热分层、并发模型、数据模型、走查、迁移。

---

## 目录

- [1. 问题集](#1-问题集)
- [2. 核心抽象与映射](#2-核心抽象与映射)
- [3. 文件目录设计](#3-文件目录设计)
- [4. 三层架构](#4-三层架构)
- [5. Dirty Tracking](#5-dirty-tracking)
- [6. 冷热分层](#6-冷热分层)
- [7. 并发模型](#7-并发模型)
- [8. 数据模型](#8-数据模型)
- [9. 端到端走查](#9-端到端走查)
- [10. 迁移方案](#10-迁移方案)
- [11. 风险与回滚](#11-风险与回滚)
- [12. 开放问题](#12-开放问题)

---

## 1. 问题集

四个互相纠缠的问题，根因都是 **AI 被要求在一次调用里、用浅信息、
做多种任务、处理远超必要的数据量**。

| # | 问题 | 当前症状 | 当前实现 |
|---|---|---|---|
| A | 全量喂入 | 200 session 每次 refresh 全过 AI，其中 ~190 一动不动 | `aggregate.py` 平等对待所有 session |
| B | 单次 AI 任务过载 | 分组 + 命名 + status + tasks + 连续性 5 件事一锅煮 | 1 prompt + Haiku 全包 |
| C | 没 dirty tracking | 不知道什么变了，只能全量重算 | 粗粒度 `last_input.sha256` |
| D | 信息密度低 | extract 每 session 压到 1.5KB，AI 看不到对话原文 | 多个有损压缩字段 |

实际表现：用户花 90 分钟排查 bug、提了 ISSUE，卡片上仍显示"还在 arthas watch"。
信息根本没传达到 AI 那里。

---

## 2. 核心抽象与映射

### 2.1 三个抽象的关系

```mermaid
erDiagram
    JSONL ||--|| SESSION : "1:1 (sid is filename)"
    SESSION ||--|| EXTRACT : "extract.py writes"
    SESSION ||--|| SUMMARY : "Layer 1 writes"
    SESSION ||--o| LOCATION : "hook writes (optional)"
    INITIATIVE ||--o{ SESSION : "0..N sessions per initiative"
    WORKSPACE ||--o{ INITIATIVE : "1..N initiatives per workspace"
    INITIATIVE ||..o{ CWD : "linked_cwds (optional)"

    JSONL { string path "~/.claude/projects/.../sid.jsonl" }
    SESSION { string sid "UUID" }
    EXTRACT { string path "cache/sessions/sid.json" }
    SUMMARY { string path "cache/summaries/sid.md (NEW)" }
    LOCATION { string path "cache/session_locations.json[sid]" }
    INITIATIVE { string id "stable" string name "AI-generated" }
    WORKSPACE { string name "AI-decided primary owner" }
    CWD { string path "the cwd that semantically owns" }
```

**关键关系**：

| 关系 | 基数 | 谁决定 |
|---|---|---|
| jsonl ↔ session | 1:1 | Claude Code（文件名 = session_id） |
| session → initiative | N:1 | AI 推断（在 Layer 2 分类时） |
| initiative → workspace | N:1 | AI 推断（按语义归属） |
| initiative → cwd | 1:1 主 + N linked | AI 选最贴合的主 cwd |

**Card** = HTML UI 上的一个卡片 = 一个 initiative 的可视化。一一对应。

### 2.2 信息流向

```mermaid
flowchart LR
    A["~/.claude/projects/<br/>X.jsonl"] -->|"extract.py"| B["cache/sessions/X.json<br/>(机器可读字段)"]
    B -->|"Layer 1<br/>per-session AI"| C["cache/summaries/X.md<br/>(narrative markdown)"]
    C --> D{"hot or cold?"}
    D -->|"hot (last 48h)"| E["进 Layer 2 prompt"]
    D -->|"cold"| F["仅在 PRIOR 中存在"]
    E --> G["Layer 2<br/>cross-session AI"]
    F --> G
    G --> H["cache/mindmap.json"]
    H --> I["render-html.py / etc"]
    H -.->|"下一轮的 PRIOR"| G

    style B fill:#ffd3b6,color:#000
    style C fill:#a8e6cf,color:#000
    style G fill:#fff3a0,color:#000
    style H fill:#a8e6cf,color:#000
```

---

## 3. 文件目录设计

### 3.1 完整布局

```
cache/                                    # 全部 gitignore
│
├── config.json                           # {lang: zh-CN}
├── mindmap.json                          # 主输出 (schema v2)
├── mindmap.html                          # 渲染产物
├── mindmap-tree.html                     # 渲染产物
│
├── sessions/                             # Stage 0: extract 输出
│   ├── <sid1>.json                       # 机器可读字段
│   ├── <sid2>.json
│   └── ...
│
├── summaries/                            # ⭐ NEW: Layer 1 输出
│   ├── <sid1>.md                         # AI 写的 narrative markdown
│   ├── <sid2>.md
│   └── ...
│
├── state.json                            # extract 的 byte offset 表
├── session_locations.json                # hook 写的 zellij pane 信息
│
├── user_overrides.json                   # UI 编辑的 task done 翻转
├── deleted_ids.json                      # 用户主动删除的 tombstone
├── archive/<workspace>/<id>.json         # 用户归档的 initiative 全量
│
├── .locks/                               # ⭐ NEW: 细粒度锁目录
│   ├── summary-<sid>.lock                # Layer 1 per-sid flock
│   ├── layer2.lock                       # Layer 2 单进程 flock
│   └── layer2.pending                    # Layer 2 coalesce 标记
│
└── (废弃)
    ├── aggregate_input.json              # ❌ Layer 2 直接读 summaries/
    ├── last_input.sha256                 # ❌ 用 mtime 比较代替
    ├── last_ai_run.epoch                 # ❌ 没 cooldown 了
    └── refresh.lock.d/                   # ❌ 锁粒度太粗
```

### 3.2 与代码组件的对应

```mermaid
graph LR
    H["Stop / SessionStart hook"] --> RB["refresh-bg.sh<br/>(simplified)"]
    RB --> RL["record-location.py"]
    RB --> EX["extract.py"]
    RB --> L1["summarize.py ⭐ NEW"]
    RB --> L2T["layer2-trigger.sh ⭐ NEW"]

    EX -.写.-> SESS["cache/sessions/"]
    L1 -.读.-> SESS
    L1 -.读.-> JL["~/.claude/projects/<br/>*.jsonl 尾部"]
    L1 -.写.-> SUMM["cache/summaries/"]

    L2T -.->|coalesce<br/>flock+pending| L2["classify.py ⭐ NEW"]
    L2 -.读.-> SUMM
    L2 -.读.-> MJ["cache/mindmap.json<br/>(作 PRIOR)"]
    L2 -.读.-> DEL["cache/deleted_ids.json"]
    L2 -.写.-> MJ

    MJ --> RH["render-html.py"]

    style L1 fill:#a8e6cf,color:#000
    style L2 fill:#a8e6cf,color:#000
    style L2T fill:#a8e6cf,color:#000
```

新增脚本：

| 脚本 | 角色 |
|---|---|
| `bin/summarize.py` | Layer 1：读 1 个 session 的 jsonl 尾部，调 Haiku 写 `summaries/<sid>.md` |
| `bin/layer2-trigger.sh` | Layer 2 触发：用 flock + pending 实现 coalesce |
| `bin/classify.py` | Layer 2：读 summaries + PRIOR，调 Haiku 写 `mindmap.json` |

废弃：

- `bin/refresh.sh` 大幅瘦身（不再包揽所有阶段，只做 apply-overrides + 拉起各 layer）
- `bin/aggregate.py` 不再需要

---

## 4. 三层架构

### 4.1 总览

```mermaid
flowchart TD
    subgraph L0["Layer 0: Extract（机器机械活）"]
        EX["extract.py<br/>jsonl byte offset → 增量解析"]
    end
    subgraph L1["Layer 1: Per-session digest（AI 理解单 session）"]
        SU["summarize.py<br/>对单个 session 调 Haiku<br/>读 jsonl 尾部 ~30KB"]
    end
    subgraph L2["Layer 2: Cross-session classify（AI 跨 session 归类）"]
        CL["classify.py<br/>读 summaries + PRIOR<br/>调 Haiku 写 mindmap.json"]
    end

    H["Stop / SessionStart hook"] --> EX
    EX -->|dirty per sid| SU
    SU -->|trigger via mtime| L2T["coalesce trigger"]
    L2T --> CL

    style L1 fill:#a8e6cf,color:#000
    style L2 fill:#fff3a0,color:#000
```

### 4.2 Layer 0: Extract

**不变**。继续是机械增量解析 jsonl 写 `cache/sessions/<sid>.json`。

变化：可以**简化字段**——既然 Layer 1 会拿 jsonl 原文，extract 的
重压缩字段（first_user_prompt / last_assistant_summary 等）不再被
下游使用。Layer 0 只需要保留**机器信号**：

```jsonc
{
  "session_id": "...",
  "cwd": "...",
  "started_at": "...",
  "last_activity_at": "...",
  "user_turns": 16,
  "edits": [{"file": "...", "kind": "create", "ops": 3}, ...],
  "tools": {"Bash": 12, "Read": 30, "Edit": 3},
  "task_events": ["created: ...", "completed: ..."]
}
```

文本内容（prompts / 回复）**完全交给 Layer 1 处理**。

### 4.3 Layer 1: Per-session digest

**职责**：单个 session → 一份结构化叙述。

**输入**：
- `cache/sessions/<sid>.json` （机器信号）
- `~/.claude/projects/.../<sid>.jsonl` 的**尾部** ~30KB
  （最近 10 个 user-assistant turn 的原文）

**输出**：`cache/summaries/<sid>.md`

```markdown
---
session_id: cbbeb23c-b6f9-4eb4-926e-7e4046c856d4
cwd: /Users/bby/Code/pandora/pandora-sar/hsf
last_activity_at: 2026-05-13T09:19:46Z
user_turns: 16
updated_at: 2026-05-13T09:25:00Z
status_guess: active
---

# 目标
排查 EagleEye 链路追踪服务端 IP 为空的问题。涉及 mtop 入口转 HSF
调用场景下的 span 归属。

# 当前状态
已定位根因：EagleEyeHttpHook.beforeProcess 中 logRemoteIp 传错了
参数（传了本机 IP 而非真正的远端 IP）。修复方案明确。

# 已下的决定
- 修改 EagleEyeHttpHook，从 HSFRequestContext 取真正的 remoteIp
- 对 mtop-uncenter 场景特殊处理（本机调用，源和目标都是本机 IP）

# 产物
- /tmp/aone-issue-hsf-eagleeye.md（已创建，待提交）

# 下一步
提交 Aone ISSUE，指派给自己；开发分支修复 EagleEyeHttpHook。

# 待解决
无（修复方案已明确）

# 任务（建议）
- [x] 收集带 @s0 前缀的 EagleEye data 样本
- [x] 用 arthas watch 抓取现场数据
- [x] 定位根因（EagleEyeHttpHook 传错参）
- [x] 撰写 Aone ISSUE 草稿
- [ ] 提交 ISSUE 到 Middleware RPC 项目
- [ ] 开发修复分支
```

**Prompt 草图**（`prompts/summarize-session.md`，~80 行）：

```
你在阅读 Claude Code 一次完整会话的尾部，目标是产出一份结构化叙述
markdown，供后续跨 session 分类使用。

输入：
  - SESSION_META: 这次会话的元数据（user_turns, edited_files 等）
  - TURNS: 最近 10 轮 user-assistant 的完整文本

输出严格 markdown，包含以下段落（按顺序）：
  # 目标 — 1-2 句话，用户为什么开这个 session
  # 当前状态 — 截至最后一轮，工作站在哪里
  # 已下的决定 — bullet 列表，活到现在的决策
  # 产物 — 编辑/创建的文件
  # 下一步 — 用户或 AI 明示的下一步
  # 待解决 — 挂起的问题
  # 任务（建议） — [x] / [ ] 列表，每条 ≤ 60 字符

规则：
  - 最后一轮 = 最权威信号；recap 和首条 prompt 可能已经过时
  - 如果 session 在闲扯（如 "好的"、"继续"），不要硬挤内容；可写
    "（无有效进展）"
  - status_guess 推断：active（有明确推进）/ paused（中途没接） /
    done（用户确认完成或 ship） / abandoned（看起来放弃了）
```

**触发**：Stop hook → 检查 dirty（见 §5）→ 跑

**成本**：~$0.01 / 次（Haiku, ~5KB prompt, ~1KB 输出，~5-10s）

**并发**：完全并发，per-sid flock。详见 §7。

### 4.4 Layer 2: Cross-session classify

**职责**：所有 hot summaries + PRIOR → mindmap.json。

**输入**：
- `cache/summaries/<sid>.md` 对所有 **hot** session（详见 §6）
- `cache/mindmap.json` 作为 PRIOR_MINDMAP（slim 后）
- `cache/deleted_ids.json` 作为 DELETED_IDS

**输出**：`cache/mindmap.json`（schema v2 不变）

**Prompt 草图**（`prompts/classify-cross-session.md`）：

```
你在做跨 session 分类。把一组 hot session summaries 归类到
initiative，并维护跨刷新的连续性。

输入：
  - HOT_SUMMARIES: 一组结构化 markdown 摘要（来自 Layer 1）
  - PRIOR_MINDMAP: 上一轮的分类结果
  - DELETED_IDS: 用户主动删除的 initiative id（tombstone）

输出严格 JSON: mindmap.json (schema v2)

铁律：
  1. PRIOR 里有、但 HOT_SUMMARIES 没出现的 initiative（cold）：
     只允许动 status（按时间衰减规则）；name/summary/tasks 必须保留 PRIOR 原值
  2. PRIOR 里的 initiative id 必须复用；不允许重命名 id
  3. Task done=true 单调，不能改回 false
  4. DELETED_IDS 里的 id 永远不出现在输出中
  5. session_id 必须是完整 UUID

新增 initiative 仅当 HOT_SUMMARIES 提供新证据且不属于任何已有 initiative
```

**触发**：summaries 比 mindmap.json 新 → 触发 Layer 2（详见 §7 coalesce）

**成本**：~$0.05 / 次（Haiku, ~40KB prompt, ~10KB 输出，~30s）

**并发**：单进程 + coalesce。详见 §7。

---

## 5. Dirty Tracking

用文件 mtime 作为隐式 dirty bit，无需独立标记文件。

```mermaid
flowchart LR
    JL["jsonl<br/>mtime: T0"] -->|extract| SJ["sessions/sid.json<br/>mtime: T1"]
    SJ -->|"Layer 1<br/>summarize.py"| SM["summaries/sid.md<br/>mtime: T2"]
    SM -->|"Layer 2<br/>classify.py"| MM["mindmap.json<br/>mtime: T3"]

    classDef mtime fill:#fff,stroke:#000,color:#000
    class JL,SJ,SM,MM mtime
```

判断规则：

| 比较 | 含义 | 该跑什么 |
|---|---|---|
| `T0 > T1` | jsonl 有新字节，extract 滞后 | 跑 extract |
| `T1 > T2` | session 已 extract，但 summary 滞后 | 跑 Layer 1（per-sid） |
| `任意 T2 > T3` | 至少一个 summary 比 mindmap 新 | 触发 Layer 2 |

**规则**：

1. **写文件即承认"我变了"**——只有真正写出新内容时才能更新文件 mtime。
   不允许"无意义写"（如只 bump generated_at 字段）。
2. **比较时取自由**：用 `os.stat().st_mtime`，POSIX 原子读，多进程安全。
3. **崩溃恢复**：进程崩溃后下次启动只看 mtime 即可恢复进度。

**触发逻辑伪代码**：

```python
# Stop hook → refresh-bg.sh → for each session whose jsonl was touched:
def maybe_layer1(sid):
    extract_path = f"cache/sessions/{sid}.json"
    summary_path = f"cache/summaries/{sid}.md"
    if not exists(summary_path) or mtime(extract_path) > mtime(summary_path):
        run_layer1(sid)
        trigger_layer2()   # 见 §7

# layer2-trigger.sh
def trigger_layer2():
    summaries_max = max(mtime(p) for p in glob("cache/summaries/*.md"))
    if summaries_max > mtime("cache/mindmap.json"):
        run_layer2_with_coalesce()
```

---

## 6. 冷热分层

### 6.1 阈值

**Hot session**：`last_activity_at` 在过去 48 小时内。

**Cold session**：其它。

48h 边界：考虑你 ±1 天的工作节奏（开发周末断档常见），48h 足够覆盖
"昨天没碰但今天继续"的场景。

可调，通过 `CLAUDE_WORKTREE_HOT_HOURS=48` env var。

### 6.2 行为对照

| 维度 | Hot session | Cold session |
|---|---|---|
| Layer 1 触发 | 正常（dirty 就跑） | 同左（用户不碰它就不会 dirty） |
| 在 Layer 2 prompt 的 SESSIONS 段？ | **在**（喂 summary） | **不在**（节省 token） |
| 在 Layer 2 prompt 的 PRIOR 段？ | 在（基线） | **在**（保持连续性） |
| AI 可以动其 initiative 的字段 | name, summary, progress, tasks, status | **只能动 status**（衰减规则） |
| 在 mindmap.json 里？ | **在** | **在**（不删除） |
| 在 HTML 卡片上？ | **在** | **在**（可能 status 变 paused） |

### 6.3 强约束：Cold initiative 的 AI 行为

Layer 2 prompt 里要 hammer 这条规则：

```
对于 PRIOR 中存在、但 HOT_SUMMARIES 中没有任何 session 出现的
initiative（即"cold initiative"），你**仅能修改其 status**：

  - 若 last_activity_at < 3 天：保持 active
  - 若 3-14 天：改为 paused
  - 若 >14 天 且没有 resume 信号：改为 archived

name / summary / progress / tasks / sessions 必须**完全等同**于 PRIOR
中的值，逐字符复制。你不能"小幅润色"。
```

### 6.4 hot/cold 边界抖动

担心 session 在 48h 边界附近反复跨越？两种处理：

**方案 A（推荐）**：48h **+ 滞回**。一旦标 cold 需要回归 hot 必须由
"jsonl 有新字节"触发（即用户真的有新活动），不靠 last_activity 自然
回头到 48h 内。

**方案 B**：阈值 + 容差，如 "48h ± 4h 之间用 PRIOR 的标记继续保留
原状态"。复杂度更高，收益微小。

→ 选 A。

---

## 7. 并发模型

### 7.1 Layer 1：per-sid flock，完全并发

```
两个 sid 同时触发：
  Stop hook for sid_A ─► fork ─► flock("summary-A.lock") ─► Haiku ─► done
  Stop hook for sid_B ─► fork ─► flock("summary-B.lock") ─► Haiku ─► done
  
  互不阻塞。
```

同 sid 双触发（罕见）：

```
Stop hook for sid_A (1st) ─► fork ─► flock("summary-A.lock") ── 持锁 ──┐
Stop hook for sid_A (2nd) ─► fork ─► flock("summary-A.lock") ── 阻塞 ─┤
                                                                       ▼
                                                              (1st 完成释放锁)
                                                                       ▼
                                                              (2nd 拿到锁)
                                                                       ▼
                                                          dirty check: 
                                                          mtime(extract) > mtime(summary)?
                                                          若 1st 已写入 → 跳过
                                                          若仍 dirty → 跑
```

锁文件路径：`cache/.locks/summary-<sid>.lock`，flock 排他。

### 7.2 Layer 2：单进程 + coalesce

```mermaid
flowchart TD
    Trigger["trigger_layer2() 被调用"] --> TryLock{"flock(<br/>layer2.lock)<br/>能拿到?"}
    TryLock -- "否（有进程在跑）" --> TouchPending["touch layer2.pending"]
    TouchPending --> Return1["return"]

    TryLock -- "是" --> LoopStart["loop:"]
    LoopStart --> RmPending["rm -f layer2.pending"]
    RmPending --> Run["run_classify.py"]
    Run --> CheckPending{"layer2.pending<br/>存在?"}
    CheckPending -- "是" --> LoopStart
    CheckPending -- "否" --> Release["release flock"]
    Release --> Done["return"]
```

效果：

| 场景 | 行为 |
|---|---|
| 触发 1 次 | 跑 1 次 → pending 不存在 → 退出 |
| 跑期间触发 N 次 | N 次 touch pending（幂等）→ 跑完后看到 pending → 再跑 1 次 |
| 持续触发 | 永远 ≤ 1 个进程在跑，新触发自动 fold 到下一轮 |

**Cooldown 完全废弃**：

- Layer 1 不需要：per-sid dirty check 已限频
- Layer 2 不需要：coalesce 已限频（永远 ≤ 1 个进程，新触发就排队）

唯一保留可选的"软上限"：每小时 Layer 2 触发不超过 N 次（如 20）。
实测活跃工作时大概 4-6/小时，不需要这个上限。**先不加**。

### 7.3 现有锁的去留

| 锁 | 去留 | 理由 |
|---|---|---|
| `cache/refresh.lock.d/` (mkdir) | **废弃** | refresh.sh 不再是单一编排器 |
| `cache/last_ai_run.epoch` | **废弃** | 没有 cooldown 了 |
| `cache/last_input.sha256` | **废弃** | mtime 比较代替 |
| `cache/.locks/summary-<sid>.lock` | ⭐ 新增 | Layer 1 per-sid |
| `cache/.locks/layer2.lock` | ⭐ 新增 | Layer 2 单进程 |
| `cache/.locks/layer2.pending` | ⭐ 新增 | Layer 2 coalesce |

---

## 8. 数据模型

### 8.1 `cache/sessions/<sid>.json`（Layer 0 输出）

**当前形状瘦身**（详见 §4.2）。只保留机器信号，文本字段全部移除。

```jsonc
{
  "session_id": "cbbeb23c-b6f9-4eb4-926e-7e4046c856d4",
  "cwd": "/Users/bby/Code/pandora/pandora-sar/hsf",
  "started_at": "2026-05-13T07:30:00Z",
  "last_activity_at": "2026-05-13T09:19:46Z",
  "user_turns": 16,
  "edits": [
    {"file": "/tmp/aone-issue-hsf-eagleeye.md", "kind": "create", "ops": 1}
  ],
  "tools": {"Bash": 12, "Read": 30, "WebFetch": 2},
  "task_events": [],
  "is_automation": false
}
```

体积估算：~400 字节 / session（之前是 1.5KB）。

### 8.2 `cache/summaries/<sid>.md`（Layer 1 输出，⭐ NEW）

详见 §4.3。结构化 markdown + YAML frontmatter。

体积估算：~1-2KB / session（密度高，叙事完整）。

### 8.3 `cache/mindmap.json`（Layer 2 输出，schema v2 不变）

不变。

### 8.4 Layer 1 prompt 输入

```
<instructions>
prompts/summarize-session.md 的内容
</instructions>

<session_meta>
{ sessions/<sid>.json 内容 }
</session_meta>

<turns count="10">
最近 10 轮 user-assistant 的完整文本，按时间顺序
</turns>
```

总大小：~5-10KB。Haiku 一次处理 OK。

### 8.5 Layer 2 prompt 输入

```
<instructions>
prompts/classify-cross-session.md 的内容
</instructions>

<context>
  <current_time>2026-05-14T10:00:00Z</current_time>
  <output_lang>zh-CN</output_lang>
</context>

<prior_mindmap>
{ slim 后的 mindmap.json }
</prior_mindmap>

<deleted_ids>
[...]
</deleted_ids>

<hot_summaries count="25">
  <summary sid="cbbeb23c-...">
    （cache/summaries/cbbeb23c-...md 的完整内容）
  </summary>
  <summary sid="...">
    ...
  </summary>
</hot_summaries>
```

总大小：~40-60KB（远小于当前 300KB）。

**Cache 友好顺序**：高频不变的 `<instructions>` 放最前，cache 命中
率最高；`<hot_summaries>` 在最后，每次都变。

---

## 9. 端到端走查

### 9.1 走查 1：新 session 第一次成卡

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant CC as Claude Code
    participant H as refresh-bg.sh
    participant EX as extract.py
    participant L1 as summarize.py
    participant TR as layer2-trigger.sh
    participant L2 as classify.py
    participant AI as Haiku
    participant FS as cache/

    U->>CC: 开新 session, 发首条消息
    CC->>FS: 写 jsonl
    CC-->>H: Stop hook
    H->>EX: extract for sid
    EX->>FS: 写 sessions/sid.json
    H->>L1: check dirty for sid<br/>(mtime cmp)
    L1->>FS: flock summary-sid.lock
    L1->>FS: 读 jsonl 尾部 + sessions/sid.json
    L1->>AI: prompt (~5KB)
    AI-->>L1: markdown summary (~1KB)
    L1->>FS: 写 summaries/sid.md
    L1->>FS: release flock
    L1->>TR: trigger_layer2

    TR->>FS: flock layer2.lock 成功
    TR->>FS: rm -f layer2.pending
    TR->>L2: 调起
    L2->>FS: 读所有 hot summaries
    L2->>FS: 读 mindmap.json 作 PRIOR
    L2->>AI: prompt (~40KB)
    AI-->>L2: mindmap.json
    L2->>FS: 写 mindmap.json
    TR->>FS: 检查 layer2.pending 不在
    TR->>FS: release flock
```

### 9.2 走查 2：用户在 UI 上勾完成 task

不变（user_overrides 流程不动）。但有一个简化：apply-overrides 不
再 inline 在 refresh.sh 里，可以**直接在 Layer 2 启动前应用**：

```
classify.py 开头：
  1. 读 user_overrides.json
  2. 应用 task done 翻转到 mindmap.json
  3. 清空 user_overrides.json
  4. 读应用后的 mindmap.json 作 PRIOR
  5. 调 AI
```

这样保证 AI 的 PRIOR 总是含最新的用户意图。

### 9.3 走查 3：用户休息一天后回来

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant FS as cache/
    participant TR as layer2-trigger
    participant L2 as classify.py
    participant AI as Haiku

    Note over U: Day 0: 工作活跃<br/>session X 在 mindmap.json
    Note over U: Day 1: 不工作<br/>X 没有任何 hook 触发<br/>X 的 summary.md mtime 不变<br/>mindmap.json mtime 也不变
    Note over U: Day 2 早上: 周期触发<br/>(也可以是用户登录时 hook)
    
    TR->>FS: 检查 summaries 是否新于 mindmap
    Note over FS: 没有更新，但 last_activity 距今 >3d<br/>需要触发 status decay
    TR->>L2: 调起 (status-only mode)
    L2->>FS: 读 PRIOR + DELETED
    L2->>FS: 不读 summaries (无 hot)
    L2->>AI: prompt: "无新证据, 仅做 status decay"
    AI-->>L2: mindmap.json (只动 status 字段)
    L2->>FS: 写 mindmap.json

    Note over U: Day 2 下午: 用户恢复 X
    U->>FS: jsonl 有新字节 (extract + Layer 1)
    FS->>TR: summary 比 mindmap 新
    TR->>L2: 调起 (full mode, X 是 hot)
    L2->>AI: prompt: PRIOR + X 的新 summary
    AI-->>L2: 更新 X 的 initiative
```

**关键**：Day 2 早上的"status decay tick"需要有人触发。两个方案：

- **launchd 每天 1 次**调 `layer2-trigger.sh` —— 简单
- **每次 Layer 2 调用前自检**：扫 PRIOR 里所有 initiative，看是否
  有应该衰减的 → 顺手做了 —— 不需额外调度

→ 选后者。每次 Layer 2 都做 status decay，反正成本固定。

---

## 10. 迁移方案

### 10.1 阶段划分

| 阶段 | 目标 | 是否可独立 ship |
|---|---|---|
| Phase 0 | 备份当前 cache + 写迁移脚本 | 必备 |
| Phase 1 | Layer 1 上线（summarize.py + summaries/）；Layer 2 还是单段 | **可** |
| Phase 2 | Layer 2 重写（classify.py 读 summaries）；保留旧 refresh.sh 路径作 fallback | **可** |
| Phase 3 | 启用冷热分层 | **可** |
| Phase 4 | 启用 coalesce + 删除 cooldown / refresh.lock.d | **可** |
| Phase 5 | 删除 legacy（aggregate.py / 旧 prompt） | 收尾 |

每阶段独立 commit + 一周 baking。任何阶段出问题，git revert 回滚。

### 10.2 一次性 backfill

第一次切到 Layer 1 架构时，要给所有 200 个 session 跑一次 Layer 1：

- 200 × $0.01 = **$2 一次性**
- 可在 install.sh 加 `--migrate-summaries` flag，用户主动触发
- 跑期间 mindmap.json 不动，UI 仍然显示老数据
- 跑完后 Layer 2 用新 summaries 做第一次分类

### 10.3 prompt 替换

`prompts/classify.md` 不直接删，改名 `prompts/legacy-classify.md`
保留两周作为 fallback / 对照。新 prompt：

- `prompts/summarize-session.md`（Layer 1）
- `prompts/classify-cross-session.md`（Layer 2）

---

## 11. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| Layer 1 prompt 质量不达标 | summary 写得糊涂 → Layer 2 分类质量退化 | 在 3 个真实 session 上 hand-tune prompt 直到主观满意；先 side-by-side 跑一周对比 |
| Layer 2 prompt 改写 break 连续性 | initiative id 漂移、task 丢失 | 保留 legacy 路径作 A/B；DIFF 监控 id 改名次数 |
| Cold initiative 被 AI 误删 | 卡片消失 | prompt 写死铁律 + 自检段落；Layer 2 输出 schema 加 "preserved_cold_ids" 必填字段强制 AI 列出来 |
| Coalesce bug 导致死锁 | Layer 2 不再触发 | flock 自动随进程崩溃释放；pending 文件 stale 检测（如 >1h 自动 rm） |
| Backfill 太贵或太慢 | $2 + 5-10 min 等待 | 可分批 backfill；或允许 Layer 2 在 backfill 进行中正常跑（缺 summary 的 session 暂时不参与分类） |

### 回滚路径

每个 Phase 都通过 git revert 回退；cache schema 兼容：

- summaries/ 目录可以保留，不影响 legacy 路径
- mindmap.json schema 不变，render 一切正常
- 用户感知：回滚后变回老的卡片质量，无数据丢失

---

## 12. 开放问题

### 12.1 已对齐（结合之前讨论）

| 决策 | 结论 |
|---|---|
| Dirty tracking 用什么 | **mtime 比较**，无独立 flag |
| Cold session 在 mindmap.json | **保留**，只是不进 Layer 2 prompt 的 SESSIONS 段 |
| AI 对 cold 能动什么 | **仅 status decay**；name/summary/tasks 不能动 |
| Layer 1 并发 | **完全并发**，per-sid flock |
| Layer 2 并发 | **单进程 + coalesce** |
| Cooldown | **全部废弃** |
| 冷热阈值 | **48h**（可 env 调整） |
| 冷热抖动 | **滞回**：只有 jsonl 新字节才能 hot 回来 |

### 12.2 待你拍板

1. **Layer 1 prompt 看多少轮 / 多少 KB**？目前提议 10 轮 OR 30KB
   先到为准。短 session 看完整，长 session 截尾部。可调。

2. **summary markdown 段落是否固定**？提议 7 段（目标 / 当前状态 /
   决定 / 产物 / 下一步 / 待解决 / 任务）。要不要更精简（如合并成 4 段：
   目标 / 状态 / 下一步 / 任务）？精简的好处是 AI 更少做选择，但
   信号量也少。

3. **触发 layer2-trigger.sh 的位置**：
   - A. 每个 Layer 1 完成时调一次（写完 summary 立刻试）
   - B. refresh-bg.sh 末尾统一调一次（一次 hook 多个 sid 时合并）
   B 更省，A 更即时。

4. **status decay 在哪做**：
   - A. classify.py 开头扫 PRIOR 主动做（每次 Layer 2 必跑）
   - B. 单独的 maintenance 脚本周期性跑
   A 更简单，每次 Layer 2 多扫一遍 PRIOR 几乎免费。倾向 A。

5. **summary 失败时怎么办**：
   - A. 用旧 summary（mtime 不更新）
   - B. 在 .md 文件里写"FAIL: <error>"占位
   - C. 不写文件，下次重试
   A 最不影响 Layer 2，但旧数据可能误导。C 最干净但要重试逻辑。
   倾向 A + 错误写到 log。

6. **大文件清理**：summaries/ 目录会无限增长。session jsonl 被删时
   要不要也删对应 summary？或定期 GC （> 30 天没更新且 initiative
   已 archived 的）。低优先级，先不管。

---

## 13. 推进顺序

按风险 / 成本权衡，建议这个顺序：

```
Step 1  写 prompts/summarize-session.md 并用 3 个真实 session 调试
        （成本: ~$0.03, 时间: 1 小时迭代）

Step 2  实现 bin/summarize.py（Layer 1 完整逻辑）
        含 dirty check / per-sid flock / 写 summaries/
        （成本: 半天编码）

Step 3  Backfill: 对所有现有 session 跑 Layer 1
        （成本: ~$2 一次性, 5-10 分钟）

Step 4  写 prompts/classify-cross-session.md
        （成本: 半天）

Step 5  实现 bin/classify.py（Layer 2 完整逻辑）+ layer2-trigger.sh
        （成本: 半天）

Step 6  side-by-side 跑 1 周
        同时跑老 refresh.sh 和新 pipeline，对比 mindmap.json DIFF
        （成本: ~$5/天 × 7 天 = ~$35，可接受）

Step 7  切换 hook 指向新 pipeline，关掉老路径
        （成本: 5 分钟改 settings.json）

Step 8  baking 1 周，观察

Step 9  删除 legacy（aggregate.py, refresh.sh 大瘦身, 旧 prompt）
```

总工作量：~3 天专注编码 + ~2 周 baking。
