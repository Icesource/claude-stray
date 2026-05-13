# 架构

`claude-code-worktree` 截至 commit `9f01447` 的实际工作方式。

英文原版：[../ARCHITECTURE.md](../ARCHITECTURE.md)

## 30 秒概览

读 `~/.claude/projects/**/*.jsonl`（Claude Code 的会话日志），把压缩
后的视图喂给 headless `claude -p` 调用，拿回结构化的工作脑图，渲染为
ANSI / HTML / markmap 三种形式。

## Pipeline

```
~/.claude/projects/*/*.jsonl
        │
        ▼ extract.py — 增量 jsonl 读取器，有状态
cache/sessions/<sid>.json   （每个 session 一份摘要）
        │
        ▼ aggregate.py — 过滤 + 压缩，按时间排序，上限 200
cache/aggregate_input.json  （单个 JSON 数组，~300KB）
        │
        ▼ refresh.sh — 编排器
        │   1. 应用 user_overrides.json
        │   2. 从 mindmap.json 移除 cache/archive/ 里的 id
        │   3. 应用 deleted_ids.json
        │   4. hash 检查（input 没变就跳过 AI）
        │   5. cooldown 闸门（读 cache/last_ai_run.epoch）
        │   6. 拼 prompt：classify.md + OUTPUT_LANG + PRIOR_MINDMAP
        │                  + DELETED_IDS + INPUT_SESSIONS
        │   7. claude -p --model haiku-4.5  （一次性，无工具）
        │   8. 解析 AI 输出 JSON，写 mindmap.json
        │   9. 用 prefix 匹配修复被截断的 session_id
        │  10. 写 cache/last_ai_run.epoch
        │  11. 重新生成 mindmap.html + mindmap-tree.html
        ▼
cache/mindmap.json
        │
        ├─ render.py             → stdout ANSI 树
        ├─ render-html.py        → cache/mindmap.html （卡片仪表盘）
        └─ render-tree.py        → cache/mindmap-tree.html （markmap）
```

## 触发源

任何想刷新脑图的入口都调 `refresh.sh`：

| 触发源 | 时机 | 路径 |
|---|---|---|
| Claude Code `Stop` hook | 每轮 assistant 响应结束 | `refresh-bg.sh`（fork+detach） |
| Claude Code `SessionStart` hook | session 开启/恢复 | 同上 |
| macOS LaunchAgent | 每 2 小时 | 同上 |
| `mindmap --refresh` | 用户主动 | 内联调用，置 `CLAUDE_WORKTREE_FORCE=1` 绕过 cooldown |
| `POST /api/refresh` | UI 上的刷新按钮 | 同 `--refresh` |

`refresh.sh` 由三层闸门控制：

- mkdir 全局锁（`cache/refresh.lock.d`）——串行化并发调用
- hash 检查——`aggregate_input.json` 没变就跳过 AI
- cooldown——`cache/last_ai_run.epoch` 距今小于 `$COOLDOWN_SECS` 就跳过
  （默认 300s；之前是 900s；用独立 marker 是因为 OUTPUT_FILE mtime 会
  被 apply-overrides 阶段污染，假性重置 cooldown）

## Cache 文件清单

全部在 `cache/` 下，整个目录被 gitignore。

| 文件 | 写入方 | 用途 |
|---|---|---|
| `mindmap.json` | refresh.sh + apply-overrides + 后处理修复 | 规范状态；schema v2 = workspaces > initiatives > tasks |
| `aggregate_input.json` | aggregate.py | 喂给 AI 的压缩输入；一个 session summary JSON 数组 |
| `sessions/<sid>.json` | extract.py | 每 session 的摘要；按 byte offset 增量构建 |
| `state.json` | extract.py | 每个 jsonl 的 byte offset，让重跑保持增量 |
| `last_input.sha256` | refresh.sh | 上次*成功*跑 AI 时的 aggregate_input hash |
| `last_ai_run.epoch` | refresh.sh | 上次成功调用 AI 的时间戳。cooldown 闸门读这个 |
| `user_overrides.json` | serve.py /api/save（或规划中的 CLI） | task 勾选翻转、删除的 task；被 refresh.sh apply-overrides 消费 |
| `deleted_ids.json` | serve.py /api/save | 用户主动删除的 initiative tombstone。AI 被告知忽略这些 id |
| `archive/<ws>/<id>.json` | serve.py /api/save | 用户归档的 initiative 完整 payload；AI 永远看不到 |
| `session_locations.json` | record-location.py（hook） | session_id → ZELLIJ_PANE_ID + cwd + 时间戳 |
| `config.json` | install.sh | `{lang: zh-CN}` |
| `mindmap.html` | render-html.py | 卡片仪表盘，单文件 |
| `mindmap-tree.html` | render-tree.py | Markmap 导出视图，单文件 |
| `refresh.lock.d/` | refresh.sh | mkdir 全局锁 |

## 组件

```
bin/
  install.sh         — 一次性安装：--lang、slash command、CLI 软链、hook、launchd
  install-hook.sh    — 单独重装 hook（幂等）
  refresh-bg.sh      — refresh.sh 的 fork-and-detach 包装；
                       fork 前先调 record-location.py
  refresh.sh         — 编排器（详见 Pipeline）
  extract.py         — jsonl reader → cache/sessions/<sid>.json
  aggregate.py       — sessions/*.json → aggregate_input.json
  record-location.py — hook → cache/session_locations.json
  render.py          — mindmap.json → ANSI 树（stdout）
  render-html.py     — mindmap.json + archive/ + locations → cache/mindmap.html
  render-tree.py     — mindmap.json → cache/mindmap-tree.html (markmap)
  serve.py           — 本地 HTTP 服务 127.0.0.1:9876
                       静态：GET / 服务 mindmap.html
                       API： GET /api/data, POST /api/save, POST /api/refresh
                       Helper: POST /focus, POST /newpane（zellij action ...）
  diagnose.py        — 给定 session_id 走一遍 pipeline，逐阶段报告状态
  mindmap            — 用户向 CLI 分发器
  uninstall.sh       — 卸载 install.sh
prompts/
  classify.md        — 跨 session 分类的 AI prompt
```

## 加载模式

HTML 可以两种方式打开，行为都对，只是持久化路径不同：

| 模式 | URL | 写盘路径 | 用户授权 |
|---|---|---|---|
| `mindmap --open` | `file:///.../mindmap.html` | File System Access API（仅 Chrome/Edge），降级为"下载补丁" | 每个 session 授权一次 |
| `mindmap --serve`（推荐） | `http://127.0.0.1:9876/` | `POST /api/save` 直接写 cache/ | 不需要——loopback 限定 |

HTML 启动时检测 `location.protocol` 自动选择路径。

## 连续性模型（让脑图真正有用的部分）

AI 不会每次重新分类。`PRIOR_MINDMAP` 作为基线喂回去。规则写在
`prompts/classify.md`：

1. Initiative `id` 是稳定的——AI 必须复用同一 id 描述同一概念的工作，
   即使 name 稍有演变
2. Task `done: true` 单调——一旦标完成永远不能被 AI 反悔
   （只有用户通过 `user_overrides.json` 才能改）
3. 状态随不活跃衰减——`active` → 3 天后 `paused` → 14 天后 `archived`
4. 只在 INPUT_SESSIONS 有新证据时才创建新 initiative
5. `DELETED_IDS` 是 tombstone——即使有新证据 AI 也不能复活

用户编辑通过 PRIOR_MINDMAP 让 AI 感知：
- 用户在 UI 勾完成 → `user_overrides.json` → refresh.sh apply-overrides
  → mindmap.json → PRIOR_MINDMAP 带着 `done: true` → 下次 AI 不能改回

## 并发

当前的锁很简陋，单用户单机够用。

| 风险 | 防护 |
|---|---|
| 两次 refresh 重叠 | `cache/refresh.lock.d` mkdir 锁在 refresh.sh 顶部 |
| serve.py /api/save 与 apply-overrides 竞争 | 暂无；依赖 /api/save 是 POSIX 原子写、refresh.sh apply 在 AI 之前先执行 |
| 多个浏览器 tab 同时 POST /api/save | 暂无；last-write-wins，单用户场景可接受 |
| Reader 读到半写的 `mindmap.json` | 暂无；json.dump 非原子。窗口 <100ms。规划：atomic tmp+rename（见 ROADMAP P11.0） |

加固方案见 [ROADMAP.md → P11.0](ROADMAP.md#p110--concurrency-lock-for-cache-writes)。

## 你可以依赖的不变量

代码或 prompt 强制保证。违反就是 bug。

1. `cache/mindmap.json` schema_version == 2（render.py 里有 legacy fallback）
2. 每个 initiative 都有非空 `id` 和 `sessions[]`
3. `sessions[]` 是完整 UUID（refresh.sh 后处理修复截断）
4. 一旦标 `done: true` 跨 refresh 都保持（除非用户主动反勾）
5. Archived initiative 永远不在 PRIOR_MINDMAP 里（refresh.sh 拼 prompt 前先剥离）
6. `cache/last_ai_run.epoch` 仅在 `claude -p` 真正成功后才更新
7. `aggregate.py` 跳过 `is_automation=true` 的 session——防止分类器看见自己的 prompt 形成自我引用

## 这套架构哪里不行

- **单 session 理解深度**。`extract.py` 把每 session 硬压成 ~1.5KB。
  分类器永远看不到完整对话上下文。症状："卡片进度滞后于实际工作"。
  修复方案见 [DD-001](design/DD-001-two-pass-classification.md)。

- **真正的实时单 session 更新**。Cooldown（默认 5min）是单一全局闸门；
  你没法只刷新单张卡片，必须重新分类全部 200 个 session。同一个修复
  方案。

- **跨主机 / 多用户**。loopback-only 是设计意图。
