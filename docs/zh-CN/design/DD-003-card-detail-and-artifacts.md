# DD-003: 卡片详情 — Artifact 提取与卡点追踪

**Status**: Proposed
**Author**: bby
**Date**: 2026-05-14
**依赖**: [DD-002](DD-002-ai-pipeline-redesign.md)（Layer 1/2 架构）

英文原版：[../../design/DD-003-card-detail-and-artifacts.md](../../design/DD-003-card-detail-and-artifacts.md)

> 让用户点击卡片就能看到该 initiative 的关键 artifacts（CR/issue/分支
> 链接）、卡点、决策、文件、相关 session。**重点解决**：CR 链接在
> 长对话里被埋住，找不到。

---

## 目录

- [1. 问题](#1-问题)
- [2. 目标](#2-目标)
- [3. 卡片详情该展示什么](#3-卡片详情该展示什么)
- [4. 数据模型](#4-数据模型)
- [5. URL Pattern 提取](#5-url-pattern-提取)
- [6. 状态追踪（AI + 用户混合）](#6-状态追踪ai--用户混合)
- [7. UI 设计（Modal）](#7-ui-设计modal)
- [8. Layer 1 prompt 改动](#8-layer-1-prompt-改动)
- [9. Layer 2 prompt 改动](#9-layer-2-prompt-改动)
- [10. 阶段实施](#10-阶段实施)
- [11. 风险](#11-风险)
- [12. 开放问题](#12-开放问题)

---

## 1. 问题

### 1.1 痛点

一个典型 1 小时的 Claude Code 排查会话最后输出几条**关键信息**：

- 提了 CR `https://code.example.com/.../codereview/27369464`
- 关联 issue `#82052410`
- 推到分支 `bugfix/hsf/trace-gateway-server-ip`
- 卡点：等 CI + 等 reviewer approve + 等 CodeOwner

这些信息**全部活在 session jsonl 里**，但用户跨多个 session 工作时根本
找不回来。用户的真实操作：

```
1. 打开 HTML 卡片 → 看到"等 CI 通过"
2. CR 链接在哪？卡片不显示
3. resume 该 session 翻 100 条历史
4. 找到 MR 号，复制 → 浏览器打开
5. （重复多次）
```

### 1.2 具体案例（Tracer）

这周排查 HSF Trace IP 为空的 session：

| 信息 | 出现位置 | 卡片当前是否显示 |
|---|---|---|
| MR 号 `27369464` | session 中第 ~80 轮 AI 回复 | ❌ |
| MR 完整 URL | 同上 | ❌（只在 Layer 1 摘要"产物"自由文本段提了一次）|
| Issue `#82052410` | 第 ~85 轮 | ❌ |
| 分支名 | 第 ~75 轮 | ❌ |
| 卡点列表（CI/reviewer/CodeOwner）| Layer 1 摘要"待解决"段 | ✅ 但要展开摘要 |

3/4 关键信息**完全不可见**。Layer 1 已经提取了，但 HTML 没渲染。

### 1.3 为什么 Layer 1 摘要不够

`cache/summaries/<sid>.md` 的"产物"段确实写了 MR URL，但：

- 是**自由文本**，HTML 没法做"点击此链接打开"
- 没有"状态"概念——CR 是 pending / approved / merged 哪个？卡片说不清
- 嵌在大段叙述里，扫描负担高

---

## 2. 目标

| 维度 | 目标 |
|---|---|
| **可发现** | 点击卡片 → 一秒看到所有 CR/issue/分支 |
| **可点击** | 链接都是可 click 的 `<a>`，浏览器一键打开 |
| **可追踪** | CR 状态：pending → approved → merged → 显式可见 |
| **可关闭** | 用户在 UI 上能手动 mark 状态（不依赖 AI 后续感知）|
| **可扩展** | 后续加 GitHub PR、Gitlab MR、Jira issue 不需要改架构 |

**非目标**：

- 不调外部 API 自动同步 CR 状态（aone API 需 token + 跨组织部署难）
- 不做 CR 评论摘要 / 审核进度可视化（超范围）
- 不做"被通知"功能（"你的 CR 被 review 了" 推送）

---

## 3. 卡片详情该展示什么

8 类信息，价值递减：

| # | 类别 | 来源 | 举例 |
|---|---|---|---|
| 1 | **🚨 卡点 / Blockers** | Layer 1 提取 + 用户 toggle | "等 CI 通过"、"等 reviewer approve" |
| 2 | **🔗 外链 (Artifacts)** | URL pattern + AI 标注 | CR #27369464、Issue #82052410 |
| 3 | **🎯 下一步** | Layer 1 摘要"下一步"段 | "等 review + 合入 master" |
| 4 | **🌿 分支 / Commit** | URL pattern + 提取 | branch、commit sha、tag |
| 5 | **📄 in-flight 文件** | extract.py 的 edited_files | TraceHttpHook.java |
| 6 | **🧠 关键决策** | Layer 1 摘要"决定"段 | "跳过本地 UT、commit+push+MR" |
| 7 | **📜 任务进度** | 已有 tasks 字段 | 4/8 done |
| 8 | **💬 关联 sessions** | initiative.sessions（已有） | + pane info + resume 命令 |

MVP 覆盖 1-3 + 5 + 7 + 8（已有数据稍微重组就行），4 用 URL pattern 顺便
做，6 复用现有摘要段。

---

## 4. 数据模型

### 4.1 Layer 1 summary frontmatter 扩展

`cache/summaries/<sid>.md` 的 YAML frontmatter 加两段：

```yaml
---
# 已有字段（不变）
session_id: cbbeb23c-…
cwd: /Users/bby/Code/pandora/runtime-sar/hsf
last_activity_at: 2026-05-13T11:10:20Z
user_turns: 21
updated_at: 2026-05-14T12:13:02Z
status_guess: paused

# 新增字段
artifacts:
  - type: cr
    title: "Tracer remoteIp fix"
    ref_id: "27369464"
    url: "https://code.example.com/acme/runtime-sar/codereview/27369464"
    status: pending
    inferred: true              # AI guess
    first_mentioned_at: "2026-05-13T10:50:00Z"
    last_mentioned_at: "2026-05-13T11:10:00Z"
  - type: issue
    title: "Trace IP null"
    ref_id: "82052410"
    url: "https://devops.example.com/v2/project/.../req/82052410"
    status: open
    inferred: true
  - type: branch
    title: "bugfix/hsf/trace-gateway-server-ip"
    status: pushed
    inferred: true

blockers:
  - "等 CI 通过"
  - "等至少 1 个 reviewer approve"
  - "等 CodeOwner approve"
---

# 目标
（不变）
...
```

**字段说明**：

- `artifacts[].type`: `cr` | `mr` | `pr` | `issue` | `branch` | `commit` | `tag` | `deployment` | `doc` | `other`
- `artifacts[].ref_id`: 平台内的短编号（CR 号、issue 号、commit sha 等）；用于显示和去重
- `artifacts[].url`: 完整 URL，可空（如本地分支没 URL）
- `artifacts[].status`: 类型相关枚举（见 §4.3）
- `artifacts[].inferred`: AI 猜的标 `true`；用户后续 confirm 时改 `false`
- `blockers[]`: 自由文本字符串列表（不强结构化）

### 4.2 dashboard.json `initiative.artifacts[]` 聚合

Layer 2 把 initiative 关联所有 sessions 的 artifacts **去重合并**（按
`url` 或 `(type, ref_id)`），写入：

```json
{
  "id": "rpc-tracing-ip-null-issue",
  "name": "HSF Tracer 链路追踪服务端 IP 为空问题排查",
  "status": "paused",
  ...,
  "artifacts": [
    {
      "type": "cr",
      "title": "Tracer remoteIp fix",
      "ref_id": "27369464",
      "url": "https://code.example.com/.../27369464",
      "status": "pending",
      "inferred": true,
      "user_confirmed": false,
      "source_sessions": ["cbbeb23c-…"],
      "first_seen": "2026-05-13T10:50:00Z",
      "last_seen": "2026-05-13T11:10:00Z"
    }
  ],
  "blockers": [
    "等 CI 通过",
    "等至少 1 个 reviewer approve",
    "等 CodeOwner approve"
  ]
}
```

- `source_sessions[]`: 哪些 session 提到了这个 artifact（多 session 都
  提同一个 CR 时 union）
- `user_confirmed`: 用户手动 toggle 后置 true，AI 后续不能覆盖

### 4.3 status 枚举（按 type）

| type | 允许的 status |
|---|---|
| `cr` / `mr` / `pr` | `pending` / `approved` / `merged` / `closed` / `unknown` |
| `issue` | `open` / `in_progress` / `resolved` / `closed` / `unknown` |
| `branch` | `pushed` / `merged` / `deleted` / `unknown` |
| `commit` / `tag` | `created` / `unknown` |
| `deployment` | `pending` / `succeeded` / `failed` / `unknown` |
| `doc` / `other` | `draft` / `published` / `unknown` |

`unknown` 是默认/兜底，**任何时候**都允许，不强制 AI 给非 unknown。

### 4.4 用户 override 模型

`cache/user_overrides.json` 新增 `artifact_states[]`：

```json
{
  "version": 1,
  "task_toggles": [...],
  "deleted_tasks": [...],
  "artifact_states": [
    {
      "initiative_id": "rpc-tracing-ip-null-issue",
      "artifact_key": "cr:27369464",
      "status": "merged",
      "dismissed": false,
      "set_at": "2026-05-14T15:00:00Z"
    }
  ]
}
```

- `artifact_key`: `<type>:<ref_id>` 或 hash(url)（去重稳定 key）
- `status`: 覆盖 AI 的判断；写入后 inferred 变 false、user_confirmed 变 true
- `dismissed: true`: 用户标"和我无关"或"已忘记"，UI 隐藏该 artifact

classify.py 在跑前 apply overrides，**user_confirmed 永远胜过 AI 判断**。

---

## 5. URL Pattern 提取

支持的平台（可扩展）：

| 平台 | 正则 | 提取 |
|---|---|---|
| aone codereview | `code.example.com/[^/]+/[^/]+/codereview/(\d+)` | `type=cr`, `ref_id=<id>` |
| aone request | `devops.example.com/v2/project/[^/]+/req/(\d+)` | `type=issue`, `ref_id=<id>` |
| aone task | `devops.example.com/v2/project/[^/]+/task/(\d+)` | `type=issue`, `ref_id=<id>` |
| GitHub PR | `github.com/([^/]+/[^/]+)/pull/(\d+)` | `type=pr`, `ref_id=<id>` |
| GitHub issue | `github.com/([^/]+/[^/]+)/issues/(\d+)` | `type=issue`, `ref_id=<id>` |
| GitLab MR | `gitlab.com/([^/]+/[^/]+)/-/merge_requests/(\d+)` | `type=mr`, `ref_id=<id>` |
| git branch | `(commit|push.*to)\s+([a-zA-Z0-9/_-]+)` | 启发式 |
| git commit | `commit\s+([a-f0-9]{7,40})` | `type=commit`, `ref_id=<sha>` |

实现策略：

- **正则在 summarize.py 后处理**：AI 输出 markdown 后，扫一遍正则把 URL 提到结构化字段。这个保证 URL 不漏。
- **AI 补充 type / title / status**：Layer 1 prompt 告诉 AI：在 jsonl
  尾部看到的 URL，请在 frontmatter 的 artifacts 里补 type 和 title。
- **去重**：正则提的 URL 如果和 AI 提的撞了 url 或 (type, ref_id)，合
  并（AI 的字段优先）。

---

## 6. 状态追踪（AI + 用户混合）

### 6.1 AI 自动感知

Layer 1 prompt 加规则：

> 当 jsonl 尾部某个 artifact URL 附近（前后 5 个 turn）出现以下信号词，
> 更新该 artifact 的 status：
>
> - "merged" / "已合入" / "ship 了" → status=`merged`
> - "approved" / "通过了" → status=`approved`
> - "closed" / "已关闭" / "abandon 了" → status=`closed`
> - 否则保持原状态或 `pending`
>
> 始终标 `inferred: true`。

### 6.2 用户 toggle

HTML modal 里每个 artifact 旁边有按钮：

```
CR #27369464  pending  [view↗]  [✓ mark merged] [✗ dismiss]
```

点击：

- `mark merged` → 写 `cache/user_overrides.json` 的 artifact_states
  `{status: "merged"}`
- `dismiss` → 写 `{dismissed: true}`，artifact 在 UI 上隐藏

下次 classify.py 跑时 apply override，写入 dashboard.json 的
`user_confirmed: true`。AI 之后即使看到反向证据也不能改。

### 6.3 优先级冲突解决

```
最终展示 status = (
    user_confirmed_state if 存在 else
    ai_inferred_state if 存在 else
    "unknown"
)
```

---

## 7. UI 设计

UI 分两层：

- **卡片外表（card surface）**——一眼可见的徽章/简讯，无需点击
- **Modal**——点击卡片打开，看全部 artifact / blocker / 决策 / files / sessions

### 7.0 卡片外表 — 徽章 + 卡点简讯

卡片头部在状态徽章后追加：

```
● HSF Tracer 链路追踪服务端 IP 为空问题排查  [已暂停]  23小时前
  🚨 3 卡点  ·  🔗 1 个 CR pending
```

规则：

| 徽章 | 显示条件 | 形式 |
|---|---|---|
| `🚨 N 卡点` | `blockers.length > 0` | 红色小 chip，N 为数量 |
| `🔗 N pending` | `artifacts` 里有 `status in {pending, open, unknown}` 且 `type in {cr, mr, pr, issue}` 的数 > 0 | 蓝色小 chip |
| `✅ N merged` | 仅当用户期望看（默认隐藏，因为不再需要关注） | 灰色，可选 |

**额外**：在卡片**进度（progress）**段下方，加一行 **"top blocker 摘要"**
（如果有 blocker）：

```
进度：…（已有内容）

⚠ 卡点（top 1）：等 CI 通过
```

只显示 blockers[0]（最高优先级的）。点击徽章或这一行 → 打开 modal 跳
到对应段落（modal 内 url 锚点）。

理由：卡片本就是状态汇总器，blockers 比 next step 更紧迫，应该和
status/age 同等可见度。

### 7.1 Modal 布局

点击卡片任何空白处 → 弹出居中 modal（半透明遮罩 + 圆角 600px 宽，max-
height 80vh，超出滚动）：

```
┌─────────────────────────────────────────────────────────┐
│                                                  [✕]    │
│  HSF Tracer 链路追踪服务端 IP 为空问题排查              │
│  📁 pandora/runtime-sar/hsf · ⏸ paused · 23小时前       │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  🚨 卡点 (3)                                              │
│    • 等 CI 通过                                          │
│    • 等至少 1 个 reviewer approve                        │
│    • 等 CodeOwner approve                                │
│                                                          │
│  🔗 关键链接                                              │
│    📋 CR #27369464  pending  [view↗] [✓merged] [✗]     │
│       Tracer remoteIp fix                              │
│    🎫 Issue #82052410  open  [view↗]   [✗]              │
│       Trace IP null                             │
│    🌿 bugfix/hsf/trace-gateway-server-ip  pushed         │
│                                                          │
│  🎯 下一步                                                │
│    等 CI + reviewer approve 后合入 master                │
│                                                          │
│  📄 涉及文件                                              │
│    • TraceHttpHook.java                              │
│    • /tmp/aone-issue-rpc-tracing.md                    │
│                                                          │
│  🧠 关键决策                                              │
│    • 跳过本地 UT，直接 commit+push+MR（风险评估为低）    │
│    • commit msg 符合 RELEASE.md §1 自动关联工作项        │
│                                                          │
│  📜 任务 (4/8 done)                                       │
│    ✓ 定位 TraceHttpHook 缺失 remoteIp 根因           │
│    ✓ 实现修复                                            │
│    ✓ commit + push                                      │
│    ✓ 通过 a1 创建 MR                                    │
│    ○ CI 通过                                            │
│    ○ Reviewer approve                                   │
│    ○ 合入 master                                        │
│    ○ 回合到 release 分支                                │
│                                                          │
│  💬 Sessions (1)                                          │
│    cbbeb23c… @ pane 27 (main)                            │
│    [🎯 resume] [📋 copy command]                         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 7.2 交互

- 点击卡片**空白处**（不含已有按钮区）→ 打开 modal
- 点击空白处或按 ESC → 关闭
- 点击 artifact `view↗` → 在新 tab 打开 URL（`target="_blank"`）
- 点击 `✓ mark merged` → POST `/api/save` artifact_states
  → toast "已标记为 merged"
- 点击 `✗ dismiss` → 隐藏 artifact，next reload 不显示
- 点击 task checkbox → 复用现有 task 翻转逻辑
- 点击 session `resume` → 复用现有 Zellij 跳转

### 7.3 空状态降级

如果某 initiative 没有 artifacts 或 blockers，对应段落不显示（不是写
"(无)"）。Modal 至少永远显示**名称 + 状态 + sessions**。

### 7.4 字段优先级（modal 高度有限时）

按 §3 表格的价值排序：blockers 在最上面、artifacts 第二、下一步第三，
依此类推。

---

## 8. Layer 1 prompt 改动

`prompts/summarize-session.md` 加一段：

```
# Frontmatter extras (artifacts + blockers)

In addition to the existing fields, the frontmatter MUST include:

  artifacts:
    - type: cr | mr | pr | issue | branch | commit | tag |
            deployment | doc | other
      title: <short, ≤60 chars>
      ref_id: <platform-specific short id, e.g. "27369464">
      url: <full URL if known, else omit>
      status: <type-specific enum, see below>
      inferred: true                  # always true from AI
      first_mentioned_at: <ISO ts>
      last_mentioned_at: <ISO ts>

  blockers:
    - <free-text string describing what this session is blocked on>

If a session has no artifacts or no blockers, emit:

  artifacts: []
  blockers: []

# Status enums by type

  cr | mr | pr     →  pending | approved | merged | closed | unknown
  issue            →  open | in_progress | resolved | closed | unknown
  branch           →  pushed | merged | deleted | unknown
  commit | tag     →  created | unknown
  deployment       →  pending | succeeded | failed | unknown
  doc | other      →  draft | published | unknown

Default to `unknown` when uncertain.

# Status inference signals

Look at the turns near where the URL/ref_id appears. Update status
when you see:
  - "merged" / "已合入" / "shipped" / "已发版"   → merged (cr/mr/pr)
  - "approved" / "approve 了" / "通过了"           → approved (cr/mr/pr)
  - "closed" / "abandoned" / "废弃" / "撤回"     → closed
  - "Fixed" / "已修复" / "resolved"               → resolved (issue)
  - "merged"近 branch                             → merged (branch)

Always emit inferred: true. The user can override later.
```

正则后处理在 `bin/summarize.py` 兜底，确保 URL 不漏：调 AI 后扫描 jsonl
找所有 URL，若 AI 输出的 artifacts 没覆盖，追加一条 minimum-info
artifact（type 按正则归类、status=unknown）。

---

## 9. Layer 2 prompt 改动

`prompts/classify-cross-session.md` 加一段：

```
# Artifacts and blockers aggregation

Each session summary may include:

  artifacts: [...]
  blockers: [...]

Aggregate these onto the initiative they belong to:

- Initiative.artifacts: union over all sessions, dedupe by
  (type, ref_id) or by url. When multiple sessions report the same
  artifact, take the most-recent inferred status. Track source_sessions
  = the sids that mentioned it.

- Initiative.blockers: union over hot sessions only (cold sessions'
  blockers may be stale). Keep wording from the most recent session.

When emitting the output, include:

  initiative:
    ...
    artifacts: [...]
    blockers: [...]
    
For cold initiatives (rule §5), preserve artifacts/blockers BYTE-
IDENTICAL to PRIOR (just like name/summary/tasks).
```

`bin/classify.py` 在 enforce_cold_and_done_monotone 里增加：

- artifacts、blockers 数组对 cold initiative 强制还原 PRIOR 值
- 对 hot initiative 也强制：`user_confirmed: true` 的 artifact 不被 AI
  覆盖

---

## 10. 阶段实施

### Phase 1 — Layer 1 提取（最低 commit）

- 改 `prompts/summarize-session.md`：加 §8 的指令
- 改 `bin/summarize.py`：YAML 序列化新字段、正则后处理兜底
- 不动 HTML，不动 Layer 2
- 验证：重跑 Tracer session，看 `artifacts:` 是否正确填出 CR/issue/branch

**Ship 条件**：3 个真实 session 上 artifacts 提取主观合格。

### Phase 2 — Layer 2 聚合

- 改 `prompts/classify-cross-session.md`：加 §9 指令
- 改 `bin/classify.py`：序列化 artifacts/blockers 到 dashboard.json；enforce
  cold immutability 包含新字段
- HTML 无变化（dashboard.json 多两个字段，旧 render-html.py 忽略）

**Ship 条件**：dashboard.json 里的 Tracer initiative 出现 artifacts
数组。

### Phase 3 — HTML Modal (read-only)

- `bin/render-html.py`：嵌入 artifacts/blockers 数据
- 添加 modal HTML + CSS + JS
- 点击卡片打开 modal，渲染所有字段
- artifacts 是可点击外链（`<a target="_blank">`），但**没有 mark 按钮**

**Ship 条件**：浏览器点击 Tracer 卡片能看到 CR #27369464 链接。

### Phase 4 — 用户 toggle (artifact_states)

- HTML modal 加 `✓ mark merged` / `✗ dismiss` 按钮
- POST `/api/save` 写入 `cache/user_overrides.json` 的 `artifact_states`
- `bin/classify.py` apply_user_overrides 包含 artifact_states 处理
- 状态显示优先 user_confirmed > inferred

**Ship 条件**：UI 标 merged → 下次 classify 后 user_confirmed=true 落地，
后续 AI 不再改。

### Phase 5 — AI 自动感知（可选，先观察 Phase 4 够不够）

- Layer 1 prompt 加 §8 末尾的 status inference signals
- Phase 4 后跑一周，看 AI 自动更新覆盖率，再决定要不要做

---

## 11. 风险

| 风险 | 缓解 |
|---|---|
| AI 提取 URL 漏掉 | 正则后处理兜底，保证 URL 全收 |
| AI status 误判 | 总是标 `inferred:true`，用户可 override；UI 区分两种 |
| artifacts 太多（>20）| Modal 内部按 status 分组+折叠，pending 在最前 |
| 数据膨胀（dashboard.json 增大）| 每 initiative 平均 3-5 个 artifact × 200 字节 = 1KB，可接受 |
| 跨 session 重复 artifact | (type, ref_id) 去重；保留 source_sessions 体现引用关系 |
| 用户 toggle 后 AI 倒回 | enforce 步骤强制 user_confirmed 不被覆盖 |
| URL pattern 不全 | 第一版只支持 aone + GitHub + GitLab；其它走 `type=other` |

---

## 12. 开放问题

1. **Modal 位置**：居中 modal vs 卡片就地展开？已选 modal（用户）。
2. **artifacts 的 first_mentioned_at**：取 jsonl 时间戳还是 AI 推断？
   提议：jsonl 时间戳（精确）。
3. **dismissed artifact 在 modal 里是隐藏还是低亮显示**？
   提议：默认隐藏，modal 顶部加一个 toggle "显示已忽略" 用于找回。
4. **CR `view↗` 是否要做"打开后自动 mark"**？比如点击 view 5 分钟后弹
   "是否 mark 状态变化"。可能过度，先不做。
5. **后续接 GitHub API 自动查 status**：DD-002 §12 契约下 是一个独立功
   能，需要 PAT 配置；先不做。
6. **blockers 是否做成 checkable 任务**？比如"等 CI 通过"也能打 ✓？
   感觉混淆了 tasks 和 blockers 的语义。暂不混。

---

## 13. 与其它 DD 的关系

- **DD-002 §12.3 契约**：本设计**扩展 trunk 数据 schema**（dashboard.json
  + summaries 加字段），按契约这应该是一次 DD-N。本文就是。
- **DD-002 §12.5 反模式**：本设计**遵守**单写者原则——dashboard.json 仍
  然只由 classify.py 写；summaries 仍然只由 summarize.py 写；
  artifact_states 写入 user_overrides.json（已有写者：serve.py
  /api/save）。
- **新增的可选第三方扩展**（如 GitHub status API 同步）走 DD-002 §12.3
  契约：自己的脚本、自己的数据产物、不动 trunk。

---

## 14. 接下来

如果方案确认，按 Phase 1 → Phase 4 顺序实施。预计 1-2 天编码 + 几天
观察。

Phase 5（AI 自动感知）作为可选优化，看用户使用 Phase 4 toggle 是否痛苦
再决定。
