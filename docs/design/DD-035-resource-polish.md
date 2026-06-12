# DD-035 — 外部资源打磨:正名、a1 状态刷新、呈现升级、注意力联动

**Status**: Draft — 待用户确认
**Author**: Claude (with user)
**Date**: 2026-06-12
**Predecessors**: DD-021(采集原则)、DD-026(URL 机械解析)、DD-017(CR watcher,idea 阶段)、
DD-015/DD-020(注意力模型)、DD-033(机械装配:能用语法的不求 AI)

## 0 — 定位(用户的话)

外部资源采集是本产品**唯一的结构性壁垒**:Aone/内网生态(CR/MR/变更单/发布单/工作项),
Agent View 只认 GitHub PR 进不来。但它「还没打磨好」。本 DD 把它打磨好。

## 1 — 现状审计(2026-06-12,真实 cache/dashboard.json)

20 张卡,12 张有 artifacts,共 44 条:
`cr 14 · mr 9 · branch 9 · deployment 7 · issue 2 · doc 2 · worktree 1`。

**已经好的**(DD-021/026 的成果,别推倒):
- 零 commit 噪声(源头过滤生效);title 覆盖 100%;同卡内无 (type,ref_id) 精确重复;
- last_mentioned_at 全有;渲染期 URL 回填/重建(DD-026)对 mr/cr/pr 生效。

**实测出的四个问题**:

1. **类型语义混乱(正名问题)**。`cr` 被 AI 重载了:14 条 `cr` 里既有
   `code.example.com/<g>/<r>/codereview/<id>`(代码评审,本质 = MR),又有
   `cd.example.com/unite/micro/cr/app/<appId>/<crId>`(Aone **变更单**,
   完全不同的东西)。同一资源 34600001 在同一张卡上同时以 `cr` 和 `deployment`
   两个类型出现 —— 去重键 (type, ref_id) 因 type 不同而漏掉。AI 决定 type,
   但 type 其实**由 URL 语法唯一决定**(DD-033 原则:机械能定的不求 AI)。

2. **状态陈旧(最痛)**。状态只来自会话文本,会话停了状态就冻结。实锤:
   - 变更单 34600001:缓存 `pending` → `a1 app cr get` 实查 **CLOSED**;
   - 发布单 155000001:缓存 `pending` → `a1 app deploy-order get` 实查 **SUCCESS**。
   当前 21 条非终态(cr:pending 9、mr:pending 7、deployment:pending 5)大概率
   多数已过期 —— 驾驶舱在用过期信号骗人。

3. **URL 缺失**:34 条外部资源 12 条缓存里无 url。DD-026 渲染期重建只覆盖
   codereview 语法;变更单/发布单/工作项 URL 需要 appId/projectId,重建不了
   (但 a1 实查回包里带 url/可拼,见 §3)。

4. **覆盖度**:GitHub PR/issue 模式在 prompt 表里但样本极少(用户主战场是 Aone,
   符合预期);**流水线/CI** 不是资源类型(刻意的 —— 流水线是步骤不是落点,
   维持 DD-021 原则不收);req/bug/task 统一进 `issue`,丢了工作项子类语义。

## 2 — 设计总览

四根支柱,每根独立成片、可独立验收:

```
S1 正名     URL 语法 → 规范 type + 规范身份(canonical id)→ 去重收敛
S2 实查     a1 CLI 按需/低频刷新状态 → sidecar 缓存 → 渲染期覆盖
S3 呈现     chips 升级:状态徽章 + 开放优先排序 + 终态灰化 + 新鲜度标记
S4 联动     状态跃迁 → 卡片注意力事件(单独成节,保守起步)
```

公共原则:
- **不分裂仓库:provider 适配器架构**(用户关切 2026-06-12:本仓已开源 GitHub,
  不能强绑 a1)。状态实查引擎只定义**契约**(`match/plan/parse/available`),
  Aone(a1)和 GitHub(gh)是两个**内置 provider**,运行时按 CLI 是否存在自动
  启用 —— 没有 a1 的机器上 Aone 资源优雅降级回会话文本态,整体功能不残缺。
  Aone URL 语法本就在公开 prompt 里(summarize Rule 10),内置 aone provider
  不新增暴露;若未来想做零内网痕迹,provider 目录支持树外丢入,但**不在本 DD 做**。
  这反而强化壁垒叙事:同一引擎、双适配器 —— Agent View 只有 GitHub 那半。
- **dashboard.json 不动**。它是 assemble 管的 AI 资产;所有机械增强走
  **渲染期 overlay**(DD-026 已开的先例 `_attach_resource_urls`)+ **sidecar 缓存**。
  好处:对全部存量卡立即生效、AI 重跑不冲掉、出错可整体禁用。
- **绝不轮询轰炸**。a1 实查 ~1-2.5s/次,只在「有人看 + 状态可能变 + 上次查得久了」
  三个条件同时成立时查,且每轮有预算上限。终态(merged/closed/SUCCESS)**永不复查**。

## 3 — S1 正名:URL 语法定 type,规范身份去重

新增纯函数模块(扩展 `bin/_resources.py`):`canonicalize(artifact) -> artifact`。

**URL 语法 → 规范 type**(实测样本归纳):

| URL 语法 | 规范 type | 语义 |
|---|---|---|
| `code.example.com/<g>/<r>/codereview/<id>` | `mr` | 代码评审(= Aone MR) |
| `cd.example.com/.../cr/app/<appId>/<crId>` | `cr` | **变更单** |
| `cd.example.com/.../publish/app/<appId>?flowId=<f>` | `deployment` | 发布(流水线实例) |
| 发布单 deploy-order id(ref_id 9 位、卡上下文) | `deployment` | 发布单 |
| `project.example.com/v2/project/<pid>/req\|bug\|task/<id>` | `issue`(+`subkind: req/bug/task`) | 工作项 |
| `github.com/<o>/<r>/pull/<id>` / `issues/<id>` | `pr` / `issue` | GitHub |

**规范身份**:`identity = (platform_class, id)`,如 `aone-codereview:27800001`、
`aone-cr:34600001`、`aone-deploy:155000001`。去重键从 (type, ref_id) 换成 identity
—— cr/deployment 同 URL 重复立即收敛。无 URL 的条目保持现状(type:ref_id)。

**接线**:assemble 的 `merge_artifacts` 吸收前先 canonicalize(增量修正存量),
cockpit 的 `artKey` 同步换键。AI prompt(Rule 10)补一行类型澄清(变更单≠代码评审),
但**不依赖** AI 改对 —— 机械层兜底。

副产物:canonicalize 顺带把 URL 里的 appId/projectId/group/repo 抽出来存在
artifact 上(`a1_ctx`),S2 直接用,不用再猜。

## 4 — S2 实查:状态刷新引擎(壁垒主体,provider 架构)

### 4.0 provider 契约(开源核心,适配器内置可插)

```python
# bin/_status_refresh.py —— 引擎只认契约,不认平台
PROVIDERS = [AoneProvider, GithubProvider]      # 内置;树外可扩展(后做)
class Provider:
    cli: str                                    # 'a1' / 'gh' —— shutil.which 探测
    def match(identity) -> bool                 # 'aone-codereview:*' / 'gh-pr:*'
    def plan(artifact) -> list[str] | None      # argv,不可查则 None
    def parse(stdout) -> {status, url?, title?} # 平台原始 → 归一化 enum
```

- 引擎启动时探测一次 `which a1` / `which gh`,缺哪个就静默禁用哪个 provider;
  无 provider 命中的资源保持会话文本态(status_source: "session"),UI 不残缺。
- GitHub provider:`gh pr view <n> --repo o/r --json state,...` /
  `gh issue view <n> --repo o/r --json state`,repo 同样从 URL 语法提取 ——
  开源用户开箱即用,a1 是内网用户的增强,同一引擎。

### 4.1 Aone provider 的四条查询路径(2026-06-12 实测全通)

| 资源 | 命令 | 上下文来源 | 关键字段 | 实测耗时 |
|---|---|---|---|---|
| 代码评审 | `a1 repo mr view <id> --repo <g/r> -f json` | URL 路径里的 group/repo | `state`: opened/merged/closed | ~2.5s |
| 变更单 | `a1 app cr get <crId> --format json` | 无需(全局 id) | `status`: DEV/CLOSED/…(+statusLabel) | ~1.5s |
| 发布单 | `a1 app deploy-order get <id> --app <appId> --format json` | URL 里的 appId | `status/finalStatus`: SUCCESS/… | ~1.5s |
| 工作项 | `a1 project workitem get <id> --format json` | 无需 | fields.status.value: 待处理/… | ~1.5s |

回包还带 `updatedAt`、reviewers、title、url —— 顺手回填缺失的 url(解决 §1 问题 3
中重建不了的变更单/发布单 URL)和更准的 title(只填空,不覆盖 AI 的语义 title)。

### 4.2 形态:`bin/_status_refresh.py`(纯函数 + 注入 runner)+ sidecar

```
cache/resource-status.json   # sidecar,serve 持有写锁
{ "<identity>": { "status": "merged",          # 归一化到现有 enum
                  "raw": "CLOSED",             # 平台原始值
                  "title": "...", "url": "...",# 实查回填(仅补空)
                  "fetched_at": iso,
                  "error": null|"404"|"auth" } }
```

- 纯函数层:`plan_fetch(artifact) -> a1 argv | None`、`parse_result(type, json) -> status`、
  状态归一化表(CLOSED→closed,SUCCESS→live,待处理→open …)。runner 注入,
  单测不碰真 a1。
- serve 渲染期新 overlay `_attach_resource_status(mindmap)`:identity 命中 sidecar
  → 覆盖 artifact.status,并打 `status_source: "a1"` + `status_fetched_at`
  (AI 文本态则为 `status_source: "session"`)。**实查赢过会话文本**(它更新)。

### 4.3 刷新策略(成本铁律)

触发只有两种,无常驻轮询:

1. **手动**:UI 每卡资源区一个「⟳ 实查」按钮 → `POST /api/resource-refresh {card_id}`
   → 该卡非终态资源逐条实查 → SSE(已有 /api/events)推回,前端原位更新。
2. **惰性低频**:dashboard 数据被请求时(`/api/data`,即有人在看),后台线程
   挑出满足全部条件的资源入队:
   - 状态非终态(pending/approved/open/active);终态永不复查;
   - `fetched_at` 超 TTL(默认 30 分钟);
   - 所在卡 7 天内有活动(死卡不查);
   - 每轮预算上限 12 次、串行(或并发 2)、错误退避(404/auth 记入 sidecar,
     24h 内不重试,UI 继续显示会话文本态)。

当前盘面 21 条非终态、多数会在首轮被实查成终态,稳态每轮实际查询 ≈ 0-5 次。

## 5 — S3 呈现:密度 + 排序,不减条目

(用户原则:density+ranking,不是 fewer items;面板 UI 迭代过多次,只做增量。)

1. **chip 状态徽章**:每个外部资源 chip 加状态角标(色点+短词):
   `待评审`(amber)/`已通过`(blue)/`已合并 ✓`(green-grey)/`已关闭`(grey)/
   `已发布 ✓`(green-grey)/`回滚`(red)。色彩语义与卡片 band 色一致。
2. **排序 = 可行动优先**:开放态(待评审/已通过/进行中)置顶,终态沉底**灰化但不隐藏**;
   同级按 last_mentioned_at 降序。卡详情、终端侧栏同一规则。
3. **新鲜度标记**:`status_source: "a1"` 的 chip 在 tooltip 标「a1 实查 · N 分钟前」;
   仅会话文本的标「来自会话 · 未实查」。不新增视觉噪声,只进 tooltip + 一个 ⟳ 按钮。
4. **类型分组维持现状**(groupByType 已做),变更单/代码评审正名后分组自然变准。
5. 列表行(midCell)**不加**新元素 —— 行密度已经很满,资源状态的行级表达走 S4 的
   注意力事件,不走常驻 chip。

## 6 — S4 注意力联动(差异化大招,单独成节、保守起步)

**原则**:资源状态跃迁是**事件**,不是新 band。band 仍由 bandFor 的既有逻辑决定;
事件以两种方式进入注意力模型:

1. **V1(本 DD 实现)— 跃迁事件行**:sidecar 记录每次实查导致的状态**变化**
   (`pending→approved` 等)。未读事件在卡 mid 格/详情顶部显示一条事件行:
   - `✓ CR 27800002 评审通过 —— 可以合并了`(可行动,着 needs_you 色)
   - `⚠ 发布单 155000002 回滚`(异常,needs_you 色)
   - `✓ MR 已合并`(信息,done 色)
   点击即已读(ack 进 sidecar)。**band 提升仅两种明确情况**:`approved`(等你合并)
   和 `rolled-back`(出事了)→ 该卡进 needs_you;其余跃迁只显示不抬band。
2. **V2(不在本 DD,挂 DD-017)— 评论触发**:reviewer 评论 → AI 读评论评估起草
   —— DD-017 的领域,等 V1 验证「实查机制 + 事件管道」这条地基后再上。

为什么保守:band 是驾驶舱的信任根基,误抬 = 狼来了。先让跃迁事件可见、可 ack、
可统计误报率,再谈更激进的接管。

## 7 — 分片实现计划(每片带测试,全绿后 commit)

| 片 | 内容 | 交付物 | 测试 |
|---|---|---|---|
| **S1** | canonicalize:URL语法→type/identity/a1_ctx;assemble+cockpit 换去重键;Rule 10 补澄清 | `_resources.py` 扩展 | 纯函数单测(真实样本表驱动) |
| **S2a** | `_status_refresh.py` provider 契约 + aone/github 双 provider(plan/parse/归一化)+ sidecar 读写 + CLI 探测降级 | 新模块 | runner 注入单测(双平台样本) |
| **S2b** | serve 接线:overlay + `/api/resource-refresh` + 惰性低频队列 + SSE 推送 | serve.py | 端到端(假 runner)+ 一次真 a1 冒烟 |
| **S3** | chips 徽章/排序/灰化/新鲜度 tooltip/⟳ 按钮 | cockpit.html | 渲染快照 + 手验截图 |
| **S4** | 跃迁事件 + ack + 两种 band 提升 | sidecar+cockpit | 单测跃迁矩阵 + 手验 |

依赖:S2a←S1(identity);S2b←S2a;S3/S4←S2b。S1 可先行落地独立见效(去重收敛)。

## 8 — 风险与边界

- **a1 鉴权过期**:错误进 sidecar、UI 降级回会话文本态,永不阻塞渲染;
- **跨仓 404**(DD-026 已知):实查 404 反而是信号 —— 标记该 reconstructed url 可疑;
- **成本**:无常驻轮询、终态免查、每轮预算上限;a1 是本地 CLI,无 API 配额焦虑,
  但仍按上表节流(尊重内网服务);
- **不做**:流水线/CI 资源类型(步骤非落点)、评论级 watcher(DD-017 V2)、
  自动回复/自动合并(永远人批)。
