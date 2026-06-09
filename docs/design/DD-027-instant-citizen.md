# DD-027: 即时公民 — 先创建,后丰富

**Status**: Implemented (slice 1)
**Author**: Claude (with user)
**Date**: 2026-06-09
**Predecessors**: DD-015 (注意力驾驶舱), DD-022 (worktree first-class),
DD-025 (parallel sub-cards), 项目北极星「卡 = 单 session」

## 问题

新建任务 / 起子卡之后,卡片不会**立刻**出现。它要等后台 AI 管线
(`extract → summarize → classify`,约 10–40s)跑完,真卡才落进
`dashboard.json` 再被 `/api/data` 渲染出来。用户在创建动作发生后,看着
一片空窗,明显感到延迟 —— 仿佛刚才那一下没生效。

这违背一个朴素但根本的模型:

> **卡片是系统公民。它应该在「创建动作那一刻」就存在 ——
> 而不是等 AI「确认」它存在之后才存在。**

AI 总结(进度 / 资源 / 语义名 / 归并)是对一个**已经存在**的公民的*事后丰富*,
不是它出生的前置条件。

## 既有的半截方案(为什么不够)

DD-025 加过一个纯客户端的「创建中…」tab(`cockpit.html` 的 `myPending`):起子卡后
在那个会话终端的「会话族」侧栏里塞一个临时占位 tab。但它:

- 只活在内存里 —— 刷新页面就没了;
- 只出现在某个会话的终端侧栏里,**不是主看板上的一张卡**;
- 不覆盖「新建任务」入口;
- 没有与真卡对齐的机制 —— 真卡出来后它不会无缝消失。

它缓解了「起子卡终端里」的空窗,但没解决「卡片这个公民何时出生」这件事。

## 设计:pending 层(占位公民层)

引入一个独立于 `dashboard.json` 的轻量 **pending 层**:
`cache/pending-cards.json`。它登记「已经被创建、但 AI 还没产出真卡」的占位公民。

### 数据流

```
创建动作(serve)                            渲染(/api/data)
─────────────────                          ──────────────────
_handle_new_session  ─┐                    load dashboard.json (真卡)
_spawn_subcard       ─┤── register() ──▶   + _pending.merge_into_mindmap()
                      │   pending-cards.json   ├─ 真卡已代表? → 丢弃占位(对齐)
                      │                        └─ 否          → 合成 _pending 卡
后台 capture 线程 ────┘                    cockpit: _pending 卡显示「准备中」
  抓到 child sid → capture_sid()
```

- **register**:创建动作发生的那一刻,立刻落一条占位记录:
  `{name, cwd, worktree_path, worktree_name, parent, created_at}`。落盘 →
  撑过页面刷新。
- **capture_sid**:两个入口本来就有后台线程用
  `_subcards.find_session_by_cwd()` 抓 child 的 session_id(为了 re-key 终端 /
  记父子链接)。复用它,把抓到的 sid 也回填进占位记录,作为对齐键。
- **merge_into_mindmap**:`/api/data` 在 `_attach_code_location` 之后调用,把
  每条「还没被真卡代表」的占位记录合成一张 `_pending` 卡,挂进对应 workspace。
  纯渲染期增强,**不**写 `dashboard.json`(对齐 DD-022-A 的 `code_location` attach
  和 DD-025 的 `_subcards.link`)。

### 对齐(无缝替换的关键)

占位卡 → 真卡的对齐用**两把键**,任一命中即认为「真卡已到」,占位卡不再合成:

1. **session_id**:占位记录被 capture 填了 sid,且该 sid ∈ 某真卡的 `sessions[]`。
2. **worktree 路径**:占位记录的 `worktree_path` == 某真卡的
   `code_location.worktree`(都走 `realpath`)。worktree 路径在**创建那一刻**就已知
   (我们自己 `git worktree add` 出来的),而真卡的 `code_location` 由
   `_attach_code_location` 从会话 cwd 机械算出 —— 两边天然一致。

worktree 路径是主对齐键:它在创建时即确定,不依赖异步 capture。session_id 是兜底
(覆盖「无 worktree 的新建任务」这种没有 worktree 路径的情形)。

### 自动过期(防幽灵)

占位记录带 TTL(默认 15 分钟)。如果创建动作启动失败、或用户开了终端啥也没干
导致真卡始终不出现,占位记录到点自我过期,不会留下永久幽灵卡。`/api/data` 顺手把
「已过期」或「已被真卡代表」的记录从文件里剪掉。

## 覆盖的两个入口

| 入口 | 触发 | worktree | sid capture | 对齐键 |
|---|---|---|---|---|
| 新建任务(无 worktree) | `/api/new-session` | 无 | 按 cwd 抓 | session_id |
| 新建任务(+worktree) | `/api/new-session` | 有 | 按 wt_path 抓 | worktree 路径(主)+ sid |
| 起子卡 | `/api/new-session`(parent+wt)→ `_spawn_subcard`;或 CLI `stray spawn` | 有 | 按 wt_path 抓 | worktree 路径(主)+ sid |

> CLI `stray spawn` 走的也是 serve 的 `_spawn_subcard`,所以登记占位卡的逻辑放在
> `_spawn_subcard` 一处即对两个子卡来源都生效。

## 驾驶舱呈现

`_pending` 卡走 `running` band(它确实「在进行中 —— 正在被创建」),midCell 显示
**「准备中…」** + 转圈。它:

- 有 parent 的(子卡)→ 通过 `parent_session_id` 自然嵌套在父卡下(复用
  `groupSubcards`);
- 点击安全:没有 session,点一下只 toast「该工作没有关联会话」,不会开错终端;
- 真卡一到,下一次 `/api/data`(驾驶舱每 8s 热刷)占位卡就被对齐丢弃,无缝换成真卡。

## 非目标 / 不破坏

- 不动 `classify` 的铸卡 / 归并 / mint / link / 分带 / 归档逻辑 —— pending 层完全
  独立,只在渲染期叠加。
- 不写 `dashboard.json`。占位卡永远不会被持久化成真卡 —— 真卡只由管线产出。
- DD-025 的客户端 `myPending` tab 保留(它是终端侧栏内的即时反馈,与主看板占位卡互补)。

## 后续(押后)

- 占位卡可显示「已发出的任务提示词」首句作为临时名(目前用用户填的 name 或「准备中」)。
- capture 失败(20–40s 没抓到 sid)可在占位卡上标注「启动可能失败了」,而不是静默等过期。
