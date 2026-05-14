# DD-001: 两段式分类——用每 session AI 摘要替代硬压缩

**Status**: **Superseded by [DD-002](DD-002-ai-pipeline-redesign.md)**
**Author**: bby
**Date**: 2026-05-13

> ⚠️ 这份文档已被 [DD-002](DD-002-ai-pipeline-redesign.md) 取代。
> DD-002 是基于 DD-001 + 后续讨论的完整设计，含冷热分层、dirty
> tracking、并发模型、文件目录、端到端走查。本文保留作历史记录。

英文原版：[../../design/DD-001-two-pass-classification.md](../../design/DD-001-two-pass-classification.md)

## 问题

活跃 session 的卡片内容滞后于实际工作，有时滞后数小时。

### 具体案例

session `cbbeb23c-b6f9-4eb4-926e-7e4046c856d4` 中，用户（bby）在排查
HSF 的 EagleEye trace IP=null。实际时间线：

```
T+0    "调研 EagleEye 链路追踪服务端 IP 为空的问题"
T+30m  "等 arthas watch 抓数据"                        ← 卡片卡在这里
T+90m  "为啥 logRemoteIp 要传本机 IP"（根因排查）
T+95m  AI 给出 HSF_CLIENT span 语义完整解释
T+110m "把问题记录一个 Aone ISSUE"
T+115m AI 写了 /tmp/aone-issue-hsf-eagleeye.md
T+120m "确认, 指派给我"
```

T+120 后用户打开仪表盘，卡片显示：

> 进度：发现关键线索…用户收集了带 @s0 前缀的 EagleEye data 样本，
> 当前等待用 arthas watch 在本地跟踪 EagleEyeUtil.logRemoteAddress
> 抓取现场数据。

这段 progress 文本是 **T+30** 状态。90 分钟的根因分析和 ISSUE 撰写
全都看不见。

### 为什么

`bin/extract.py` 把每个 session 摘要压到这么大：

- `first_user_prompt`：400 字符
- `recent_user_prompts`：最近 5 条，每条 400 字符
  （本文档之前是 3 × 300）
- `last_assistant_summary`：最后一条 assistant 文本回复**前 1500 字
  符**（之前只取第一段）
- `edited_files`：文件名列表（无内容）
- `task_events`：TaskCreate/TaskUpdate 字符串
- `recap`：Claude Code 的 `away_summary`，可能滞后几小时
- `tools_used`：工具名

每 session 合计：**~1.5 KB 结构化 JSON**。

分类器（`prompts/classify.md`）然后看到 200 份这样的摘要
（~300 KB 总量），一次性完成：

1. 跨 session 归组到 initiative
2. 每个 initiative 写 name + summary + progress + tasks + sessions
3. 维持和 PRIOR_MINDMAP 的连续性
4. 尊重 DELETED_IDS

Haiku 4.5 的输出预算 ~10 KB——平均每个 initiative 只有 50 字节预算。
**分类器被要求用过少的信息密度做过多的事。**

### 为什么加大限制治不了根

`last_assistant_summary` 从"第一段"改到"1500 字符"是这次 EagleEye
case 能跑通的关键。但这是结构性的运气：

- 如果 session 最后一轮 assistant 回复是 3000 字符的深度技术解析，
  我们只取前 1500，可能漏掉结论
- 如果关键内容在 N-3 轮，永远看不到
- 分类器看到的是文本碎片，不是叙事——它必须从断片重构意图和进展

分类器输出质量被输入信息密度所限。输入是有损压缩，恰恰丢掉了最重要
的东西（叙事）。我们可以调压缩 heuristic，但天花板很低。

## 目标

1. **活跃 session 的卡片内容跟上用户最后一轮 assistant 的时间差
   ≤ 1 分钟**。活跃 session 的卡片永远不应该描述几轮之前的状态。
2. **跨 session 分类精度不退化**。Initiative 归组、状态衰减、连续性
   都还要正常工作。
3. **成本控制在活跃工作期 ~$3/小时以内**（当前 Haiku 5min cooldown
   ~$2.5/小时）。
4. **"用户完成一轮 → 卡片更新"延迟 ≤ 30 秒**（常见情况）。

## 非目标

- 真正流式更新（SSE、websocket）。每 8 秒轮询足够。
- 把人写的 prompt 完全消掉。两段式拆分会增加 prompt；只要各自更短
  更清晰就行。
- 取消周期性全量分类。跨 session 结构整理仍然需要。

## 方案：两段

```
[Stop hook 触发 session X]
     │
     ▼
extract.py — 增量读 jsonl（不变）
     │
     ▼
summarize.py [新]
     读 cache/sessions/X.json 和 X.jsonl 的最近 N 轮原文
     prompt：classify-session.md（新）
     模型：Haiku，~5KB prompt → ~500 tokens 输出，~$0.01，5-10s
     输出：cache/summaries/X.md（结构化 markdown）
     │
     ▼
[条件性]
classify.py [refresh.sh 逻辑重写]
     读所有 cache/summaries/*.md
     prompt：classify-cross-session.md（当前 classify.md 重写）
     模型：Haiku，~40KB prompt → ~5KB 输出，~$0.05，30s
     输出：cache/mindmap.json
```

### Pass 1: `bin/summarize.py` — 单 session 进，摘要出

**输入**（完整文本，不再二次压缩）：

- `cache/sessions/X.json`（已有 extract 骨架）
- 原 jsonl 的尾部——最近 K 轮 user-assistant 或 最近 L KB
  （建议 K=10 轮，L=30 KB，取较小者）

**输出**：`cache/summaries/X.md`

格式选 markdown 是为了人类可读（`cat cache/summaries/<sid>.md`）。
带结构化 YAML frontmatter + 标题段落：

```markdown
---
session_id: cbbeb23c-b6f9-4eb4-926e-7e4046c856d4
cwd: /Users/bby/Code/pandora/pandora-sar/hsf
last_activity_at: 2026-05-13T09:19:46.447Z
status_guess: active  # active | paused | done | abandoned
updated_at: 2026-05-13T09:25:00Z
---

# 目标
用户出发点要做的事。一段话。

# 当前状态
工作站在哪里——截至最后一轮 assistant。不是"AI 做了什么"，而是
"已搞清楚什么 / 卡在哪里 / 下一个交接点是什么"。

# 已下的决定
具体决策或结论的 bullet 列表，活到最新一轮的那些。（用户点头的事，
或 AI 已经写到代码里的事）

# 产物
- /tmp/aone-issue-hsf-eagleeye.md （已创建）
- src/main/java/.../EagleEyeHttpHook.java （计划改动，未写）

# 下一步
用户或 AI 说的下一步是什么。如果 session 半途中断，写明。

# 待解决
任何挂起的问题，用户在等什么。

# 任务（建议）
- [ ] task 标题 1
- [x] task 标题 2 （已完成：简短证据）
```

Pass 2 的分类器直接读这些 markdown，不再解析——markdown 本身就是
结构化表示。

**Prompt**（新文件 `prompts/summarize-session.md`）：

简短。让 Haiku 读原始轮和 extract 骨架，输出上述 markdown。重笔强调
"最后一轮最权威；新的胜过 recap；用户说 X 就是在做 X"。

### Pass 2: 跨 session 分类器——重写

**输入**：

- `cache/summaries/*.md`，所有活跃 session
- PRIOR_MINDMAP（mindmap.json）
- DELETED_IDS
- OUTPUT_LANG

**不再**需要 `aggregate_input.json`——summaries 替代它。总 prompt
体积从 ~300 KB → ~40 KB。

**输出**：`cache/mindmap.json` schema 不变。

**Prompt**（新文件 `prompts/classify-cross-session.md`，今天
`classify.md` 的重写）：

分类器的职责缩小：归组、命名、状态衰减、连续性。每个 initiative
的"在发生什么"直接来自 summaries——分类器不再合成叙事，只挑选
合适的 summary 文本并裁剪。

### 触发策略

按用户已确认的选择（总是 summarize、条件性 classify）：

| 触发源 | Pass 1 | Pass 2 |
|---|---|---|
| Stop hook | 总是为触发的 session 跑（~$0.01） | 仅当 pass 1 有实质变化 AND classify-cooldown 已清 |
| SessionStart hook | 总是 | 同上 |
| LaunchAgent（2h） | 自上次 summarize 后有变更的所有 session | 跑 |
| `mindmap --refresh` | 自上次 summarize 后变更的所有 session | 跑，force |
| `POST /api/refresh` | 同 --refresh | 同上 |

"实质变化"判定（防止每个 Stop 都消耗 Haiku）：diff 新的
`summaries/X.md` 和盘上的旧版；忽略 frontmatter（时间戳每轮都变）；
如果 `# 当前状态`、`# 下一步`、`# 任务（建议）`段落变化才触发
pass 2。否则单 pass-1 足够——HTML 热轮询直接拉到新 summary 内容。

### 独立 cooldown

把今天单一的 `last_ai_run.epoch` 改成两个 marker：

- `cache/last_summarize_run.epoch` —— pass 1 闸门，默认 60s
- `cache/last_classify_run.epoch` —— pass 2 闸门，默认 300s

便宜的 pass 1 速率比贵的 pass 2 快 5×。即便满负荷 pass 1 最多
60/小时 × $0.01 = $0.60/小时，pass 2 是 12/小时 × $0.05 = $0.60/小时。
合计最坏 $1.20/小时 vs 今天 $2.50/小时。

## 按组件列改动

| 文件 | 改动 |
|---|---|
| `bin/summarize.py` | 新增。读 session jsonl 尾部 + extract 骨架，调 Haiku，写 `cache/summaries/<sid>.md` |
| `bin/extract.py` | 瘦身——丢弃 `first_user_prompt`、`recent_user_prompts`、`last_assistant_summary`、`recap`（不再需要）。保留时间戳、cwd、message count、edited_files（仍是机器可读信号）。新加 `is_summarized` 标志，pass 1 跑完后置 true |
| `bin/aggregate.py` | 删除。pass 2 直接读 `summaries/*.md` |
| `bin/refresh.sh` | 重写调度：可选的 pass-1（按 session_id 通过 env 传入或扫脏目录）、条件性 pass-2。两个独立 cooldown。Apply-overrides + 修复不变 |
| `bin/refresh-bg.sh` | 把 hook stdin 里的 `CLAUDE_SESSION_ID` 透传到 refresh.sh，让其定位 pass 1 |
| `prompts/classify.md` | 删除。被两个新 prompt 取代： |
| `prompts/summarize-session.md` | 新增。~80 行，专注单 session |
| `prompts/classify-cross-session.md` | 新增。~200 行，比今天的 classify.md 简单（不再合成每个 initiative 的叙事） |
| `bin/render-html.py` | 可选：卡片里加 "📝 详细" 展开按钮，读 `cache/summaries/<sid>.md` 内联展示 |
| `bin/diagnose.py` | 在 extract 和 aggregate 之间加一个 `[2.5]` 阶段："Pass 1 摘要存在吗？" |
| `cache/summaries/` | 新目录，每个活跃 session_id 一个 `.md` |
| `docs/ARCHITECTURE.md` | 更新 pipeline 图 + cache 文件表 |

## 迁移

升级后第一次 refresh 给所有 `cache/sessions/` 中没有对应
`cache/summaries/` 的 session 跑一次 pass 1。约 200 × $0.01 = $2 一次
性。然后进入稳态。

旧的 `aggregate_input.json` 和 `prompts/classify.md` 保留一个版本周期
作为 fallback；重写代码检查 `cache/summaries/` 存在则走新路径，否则
走 legacy（防止 pass 1 prompt 写废了产不出可用结果）。

稳定运行两周后删 legacy。

## 成本 / 风险

### 成本最坏情况（Haiku 现价）

| 路径 | 频率 | 单次 | $/小时 |
|---|---|---|---|
| Pass 1 Stop hook | 最多 60/小时（cooldown 上限 1/分钟） | ~$0.01 | $0.60 |
| Pass 2 条件性 | 最多 12/小时（5min cooldown） | ~$0.05 | $0.60 |
| 迁移 backfill | 一次性 | $2 | one-shot |

稳态最坏 **$1.20/小时** vs 当前 **$2.50/小时**。空闲成本近零（两个
pass 都 hit cooldown）。

### 风险

| 风险 | 缓解 |
|---|---|
| Pass 1 摘要错误/幻觉 | 摘要落盘且用户可审（HTML 卡片有 "📝" 按钮）。错了就 `rm cache/summaries/<sid>.md` 重跑。AI 调用范围有界——一次一个 session |
| Pass 2 prompt 丢失了旧分类器有的上下文 | 迁移期 side-by-side 跑：保留老 pipeline 一周，对比 DIFF |
| `cache/summaries/` 磁盘占用 | 每个摘要 ~2-5 KB；200 个 session ~600 KB。session jsonl 不在了的摘要做 GC |
| `cache/summaries/<sid>.md` 和 `cache/mindmap.json` 漂移 | Pass 2 永远读最新 summaries 目录；漂移窗口至多一个 pass-1 周期（60s） |
| 两个 cooldown 比一个混乱 | 文档讲清楚；`mindmap --diagnose` 把两个都报出来 |

## 拒绝的方案

### A. 继续加大 extract 上限

我们对 `last_assistant_summary`（第一段 → 1500 字符）就这么做了，
EagleEye case 通了。但这是 heuristic 天花板，不是修复。关键内容不
在选择窗口里的 session 仍然会被错分。**拒绝**。

### B. 分类器升级到 Sonnet

Sonnet 4.6 是 Haiku 的 3-5 倍 token 成本。同样压缩的输入仍然是同样的
信息密度天花板。更强模型 + 烂输入 ~20% 提升，不是 5×。成本从
$2.5/小时 → $10/小时。**拒绝**。

### C. Stop hook 只喂当前 session，不做跨 session 分类

用户的初始直觉。但"这个新 session 属于哪个已有 initiative"需要 AI
看到其他 session。会完全失去跨 session 归组——这是核心特性
（例如一个 "ChangeFree refactor" initiative 横跨一周内 ~5 个 session）。
**拒绝**，改用两段式。

### D. 每 session 分类，无跨 pass

像 B，但不要单独分类器，每个摘要直接产出自己的 initiative 条目。
脑图只是 session 级输出的拼接。失去把多个 session 合并到一个
initiative 的能力。**拒绝**。

### E. 流式增量更新（SSE / websocket）

听起来不错，引入很多活动部件（server 重连、client 状态对账、消息
顺序）。P9.4 实现的 8 秒轮询已经满足用户"卡片自动更新"需求。
**拒绝**，过早。

## 等待 review 的开放问题

1. **摘要存储格式：markdown 还是 JSON？** Markdown 人类可读
   （用户能 `cat`）；JSON 对跨分类器无歧义。当前提案是 markdown +
   YAML frontmatter——两者兼得。备选：纯 JSON + 单独
   `render-summary.py` 给人看。

2. **Pass 1 看 jsonl 多少轮 / 多少字符？** 建议 K=10 轮或 L=30 KB。
   长技术 session 可能需要更多；闲聊型可能更少。可以从 30 KB 起步，
   按实证数据调。

3. **`mindmap --refresh` 里 pass 2 是否先于 pass 1？** 用户明确要
   全量刷新时，重新 summarize 所有 session（慢但彻底）还是直接基于
   已有摘要重分类（快）？建议：`--refresh` 触发两段；加一个
   `--refresh-classify-only` 给快速版。

4. **过期摘要清理**。当 `cache/sessions/<sid>.json` 消失（如用户
   删了 jsonl），是否保留 `cache/summaries/<sid>.md`？建议：保留，
   视作 archive——除非用户明确要求否则永不删 summary。

## 实施计划（批准后）

1. 写 `prompts/summarize-session.md` + 用 3 个手挑的 session 迭代
   到 bby 主观满意为止
2. 实现 `bin/summarize.py`，含脏检测（`cache/sessions/<sid>.json`
   和 `cache/summaries/<sid>.md` 的 mtime 比对）
3. 迁移 backfill 脚本：对所有已有 session 跑一遍 pass 1
4. 基于 summary 输入重写 `prompts/classify-cross-session.md`
5. 修改 `refresh.sh` 走两段调度 + 独立 cooldown
6. 更新 `render-html.py` 让卡片 UI 露出 summary
7. 更新 `diagnose.py` 把 pass 1 也走一遍
8. Side-by-side 跑一周：保留老 pipeline，对比输出
9. 通过验证后删 legacy

预计：代码 ~2 天聚焦工作，~1 周观察期。
