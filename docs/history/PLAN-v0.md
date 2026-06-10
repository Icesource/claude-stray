> **[历史文档 — 已退役]**
> 本文件是 2026-05 初版设计笔记，描述的单脚本架构（`refresh.sh` / `aggregate.py` / launchd 兜底）
> 以及 `/mindmap` 命名均已退役（退役提交：`2ae5071`）。
> 现状请看 [docs/ARCHITECTURE.md](../ARCHITECTURE.md)。
>
> **但以下结论仍然有效，且已被现版本吸收：**
> - **jsonl 结构探针发现**：`away_summary` 以 `system/subtype=away_summary` 落盘，已成为 Layer 0 `extract.py` 的核心信号。
> - **`--bare` 认证坑**：`claude -p` 的 `--bare` 模式不读 OAuth keychain，与订阅凭据方案互斥，现版本 Layer 1/2 均不使用 `--bare`。
> - **锁设计取舍**：全局 `mkdir` 原子锁"抢锁失败即放弃"的哲学被保留；现版本演进为层级锁（per-sid Layer 1 + 全局 Layer 2），与本文相同的 macOS-safe（无 `flock(1)`）方式实现。
> - **信号权威序**（`task_events` > `edited_files` > `last_assistant_summary` > `recap/away_summary` > `recent_user_prompts` > `first_user_prompt`）已固化进 `prompts/summarize-session.md`。

# Claude Code Worktree (Design Notes)

一个为 Claude Code 提供"会话脑图"能力的本地工具：定时读取历史会话，用 AI 自动分类工作项目与进展，最终通过 `/mindmap` 命令在终端以 shell 风格树状图呈现。

## 背景与动机

Claude Code 会话记录以 jsonl 形式存在本地 (`~/.claude/projects/<encoded-cwd>/*.jsonl`)，但用户没有跨会话、跨项目的全局视角。本工具希望解决：

- 我最近在做哪些项目？各自进展到哪一步？
- 不同会话之间的任务如何归类？
- 不用主动翻历史，就能看到一张"工作全景图"。

## 核心需求

1. **数据源**：读取 `~/.claude/projects/**/*.jsonl`，解析消息、工具调用、时间戳、cwd 等
2. **AI 分类总结**：调用 `claude -p` (headless 模式) 让 Claude 自己对会话做分类与进展摘要
3. **后台定时运行**：通过 launchd 定时触发，无需用户手动调用
4. **终端渲染**：shell 风格树状图（Unicode box-drawing + ANSI 颜色）
5. **快速查看**：`/mindmap` slash command 直接读取缓存结果，秒开

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  触发源(三选一或组合,见下节"触发策略")                 │
│    · Claude Code Stop hook       (每轮响应结束)          │
│    · Claude Code SessionStart hook (打开会话时)          │
│    · launchd LaunchAgent         (每 2h 兜底)            │
│           │                                              │
│           ▼                                              │
│    bin/refresh-bg.sh  (fire-and-forget + mkdir 锁)      │
│           └─> bin/refresh.sh                             │
│                 ├─> bin/extract.py  (增量读 jsonl)       │
│                 ├─> bin/aggregate.py (构建 AI 输入)      │
│                 ├─> claude -p < prompt                   │
│                 └─> cache/mindmap.json                   │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  ~/.claude/commands/mindmap.md (slash command)           │
│    └─> bin/render.py cache/mindmap.json                 │
│          └─> ANSI 树形渲染到终端(零依赖)                │
└─────────────────────────────────────────────────────────┘
```

## 触发策略

定时 vs 事件驱动的权衡:

| 方案 | 优点 | 缺点 |
|------|------|------|
| launchd 每小时 | 与 Claude Code 无关,稳定 | 没用的时候也跑,不够新鲜 |
| `Stop` hook | 每轮响应后立即刷新,最新鲜 | 未开 Claude Code 时完全不触发 |
| `SessionStart` hook | 打开就刷新 | 首次刷新要等 AI 跑完 |

**采用组合:Stop + SessionStart + launchd 兜底**
- `Stop` hook 是主力 —— 用户每发送一条消息、Claude 每响应一次都触发(不是会话结束!很多人对 Stop 语义有误解)。长会话天然增量更新。
- `SessionStart` hook 在打开新会话时触发,保证"打开 Claude Code 就能看到近期"。
- launchd 每 2h 作为兜底,防止长期不用后第一次打开等 AI 太久。
- 所有触发都走 `refresh-bg.sh`:fork 到后台立即返回,不阻塞 hook;用 `mkdir` 原子锁防止并发冲突,10 分钟以上的 stale lock 自动清理。

**hook 配置写入位置**:`~/.claude/settings.json` 的 `hooks.Stop` 和 `hooks.SessionStart` 数组,由 `bin/install-hook.sh` 幂等合并。

## 认证方案

使用 **方案 2：Headless Claude Code**。
刷新脚本里直接调用 `claude -p "..."`，复用当前用户登录的 Claude Code OAuth 凭据，走订阅额度，不需要额外 `ANTHROPIC_API_KEY`，也不产生独立 API 计费。

## 目录结构

```
claude-mindmap/
├── PLAN.md                    # 本文件
├── README.md                  # 安装与使用说明 (后续补)
├── bin/
│   ├── extract.py             # 增量解析 jsonl → cache/sessions/*.json
│   ├── aggregate.py           # 聚合 sessions 为 AI 输入
│   ├── refresh.sh             # 编排 extract → aggregate → claude -p
│   ├── refresh-bg.sh          # 后台 fork + mkdir 锁,供 hook 使用
│   ├── render.py              # 零依赖 ANSI 树形渲染
│   ├── install.sh             # 安装 slash command + launchd
│   └── install-hook.sh        # 幂等合并 hooks 到 settings.json
├── prompts/
│   └── classify.md            # 给 claude -p 的分类/总结提示词
├── cache/                     # 运行时数据 (gitignore)
│   ├── state.json             # jsonl 增量游标
│   ├── sessions/<id>.json     # 每个会话的结构化摘要
│   ├── mindmap.json           # AI 聚合结果
│   └── refresh.lock.d/        # mkdir 原子锁目录
├── launchd/
│   └── com.claude-code-worktree.plist   # LaunchAgent 模板(兜底)
└── commands/
    └── mindmap.md             # slash command 模板 (软链到 ~/.claude/commands/)
```

## 数据流

1. **extract.py** 遍历 jsonl,每个会话抽取一组结构化信号(见下节"信号权威序"),并通过 `is_automation` 字段标记自指的刷新会话以供下游过滤。长会话按字段级上限(recent prompts 3 条、edited_files 20 个、task_events 20 条)截断,控制 token 预算。
2. **aggregate.py** 读 `cache/sessions/*.json`,过滤 `user_message_count=0` 的壳会话,按 `last_activity_at` 倒序,截前 200 个,输出紧凑 JSON 数组。
3. **refresh.sh** 拼装 prompt:`classify.md` + `CURRENT_TIME: <now>`(作为时间锚) + aggregate 输出,喂给 `claude -p`。**不使用 `--bare`** —— 该模式不读 OAuth keychain,与我们复用订阅的方案冲突。
4. 输出 JSON 结构(strict,无 markdown):
   ```json
   {
     "generated_at": "<ISO-8601 UTC,刷新脚本墙钟覆盖>",
     "projects": [
       {
         "name": "claude-mindmap",
         "cwd": "...",
         "status": "active | paused | done | archived",
         "summary": "...",
         "progress": "...",
         "tasks": [{"title": "...", "done": true}],
         "sessions": ["abc123"],
         "last_activity_at": "..."
       }
     ]
   }
   ```
   状态语义(实际规则见 `prompts/classify.md`):
   - **active** — 近 3 天有活动,工作进行中
   - **paused** — 3–14 天无活动,或更久但有明确"待恢复"信号(未合 MR、开 issue)
   - **done** — 明确完成(合并、交付、会话里有结论)
   - **archived** — >14 天无活动且无恢复信号,或一次性探索/失败实验/废弃调试
   `archived` 项目在渲染时单独分组、折叠为单行,避免污染主视图。
5. **render.py** 纯 stdlib ANSI 渲染,无 pip 依赖(刻意不用 `rich` 避免 `pip install` 步骤)。非 TTY 或 `NO_COLOR` 时自动去色。`archived` 项目单独分组折叠到底部,避免污染主视图。

## 信号权威序(关键设计)

**问题发现**:第一版只喂 `first_user_prompt + recap + tools_used` 时,活跃会话因为没有 recap、开头 prompt 又已过时,导致 AI 生成的 tasks 列表严重滞后(会把早已完成的任务标成 `{done: false}`)。

**解法**:extract.py 现在每个会话提取一组"进展轨迹"信号,classify prompt 里明确告诉 AI **按权威序信任**:

| 权威 | 信号 | 含义 |
|-----|------|------|
| 1(最强) | `task_events` 里的 `completed:` | 用户显式标记完成,硬事实 |
| 2 | `edited_files` | Write/Edit 实际写过的文件路径,无法伪造 |
| 3 | `last_assistant_summary` | 最新一次 assistant 回复首段,通常含结论 |
| 4 | `recap` (away_summary) | Claude Code 原生摘要,权威但活跃会话上会滞后 |
| 5 | `recent_user_prompts` (最后 3 条) | 当前关注点 |
| 6(最弱) | `first_user_prompt` | 原始目标,早已过时 |

**硬规则**:如果 `edited_files` / `last_assistant_summary` / `task_events` 任一明显表明某事已完成,绝不能在 tasks 里标成 `{done: false}`。

## 自指反馈环过滤

`refresh.sh` 会调用 `claude -p` 执行 `classify.md`,这一步本身会在某个 Claude Code 项目目录下写一条新的 jsonl,它的 `first_user_prompt` 是我们自己的 classifier prompt。如果不过滤,下次刷新 AI 就会"看到自己",把这些 headless 刷新请求误当成真实用户会话,产生无意义的 "Claude Mindmap Classifier" 项目并污染结果。

**检测方式**:`extract.py` 里硬编码一组起始匹配(目前是 `"You are analyzing a developer's Claude Code session history"`),命中则给 session 标 `is_automation=True`。`aggregate.py` 在构建 AI 输入时跳过这些。

**注意**:这不是过滤 `claude-mindmap` 项目本身 —— 真实的开发会话(像这次我们迭代 claude-mindmap 的对话)必须保留。只过滤 refresh pipeline 自己触发的 headless 调用。

## 增量刷新策略

全量轮询成本过高,采用多级增量:

### 文件级增量
维护 `cache/state.json`,记录每个 jsonl 的 `{path, mtime, byte_offset}`:
- mtime 未变 → 整文件跳过
- mtime 变了 → 从 `byte_offset` 继续读到 EOF(jsonl 只追加)
- 新文件 → 从头读
- 读完后更新 offset

### 会话级缓存
`cache/sessions/<session_id>.json` 保存每个会话的结构化摘要。只有内容变化过的会话才重新生成摘要。

### "增量"这个词的范围(容易混淆,必读)

**增量只发生在 `extract.py` 这一层**,不在 AI 调用层:

```
jsonl 文件 ──[extract.py: mtime + byte_offset 增量]──> cache/sessions/*.json
                                                              │
                                                              ▼ (aggregate.py 全量读本地)
                                                      aggregate_input.json
                                                              │
                              ┌───────────── hash 短路 ──────┤
                              ▼                              ▼
                    复用旧 mindmap.json          (claude -p 全量送 AI)
                    (仅刷 generated_at)                mindmap.json
```

- `extract.py` 稳态下只读几百字节追加数据 → 毫秒级
- `aggregate.py` 每次全量拼 session 本地文件 → 零成本
- `claude -p` 一旦触发就是**全量**送 100+ 会话的压缩摘要(~50KB),**不是 AI 层的增量**

### 为什么不做 AI 层的增量(只送变化会话 + patch 输出)

讨论过,**刻意不做**。理由:
- 只送变化会话 → AI 失去跨项目上下文,不知道该会话并入哪个已有项目
- 要保留上下文就必须把现有 `mindmap.json` 也喂回去当参照,输入反而接近全量
- patch 型输出更难约束,容易错位、丢项目、状态一致性难保证
- 边际收益小、风险大

### 真正的 AI 省钱机制:Hash 短路 + Prompt Caching

1. **Hash 短路(已实现)**:`refresh.sh` 对 `aggregate_input.json` 算 SHA256,存 `cache/last_input.sha256`。下次运行若 hash 未变,直接复用 `mindmap.json` 只刷新 `generated_at`,**完全跳过 `claude -p`**。稳态下(没新会话活动)0 AI 调用。
2. **Prompt Caching**:`claude -p` 自动缓存重复的 prompt 前缀(`classify.md` 指令部分),Anthropic cache TTL 5 分钟。频繁触发时天然命中,真正计费的只有新增 sessions 的 token 差量。

### Level 1 AI 回填(规划中,未实现)

对没有原生 `away_summary` 的老会话(实测 ~92%),可以单独跑一次 `claude -p` 生成 2 句摘要写回 `cache/sessions/<id>.json` 的 `recap` 字段,一次性成本,之后增量命中。见"未来扩展"。

## Slash Command

见 `commands/mindmap.md` 和 `commands/mindmap-refresh.md`。两者都用 `!`-前缀执行 shell,然后要求模型把输出原样放进 fenced code block —— 这是因为 `!` 输出只注入到 prompt 不会自动显示给用户(见"已知风险"一节)。两个命令都配了 `allowed-tools` frontmatter 限制工具范围,降低模型自由发挥的空间。

## 定时任务 (launchd,兜底)

LaunchAgent(用户级,`~/Library/LaunchAgents/com.claude-code-worktree.plist`),每 2 小时触发一次 `refresh-bg.sh`,日志写到 `~/Library/Logs/claude-code-worktree.log`。仅作为 hook 方案的兜底 —— 主力刷新靠 Claude Code 的 `Stop` / `SessionStart` hook。

控制:`launchctl load/unload <plist>`;查看:`launchctl list | grep claude-mindmap`。

## 里程碑

- [x] M0:梳理方案(本文件)
- [x] M1:`extract.py` 增量解析 jsonl
- [x] M2:`refresh.sh` 打通 `claude -p` 分类流水线
- [x] M3:`render.py` ANSI 树形渲染
- [x] M4:launchd plist + slash command + install.sh
- [x] M5:`archived` 状态 + Claude Code hook(Stop / SessionStart) + install-hook.sh
- [x] M6:`/mindmap-refresh` 命令、`bin/mindmap` 零模型 wrapper、README
- [x] M7:进展信号增强(`recent_user_prompts` / `last_assistant_summary` / `edited_files` / `task_events`)+ 自指反馈环过滤
- [x] M8:全局锁迁入 `refresh.sh`、hash 短路跳过未变化 AI 调用、`claude -p` 超时保护
- [ ] M9:git log 信号(见"未来扩展")
- [ ] M10:退化场景兜底(超时自适应 / 熔断 / 降级告警)
- [ ] M11:长会话 token 总量上限、Level 1 AI 回填

## 未来扩展

### git log 作为进展信号(M8 候选)

对 `cwd` 落在某个 git 仓库里的会话,可以在 extract 阶段按 session 时间窗跑:

```bash
git -C <cwd> log --since="<started_at>" --until="<last_activity_at>" \
    --pretty="%h %s" --no-merges
```

好处:
- commit message 是"已完成事实"的最权威来源,比 assistant 的自述更硬
- 不占 session 内 token,独立 enrich
- 和 `edited_files` 交叉验证,能识别"写了但没 commit(草稿)" vs "写了且已入库"

待办:
- 处理 cwd 不是 git 仓库的情况(静默跳过)
- 处理 cwd 不存在的情况(被 rename / 删除)
- 处理 worktree 和多分支(取当前 HEAD 即可)
- 限制每会话 commit 数(比如最多 10 条,避免超长合并洪水)
- 性能:缓存每仓库每时间窗的结果,避免同一仓库下多个会话反复跑

### Level 1 AI 回填(M9 的一部分)

历史会话里只有约 8% 有原生 `away_summary`,其余完全靠 extract 信号 + classifier 推理。可以加一个 Level 1 步骤:对 `recap is None` 且信号稀薄的会话,单独用 `claude -p` 生成 ~2 句摘要写回 `cache/sessions/<id>.json` 的 `recap` 字段。只做一次,后续增量命中。

## 触发命令的设计取舍

Claude Code 没有公开"注册 `/`-prefix handler 命令不走模型"的接口 —— 内置 `/usage`、`/help` 是 CLI 源码硬编码。用户扩展(markdown command / skill / subagent)本质都是 prompt 模板,必走模型;`hook` 只能事件驱动;`!` 前缀可直通 shell 但无 `/` 自动补全。

**因此采用双路径并存**:
- **零模型路径**:`bin/mindmap` 可执行 wrapper(软链到 `~/.local/bin/mindmap`),shell 里 `mindmap` 或 Claude Code 里 `!mindmap` 直接调用 `render.py`,零 token、零延迟、无补全。
- **`/`-补全路径**:`/mindmap` / `/mindmap-refresh` 保留原 markdown command,优势是 `/` 自动补全和界面一致性,代价是每次一小轮模型 round-trip(prompt 已最小化为"原样输出注入的 shell 结果")。

让用户按场景自选,不强制二选一。

## jsonl 结构探针发现

实际文件:`~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`,每行一个 JSON 对象,追加写入。

**消息类型 (`type` 字段)**
- `user` — 用户消息 / tool_result
- `assistant` — 模型输出
- `system` — 系统事件,通过 `subtype` 区分
- `attachment` — 附件
- `file-history-snapshot` — 文件快照
- `permission-mode` — 权限模式切换

**通用字段**
`uuid` / `parentUuid` / `timestamp` / `cwd` / `sessionId`,可用于串联消息、溯源、按目录聚合。

**recap 原生落盘 ✨**
Claude Code 的会话 recap 以 `system` + `subtype: "away_summary"` 写入 jsonl:

```json
{
  "type": "system",
  "subtype": "away_summary",
  "content": "<recap 文本>",
  "timestamp": "...",
  "uuid": "..."
}
```

**这是关键发现**:Level 1 单会话摘要可以直接读这个字段,零 AI 调用。
回退策略:若某会话没有 `away_summary`(会话太短、老版本、已被关闭 recap),才走原始消息抽取 + `claude -p` 生成摘要。

## 已知风险与坑

### 版本 / 格式耦合
- jsonl 结构和 `system.subtype = away_summary` 是 Claude Code 内部格式,随版本可能变动。`extract.py` 用宽松解析,字段缺失时跳过,不 crash。
- `load_session` 会剔除 schema 中不存在的字段再构造 dataclass,允许本工具自身迭代 schema 时缓存平滑迁移。添加新字段只需给 dataclass 加默认值,无需清缓存。

### `claude -p` 认证踩坑
**`--bare` 模式与本方案互斥**。官方文档说 bare 模式"严格只读 `ANTHROPIC_API_KEY` 或 `apiKeyHelper`,不读 OAuth / keychain"。我们依赖 Claude Code 订阅 OAuth 凭据,所以 refresh.sh 绝不能加 `--bare`,否则会得到 `Not logged in · Please run /login`。

### Hook 绑定生命周期
Claude Code 的 Stop / SessionStart hook **只对 `install-hook.sh` 之后开启的会话生效**。当前正在使用的会话不会被它自己的 hook 触发,唯一的刷新路径是 `mindmap --refresh` / `/mindmap-refresh` / launchd 兜底。README troubleshooting 已说明。

### 后台刷新的静默性
`refresh-bg.sh` fork 到后台立即返回,用户完全看不到它跑。验证办法只有 `tail -f ~/Library/Logs/claude-code-worktree.log`。这是设计(不打断)而不是 bug。

### Slash command 的模型不可避免
Claude Code 没给用户注册纯 handler 命令的接口,`~/.claude/commands/*.md` 本质是发给模型的 prompt 模板。想"零模型 + `/`-自动补全"两全其美目前不可能。我们接受这个现实,提供双路径(见"触发命令的设计取舍")。

顺带一个曾经踩过的坑:slash command 里 `!` 前缀运行的 shell 输出会注入到**模型的 prompt 里**,不会显示给用户。所以 `/mindmap` 命令里必须显式要求模型"原样输出到 fenced code block",否则用户看不到任何东西,只看到模型说了句"已展示脑图"。

### 并发控制 & 超时保护

- **单一全局锁**:`refresh.sh` 用 `mkdir cache/refresh.lock.d` 原子锁,**整个 pipeline(含 extract/aggregate/claude -p)都串行化**。任何路径(slash command、`mindmap --refresh`、hook、launchd)都会撞到同一把锁。`refresh-bg.sh` 只是 fire-and-forget 的 fork 包装,不自己持锁。
- **为什么锁要放在 refresh.sh 里**:早期版本锁放在 refresh-bg.sh,导致 `mindmap --refresh`(前台)与 hook 触发的 bg(后台)共享 `_prompt.txt` / `_raw_output.txt` 但互不感知,并发时互相覆盖,直接导致前台 JSON 解析失败。
- **抢锁失败 = 立即放弃,不排队**:这是刻意设计。hook 在长会话里会高频触发,如果排队,早期的过时刷新会堆在后面没意义。`refresh.sh` 抢锁失败就 `exit 0`,日志写一行 `refresh already running, skip`。
- **claude -p 超时**:`refresh.sh` 用 `perl -e 'alarm ...; exec'` 给 `claude -p` 套 600s 硬超时(可通过 `CLAUDE_MINDMAP_TIMEOUT` 环境变量覆盖)。超时则非零退出,**不写 hash**,下次重新尝试。
- **Stale lock 回收**:锁目录修改时间 > 660s 就视为崩溃遗留,自动清掉重抢。这个阈值必须大于 `claude -p` 超时(600s)+ 预留 buffer,否则正常慢运行会被误判。

### 退化场景(已记录,暂未兜底)

**超时始终失败导致永远拿不到新结果**:如果每次 `claude -p` 都跑超 600s(例如输入规模失控、模型持续限流),hash 永远不更新,每次调用都从头超时,`mindmap.json` 停在上次成功的快照。用户看到的是"数据不再新鲜但不报错"—— 静默降级,不算 crash,但需要用户主动看日志才能发现。

未来可选缓解:
- 超时自适应:每次失败把超时值放大(600 → 900 → 1200),几次后停止尝试
- 失败时缩减输入:按 `last_activity_at` 丢弃最旧的会话,剩下重试
- 熔断:连续 N 次失败后,写一个 `cache/circuit_open` 标记,跳过所有刷新直到用户手动清除
- 用户可见降级:渲染时若日志显示最近几次都失败,在树顶部加一行告警

暂不实现,等真有复现再加。

### 订阅额度 / Token 消耗
- 每次 refresh 一次 `claude -p` 调用,输入是 100+ 会话的压缩摘要(当前约 50 KB),不算便宜但可接受
- 真正的 token 杀手是"长会话"—— 如果单会话的 edited_files / task_events 特别长,aggregate 会被撑大。当前用字段级上限截断,但还没做跨会话的总量上限 —— 未来可以加 `TOTAL_INPUT_TOKENS_BUDGET`
- 触发频率:Stop hook 每轮都触发,但增量模式下 mindmap 实际重新生成只在"有会话变化 + 锁空闲"时发生,稳态成本很低
