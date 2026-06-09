# claude-stray Prompt 清单(完整文案 · 中文翻译版)

> 本文件由代码库梳理生成,收录 claude-stray 所有发送给 LLM 的 prompt,
> 含场景说明与**逐字完整文案**。文案区块用 6 个反引号围栏包裹,内部原样保留
> Markdown / 代码 / XML 占位符。
>
> 注:本文件为**翻译参考版**,围栏内的 prompt 文案已译为简体中文;实际发送给 LLM 的仍是 PROMPTS-INVENTORY.md 中的英文原文。
>
> 生成自仓库 `prompts/` 目录与 `bin/` 源码。占位符约定:`<context>`、`<turns>`
> 等 XML 块在运行时由 `build_prompt()` 注入动态数据。

## 总览

claude-stray 的 AI 是一条**三层流水线** + 若干**派生分析**:

| 层 | Prompt | 文件 | 调用方 | 输出 | 预算/次 |
|---|---|---|---|---|---|
| Layer 1 | 单会话摘要 | `prompts/summarize-session.md` | `bin/summarize.py` | YAML frontmatter + Markdown | $0.50 |
| Layer 2 | 跨会话分类(三级层级) | `prompts/classify-cross-session.md` | `bin/classify.py` | 严格 JSON(mindmap v3) | $2.50 |
| 工具 | 任务去重合并 | `prompts/consolidate-tasks.md` | `bin/serve.py` | 严格 JSON 去重计划 | $0.20 |
| 派生 | 下一条消息建议 | `bin/serve.py` `_suggest_prompt()`(内联) | `bin/serve.py` | JSON 字符串数组 | $0.30 |
| 派生 | 每周工作总结 | `bin/derived/weekly_report.py`(内联) | 同左 | Markdown | ~$0.03 |
| 派生 | 挑选 3 个下一步重点 | `bin/derived/next_steps.py`(内联) | 同左 | 严格 JSON | $0.20 |
| 派生 | 仪表盘 20 条 tips | `bin/derived/tips.py`(内联) | 同左 | 严格 JSON | $0.15 |
| 派生 | 过劳关怀提醒 | `bin/derived/wellness.py`(内联) | 同左 | 严格 JSON | $0.10 |
| ⚠️ 遗留 | v1 分类(**已废弃,无任何引用**) | `prompts/classify.md` | — | — | — |

**通用机制**:所有调用都走 headless `claude --no-session-persistence -p`,
带 `--max-budget-usd` 上限与 `--disallowedTools`,默认模型
`CLAUDE_WORKTREE_MODEL`(`claude-haiku-4-5-20251001`)。`--no-session-persistence`
是为避免被 Claude Code 自身 session 持久化重新摄取而触发递归(历史上曾因递归烧到 $51)。

---

## 1. Layer 1 — 单会话摘要

- **场景**:对单条 Claude Code 会话生成稠密摘要,产出 YAML frontmatter + 6 个 H1 段落(资源/分支/文档产物、卡点、任务、封存片段等)。这是整条流水线的输入源。
- **文件**:`prompts/summarize-session.md`(418 行)
- **调用方**:`bin/summarize.py`(`PROMPT_FILE` @ line 51;`build_prompt()` @ 338–405 追加 XML 块)
- **运行时占位符**:`<context>` `<session_meta>` `<prior_tasks>` `<prior_sealed_segments>` `<turns>`
- **输出**:YAML frontmatter + Markdown 正文;`_guard_done_status()` 会机械纠正 done/active 状态
- **预算**:$0.50/次

### 完整文案

``````markdown
你正在为单条 Claude Code 会话生成摘要。你产出的摘要将作为约 200 份输入之一
喂给跨会话分类器,因此它必须**稠密、准确、且机器可解析**。

输出严格的 markdown,不要前言、不要后记,也不要在整体外面套代码围栏。

# 输入

prompt 正文中有三个 XML 块:

- `<context>` — `output_lang`、`now`(当前 ISO 时间戳)。
- `<session_meta>` — 一个包含机器可观测信号的 JSON 对象:
  `session_id`、`cwd`、`started_at`、`last_activity_at`、`user_turns`、
  `edits`(近期文件编辑,含 kind+ops)、`tools`(工具→次数映射)、
  `task_events`(若存在,为 TaskCreate/TaskUpdate 字符串)。
- `<turns>` — 本会话最近 N 轮 user 与 assistant 对话,按时间顺序排列,
  每轮标注为 `### user` 或 `### assistant`。

`<turns>` 块是你叙事的主要来源。`<session_meta>` 块是你的**机器事实**来源
(哪些文件被改动、用了什么工具、会话有多活跃)。

# 输出格式

恰好一个 YAML frontmatter 块(由 `---` 行界定 —— 切勿用 ```` ``` ````
作为 frontmatter 围栏;那会破坏下游解析器),其后紧跟六个 H1 段落,顺序如下。
即使某段为空也**不要跳过** —— 改写 "(无)"(中文)或 "(none)"(英文)。

```
---
session_id: <从 session_meta 逐字复制>
cwd: <逐字复制>
last_activity_at: <逐字复制>
user_turns: <逐字复制>
updated_at: <从 context.now 复制>
status_guess: active | paused | done | abandoned
next_step: 跑 daily 验证 tri 路由到 12222   # 见规则 14。一条具体的下一步动作,≤ 80 字符。无则省略。
awaiting_user: 确认是否接受仅兼容 3 个 _ALL ACL   # 见规则 14。仅当卡在等人时才写。否则省略。
artifacts:                                # 见规则 10。无则省略该键。
  - type: cr                              # cr|mr|pr|issue|deployment|doc|branch|tag|worktree|other  (不含 commit;doc=仅限外部 URL)
    title: HSF EagleEye 链路追踪修复       # ≤ 60 字符;对外部资源**必填且要有语义**(不能是裸 id)
    ref_id: "27369464"                    # 平台特定 id,可选
    url: https://aone.alibaba-inc.com/code/g/...?cr=27369464
    status: pending                       # 见规则 10 的枚举表
    last_mentioned_at: 2026-05-13T15:10:00Z   # ISO;不确定则省略
blockers:                                 # 见规则 11。无则省略该键。
  - 等 CodeOwner 评审通过
  - CI 失败：unit test 红
tasks:                                    # 见规则 12。无则省略该键。
  - title: 收集 EagleEye 数据样本           # ≤ 60 字符
    status: done                          # pending | done | cancelled
    evidence: 已上传至 /tmp/eagleeye-sample/ # 当 status != pending 时必填
  - title: 提交 Aone ISSUE
    status: pending
sealed_segments:                          # 见规则 13。除非有更早的子任务已封存,否则整体省略。罕见。
  - seg_id: linkify-error-message-url     # 该片段稳定的英文 kebab slug
    title: 错误消息 URL linkify             # output_lang,≤ 60 字符
    status: done                          # done | abandoned —— 仅终态
    summary: 把后端错误消息里的申请权限 URL 渲染成可点击链接，已合并上线  # ≤ 200 字符
    sealed_at: 2026-06-03T02:50:08Z       # ISO;该片段到达终态的时间
    artifacts:                            # 与顶层 artifacts 同结构(规则 10)
      - type: mr
        ref_id: "27752189"
        status: merged
    tasks:                                # 可选;属于该片段的 done/cancelled 任务
      - title: 将旧分支蓝色链接样式吸收进 Linkify 组件
        status: done
        evidence: commit ef2219c，MR 27752189 已合并
---

# 目标
用一两句话描述用户从根本上想做什么。即使会话演进也应站得住脚
(早期与后期的轮次对此应一致)。

# 当前状态
**截至最后一轮**工作进展到哪一步。要具体。"已定位根因
EagleEyeHttpHook 传错参；修复方案明确" 胜过 "继续调试中"。

# 已下的决定
以列表形式列出已做出且仍然有效的决定。每行 ≤ 80 字符。
- 采用 X 方案而非 Y（理由：…）
- 先做 A 再做 B

跳过 "用 git 提交" 这类通用决定。

# 产物
本会话中具体创建或大幅编辑的文件。
注明路径 + 类型。每行一个。
- /tmp/foo.md (created)
- src/Bar.java (edited)

只读式查看文件**不算**产物。

# 下一步
用户或 AI 明确说出的下一步具体动作。紧贴原意引用
或转述。如果会话在话还没说完时就结束、没有声明下一步,
写 "(无明确)" / "(none stated)"。

# 待解决
待回答的问题、卡点,或正在推进中的事项。每行一个。
若无待解决项,写 "(无)" / "(none)"。

```

(任务存放在 `tasks:` frontmatter 中 —— 见规则 12。正文不再
带 `# 任务` 段落:Layer 2 是从 frontmatter 结构化读取任务的,
因此 markdown 形式只会成为有漂移风险的死负担。)

# 规则

1. **最近一轮优先。** 当最新的 user 轮次扭转了工作方向,就描述**那个**
   方向。第一条 user prompt 以及任何旧的回顾文本都可能过时;不要让它们延续。

2. **status_guess 启发式**(拿不准时默认 `active`;`done`
   必须越过一道**很高**的门槛):
   - `active`:最新一轮显示工作仍在进行、有新决定、正在积极
     编辑 —— 或一项调查仍在收敛(已收集证据、有多个假设,
     但问题尚未被确凿回答)。
   - `paused`:最新一轮话说到一半、没有清晰的下一步,
     或 `last_activity_at` 距 `now` ≥ 3 天。
   - `done`:会话的**目标**确实已达成 —— 一项变更已发布
     **并且**已验证,或一个问题被**确凿回答** —— 且
     再无具体遗留。证据:用户收尾("ship it"、
     "merged"、"完成了"、"搞定"),或工作明确无歧义地完成。
     ⚠️ 仅仅**定位到根因 / 找到有力证据 / 收敛到几个假设的
     诊断不算 done** —— 确认*某事会发生* ≠ 确认*为什么*。如果
     `下一步` 段落会列出任何具体的后续动作,或 `待解决`
     非空,状态就是 `active`(或 `paused`),**绝不是 `done`**。这三项
     —— `status_guess`、`下一步`、`待解决` —— 必须彼此一致。
   - `abandoned`:最新一轮显示出沮丧或放弃 —— "算了"、
     "this isn't working, let me try something else",且之后无后续。

3. **输出语言。** 对所有自然语言内容应用 `output_lang`,无论
   它在正文还是 frontmatter 中。技术
   术语 —— `HSF`、`MR`、`IP`、`span`、`OAuth`、`prompt`、`cache`、
   文件路径、标识符 —— 即便在中文模式下也保留英文。

   - **正文**(每个 H1 段落):用 `output_lang`。
   - **frontmatter 中的自然语言字段**(用 `output_lang`):
     - `tasks[].title`、`tasks[].evidence`
     - `artifacts[].title`
     - `blockers[]` 字符串
   - **frontmatter 中的机器字段**(无论 `output_lang` 为何,
     始终用英文/原始值):
     - `session_id`、`cwd`、`started_at`、`last_activity_at`、
       `updated_at`、`user_turns`、`status_guess`
     - `artifacts[].type`、`artifacts[].url`、`artifacts[].status`、
       `artifacts[].ref_id`、`artifacts[].last_mentioned_at`
     - `tasks[].status`

   在中文 locale 的摘要里混入英文 title 会破坏下游
   基于 slug 的去重(同一任务最终会变成两条:一条中文、
   一条英文)。title 始终遵循 `output_lang`。

4. **不要废话。** "继续推进中" / "the user is using Claude Code" 都是
   禁止的。每句话都必须携带具体信号,是别的
   会话摘要不会也有的。

5. **不要编造。** 如果某事在输入中没有依据,写
   "(无)",而不是捏造进展。

6. **Tasks(proposed)很特殊。** 只反映本会话的
   工作,而不是整个项目的全貌。一次 10 分钟的调查
   会话可能提出 2-3 个任务;一次多小时的构建会话可能
   提出 6-8 个。不要凑数。

7. **节制引用。** 当引用有帮助时,只保留实际 prompt 或
   回复中的一短行。不要粘贴整段。

8. **边界情况:闲聊会话。** 如果会话确实是
   空操作("你好" / "继续" / 没有任何实质内容),则除
   `目标` 和 `当前状态` 外的所有段落都可以为 `(无)`,且 `status_guess` 应视情况
   为 `paused` 或 `abandoned`。

9. **边界情况:工具密集型自动化。** 如果会话跑了大量
   工具工作但用户给出的叙事很少,从
   `tools` + `edits` 信号推导目标。不要仅仅因为轮次
   文字稀少就写 "(无)"。

10. **artifacts:提取资源,而非步骤。** 资源是一个
    持久的、可外部寻址的句柄,用户会去跟进
    或交接 —— 它必须 (a) 有外部地址(URL 或一个能
    解析为 URL 的 ID),(b) 是结果而非中间步骤,
    (c) 存在于会话之外(在服务器上 / 作为稳定的工作
    锚点)。遍历 `<turns>`,把每一个不同的资源都拉出来。
    artifact 类型分两组:

    - **外部资源**(跟进端点):`cr` `mr` `pr`
      `issue` `deployment` `doc` `other`。
    - **代码位置**(重新进入工作的锚点):`branch` `tag`
      `worktree`。

    **不要发出以下内容 —— 它们是噪声,不是资源:**
    - **`commit`** —— 一个 commit SHA 是内部*步骤*,不是
      跟进端点。绝不发出 `type: commit`。(commit 可以
      作为任务的*evidence*出现;那没问题 —— 它只是不算
      artifact。)
    - **本地文件路径** —— 你编辑过的文件路径不是
      资源:没有外部地址,而且一旦切分支它就过时了。
      绝不把文件路径作为 artifact 发出。这
      也包括仓库本地文档 —— 见下文 `doc`。

    **URL 模式表 —— 仅供识别,不用于构造。**
    这些模式帮你在 `<turns>` 中*识别*出 URL 并分类
    其 `type`。你绝不可用它们从
    一个纯 ID 数字去合成 URL。如果 URL 没有在对话中
    逐字出现,省略 `url` 字段(见下文硬规则)。

    | type | URL 提示或模式 |
    |---|---|
    | `cr` | `aone.alibaba-inc.com/.../codereview/...`、`?cr=<id>`、`code.aone.alibaba.../cr/<id>` |
    | `mr` | `gitlab.*/-/merge_requests/<id>`、`gitlab.alibaba-inc.com/.../merge_requests/<id>`、`code.alibaba-inc.com/<group>/<repo>/codereview/<id>` |
    | `pr` | `github.com/<org>/<repo>/pull/<id>` |
    | `issue` | `github.com/<org>/<repo>/issues/<id>`、Aone 工作项:`aone.alibaba-inc.com/.../task/<id>`、`project.aone.alibaba-inc.com/.../req/<id>`(需求)、`.../bug/<id>`、`.../task/<id>`、`.../story/<id>`、`.../workitem/<id>`、JIRA 风格 `[A-Z]+-\d+` |
    | `branch` | `git checkout <name>`、计划或 PR url 中提到的 `branch=<name>` |
    | `worktree` | 工作所在的某个 `git worktree` 目录(被声明为 worktree/checkout 位置的绝对目录路径)。不是任意被编辑的文件 —— 只是 worktree/checkout 根。把目录路径放进 `ref_id`(它没有 URL)。 |
    | `tag` | 作为发布提及的 `v\d+\.\d+\.\d+` |
    | `deployment` | "上线 / 灰度 / publish / deploy" + 一个目标环境 |
    | `doc` | **仅限外部文档 URL** —— `yuque.com/...`、`confluence/...`、`notion.so/...`、内部 wiki URL。像 `docs/xxx.md` 这样的仓库本地路径**不是** doc artifact(它是本地文件路径 —— 不要发出)。 |
    | `other` | 其他任何带外部 URL、值得追踪的东西(如某个论坛帖子) |

    按 type 区分的 `status` 枚举:

    | type | 可能的 status 取值 |
    |---|---|
    | cr/mr/pr | `pending`(待评审)、`approved`、`merged`、`closed`、`unknown` |
    | issue | `open`、`closed`、`wontfix`、`unknown` |
    | branch | `active`、`merged`、`stale`、`unknown` |
    | worktree | `active`、`removed`、`unknown` |
    | tag | `released`、`unknown` |
    | deployment | `pending`、`live`、`rolled-back`、`unknown` |
    | doc/other | `unknown` |

    artifacts 的硬规则:
    - **绝不合成 URL。** `url` 字段只有在
      确切的 URL 字符串逐字出现在 `<turns>` 中时才有效。如果用户
      只提到一个数字(如 "MR 27499051 已合并")而没有
      粘贴链接,**不要**根据模式表去构造 URL。
      发出带 `ref_id: "27499051"` 和 `type: mr` 的条目,但
      完全省略 `url` 字段。上面的模式表是用于
      识别用户粘贴的 URL,不是用于构造新的。
    - **但只要 URL 确实存在就务必逐字带上。** 如果
      该 artifact 的真实 `http(s)://…` 链接出现在 `<turns>` 中,
      就把它放进 `url` —— 即使它的路径不匹配上表中任何
      一行(该表只是非穷尽提示)。例如某个 Aone
      需求 `https://project.aone.alibaba-inc.com/v2/project/<pid>/req/<id>`
      → `type: issue`、`ref_id: <id>`、`url: <那条完整链接>`。不要
      仅因链接形状陌生就丢弃它。
    - **每条最少要素:`type` + `status` + (`url` 或 `ref_id`)。**
    - **外部资源**(`cr`
      `mr` `pr` `issue` `deployment` `doc` `other`)**必须有语义化的 `title`**。title 是
      用户在 cockpit 里读到的内容 —— 像 "CR 27369464" 或
      "MR 27752189" 这样的裸 id 单独看毫无用处。要从对话
      上下文写一段简短的人类可读
      描述,说明*这个资源是什么*(例如 `HSF EagleEye 链路追踪修复`,
      而不是 `27369464`)。≤ 60
      字符,用 output_lang。只有当 transcript 确实没给出任何
      线索表明它是关于什么的时,你才可退回到仅 id。代码位置类型
      (`branch` `tag` `worktree`)不需要 title —— 它们的名字/路径
      本身就有意义。
    - **`status` 取自最近一次谈到它的轮次。** 如果用户在 5 轮前说
      "CR passed review" 且之后没有更新,status 是
      `approved`(不是 `merged`)。不要推断超出证据的范围。
    - **去重。** 若两者都有 `url` 则先按 `url`;否则按
      (`type`、`ref_id`)。同一 artifact 被提及 3 次 = 一条。
    - **`last_mentioned_at`** = 最近一次引用此 artifact 的
      那一轮的 ISO 时间戳。不确定则省略该键。
    - **不编造。** 不要仅因为提到了 "CR 评审" 而没有数字
      就发出一条 CR 条目。只有具体的 URL/ID 才算数。
    - **每会话上限 12 条。** 如果你不知怎么就超了,丢弃信号最低
      的那些。

    如果会话确实零个可追踪的 artifact,完全省略
    `artifacts:` 键(**不要**写 `artifacts: []` —— yaml
    库会噎住)。

11. **blockers:捕获正在拖住用户的东西。** 一个
    blocker 是一个具体的外部依赖或开放问题,它**截至
    最新一轮**阻止工作推进。

    格式:简短自由文本字符串,每个 blocker 一条,≤ 80 字符。
    算数的例子:
    - 等 CodeOwner @bowen 评审
    - 等 CI 红：HSFEagleEyeIntegrationTest 跑不过
    - 等 dev_test_a 环境恢复（运维处理中）
    - 待 user 给 prod cluster 访问权限

    blockers 的硬规则:
    - **外部信号。** "等 X 通过 / 等 X 回复 / 等 X 恢复" 模式。
      像 "我还要写测试" 这样的内部待办**不是** blocker(那些放进
      `# 下一步` 或 `# 待解决`)。
    - **最近一轮优先。** 如果用户后来说了 "CI 终于过了",就
      移除 "等 CI" 这个 blocker。
    - **具体的谁/什么。** "等评审" → 写明等谁 / 哪个 CR。
    - **去重。** 同一 blocker 被多次提及 = 一条
      字符串。
    - **上限 5 条。**

    若无 blocker,完全省略 `blockers:` 键。

12. **tasks:本会话对该项目任务清单的贡献。**
    最多 8 条。每个任务是一个独立的、复选框形态的条目,带
    三态 status:`pending`(进行中)、`done`(已发布),或
    `cancelled`(不再相关 —— 已合并、被砍、被替换)。

    格式(`tasks:` frontmatter 键下的 YAML 列表):

    ```yaml
    tasks:
      - title: <≤ 60 字符,陈述句>
        status: pending | done | cancelled
        evidence: <≤ 80 字符,当 status != pending 时必填>
    ```

    tasks 的硬规则:
    - **PRIOR 的 title 神圣不可侵犯 —— 逐字节复用。** 当
      输入有 `<prior_tasks>` 块时,其中每个条目都是一个
      已经挂在本会话项目卡上的任务 title。
      如果你的 transcript 分析会产出一个在
      概念上与某个 PRIOR title 相同的任务 —— **即使
      换种措辞、换种语言、换种详略程度或加个前缀会
      感觉更自然** —— 你也**必须**把那个 PRIOR title 逐字
      复制进你的 `tasks:` frontmatter。不要翻译(`重构授权链`
      ↔ "Refactor authorization chain")。不要重打标签(`[F1-body] X`
      ↔ `X`)。不要扩写(`实现 service doc MVP` ↔ `实现 service
      doc MVP with flag-based slicing`)。不要概括。只有当工作
      确实是一个*不同的*任务、而非同义说法时,才发出
      一个*不同的* title。Layer 2 按精确 slug 相等去重;
      每一个改写过的变体都会变成一条新的永久任务条目,
      需要用户手动删除。
    - **非 pending 状态须有证据支撑** —— 对于 `status: done`,
      引用一次 edit / merge / "完成" / "shipped" / task_events.completed。
      对于 `status: cancelled`,引用一次用户改向("算了 / 不做了 /
      合并到 X / 改方案")。在 `evidence:` 里写一句简短转述。
    - **`cancelled` 用于 AI 可见的放弃**,而不是用于 "我有阵子
      没看的任务"。只有当某一轮或某个下游 artifact 明确
      表示该任务不再被需要时才发出 `cancelled`。拿不准时,
      保持 `pending`。
    - **不凑数。** 一次 10 分钟的调查会话可能提出
      2-3 个任务;一次多小时的构建会话可能提出 6-8 个。
    - **上限 8 条。** 如果工作明显跨度更大,挑出最
      承重的 8 个。

    如果会话没有清晰的任务形态贡献,完全省略
    `tasks:` 键。(不要写 `tasks: []`。)

13. **sealed_segments:拆分出一个更早的、已完成的子任务(罕见)。**
    一个长会话可能随时间转换主题 —— 完成一件事,然后
    转去做别的。默认一个会话映射到**一件**
    工作,所以**默认完全省略 `sealed_segments` 键**。仅当
    以下三点**全部**成立时才发出它:

    1. 一个更早的、明显有别的子任务到达了**终态**
       —— 已发布/已合并/已放弃 —— 由一个**具体
       artifact** 佐证(一个已合并的 MR/PR/CR、一个已推送
       **且**其分支已合并的 commit,或一次明确的放弃 "算了 / 不做了")。
       含糊的 "看起来做完了"**不够**。
    2. 会话随后**转向了一个明显不同的当前
       焦点** —— 不同目标、不同文件/子系统 —— 而**不是**
       已封存工作的延续或后续。
    3. 这次转向在 `<turns>` 中明确无歧义,不是一次瞬时的离题。

    当你封存时:
    - **顶层** frontmatter(`status_guess`、`artifacts`、
      `tasks`)以及全部六个正文段落只描述**当前**
      (较晚)的焦点。
    - 每个终态的较早子任务放进 `sealed_segments`,带
      自己的 `seg_id`(稳定英文 kebab slug)、`title`、`status`
      (仅 `done`|`abandoned`)、`summary`、`sealed_at`,以及
      锚定它的 `artifacts`/`tasks`。把那些 artifacts/tasks
      从顶层列表**移出**到该片段中 —— 不要在
      两处都列。
    - **保守门槛:** 拿不准时,**不要**封存。封得不够是
      无害的(旧行为);一个错误封存的片段会铸出一张幻影
      "done" 卡,用户得去删它。

    **逐字重新发出已封存片段(向前结转)。** 当输入
    有 `<prior_sealed_segments>` 块时,其中每个条目都是你在
    上一次运行中封存的片段。你**必须逐字节**重新发出每一个
    (`seg_id`、`title`、`status`、`summary`、`sealed_at`、`artifacts`)——
    不要重新翻译、重新 slug、重新润色、重新排序或丢弃它。一个片段
    一旦封存就不可变。只有当此后又有*进一步*的转向封存了*另一个*
    明显不同的工作时,才**新增**一条 `sealed_segments` 条目。

14. **next_step 与 awaiting_user —— cockpit 的两个注意力信号。**
    它们喂给一个注意力仪表盘,其全部职责就是 "什么需要我,以及
    我怎么跳回去"。保持它们干脆而诚实。
    - **`next_step`**:这项工作的**一个**具体下一步动作 —— 接下来应当
      发生什么(≤ 80 字符,祈使句)。优先写可操作的,例如
      "跑 daily 验证 tri 路由到 12222" / "等 MR 27752189 评审" / "查旧 7 个 ACL
      的持有人数"。这是 `# 下一步` 的简短结构化形式;保持它们
      一致。只有当工作真正完成、再无下一步时才省略该键。
    - **`awaiting_user`**:当工作**卡在等人**时发出 —— 球
      在用户那边,工作在他们行动之前无法推进。
      这涵盖两种情形:
      (a) **AI 需要的一个决定/答复/批准** —— 例如 "确认是否接受仅兼容
          3 个 _ALL ACL" / "选 A 方案还是 B 方案";以及
      (b) **只有用户能在本会话之外执行的一个交接动作** ——
          AI 已做完自己那部分,下一步是一个它自己无法完成的手动
          人工步骤:跑一条 prod/DB 平台 SQL、点击 deploy/发布、merge
          /approve 一个 CR、在控制台翻一个配置开关等。例如 "去数据库
          平台执行 ALTER 发布 step 3" / "在发布单点确认上线" / "合并 CR 27724957"。
      判定标准是**谁来执行下一步动作**:如果只有人能(或
      必须由人来决定),就用那条具体的一句话发出 `awaiting_user`。如果 AI
      下一轮自己就会做(跑测试、grep 代码、写补丁),就**不要**
      发出 —— 那是普通的 `next_step`。这是 cockpit 中最强的信号
      (驱动 "需要你" 栏),所以不要为 "我可以问但
      不必问" 或例行 FYI 而发出它。当下一步确实是一个手动的
      用户动作时,即使 AI 从未真正提过问题,它也算 awaiting_user。如果你
      发出 `awaiting_user`,`status_guess` 必须为 `active`
      (不是 `done`);且 `next_step` 通常应回显同一个交接动作。

``````

---
## 2. Layer 2 — 跨会话分类(三级层级)

- **场景**:把多条会话摘要聚合成 workspace → initiative → task 三级层级 mindmap,负责状态衰减、产物聚合、任务管理、层级 `level`/`parent_thread_id` 维护,尊重删除。
- **文件**:`prompts/classify-cross-session.md`(493 行)
- **调用方**:`bin/classify.py`(`PROMPT_FILE` @ line 54;`build_prompt()` @ 1112–1154)
- **运行时占位符**:`<context>` `<prior_mindmap>` `<deleted_ids>` `<hot_summaries>`
- **输出**:严格 JSON(mindmap schema v3)
- **预算**:$2.50/次(可处理最多 120 条 hot summaries)

### 完整文案

``````markdown
你正在进行跨会话分类。请把会话摘要分组到若干个 "initiatives"(逻辑上的
工作单元)中,与上一轮保持连续性,并尊重用户设定的删除标记(tombstone)。

每条会话摘要都是一份你可以信任的结构化 markdown —— Layer 1 已经提取出了
叙事。**你的工作是分组与保持连续性,而不是从原始对话中做综合。**

输出严格的 JSON。不要代码围栏,不要前言,不要后记。

# 输入(XML 标签块)

- `<context>` —— `output_lang`(zh-CN | en)以及 `now`(ISO 时间戳)。
- `<prior_mindmap>` —— 上一轮的 `mindmap.json`。首次运行时可能不存在。
- `<deleted_ids>` —— JSON `{"deleted_initiative_ids": [...]}`。可能不存在。
- `<hot_summaries count="N">` —— N 条会话摘要,每条都是一份完整的
  markdown 文件,带有 YAML frontmatter(session_id、cwd、
  last_activity_at、user_turns、updated_at、status_guess)以及七个
  H1 章节。这些是过去 48 小时内活跃的会话。

**不在 `<hot_summaries>` 中、但在 `<prior_mindmap>` 中被引用的会话属于
"冷"会话。它们仍然存在;你必须在输出中保留它们的 initiatives,且只能做
受限的修改(见规则 §5)。**

# 输出 schema

```
{
  "schema_version": 3,
  "generated_at": "<context.now>",
  "workspaces": [
    {
      "name": "<short, usually folder name>",
      "cwd": "<primary cwd>",
      "last_activity_at": "<max over its initiatives>",
      "initiatives": [
        {
          "id": "<stable slug, English/kebab-case>",
          "name": "<human-readable in output_lang>",
          "status": "active | paused | done | archived",
          "level": "thread | card | chip",          // DD-014; see §8
          "parent_thread_id": "<id of a sibling thread> | null",  // DD-014
          "summary": "<1-2 sentences: what this initiative is about>",
          "progress": "<1-2 sentences: current state>",
          "tasks": [
            {
              "id":  "<optional — REUSE PRIOR's id when continuing a task>",
              "title": "<≤80 chars>",
              "status": "pending | done | cancelled",
              "evidence": "<optional — required when flipping
                           PRIOR.status pending→done OR pending→cancelled
                           (see §7d), ≤80 chars>",
              "terminal_at": "<set by post-process; do not emit>"
            }
          ],
          "sessions": ["<full UUID>", ...],
          "linked_cwds": [],
          "last_activity_at": "<max over its sessions>",
          "artifacts": [                          // omit key if empty
            {
              "type": "cr|mr|pr|issue|branch|commit|tag|deployment|doc|other",
              "title": "<≤60 chars or null>",
              "ref_id": "<platform id or null>",
              "url": "<exact URL from a hot summary; omit if none>",
              "status": "<see Layer 1 enum>",
              "last_mentioned_at": "<ISO or null>"
            }
          ],
          "blockers": ["<≤80 chars>", ...]        // omit key if empty
        }
      ]
    }
  ]
}
```

# 硬性规则(违反 = bug)

## §1 —— `session_id` 是完整 UUID

始终复制完整 UUID。切勿截断为 8 个字符。错误:
`"sessions": ["cbbeb23c"]`。正确:
`"sessions": ["cbbeb23c-b6f9-4eb4-926e-7e4046c856d4"]`。

## §2 —— 逐字复用 PRIOR 的 id

对于任何工作得以延续的 initiative,请原样使用 PRIOR_MINDMAP 中已有的
`id`。即使 `name` 应当被润色,也不要重命名 id。按概念上的同一性匹配,
而非精确的名称。

## §3 —— DELETED_IDS 是删除标记(tombstone)

切勿在输出中包含 `deleted_initiative_ids` 中的任何 id。即使某条 hot
会话天然属于那个 initiative,你也必须:要么(a)跳过该会话,要么(b)
在另一个 id 下创建一个全新的 initiative。绝不复活已删除的 id。

## §4 —— 终态状态是单调的(AI 侧)

如果 PRIOR 中某任务的 `status: done` 或 `status: cancelled`,输出中
同一任务必须保持该状态。绝不翻转 `done → pending`、
`cancelled → pending`,也不在 `done` 与 `cancelled` 之间互转。(即使你
认为原先的终态状态是错的。)只有用户能复活一个终态任务 —— 那是通过
`user_overrides.json` 里的 `task_toggles` 实现的,而不是通过你的输出。

## §5 —— 冷 initiative 规则 ⚠️ 关键

如果一个 initiative 存在于 PRIOR_MINDMAP 中,但**它的 `sessions[]`
没有一个出现在 HOT_SUMMARIES 中**,那么它就是**冷**的。

对于冷 initiatives,你只能修改:
- `status`(按下方的衰减规则)
- `last_activity_at`(仅在需要时;通常保留 PRIOR 的值)

你绝不能修改(必须与 PRIOR 逐字节相同):
- `name`
- `summary`
- `progress`
- `tasks`(整个数组、每一个条目,包括顺序)
- `sessions[]`
- `linked_cwds[]`
- `id`
- `artifacts[]`(整个数组,逐字节相同)
- `blockers[]`(整个数组,逐字节相同)

不允许 "小幅润色"。不允许 "我就清理一下措辞"。本规则是绝对的。

**冷 initiatives 的状态衰减**,基于 `last_activity_at` 相对于 `now`:

| 距 last_activity_at 的时间 | 新状态 |
|---|---|
| < 3 天 | 保持 `active`(不变) |
| 3 到 14 天 | `paused` |
| > 14 天,且 PRIOR 中无恢复信号 | `archived` |
| 已经是 `done` | 保持 `done` |

## §6 —— Workspace 决策

- **单 cwd 的 initiative**:workspace 名称 = 该 cwd 的文件夹 basename
  (例如 `/Users/bby/Code/hsf/hsfops` → workspace `hsfops`)。
- **多 cwd 的 initiative**:将 `linked_cwds` 设为次要的 cwds。
  按**语义归属**而非活动量来选择 workspace:
  "这项工作从根本上是关于哪个领域的?"
  例如:一项触及 frontend + backend + skill 文件的 Claude Skill 工作
  归属于 workspace `skills`,即使更多 commit 落在 frontend 仓库里。

## §7 —— HOT initiatives 的状态

> **注(机械安全网)。** classify.py 中的后处理
> `enforce_hot_initiative_status` 会对任何 hot initiative 确定性地应用
> 下方规则,**无条件覆盖你的输出**。所以你为 hot inits 给出的 `status`
> 仅供参考 —— 后处理才是真相之源。当某条 hot 会话已经重置了局面时,不要
> 把 `PRIOR.status = done` 延续下来;后处理会抓住你,并把它翻回
> `status_guess` 所说的值。仍然给出你最准确的判断,但要知道确定性版本
> 会胜出。

对于确实有 hot 会话的 initiatives:
- 阅读每条 hot 会话的 frontmatter `status_guess`。
- 如果最近的(按 `last_activity_at`)会话说 `done`,就把 initiative 设为
  `done`。如果任一会话说 `paused` 或 `abandoned`,倾向于 `paused`,
  除非另有会话为 `active`。否则为 `active`。

## §7a —— 聚合 artifacts(仅 hot initiatives)

> **注(机械安全网)。** classify.py 中的后处理 `aggregate_artifacts`
> 现在会确定性地从 PRIOR + hot 会话 frontmatter + 你的输出做并集/去重。
> 你**无法**通过省略来删除某个 artifact —— 后处理会把你丢掉的任何东西
> 重新加回来。一旦某个 artifact 的状态达到 `merged|closed|wontfix|
> released|stale|rolled-back|pushed`,它就被**冻结**,无法回退。身份字段
> (`type`、`ref_id`、`url`、`title`)也会被冻结为 PRIOR + hot 会话中
> 最早的非空值。只有用户,通过 `user_overrides.json` 里的
> `hidden_artifacts`,才能从某个 initiative 移除一个 artifact。
>
> 仍然请按下方规则尽力给出 `artifacts[]`;后处理会信任你对真正新增条目
> 以及对状态向前推进的输出,但不会兑现删除或回退。

对于至少有一条 hot 会话的 initiative,将 `artifacts[]` 构建为以下两者
的并集:

1. PRIOR.initiative.artifacts 中已有的 artifacts(若有),以及
2. 属于该 initiative 的每条 HOT 会话的 `artifacts:` frontmatter。

去重规则:

- **当两个条目都有 `url` 时,主键是 `url`。** 否则回退到
  (`type`、`ref_id`)。同一个 artifact → 一个条目。
- **绝不合成 URL。** 如果某条 hot 摘要的 artifact 只有 `ref_id`
  (没有 `url`),就在输出中保持原样 —— 不要试图用 ref_id 和模式表
  构造出一个 URL。(Layer 1 prompt 有同样的规则。URL 模式表是用来在
  对话记录中识别 URL 的,不是用来构造 URL 的。)
- **`url` 字段如果存在,必须非空,且以 `http://` 或 `https://` 开头。**
  如果否则你只会给出一个空字符串,那就省略该键。
- **状态:最近者胜、终态单调。** 使用 `last_mentioned_at` 更近的那个
  来源的 `status`。如果某条 hot 会话显示同一 artifact 为
  `status: merged` 而 PRIOR 显示 `pending`,新状态就是 `merged`。
  **绝不**把终态状态回退到 open 状态 —— 那是后处理的不变式,如果你尝试,
  你的输出会被钳制。
- **Title/ref_id**:优先非 null,然后优先最近一次提及。
- **last_mentioned_at**:所有来源的最大值。
- **每个 initiative 上限 20 个条目。** 如果超过,先丢弃
  `last_mentioned_at` 最旧的。
- **顺序**:按状态优先级排序(pending|open > approved > merged
  > closed > unknown),然后按 `last_mentioned_at` 降序。

如果 PRIOR 和 hot 会话产出的 artifacts 都为零,就完全省略
`artifacts` 键(不要给出 `[]`)。

## §7b —— 聚合 blockers(仅 hot initiatives)

对于至少有一条 hot 会话的 initiative,将 `blockers[]` 构建为属于它的
每条 HOT 会话的 `blockers:` 的并集。

- **去重**:相同或近乎相同的字符串只计一次。如果两个 blocker 仅在
  大小写/空白上不同,视为相同。
- **已解决的 blockers**:如果该 initiative 中**最近的那一条** hot 会话
  没有提到某个 blocker(字符串匹配)且该会话的 `# 当前状态` 提到了解决
  ("CI 通过 / approved / 已 merge"),就丢弃该 blocker。否则保留。
- **上限 8 个条目**。先丢弃最长的字符串。

如果为空,省略 `blockers` 键。

## §7c —— 聚合 tasks(仅 hot initiatives)

**从你的视角看,tasks 是只追加的。** 你可以添加新任务(带 hot 摘要
证据),也可以把某任务的 `status` 从 `pending` 翻转为 `done` 或
`cancelled`(带 §7d 证据)。你**不能**丢弃任务、隐藏任务,或收缩任务
列表。任务离开一个 initiative 的唯一途径是用户在 UI 中点击 🗑️ ——
那走的是 DELETED_IDS,绝不是你的输出。

对于每个 hot initiative,你给出的 `tasks[]` 必须包含:

1. **该 initiative 的每一个 PRIOR 任务** —— 全部延续下来,无论其
   `status` 为何,即使没有任何 hot 摘要提到它们。它们代表已被接受的
   决定 / 工作计划;你无权撤销。
2. **来自 hot 会话摘要的新任务** —— 该 initiative 的 `sessions[]` 中
   每条会话都有自己的 `tasks:` frontmatter;添加任何尚未在 PRIOR 中
   出现的。
3. **PRIOR 的延续** —— 对于被重新描述的 PRIOR 任务(可能被改写措辞或
   翻译),给出它时要带上其 PRIOR 的 `id` 字段,以便后处理把它识别为
   同一任务(而不是在一个新 slug 下插入一个重复项)。

硬性规则:

- **复用 PRIOR 的 `id`**,当某条 hot 摘要的任务在语义上与某个 PRIOR
  任务相同时。改写过的标题、翻译(中文 ↔ English),或扩写的措辞,只要
  概念上的动作相同,都算 "相同"。
- **终态状态是单调的**(§4):一旦某任务在 PRIOR 中为 `done` 或
  `cancelled`,在输出中就保持原样。即使你忘记给出,后处理也会保留终态
  状态。
- **没有可见上限。** 给出每一个 PRIOR 任务,加上每一个新的 hot 摘要
  任务。UI 会把已完成/已取消的任务内联折叠,所以数量是廉价的。
- **输出的 `tasks[]` 数量 ≥ PRIOR 的 `tasks[]` 数量。** 数量缩小是
  你试图丢弃某任务的标志性信号 —— 后处理会检测到并拒绝写入。

如果 PRIOR 和任何 hot 摘要都没有该 initiative 的任务,就完全省略
`tasks` 键(不要给出 `[]`)。

## §7d —— 依据 hot 证据把 PRIOR 的 pending 任务翻转为终态状态

对于 hot initiative 中每个 PRIOR `status: pending` 的任务,检查 hot
摘要的内容(它们的 `# 当前状态` / `# 已下的决定` / `# 产物` 章节,
加上它们的 `tasks:` frontmatter),并判断该具体任务现在是否已成终态
—— 要么 **done**,要么 **cancelled**。

### Done

某个 PRIOR 任务 X 只有在 hot 摘要明确说明相应工作已交付时才算 **done**
—— MR 已 merge、功能已部署、测试通过,或有明确的 "X 完成 / done /
shipped" 措辞且毫不含糊地指向 X(或一个明确的转述)。像 "完成了" 这样
没有指代对象的孤立词不算数。

### Cancelled

某个 PRIOR 任务 X 在 hot 摘要明确说明该工作被放弃、推迟,或被并入别的
东西时算 **cancelled**:
- "算了 / 不做了 / 改方案",且 X 有清晰的指代
- "合并到 <other task>" —— X 已被并入另一个 initiative 任务;存续的
  任务继续,X 变为 cancelled,带
  `evidence: "merged into <other task title>"`
- "scoped out / dropped / redirected" —— 最新一轮中明确的重定向

Cancellation 也处理 "重复合并" 的情形:如果两个 PRIOR 任务描述的是
同一概念上的工作(轻微的措辞偏移,逃过了基于 slug 的去重),你可以保留
一个,并把另一个标记为 `cancelled`,带
`evidence: "merged into <surviving title>"`。

### 如何给出

无论标记 `done` 还是 `cancelled`:
- 为该任务使用 PRIOR 的 `id`(以便后处理把它识别为延续,而非新任务)
- 把 `status` 设为新的终态值
- 添加一个 `evidence` 字段:≤80 字符,简短的转述或来自 hot 摘要的简短
  引用,说明 WHY(为什么)。这会成为 UI tooltip 中的审计记录。

**如果证据有歧义,就不要翻转。** 终态单调使得翻转从用户的正常流程看是
不可逆的。过于急切地完成或取消会让用户面对被误述的任务,他们之后还得
手动反向切换。拿不准时,保持 `pending`。

示例(done):
- PRIOR: `{"id": "implement-online-offline-is-online-commands",
           "title": "Implement online/offline/is-online commands",
           "status": "pending"}`
- Hot 摘要的 # 当前状态: "三个命令 (online/offline/is-online)
  已实现完毕,MR 27411369 已合并。"
- → 给出 `{"id": "implement-online-offline-is-online-commands",
            "title": "实现 online/offline/is-online 命令",
            "status": "done",
            "evidence": "MR 27411369 已合并,三个命令实现完毕"}`

示例(cancelled / merged):
- PRIOR: 两个任务: `{"id": "fix-eagleeye-trace", "title": "修复
  EagleEye 链路追踪"}` 与 `{"id": "patch-eagleeyehttphook",
  "title": "Patch EagleEyeHttpHook parameter"}` —— 同一工作。
- Hot 摘要的 # 已下的决定: "走 EagleEyeHttpHook 参数补丁方案"
- → 把 `patch-eagleeyehttphook` 保持为 `pending`;给出
  `{"id": "fix-eagleeye-trace", "status": "cancelled",
    "evidence": "merged into Patch EagleEyeHttpHook parameter"}`

## §8 —— `level`:thread / card / chip(DD-014)

> **注(机械覆盖)。** classify.py 中的后处理 `enforce_level_ceiling`
> 会用一个纯粹从 initiative 自身信号(session 数、task 数、artifacts、
> blockers)推导出的值**覆盖**你给出的 `level`。AI 的给出仅供参考,通常
> 会被忽略 —— 首次真实数据的 v3 运行中,AI 把每个 initiative 都声明为
> `thread`,被机械层纠正了。为叙事一致性给出一个合理的值,但别指望它能
> 一路存活到 dashboard。

每个 initiative 携带一个层级标签,用于塑造它在 dashboard 上的渲染。
根据下方信号,选择与该 initiative 表现出的分量相匹配的值。

| level | 何时选择 |
|---|---|
| `thread` | 跨多会话的脉络(`len(sessions) ≥ 3`)或可观的任务列表(`≥ 8` 个任务)或明显是一个长期运行、承载过多个不同工作单元的主题。 |
| `card`   | 默认值。一个有实质内容的单一工作单元:一次专注的会话、一个有意义的目标、一些任务或产物。 |
| `chip`   | 确实很小。1 个会话、≤ 5 个用户回合、≤ 1 个任务、无产物、无 blockers、无值得记录的决定。一次快速查询或一次性问题,不配拥有一张完整的卡片。 |

`level` 的硬性规则:
- **PRIOR 是下限(floor)。** 如果 PRIOR 说 `card`,绝不给出 `chip`。
  如果 PRIOR 说 `thread`,绝不给出 `card` 或 `chip`。你若尝试降级,
  后处理会恢复 PRIOR。
- **首轮 chip。** 对于不在 PRIOR 中的 initiative,无条件给出 `chip`
  —— 即使信号暗示 `card`。后处理层也会强制这一点;你提前认同,这样
  diff 更干净。
- **晋升需要证据。** 一个 `chip` 只有在新鲜的 hot 会话信号真正壮大了
  该 initiative(新任务、新产物、更多回合)时才变成 `card`。一个 `card`
  只有在该 initiative 跨越 3 个以上会话或积累了可观的任务列表时才变成
  `thread`。
- **不降级。** AI 绝不给出比 PRIOR 更小的 level。只有用户,通过 UI
  操作,才能降级。后处理会回退。

## §9 —— `parent_thread_id`:可选的 thread 归属

当一个 initiative 是 `level: card` 或 `level: chip`,且概念上属于
**同一 workspace** 中某个兄弟 `level: thread` initiative 时,把
`parent_thread_id` 设为那个 thread 的 `id`。否则给出 `null`。

硬性规则:
- 只能指向一个同样在你输出中、`level: thread`、且在同一 workspace 中的
  initiative。不允许跨 workspace 链接;后处理会清除它们。
- 一个 `level: thread` 的 initiative 必须有 `parent_thread_id: null`
  —— thread 本身就是层级的顶端。
- 一旦在 PRIOR 中设定,`parent_thread_id` 是稳定的:AI 只有在 thread
  本身被移除,或该归属明显不再合适(某条 hot 会话已把工作转移到一个
  不同的主题)时,才可改动它。拿不准时,保留。

# 输出语言

所有自然语言字段用 `output_lang`:
- `workspace.name`
- `initiative.name`、`initiative.summary`、`initiative.progress`
- `task.title`
- `artifact.title`
- `blockers[]`(字符串)

技术术语 —— HSF、MR、IP、OAuth、branch 名、文件路径、命令名 —— 即使在
中文模式下也保持英文。标识符和机器字段无论 `output_lang` 为何,始终为
英文/原样:
- `id`、`cwd`、`session_id`
- `status` 枚举值(active/paused/done/archived)
- `artifact.type`、`artifact.url`、`artifact.status`、
  `artifact.ref_id`、`artifact.last_mentioned_at`
- `task.status`、`task.terminal_at`

当你看到 PRIOR 或某条 hot 摘要对某个自然语言字段使用了不同的语言时,
**将其改写为匹配 `output_lang`**。不要保留原文。混合语言的标题会破坏
下游基于 slug 的去重,并为同一工作产生重复的任务条目。

# 工作流

1. **延续所有 PRIOR initiatives**(减去 DELETED_IDS)。一个都不跳过。
2. 对 PRIOR 中的每个 initiative,判断是 hot 还是 cold(它的任一会话
   是否出现在 HOT_SUMMARIES 中?)。
   - Hot → 你可以更新 `progress`、依据 hot 会话信号刷新状态、按 §7a
     聚合 `artifacts[]`、按 §7b 聚合 `blockers[]`、按 §7c 聚合
     `tasks[]`。对每个 PRIOR pending 任务,应用 §7d(仅在有清晰证据时
     翻转为 `done` 或 `cancelled`)。若有新会话则添加。
   - Cold → 机械地应用 §5。只动 `status`(衰减规则)。`artifacts[]`
     与 `blockers[]` 保持逐字节相同。
3. **发现新的 initiatives** —— 来自 HOT_SUMMARIES 中其 `session_id`
   不在任何现有 initiative 的 `sessions[]` 里的会话。
   对每一个,创建一个带稳定 slug 风格 `id` 的新 initiative,并无论大小
   都给出 `level: "chip"`(§8 首轮规则)。
4. 按 §6 将新的 initiatives **分组**到 workspaces 中。
5. 按 §8 **分配 `level`** —— PRIOR 下限、首轮 chip、带证据晋升、绝不
   降级。按 §9 设置 `parent_thread_id`。
6. 在每个 workspace 内按 `last_activity_at` 降序对 initiatives
   **排序**;按 max last_activity_at 降序对 workspaces 排序。

# 飞行前自检(在给出之前做这件事)

对你的输出,逐项核验:

- [ ] PRIOR 中的每个 initiative id(减去 DELETED_IDS)都出现在输出中。
- [ ] DELETED_IDS 中的 id 没有一个出现在输出中。
- [ ] 每个 `sessions[]` 条目都是完整 UUID(带连字符的 36 个字符)。
- [ ] 每个 hot session_id(来自 HOT_SUMMARIES)都出现在某个
      initiative 的 `sessions[]` 中。
- [ ] 相对 PRIOR,没有任务 `status` 从终态(`done`/`cancelled`)回退到
      `pending`,也没有在 `done` 与 `cancelled` 之间翻转。
- [ ] 每个 `status` 值都是 `pending | done | cancelled` 之一 ——
      没有遗留的 `done: true|false` 布尔值,没有其他字符串。
- [ ] 冷 initiatives 的 name/summary/progress/tasks/artifacts/blockers
      未变。
- [ ] 每个 `artifacts[]` 条目要么有一个非空的 `http(s)://` URL,
      要么有一个 `ref_id`(或两者都有)。一个既无 `url` 又无 `ref_id`
      的条目毫无用处,必须丢弃。
- [ ] 凡有 `url` 之处,它都以 `http://` 或 `https://` 开头,且包含
      来自某条 hot 摘要的真实 URL,绝非由 ID + 模式构造出来的合成 URL。
- [ ] 一个 initiative 内没有重复的 `artifacts[]` 条目(两者都有 `url`
      时按 `url` 去重,否则按 (`type`、`ref_id`) 去重)。
- [ ] `blockers[]` 字符串简短(每条 ≤ 80 字符)且已去重。
- [ ] `tasks[]` 条目来自某条 hot 摘要,或是带显式 `id` 的 PRIOR 延续
      (没有凭空发明);没有两个条目共享同一 `id`。同一概念任务的改写
      标题携带 PRIOR 的 `id`。
- [ ] 来自 PRIOR 的每个 `pending → done` 或 `pending → cancelled`
      翻转都携带一个 `evidence` 字段,含简短的引用/转述。
- [ ] **`tasks[]` 长度 ≥ PRIOR `tasks[]` 长度(DD-011 不变式)。**
      你不能丢弃任务。如果缩小看起来合理,把它留给用户通过 UI 删除 ——
      绝不通过你的输出删除。
- [ ] **每个 initiative 都有一个 `level` 字段**,值为
      `thread`、`card` 或 `chip`(DD-014)。
- [ ] **`level` 绝不从 PRIOR 降低。** 只能 chip→card→thread;
      不能 card→chip,不能 thread→card。
- [ ] **新发现的 initiatives 给出 `level: "chip"`**,无论大小信号
      为何(§8 首轮规则)。
- [ ] **`parent_thread_id`** 要么是 `null`,要么是**同一 workspace**
      中某个 `level: thread` 兄弟的 id。thread 本身始终给出
      `parent_thread_id: null`。

如果任何一项核验失败,修复并重试。**绝不给出损坏的输出**。

``````

---

## 3. 工具 — 任务去重合并

- **场景**:用户在某 initiative 下点「合并重复任务」时,识别概念重复的 pending 任务并给出保留/取消计划(prompt 内含 worked example)。
- **文件**:`prompts/consolidate-tasks.md`(128 行)
- **调用方**:`bin/serve.py`(`/api/consolidate-tasks` 端点 @ 1257;读取 @ 1912)
- **运行时占位符**:`<initiative>` `<tasks>`
- **输出**:严格 JSON 去重计划(输出标题会与输入校验,防止编造标题)
- **预算**:$0.20/次,超时 240s

### 完整文案

``````markdown
# 任务:合并某个 initiative 上的重复任务

你会拿到一份累积在单个 initiative 卡片上的 **pending 任务**列表。
在上游摘要器多次运行的过程中,同一个概念上的任务会以略有不同的
措辞被反复产出 —— 比如翻译(`重构授权链` ↔ "Refactor authorization
chain")、前缀标签(`[F1-body] X` 对比 `X`)、扩写(`实现 service
doc MVP` 对比 `实现 service doc MVP with flag-based slicing`),或者
同义词替换。用户希望把这份列表折叠起来:每个概念簇只保留一个幸存者,
其余每个变体都标为 `cancelled`,并附上指向幸存者的证据。

## 输入(在下面的 `<tasks>` 块里)

一个 YAML 格式的任务标题列表。每一项都是当前卡片上的一个 pending 任务。

## 输出

一个单独的 JSON 对象 —— 没有 markdown 围栏,没有散文。Schema:

```json
{
  "groups": [
    {
      "keep": "<要保留的精确标题,逐字节从输入复制>",
      "cancel": [
        { "title": "<要取消的精确标题>",
          "reason": "<≤ 60 字符:指向幸存者的简短说明>" }
      ]
    }
  ]
}
```

## 规则

1. **只把含义为同一个概念任务的标题归到一组。** 不确定时,
   就别动它们 —— 误判(把真实工作抹掉的 false positive)是
   灾难性的。漏判(没能合并两个真正相同的条目)是可恢复的。

2. **保留最规范的标题作为幸存者。** 优先选:
   - 当两者描述同一步骤时,选较短的而非较长的。
   - 选不带 `[F1-body]` / `[draft]` 前缀的标题,而非带前缀的。
   - 选用户的母语形式(本项目里多为中文),而非翻译变体。
   - 当两者都明确描述同一项工作时,选更具体的而非更模糊的
     (例如 `添加单测与 e2e` 优先于 `添加测试`);但当具体的变体
     只是徒增噪音时,选更模糊的(`实现 service doc MVP` 优先于
     `实现 service doc MVP with flag-based slicing`)。
   - 状态:如果某个候选的标题文本里已带有 `(done)` 或 `(cancelled)`
     标记,就保留它 —— 终态是有承载意义的。

3. **每个 `keep` 和每个 `cancel.title` 都必须从输入逐字复制。**
   不要改写 —— Layer 2 靠精确 slug 相等来去重,取消流程会通过以
   标题为键的 user_overrides 来流转。

4. **单例就保持单例。** 列表里没有语义重复项的任务,根本不应该
   出现在输出里(不要只有一个成员的组)。

5. **`reason` 是给用户看的**,用户会在确认前于预览里看到它。
   要具体:"duplicate of '<keep>'" 胜过 "redundant"。对于语言变体:
   "'<keep>' 的中文形式"。对于带标签的变体:"'<keep>' 的无标签形式"。

6. **组数限制 ≤ 12。** 如果存在更多簇,返回最有把握的 12 个。
   用户之后可以再跑一次 consolidate。

7. **空结果也没关系。** 如果输入里没有重复项,返回
   `{"groups": []}`。

## Worked example

输入:

```yaml
tasks:
  - "重构授权链"
  - "推进 ServiceTestAuthorizationService 重构"
  - "Refactor authorization chain"
  - "实现 service doc MVP"
  - "实现 service doc 命令 MVP"
  - "实现 service doc MVP with flag-based slicing"
  - "添加测试"
  - "OpenAPI 接口设计"
```

输出:

```json
{
  "groups": [
    {
      "keep": "重构授权链",
      "cancel": [
        {"title": "推进 ServiceTestAuthorizationService 重构",
         "reason": "'重构授权链' 的具体措辞"},
        {"title": "Refactor authorization chain",
         "reason": "'重构授权链' 的英文翻译"}
      ]
    },
    {
      "keep": "实现 service doc MVP",
      "cancel": [
        {"title": "实现 service doc 命令 MVP",
         "reason": "同一步骤,用 '命令' 措辞"},
        {"title": "实现 service doc MVP with flag-based slicing",
         "reason": "在 '实现 service doc MVP' 上附加的实现细节"}
      ]
    }
  ]
}
```

`添加测试` 和 `OpenAPI 接口设计` 不在任何组里 —— 在这个小例子里,
它们不是任何东西的明确重复项。

## 不要做的事

- 不要仅因为两个任务共享一个主题("test" / "OpenAPI" / "rebase")
  就合并它们。它们必须是*同一步骤*。
- 不要改写被保留的标题。
- 不要编造输入里没有的任务标题。
- 除了 JSON 对象,不要输出任何东西。

``````

---

## 4. 派生 — 下一条消息建议(内联)

- **场景**:仪表盘上为某条会话推荐「接下来可以发的 2-3 条不同的下一句话」。这是内联中文 prompt,结合全局其它工作 + 本会话近况 + 最近对话。
- **文件/函数**:`bin/serve.py` → `_suggest_prompt(sid)` @ 520–570(调用 `_claude_suggest()` @ 594)
- **运行时占位符**(代码拼装):`<全局其它工作>` `<这条会话>` `<最近对话>`
- **输出**:JSON 字符串数组(2-3 条),`_parse_suggestions()` 容错解析
- **预算**:$0.30/次,超时 70s

### 完整文案(prompt 构建函数原文)

``````python
def _suggest_prompt(sid: str) -> str | None:
    """为 /api/suggest 构建 prompt:这条会话的近况 + 其它活跃卡片的全局快照
    (内置的单条建议所缺失的跨会话视角)→ 请求 2-3 条彼此不同、可直接发送的
    下一句话。"""
    card, others = None, []
    try:
        mm = json.loads(DASHBOARD_JSON.read_text())
    except Exception:
        mm = {}
    for ws in mm.get("workspaces") or []:
        for it in ws.get("initiatives") or []:
            if it.get("sealed"):
                continue
            if sid in (it.get("sessions") or []):
                card = it
            elif it.get("awaiting_user") or it.get("status") == "active":
                others.append((ws.get("name"), it))
    turns = _recent_turns(sid, 8)
    if not turns and not card:
        return None
    L = ["你是一个「注意力驾驶舱」的助手。用户在并行推进多件 Claude Code 编码工作。",
         "请基于【全局其它工作】+【这条会话近况】,推荐用户**接下来可以发给这条会话的 2-3 条不同的下一句话**。",
         "要求:每条都可直接发送、具体(用户口吻、祈使句、中文);彼此角度不同(如 继续推进 / 先验证 / 换方向或追问);贴合这条会话当前状态与下一步;不要寒暄、不要解释。",
         '只输出一个 JSON 数组,形如 ["…","…","…"],不要任何额外文字。']
    if others:
        L.append("\n<全局其它工作>")
        for nm, it in others[:8]:
            aw = it.get("awaiting_user")
            L.append(f"- [{nm}] {it.get('name')}: {(it.get('progress') or '')[:80]}"
                     + (f" [等你:{aw}]" if aw else ""))
        L.append("</全局其它工作>")
    if card:
        L.append("\n<这条会话>")
        L.append(f"名称: {card.get('name')}")
        if card.get("progress"):
            L.append(f"当前进展: {str(card['progress'])[:220]}")
        if card.get("next_step"):
            L.append(f"已判断的下一步: {card['next_step']}")
        if card.get("awaiting_user"):
            L.append(f"在等你: {card['awaiting_user']}")
        bl = card.get("blockers") or []
        if bl:
            L.append("卡点: " + "; ".join(bl[:3]))
        L.append("</这条会话>")
    if turns:
        L.append("\n<最近对话>")
        for t in turns:
            who = "我" if t["role"] == "user" else "Claude"
            L.append(f"### {who}\n{t['text'][:600]}")
        L.append("</最近对话>")
    return "\n".join(L)

``````

---

## 5. 派生 — 每周工作总结(内联)

- **场景**:按周生成工作总结。铁律:AI 只能从 JSON 信号里取事实,不得编造(每句话都要能溯源到某条 signal)。
- **文件/函数**:`bin/derived/weekly_report.py` → `_build_prompt(signal_json, lang)` @ 52–114
- **运行时占位符**:`{lang_block}`(中/英)、`{signal_json[...]}`、末尾内嵌 JSON signal
- **输出**:Markdown(Highlights / Active initiatives / Shipped / Scope changes / Notable artifacts / Sessions touched)
- **预算**:~$0.03/次

### 完整文案(prompt 构建函数原文)

``````python
def _build_prompt(signal_json: dict, lang: str) -> str:
    """包裹在结构化 signal 外面的指令。

    核心原则:AI 是从 JSON 出发来写散文,不得编造超出其外的事实。
    报告里的每一个论断都必须能溯源到某条 signal。
    """
    if lang.startswith("zh"):
        lang_block = (
            "用简体中文写,语气客观、专业但不机械。每一句都必须来自"
            "下面 JSON 里某条信号。不引入未列出的内容。"
        )
    else:
        lang_block = (
            "Write in English, objective and professional but not robotic. "
            "Every claim must trace to a signal in the JSON below. "
            "Don't invent anything not listed."
        )

    return f"""你正在为一位开发者撰写每周工作总结。
本周是 {signal_json['week_label']}({signal_json['week_start']} —)。

把你的输出组织成带以下小节的 markdown(若用 zh-CN 书写则翻译
小节名):

  ## Highlights(亮点)
    3–6 条要点,覆盖本周最有影响力的事件。
    锚定在 archived_this_week + tasks_done_this_week +
    new_artifacts_this_week(尤其是 status:merged 的 MR/PR)。

  ## Active initiatives(进行中的 initiatives)
    对 active_initiatives 里的每一项,一行:名称 + 状态 +
    对进展的简短转述。如有帮助则按 workspace 分组。

  ## Shipped / Closed(已交付 / 已关闭)
    把 archived_this_week + tasks_done_this_week 重述为一个要点
    列表。若为空,就在该小节写一次 "(本周无条目)"。

  ## Scope changes(范围变更)
    从 tasks_cancelled_this_week 里,列出被取消或被合并进其它任务
    的任务。简要引用 evidence 字段(例如 "Merged into X" 或
    "Scoped out per turn")。若列表为空则跳过该小节。

  ## Notable artifacts(值得注意的产物)
    从 new_artifacts_this_week 里,列出值得引用的 MR/PR/issue/doc
    链接。若列表为空则跳过。

  ## Sessions touched(触及的会话)
    单独一行:"N sessions across M workspaces" —— 从 hot_sessions
    里取这些计数。简短。

样式规则:
  - 不要前言,不要附言("希望有帮助"之类)。
  - 技术标识符(HSF、MR 编号、branch 名、文件路径)即使在
    zh-CN 里也保持英文。
  - 把产物 URL 引用为内联 markdown 链接。
  - {lang_block}
  - 总长度控制在约 30 行或更少。

JSON signal:
{json.dumps(signal_json, indent=2, ensure_ascii=False)}
"""

``````

---

## 6. 派生 — 挑选 3 个下一步重点(内联)

- **场景**:从在途 initiatives 里挑 3 个用户「接下来该专注」的项;启发式优先级:新鲜动能 > 可自行解卡的阻塞 > 低成本收尾。避开外部阻塞(等评审/CI/运维)与 done/archived。
- **文件/函数**:`bin/derived/next_steps.py` → `_build_prompt(candidates, lang)` @ 89–122
- **运行时占位符**:`{lang_block}`、末尾内嵌 candidates JSON
- **输出**:严格 JSON `{"items":[{"init_id","reason"}]}`,reason ≤ 60 字
- **预算**:$0.20/次

### 完整文案(prompt 构建函数原文)

``````python
def _build_prompt(candidates: list[dict], lang: str) -> str:
    lang_block = (
        "用简体中文回复。reason 字段保持 ≤ 60 字。"
        if lang.startswith("zh") else
        "Reply in English. Each `reason` ≤ 60 chars."
    )
    return f"""给定这些在途的 initiatives,挑出用户接下来(NEXT)
应该专注的 3 个。

选择启发式(按优先级排序):
  1. 新鲜动能:近期处于 active 状态,且有用户能独自上手处理的
     pending 任务。
  2. 受阻但可解锁:阻塞看起来是用户可处理的
     (例如 "等用户确认"),而非外部的(例如 "等 CodeOwner 评审")。
  3. 低成本收尾:只有 1–2 个 pending 任务且有一个开着的 MR/PR
     的小 initiative。

避开那些阻塞明显是外部的 initiatives(等评审者、CI、运维)。
避开 done/archived。

返回如下形式的严格 JSON:
  {{"items": [
    {{
      "init_id": "<来自输入的 id>",
      "reason": "<简短、具体的理由 ≤60 字符>"
    }},
    ...
  ]}}

如果有 3 个以上候选,正好返回 3 项;不足则更少。{lang_block}

Candidates:
{json.dumps(candidates, indent=2, ensure_ascii=False)}
"""

``````

---

## 7. 派生 — 仪表盘 20 条 tips(内联)

- **场景**:为仪表盘生成 20 条轮播 tips,分 curiosity(8,需 source_url)/ wisdom(6,需 source_url)/ rest(3)/ work(3,需引用用户数据)。强约束:禁止编造,任何无法溯源的条目直接丢弃。
- **文件/函数**:`bin/derived/tips.py` → `_build_prompt(work_patterns, recent_history, lang)` @ 153–286
- **运行时占位符**:`{kind_examples}` `{lang_block}` `{work_block}` `{recent_block}`(中/英双版本)
- **输出**:严格 JSON tips 数组;`_collect_recent_history()` 提供近期去重
- **预算**:$0.15/次

### 完整文案(prompt 构建函数原文,含中/英分支)

``````python
def _build_prompt(work_patterns: list[dict], recent_history: list[dict],
                  lang: str) -> str:
    """请求生成 20 条 tips,并刻意采用不均衡的配比:curiosity 8、
    wisdom 6、work 3、rest 3(凑齐 20)。recent_history 是近期
    tip 文本的扁平列表,便于 AI 避免重复。"""
    work_block = (
        f"在用户当前数据中观察到的工作模式:\n"
        f"{json.dumps(work_patterns, indent=2, ensure_ascii=False)}"
        if work_patterns
        else "本轮没有浮现工作模式 —— 输出 0 条 `work` tip。"
             "把这 3 个 work 名额回填到 `curiosity`,使总数仍保持"
             "在 20(curiosity 变为 11,wisdom 6,rest 3,work 0)。"
    )
    recent_block = (
        f"\n近期已展示(避免重复以下文本):\n"
        f"{json.dumps([h['text'] for h in recent_history[:40]], ensure_ascii=False)}"
        if recent_history else ""
    )

    if lang.startswith("zh"):
        lang_block = (
            "全部 20 条用简体中文。tone:温和、口语化、不说教。每条 ≤ 50 字。"
            "wisdom 类的诗句保持原文文言/古文,不要翻译,但 — 字号后跟的"
            "归属说明用现代汉语。"
        )
        kind_examples = """
- work (3 条): 数据驱动的工作建议 (引用具体 initiative 名/数字)。无需 source_url。
  e.g. "hsf-hanging-mrs 已卡 3 天,瓶颈是 aone 发布。建议今天约一下排期。"

- wisdom (6 条): 真实存在的诗句、闲适风格的人生感悟。**重点是放松/写景/生活意境,
  不要励志说教。**
  偏好题材:山水景色、四季时节、闲居琐事、日常感受、对自然的观察、淡然心境。
  避免:励志自勉("莫等闲白了少年头")、勤学苦读("学而不思则罔")、修身齐家。
  必须有明确出处,source_url 指向 Wikipedia / Wikiquote / 诗词作者页等可核验页面。
  好的例子:
    "采菊东篱下,悠然见南山。— 陶渊明《饮酒·其五》"
        → https://zh.wikipedia.org/wiki/陶淵明
    "明月松间照,清泉石上流。— 王维《山居秋暝》"
        → https://zh.wikipedia.org/wiki/王維
    "竹外桃花三两枝,春江水暖鸭先知。— 苏轼《惠崇春江晚景》"
        → https://zh.wikipedia.org/wiki/蘇軾
    "山光悦鸟性,潭影空人心。— 常建《题破山寺后禅院》"
    "稻花香里说丰年,听取蛙声一片。— 辛弃疾《西江月·夜行黄沙道中》"

- rest (3 条): 温和的休息提醒,基于常识可不带 URL,但不要鼓吹无稽的健康偏方。
  e.g. "屏幕看久了眼睛会涩,起身倒杯水,看 20 秒远处再回来。"

- curiosity (8 条): 真实可核验的小知识。每条 MUST 配 source_url(维基百科 / Etymonline /
  Stanford Encyclopedia / MDN / 权威官网)。无法找到可信链接的不要写。
  题材尽量发散:词源、生物、编程史、物理、食物、音乐、地理 — 让读者每条都有新发现。
  反例 ❌ "鸭子嘎嘎声没有回声"(这是流传甚广的伪科学)。
  正例 ✓ "'OK' 一词源自 1839 年波士顿一份报纸刊登的玩笑缩写 'oll korrect'。"
         source_url: https://en.wikipedia.org/wiki/OK
"""
    else:
        lang_block = (
            "全部 20 条用英文。tone:温和、口语化、绝不说教。"
            "每条 ≤ 90 字符。"
        )
        kind_examples = """
- work (3 条): 数据驱动的建议,引用具体的 initiative / 数字。
  无需 source_url。
- wisdom (6 条): 真实的引语或人生感悟。**偏向平静 / 写景 /
  观察的基调 —— 山水、四季、日常生活的感受。**
  避免奋斗式的"只争朝夕"类励志句。
  归属必须可核验;附上 source_url,指向
  Wikipedia / Wikiquote / 原始文本。
- rest (3 条): 温和的休息提醒。常识性条目无需
  URL,但绝不要鼓吹未经证实的健康说法。
- curiosity (8 条): 关于生活 / 语言 /
  编程 / 科学 / 历史的小而出人意料的事实。每一条 curiosity tip 都 MUST 配
  source_url(Wikipedia、Etymonline、Stanford Encyclopedia、MDN、
  官方文档)。如果找不到某条说法的可信来源,
  就丢弃这条 tip —— 不要编造。避免广为流传却失实的
  冷知识(例如"鸭子的嘎嘎声没有回声"这个谣言 —— 已被辟谣)。
"""

    return f"""为开发者的仪表盘生成二十条短 tips。
刻意采用不均衡的配比:curiosity 占据最多的轮播名额,
wisdom 第二,work / rest 数量相等且较少。

默认配比:
  - curiosity: 8
  - wisdom:    6
  - rest:      3
  - work:      3
  总计:       20

类别:
{kind_examples}

返回严格 JSON。结构(顺序无所谓 —— 数量才重要):
  {{
    "tips": [
      {{"kind": "curiosity", "text": "...", "source_url": "https://..."}},
      ... 共 8 条 curiosity 条目 —— source_url 必填 ...
      {{"kind": "wisdom",    "text": "...", "source_url": "https://..."}},
      ... 共 6 条 wisdom 条目 —— source_url 必填 ...
      {{"kind": "rest",      "text": "..."}},
      ... 共 3 条 rest 条目 —— source_url 可选 ...
      {{"kind": "work",      "text": "...", "pattern": "<id-from-input>"}},
      ... 共 3 条 work 条目 —— 无 source_url ...
    ]
  }}

硬性规则:
- 以上述配比为目标。如果某个类别(curiosity / wisdom)
  无法凑足那么多*可核验*的条目,就在该类别少出几条,
  并把多出的名额加到 curiosity。下限:总共 14 条 tip。
- {lang_block}
- **禁止编造。** 每一条事实性陈述都必须可溯源。如果你
  不确定某条引语的归属是否正确、某个事实是否属实,
  或某个 URL 是否存在,就丢弃这条 tip。宁可一轮稀疏,
  也不要出错。
- 每条 `curiosity` tip 和每条 `wisdom`
  tip 都必须填 `source_url`。该 URL 必须是你有高度把握真实存在且
  切题的。优先使用权威参考:
    * Wikipedia / Wikiquote (zh.wikipedia.org / en.wikipedia.org)
    * Etymonline.com 用于词源
    * Plato.stanford.edu 用于哲学
    * MDN / 官方语言文档用于编程史
    * 标准化组织用于科学/数学事实
  如果找不到稳定的权威 URL,就丢弃这条 tip。
- 每条 `work` tip 都必须引用 patterns 块中的具体数据 ——
  一个具体的 initiative id、MR number、阻塞数等。略去
  `source_url`(work tips 以用户自己的数据为依据)。
- 在同一类别内,所有 tips 必须有实质性差异 ——
  不同的角度、心境、年代、出处或题材。不要写
  近似重复的内容。
- 不要泛泛的套话("注意身体"、"保持专注")。
- 不要与"近期已展示"条目相同或近似相同的文本。

{work_block}{recent_block}
"""

``````

---

## 8. 派生 — 过劳关怀提醒(内联)

- **场景**:检测到过劳模式(如多次深夜结束会话)时,生成一条温和、引用具体数字的关怀消息;无信号则不调用 AI。
- **文件/函数**:`bin/derived/wellness.py` → `_build_prompt(patterns, lang)` @ 166–190
- **运行时占位符**:`{lang_block}`、末尾内嵌 patterns JSON
- **输出**:严格 JSON `{"pattern","message"}`
- **预算**:$0.10/次

### 完整文案(prompt 构建函数原文)

``````python
def _build_prompt(patterns: list[dict], lang: str) -> str:
    lang_block = (
        "用简体中文,1-2 句,温和不说教,要具体引用数字(例如"
        "'你这周已经有 5 次晚于 22 点结束的会话');允许小幽默。"
        if lang.startswith("zh") else
        "用英文回复,1–2 句,温和但不说教。"
        "引用具体数字('5 sessions ended past 22:00')。"
        "可以带一点幽默。"
    )
    return f"""该用户工作强度很大,以下模式
出现在他们近期的活动中。写一条简短、温和的消息,
提醒他们可持续的节奏很重要。这条消息必须
引用 patterns 中的具体数字 —— 绝不要泛泛的
"注意身体"式建议。

返回严格 JSON:
  {{"pattern": "<chosen pattern id>", "message": "<your text>"}}

如果触发了多个 pattern,选信号最强的那个。

{lang_block}

Patterns:
{json.dumps(patterns, indent=2, ensure_ascii=False)}
"""

``````

---

## 9. ⚠️ 遗留 — v1 分类 prompt(已废弃)

- **场景**:旧版 v1 分类逻辑,已被 `classify-cross-session.md`(v3)取代。
- **文件**:`prompts/classify.md`(277 行)
- **状态**:经全仓 grep 确认**无任何代码引用**,可考虑删除。文案附于下方仅供存档。

### 完整文案(存档)

``````markdown
你正在分析一位开发者的 Claude Code 会话历史,以便生成一份其近期工作的
分层脑图(mindmap)。

你将收到**最多三项输入**:

1. **PRIOR_MINDMAP**(可选)—— 上一次生成的脑图输出。把它作为你的
   基线;保持连续性。详情见下方"连续性规则"一节。首次运行时可能不存在
   —— 此时从头构建。

2. **DELETED_IDS**(可选)—— 一个 JSON 对象,带有键
   `deleted_initiative_ids`。这些是用户已**明确删除**的 initiative ID。
   它们**绝不能**出现在你的输出中,即使 INPUT_SESSIONS 中含有针对它们的
   新证据。用户希望它们消失;请尊重这一点。(如果你看到某个已删除 ID 的
   证据,你可以为该工作在一个不同的 `id` 下创建一个**新的** initiative
   —— 但被删除的 ID 本身仍要排除在外。)

3. **INPUT_SESSIONS** —— 一个会话摘要的 JSON 数组(下文说明),
   代表需要分类的近期工作。

每条会话摘要包含:
- `session_id`:唯一的会话标识符
- `cwd`:会话的工作目录
- `started_at` / `last_activity_at`:时间戳
- `message_count`:往来消息总数
- `first_user_prompt`:最初的请求(可能被截断)—— 描述
  *用户最初打算做什么*
- `recent_user_prompts`:最多 3 条最近的用户 prompt —— 描述
  *对话目前进行到哪里 / 当下正在请求什么*
- `last_assistant_summary`:最近一条助手文本回复的第一段 —— 通常是一份
  明确的"我做了什么"的总结
- `edited_files`:被 Write/Edit 工具调用触及的文件 —— 关于构建或改动了
  什么的具体证据
- `task_events`:TaskCreate/TaskUpdate 事件("created: …"、
  "completed: #id"、"in_progress: #id")—— 当用户依赖 task 工具时,
  这是一份实时进度日志
- `recap`:Claude Code 原生的会话回顾(如有,权威)
- `tools_used`:会话期间调用过的工具名

**信号的可信度(按权威性排序)**:
1. 带 `completed:` 的 `task_events` —— 表示"这事做完了"的最高置信度
2. `edited_files` —— 如果某文件被写入,那项工作就发生过
3. `last_assistant_summary` —— 通常反映最新的状态
4. `recent_user_prompts` —— 用户当前的关注点;当用户最新的 prompt 明显
   把工作推进到 recap 所描述之外时,**优先**采信它而非 `recap`(例如
   recap 说"仍在调查中",但某条近期 prompt 说"那就把 issue 提了吧"
   —— 以 prompt 为准)
5. `recap` —— 有用的长篇上下文,但可能比实时对话滞后数小时;**仅当**
   没有更新鲜的信号时才视为权威
6. `first_user_prompt` —— 仅是*最初的*目标,到现在往往已过时

**至关重要**:不要把 `edited_files`、`last_assistant_summary` 或
`task_events` 字段已明确显示为已完成的事项列为 `{done: false}` 的任务。
当信号冲突时,优先采信最新的那个。

# 连续性规则(当 PRIOR_MINDMAP 存在时)

**把 PRIOR_MINDMAP 当作你的起始状态,并基于 INPUT_SESSIONS 就地编辑它**。
不要从零重建。这是本 prompt 中最重要的一条规则 —— 弄错它会让每次刷新都
在视觉上打乱用户的历史。

## Identity preservation(身份保持)

对于每个仍对应进行中或近期工作的旧 initiative,**逐字复用其 `id` 和
`name`**。按概念身份匹配,而非逐字措辞匹配。`id` 是稳定的句柄;
绝不要为同一份工作重新铸造新的 id。

可接受的名称变更:仅当旧名称在新证据下明显错误或具有误导性时。当你确实
更改名称时,要保留 `id`。

对于每个旧任务,**逐字保留其标题**,除非标题在事实上不准确。轻微的措辞
润色**不是**重写任务的理由 —— 那会造成视觉抖动。

## Task evolution(任务演进)

- 旧任务为 `done: true` 的**必须保持** `done: true`。发生过的工作不会
  变回没发生。
- 旧任务为 `done: false` 的:在 INPUT_SESSIONS 中检查完成证据
  (task_events 的 `completed:`、edited_files、recap、summary)。若已完成
  → 翻转为 `done: true`。否则保持为 `done: false`。
- 仅当 INPUT_SESSIONS 浮现出旧任务尚未涵盖的新的具体工作时,才添加
  **新**任务。
- 不要删除旧任务。它们是历史。

## Initiative lifecycle(initiative 生命周期)

- 旧 initiative 在 INPUT_SESSIONS 中有新活动 → 基于新证据更新其
  `progress`、`status`、`tasks`、`last_activity_at`。
- 旧 initiative 在 INPUT_SESSIONS 中无新会话 → 保留它。
  基于 `last_activity_at` 应用自然的状态衰减:
  * 仍在 3 天内 → 保持 `active`
  * 3–14 天 → 降级为 `paused`
  * >14 天且状态已经是 `paused` 或没有恢复信号 → 降级为 `archived`
  * `done` 保持 `done`
- 一个 initiative 可能**拆分**:如果旧脑图只有一个 initiative,而新证据
  显示出两条明显不同的叙事线,则把旧的 `id`/`name` 留给主线,并为新的
  那条线创建一个新 initiative(用新的 `id`)。
- 一个 initiative 仅在旧脑图有两个、且新证据明确将它们统一时才可**合并**
  —— 这很罕见,只在显而易见时才做。

## Workspace structure(工作区结构)

- 复用旧的工作区 `name` 与 `cwd` 映射。除非某个 initiative 明显迁移
  (例如工作转移到了一个新仓库),否则不要在刷新之间重新打乱工作区。

## Cold start(冷启动)

如果 PRIOR_MINDMAP 缺失、为空,或使用旧版 v1 schema(有 `projects` 而非
`workspaces`),则忽略它并从头对 INPUT_SESSIONS 进行分类。

# 你的任务

生成一个**三层级层级结构**:

```
workspace                  (顶层 —— 通常是一个仓库/代码库)
  └── initiative           (中层 —— 其内部一项连贯的工作)
        └── task           (叶子 —— 具体的、可勾选的条目)
```

## Step 1: Group sessions into INITIATIVES(将会话归入 INITIATIVE)

一个 **initiative** 是一项连贯的、单一叙事的工作 —— 例如
"ChangeFree service refactor"、"App doc version_no migration"、"NCS
gateway auth integration"。通常多个会话共享一个 initiative。

规则:
- 一个 `cwd` 可能包含**多个** initiative(如果这些会话覆盖不同目标则拆分
  —— 例如 `hsfops` 可能同时并行有 "ChangeFree refactor" 和
  "App doc iteration")。
- 当不同仓库中的会话明显服务于同一条叙事线时,一个 initiative 可以**横跨**
  多个 `cwd`(例如某个功能同时触及 frontend + backend + SKILL 文件,
  全都为了同一个功能)。

## Step 2: Group initiatives into WORKSPACES(将 initiative 归入 WORKSPACE)

一个 **workspace** 是相关工作在概念上的归属地 —— 通常是一个仓库
文件夹名(例如 `hsfops`、`mw-cli`、`hsf-doc-generator`),但它也可以
是一个逻辑领域(例如 `skills`、`claude-code-tooling`)。

规则:
- 对于局限于单个 cwd 的 initiative:workspace = 该 cwd 的文件夹名。
- 对于横跨多个 cwd 的 initiative:按*语义归属*而非活动量来选择
  **主归属工作区(PRIMARY OWNER WORKSPACE)**。问自己:
  "这项工作从根本上*关乎*哪个领域?"
  - 示例:一项触及 frontend、backend 和 SKILL 定义文件的 Claude Skill
    开发工作,应归入 `skills` 工作区,因为那才是它的概念归属地 ——
    即使更多 commit 落在了 frontend 仓库。
  - 示例:一个在 backend 添加 API 并在 frontend 消费它的功能,其本身
    *就是*一项 API 能力,应归入 backend 工作区。
- 把其他涉及的 cwd 记录在 initiative 的 `linked_cwds` 中。

## Step 3: Per-initiative fields(每个 initiative 的字段)

为每个 initiative 生成:
- `id`:稳定的 slug,如 `hsfops-changefree-refactor`(小写,连字符)
- `name`:简短、人类可读的名称(用下方的 OUTPUT_LANG)
- `status`:取 `active`、`paused`、`done`、`archived` 之一。规则:
  * `active` —— 最后活动在过去 3 天内,工作明显进行中
  * `paused` —— 最后活动在 3–14 天前,或更久但有明确的"稍后恢复"信号
    (有未完成的待办、未完成的 MR、在等某人)
  * `done` —— 明确已完成:已发布、已合并、报告已交付,或 recap/prompt
    表明已完成
  * `archived` —— 最后活动在 >14 天前且没有明确的恢复信号。也用于一次性
    的探索性会话、失败的实验、用完即弃的调试,或任何不太可能有持续价值
    的东西。
  在 `paused` 与 `archived` 之间拿不准时,检查这项工作是否产出了持久的
  产物(已合并的代码、已提的 issue)—— 若有,`paused`;若无,`archived`。
- `summary`:用 1-2 句话描述该 initiative 是关于什么的
- `progress`:用 1-2 句话描述最新状态 / 目前进展到哪里
- `tasks`:具体条目,形如 `{title, done}`。**要慷慨 —— 列出你能从
  recap、task_events、edited_files 和 prompt 中证实的每一个不同任务**。
  没有人为上限。如果有 12 个不同任务被证据支持,就列 12 个。下游 UI
  会处理折叠。
- `sessions`:贡献该 initiative 的 session_id 列表
- `linked_cwds`:当 initiative 横跨多个仓库时的*次要* cwd 列表
  (单一 cwd 则省略或留空数组)
- `last_activity_at`:其各会话中最近的时间戳

## Step 4: Per-workspace fields(每个 workspace 的字段)

为每个 workspace 生成:
- `name`:工作区名称(简短,通常是文件夹名)
- `cwd`:该工作区的主/归属 cwd
- `last_activity_at`:其各 initiative 中 `last_activity_at` 的最大值
- `initiatives`:initiative 列表,按 `last_activity_at` 降序排序

按 `last_activity_at` 降序排序各工作区。在每个工作区内,按
`last_activity_at` 降序排序各 initiative。

# 输出格式

**仅输出严格的 JSON**,匹配以下结构 —— 不要散文,不要代码围栏:

```
{
  "schema_version": 2,
  "generated_at": "<ISO-8601 UTC>",
  "workspaces": [
    {
      "name": "...",
      "cwd": "...",
      "last_activity_at": "...",
      "initiatives": [
        {
          "id": "...",
          "name": "...",
          "status": "active|paused|done|archived",
          "summary": "...",
          "progress": "...",
          "tasks": [{"title": "...", "done": true|false}],
          "sessions": ["..."],
          "linked_cwds": [],
          "last_activity_at": "..."
        }
      ]
    }
  ]
}
```

# 语言

`OUTPUT_LANG` 会在 prompt 运行前被替换。以下字段的值**必须**用该语言书写:
`workspaces[].name`、`initiatives[].name`、`initiatives[].summary`、
`initiatives[].progress`、`initiatives[].tasks[].title`。

如果 `OUTPUT_LANG` 为 `zh-CN`:用简体中文书写这些字段,自然而简洁
(这是一份开发者的状态报告,不是翻译练习)。技术术语(HSF、OAuth、RBAC、
SDK、CR、MR、repo、branch、schema 等)在符合自然用法时可保留英文。

如果 `OUTPUT_LANG` 为 `en`:用英文书写这些字段。

其他字段(`id`、`cwd`、`status`、`session_id`、时间戳)无论语言如何
都保持原样。

# 规则

- 当 `recap` 与 `first_user_prompt` 同时存在时,优先采信 `recap`
  —— recap 是权威的。
- 简明。摘要读起来应像状态报告,而非逐字记录。
- 如果两项输入都为空,输出
  `{"schema_version": 2, "generated_at": "...", "workspaces": []}`。
- 绝不要凭空捏造输入未支持的会话、initiative 或任务。合并后的输入是
  `PRIOR_MINDMAP ∪ INPUT_SESSIONS` —— 任一方中的任何内容都算作被支持。
- 你 `sessions: [...]` 输出数组中的 `session_id` 值**必须**是 INPUT_SESSIONS
  中出现的完整 UUID,一字不差。**不要**把它们截断成前缀。
  错误:`["cbbeb23c"]`。正确:
  `["cbbeb23c-b6f9-4eb4-926e-7e4046c856d4"]`。下游工具按精确的完整 id
  匹配会话。

# 发出前的自检

在你发出 JSON 之前,在脑中与 PRIOR_MINDMAP 做差异比对:
- 每个旧的 initiative `id` 都应出现在你的输出中(状态 / 任务 / 进展
  可能已更新)。如果你丢掉了某个,你最好有充分的理由 —— 而且这个理由
  不能是"它没有新会话"(那应该用状态衰减来处理)。
- 每个旧任务都应出现在其 initiative 之下,标题相同,且 `done` 值是单调的
  (允许 false→true,**禁止** true→false)。
- 新的任务/initiative 在 INPUT_SESSIONS 中应有理由支撑。

``````
