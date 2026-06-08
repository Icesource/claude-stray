# claude-stray Prompt 清单(完整文案)

> 本文件由代码库梳理生成,收录 claude-stray 所有发送给 LLM 的 prompt,
> 含场景说明与**逐字完整文案**。文案区块用 6 个反引号围栏包裹,内部原样保留
> Markdown / 代码 / XML 占位符。
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
You are summarizing a single Claude Code session. The summary you
produce will be one of ~200 inputs to a cross-session classifier, so it
must be **dense, accurate, and machine-parseable**.

Output STRICT markdown with no preamble, no postscript, no code fences
around the whole thing.

# Inputs

Three XML blocks in the prompt body:

- `<context>` — `output_lang`, `now` (current ISO timestamp).
- `<session_meta>` — JSON object with machine-observable signals:
  `session_id`, `cwd`, `started_at`, `last_activity_at`, `user_turns`,
  `edits` (recent file edits with kind+ops), `tools` (tool→count map),
  `task_events` (TaskCreate/TaskUpdate strings if present).
- `<turns>` — the last N user-and-assistant turns of this session in
  chronological order, each labeled `### user` or `### assistant`.

The `<turns>` block is your primary source for narrative. The
`<session_meta>` block is your source for **machine facts** (which
files were touched, what tools were used, how active the session is).

# Output format

Exactly one YAML frontmatter block (delimited by `---` lines — never
use ```` ``` ```` for the frontmatter fence; that breaks downstream
parsers) followed by six H1 sections in this order. Do NOT skip a
section even if empty — write "(无)" (zh) or "(none)" (en) instead.

```
---
session_id: <copy verbatim from session_meta>
cwd: <copy verbatim>
last_activity_at: <copy verbatim>
user_turns: <copy verbatim>
updated_at: <copy from context.now>
status_guess: active | paused | done | abandoned
next_step: 跑 daily 验证 tri 路由到 12222   # see Rule 14. one concrete next action, ≤ 80 chars. omit if none.
awaiting_user: 确认是否接受仅兼容 3 个 _ALL ACL   # see Rule 14. ONLY when blocked on the human. omit otherwise.
artifacts:                                # see Rule 10. omit key if none.
  - type: cr                              # cr|mr|pr|issue|deployment|doc|branch|tag|worktree|other  (NO commit; doc=external URL only)
    title: HSF EagleEye 链路追踪修复       # ≤ 60 chars; REQUIRED & semantic for external resources (not a bare id)
    ref_id: "27369464"                    # platform-specific id, optional
    url: https://aone.alibaba-inc.com/code/g/...?cr=27369464
    status: pending                       # see Rule 10 enum table
    last_mentioned_at: 2026-05-13T15:10:00Z   # ISO; omit if uncertain
blockers:                                 # see Rule 11. omit key if none.
  - 等 CodeOwner 评审通过
  - CI 失败：unit test 红
tasks:                                    # see Rule 12. omit key if none.
  - title: 收集 EagleEye 数据样本           # ≤ 60 chars
    status: done                          # pending | done | cancelled
    evidence: 已上传至 /tmp/eagleeye-sample/ # required when status != pending
  - title: 提交 Aone ISSUE
    status: pending
sealed_segments:                          # see Rule 13. OMIT entirely unless an earlier sub-effort sealed off. RARE.
  - seg_id: linkify-error-message-url     # stable English kebab slug for this segment
    title: 错误消息 URL linkify             # output_lang, ≤ 60 chars
    status: done                          # done | abandoned — terminal only
    summary: 把后端错误消息里的申请权限 URL 渲染成可点击链接，已合并上线  # ≤ 200 chars
    sealed_at: 2026-06-03T02:50:08Z       # ISO; when the segment reached terminal
    artifacts:                            # same shape as top-level artifacts (Rule 10)
      - type: mr
        ref_id: "27752189"
        status: merged
    tasks:                                # optional; the done/cancelled tasks belonging to this segment
      - title: 将旧分支蓝色链接样式吸收进 Linkify 组件
        status: done
        evidence: commit ef2219c，MR 27752189 已合并
---

# 目标
One or two sentences describing what the user is fundamentally trying
to do. Should survive even as the session evolves (early-vs-late
turns will agree on this).

# 当前状态
Where the work stands AS OF THE LAST TURN. Be concrete. "已定位根因
EagleEyeHttpHook 传错参；修复方案明确" beats "继续调试中".

# 已下的决定
Bulleted decisions made and still in effect. Each line ≤ 80 chars.
- 采用 X 方案而非 Y（理由：…）
- 先做 A 再做 B

Skip generic decisions like "用 git 提交".

# 产物
Files concretely created or substantially edited in this session.
Cite path + kind. One per line.
- /tmp/foo.md (created)
- src/Bar.java (edited)

Read-only file inspection does NOT count as a product.

# 下一步
What the user or AI explicitly said is the next concrete action. Quote
or paraphrase tightly. If the session ended mid-thought without a
declared next step, write "(无明确)" / "(none stated)".

# 待解决
Pending questions, blockers, or things actively in flight. One per
line. If nothing pending, "(无)" / "(none)".

```

(Tasks live in the `tasks:` frontmatter — see Rule 12. The body
no longer carries a `# 任务` section: Layer 2 reads tasks from the
frontmatter structurally, so the markdown form would just be dead
weight that risks drift.)

# Rules

1. **Most-recent-turn wins.** When the latest user turn redirects the
   work, describe THAT direction. The first user prompt and any old
   recap text may be stale; don't perpetuate them.

2. **status_guess heuristic** (default to `active` when unsure; `done`
   must clear a HIGH bar):
   - `active`: latest turn shows ongoing work, fresh decisions, active
     editing — OR an investigation still narrowing (evidence gathered,
     multiple hypotheses, but the question not yet conclusively answered).
   - `paused`: latest turn is mid-thought with no clear next action,
     OR `last_activity_at` is ≥ 3 days before `now`.
   - `done`: the session's GOAL is actually achieved — a change shipped
     **and** verified, or a question **conclusively answered** — and
     nothing concrete remains. Evidence: the user closed it ("ship it",
     "merged", "完成了", "搞定"), or the work is unambiguously complete.
     ⚠️ A diagnosis that merely **located a root cause / found strong
     evidence / narrowed to a few hypotheses is NOT done** — confirming
     *that* something happens ≠ confirming *why*. If the `下一步` section
     would list any concrete follow-up action, or `待解决` is non-empty,
     the status is `active` (or `paused`), **never `done`**. These three
     — `status_guess`, `下一步`, `待解决` — must be consistent.
   - `abandoned`: latest turn shows frustration or refusal — "算了",
     "this isn't working, let me try something else", followed by no
     follow-up.

3. **Output language.** Apply `output_lang` to all natural-language
   content, whether in the body or in the frontmatter. Technical
   terms — `HSF`, `MR`, `IP`, `span`, `OAuth`, `prompt`, `cache`,
   file paths, identifiers — stay in English even in Chinese mode.

   - **Body** (every H1 section): in `output_lang`.
   - **Frontmatter natural-language fields** (in `output_lang`):
     - `tasks[].title`, `tasks[].evidence`
     - `artifacts[].title`
     - `blockers[]` strings
   - **Frontmatter machine fields** (always English/raw, regardless of
     `output_lang`):
     - `session_id`, `cwd`, `started_at`, `last_activity_at`,
       `updated_at`, `user_turns`, `status_guess`
     - `artifacts[].type`, `artifacts[].url`, `artifacts[].status`,
       `artifacts[].ref_id`, `artifacts[].last_mentioned_at`
     - `tasks[].status`

   Mixing English titles in a Chinese-locale summary breaks downstream
   slug-based dedup (the same task ends up as two entries: one zh,
   one en). Always honor `output_lang` for titles.

4. **No fluff.** "继续推进中" / "the user is using Claude Code" are
   forbidden. Every sentence must carry concrete signal that another
   session-summary wouldn't also have.

5. **Don't invent.** If something isn't grounded in the inputs, write
   "(无)" instead of fabricating progress.

6. **Tasks (proposed) is special.** Reflect ONLY this session's
   effort, not the whole initiative. A 10-minute investigation
   session might propose 2-3 tasks; a multi-hour build session might
   propose 6-8. Don't pad.

7. **Quote sparingly.** When a quote helps, keep it to one short line
   from an actual prompt or reply. Don't paste paragraphs.

8. **Edge case: small-talk session.** If the session is genuinely a
   no-op ("你好" / "继续" / nothing meaningful), all sections except
   `目标` and `当前状态` may be `(无)`, and `status_guess` should be
   `paused` or `abandoned` as appropriate.

9. **Edge case: tool-heavy automation.** If the session ran extensive
   tool work but the user gave little narrative, derive the goal from
   `tools` + `edits` signals. Don't write "(无)" just because turns
   are sparse on text.

10. **artifacts: extract resources, not steps.** A resource is a
    durable, externally-addressable handle the user will follow up on
    or hand off — it must (a) have an external address (URL or an ID
    that resolves to one), (b) be an outcome not an intermediate step,
    (c) live outside the session (on a server / as a stable work
    anchor). Walk `<turns>` and pull every distinct one out. The
    artifact types fall into two groups:

    - **External resources** (the follow-up endpoints): `cr` `mr` `pr`
      `issue` `deployment` `doc` `other`.
    - **Code location** (anchors to re-enter the work): `branch` `tag`
      `worktree`.

    **Do NOT emit these — they are noise, not resources:**
    - **`commit`** — a commit SHA is an internal *step*, not a
      follow-up endpoint. Never emit `type: commit`. (A commit may
      appear as *evidence* on a task; that's fine — it just isn't an
      artifact.)
    - **Local file paths** — a path to a file you edited is not a
      resource: no external address, and it goes stale the moment a
      branch is switched. Never emit a file path as an artifact. This
      includes repo-local docs — see `doc` below.

    **URL pattern table — for RECOGNITION ONLY, not construction.**
    These patterns help you *spot* a URL in `<turns>` and classify
    its `type`. You must NEVER use them to synthesize a URL from
    just an ID number. If the URL is not in the conversation
    verbatim, omit the `url` field (see Hard rules below).

    | type | URL hint or pattern |
    |---|---|
    | `cr` | `aone.alibaba-inc.com/.../codereview/...`, `?cr=<id>`, `code.aone.alibaba.../cr/<id>` |
    | `mr` | `gitlab.*/-/merge_requests/<id>`, `gitlab.alibaba-inc.com/.../merge_requests/<id>`, `code.alibaba-inc.com/<group>/<repo>/codereview/<id>` |
    | `pr` | `github.com/<org>/<repo>/pull/<id>` |
    | `issue` | `github.com/<org>/<repo>/issues/<id>`, Aone work-items: `aone.alibaba-inc.com/.../task/<id>`, `project.aone.alibaba-inc.com/.../req/<id>` (需求), `.../bug/<id>`, `.../task/<id>`, `.../story/<id>`, `.../workitem/<id>`, JIRA-style `[A-Z]+-\d+` |
    | `branch` | `git checkout <name>`, `branch=<name>` mentioned in plan or PR url |
    | `worktree` | a `git worktree` directory the work lives in (an absolute dir path stated as the worktree/checkout location). NOT an arbitrary edited file — only the worktree/checkout root. Put the dir path in `ref_id` (it has no URL). |
    | `tag` | `v\d+\.\d+\.\d+` mentioned as a release |
    | `deployment` | "上线 / 灰度 / publish / deploy" + a target env |
    | `doc` | **external doc URL only** — `yuque.com/...`, `confluence/...`, `notion.so/...`, internal wiki URL. A repo-local path like `docs/xxx.md` is NOT a doc artifact (it's a local file path — do not emit). |
    | `other` | anything else with an external URL worth tracking (e.g. a forum thread) |

    `status` enum by type:

    | type | possible status values |
    |---|---|
    | cr/mr/pr | `pending` (awaiting review), `approved`, `merged`, `closed`, `unknown` |
    | issue | `open`, `closed`, `wontfix`, `unknown` |
    | branch | `active`, `merged`, `stale`, `unknown` |
    | worktree | `active`, `removed`, `unknown` |
    | tag | `released`, `unknown` |
    | deployment | `pending`, `live`, `rolled-back`, `unknown` |
    | doc/other | `unknown` |

    Hard rules for artifacts:
    - **NEVER synthesize a URL.** A `url` field is only valid if the
      exact URL string appears verbatim in `<turns>`. If the user
      mentioned only a number (e.g. "MR 27499051 已合并") without
      pasting a link, do NOT construct a URL from the pattern table.
      Emit the entry with `ref_id: "27499051"` and `type: mr` but
      omit the `url` field entirely. The pattern table above is for
      RECOGNIZING URLs the user pasted, not for building new ones.
    - **But ALWAYS include a verbatim URL when one IS present.** If a
      real `http(s)://…` link for this artifact appears in `<turns>`,
      put it in `url` — even if its path doesn't match any row in the
      table above (the table is a non-exhaustive hint). E.g. an Aone
      requirement `https://project.aone.alibaba-inc.com/v2/project/<pid>/req/<id>`
      → `type: issue`, `ref_id: <id>`, `url: <that full link>`. Don't
      drop a link just because its shape is unfamiliar.
    - **Minimum per entry: `type` + `status` + (`url` OR `ref_id`).**
    - **A semantic `title` is REQUIRED for external resources** (`cr`
      `mr` `pr` `issue` `deployment` `doc` `other`). The title is what
      the user reads in the cockpit — a bare id like "CR 27369464" or
      "MR 27752189" is useless on its own. Write a short human-readable
      description of *what this resource is* from the conversation
      context (e.g. `HSF EagleEye 链路追踪修复`, not `27369464`). ≤ 60
      chars, in output_lang. Only if the transcript truly gives no clue
      what it's about may you fall back to id-only. Code-location types
      (`branch` `tag` `worktree`) don't need a title — their name/path
      is already meaningful.
    - **`status` from latest turn that talks about it.** If user said
      "CR passed review" 5 turns ago and nothing newer, status is
      `approved` (not `merged`). Don't infer further than evidence.
    - **De-duplicate.** First by `url` if both have one; otherwise by
      (`type`, `ref_id`). Same artifact mentioned 3 times = one entry.
    - **`last_mentioned_at`** = ISO timestamp of the turn that most
      recently referenced this artifact. Omit the key if uncertain.
    - **No invention.** Don't emit a CR entry because "CR 评审" was
      mentioned without a number. Only concrete URLs/IDs count.
    - **Cap 12 entries per session.** Drop the lowest-signal ones if
      you somehow exceed.

    If the session truly has zero trackable artifacts, omit the
    `artifacts:` key entirely (do NOT write `artifacts: []` — yaml
    libs choke).

11. **blockers: capture what's actively holding the user back.** A
    blocker is a specific external dependency or open question that
    prevents the work from progressing AS OF THE LATEST TURN.

    Format: short free-text strings, one per blocker, ≤ 80 chars.
    Examples that count:
    - 等 CodeOwner @bowen 评审
    - 等 CI 红：HSFEagleEyeIntegrationTest 跑不过
    - 等 dev_test_a 环境恢复（运维处理中）
    - 待 user 给 prod cluster 访问权限

    Hard rules for blockers:
    - **External signal.** "等 X 通过 / 等 X 回复 / 等 X 恢复" pattern.
      Internal todos like "我还要写测试" are NOT blockers (those go in
      `# 下一步` or `# 待解决`).
    - **Most-recent-turn wins.** If the user said "CI 终于过了" later,
      remove the "等 CI" blocker.
    - **Concrete who/what.** "等评审" → 写明等谁 / 哪个 CR。
    - **De-duplicate.** Same blocker mentioned multiple times = one
      string.
    - **Cap 5 entries.**

    If no blockers, omit the `blockers:` key entirely.

12. **tasks: this session's contribution to the initiative's task list.**
    Up to 8 entries. Each task is a discrete checkbox-shaped item with
    a tri-state status: `pending` (in flight), `done` (shipped), or
    `cancelled` (no longer relevant — merged, scoped out, replaced).

    Format (YAML list under the `tasks:` frontmatter key):

    ```yaml
    tasks:
      - title: <≤ 60 chars, declarative>
        status: pending | done | cancelled
        evidence: <≤ 80 chars, required when status != pending>
    ```

    Hard rules for tasks:
    - **PRIOR titles are sacred — reuse them byte-for-byte.** When the
      input has a `<prior_tasks>` block, every entry inside it is a
      task title already attached to this session's initiative card.
      If your transcript analysis would produce a task that is
      conceptually the same as one of those PRIOR titles — **even if
      a different wording, language, level of detail, or prefix would
      feel more natural** — you MUST copy the PRIOR title verbatim
      into your `tasks:` frontmatter. Do not translate (`重构授权链`
      ↔ "Refactor authorization chain"). Do not retag (`[F1-body] X`
      ↔ `X`). Do not expand (`实现 service doc MVP` ↔ `实现 service
      doc MVP with flag-based slicing`). Do not summarize. Only emit
      a *different* title when the work is genuinely a different
      task, not a synonym. Layer 2 dedups by exact-slug equality;
      every reworded variant becomes a new permanent task entry that
      the user has to manually delete.
    - **Evidence-grounded for non-pending** — for `status: done`,
      cite an edit / merge / "完成" / "shipped" / task_events.completed.
      For `status: cancelled`, cite a user redirect ("算了 / 不做了 /
      合并到 X / 改方案"). One short paraphrase in `evidence:`.
    - **`cancelled` is for AI-visible abandonment**, not for "task
      I haven't looked at in a while." Only emit `cancelled` when a
      turn or a downstream artifact clearly says the task is no
      longer wanted. When in doubt, leave it `pending`.
    - **No padding.** A 10-minute investigation session might propose
      2-3 tasks; a multi-hour build session might propose 6-8.
    - **Cap 8 entries.** If the work clearly spans more, pick the most
      load-bearing 8.

    If the session has no clearly task-shaped contribution, omit the
    `tasks:` key entirely. (Don't write `tasks: []`.)

13. **sealed_segments: split off an EARLIER, FINISHED sub-effort (rare).**
    A long session can pivot topic over time — finish one thing, then
    move on to something else. By default a session maps to ONE piece of
    work, so **OMIT the `sealed_segments` key entirely**. Emit it ONLY
    when ALL THREE of these hold:

    1. An earlier, clearly-distinct sub-effort reached a **terminal**
       state — shipped/merged/abandoned — evidenced by a **concrete
       artifact** (an MR/PR/CR that merged, a commit pushed AND its
       branch merged, or an explicit abandonment "算了 / 不做了"). A
       vague "seems done" is NOT enough.
    2. The session then **pivoted to a distinctly different current
       focus** — different goal, different files/subsystem — NOT a
       continuation or follow-up of the sealed work.
    3. The pivot is unambiguous in `<turns>`, not a momentary digression.

    When you seal:
    - The **top-level** frontmatter (`status_guess`, `artifacts`,
      `tasks`) and all six body sections describe ONLY the **current**
      (later) focus.
    - Each terminal earlier sub-effort goes under `sealed_segments` with
      its own `seg_id` (stable English kebab slug), `title`, `status`
      (`done`|`abandoned` only), `summary`, `sealed_at`, and the
      `artifacts`/`tasks` that anchor it. **Move** those artifacts/tasks
      OUT of the top-level lists into the segment — do NOT list them in
      both places.
    - **Conservatism bar:** when in doubt, do NOT seal. Under-sealing is
      harmless (old behavior); a wrongly-sealed segment mints a phantom
      "done" card the user has to delete.

    **Re-emit sealed segments verbatim (carry-forward).** When the input
    has a `<prior_sealed_segments>` block, every entry there is a segment
    you sealed on a prior run. You MUST re-emit each one **byte-for-byte**
    (`seg_id`, `title`, `status`, `summary`, `sealed_at`, `artifacts`) —
    do not re-translate, re-slug, restyle, reorder, or drop it. A segment,
    once sealed, is immutable. Only ADD a new `sealed_segments` entry when
    a *further* pivot has sealed *another* distinct effort since.

14. **next_step & awaiting_user — the cockpit's two attention signals.**
    These feed an attention dashboard whose whole job is "what needs me, and
    how do I jump back in". Keep them crisp and honest.
    - **`next_step`**: ONE concrete next action for this work — what should
      happen next (≤ 80 chars, imperative). Prefer something actionable, e.g.
      "跑 daily 验证 tri 路由到 12222" / "等 MR 27752189 评审" / "查旧 7 个 ACL
      的持有人数". This is the short structured form of `# 下一步`; keep them
      consistent. Omit the key only when the work is truly finished with
      nothing next.
    - **`awaiting_user`**: emit when the work is **blocked on the human** — the
      ball is in the user's court and the work cannot progress until they act.
      This covers BOTH:
      (a) **a decision/answer/approval the AI needs** — e.g. "确认是否接受仅兼容
          3 个 _ALL ACL" / "选 A 方案还是 B 方案"; AND
      (b) **a hand-off action only the user can perform outside this session** —
          the AI has done its part and the next move is a manual human step it
          cannot do itself: run a prod/DB-platform SQL, click deploy/发布, merge
          /approve a CR, flip a config switch on a console, etc. e.g. "去数据库
          平台执行 ALTER 发布 step 3" / "在发布单点确认上线" / "合并 CR 27724957".
      The test is **WHO performs the next action**: if only the human can (or
      must decide), emit `awaiting_user` with that specific one-liner. If the AI
      will just do it next turn (run tests, grep code, write a patch), do NOT
      emit — that's a plain `next_step`. This is the strongest signal in the
      cockpit (drives the 需要你 band), so don't emit it for "I could ask but
      don't need to" or routine FYIs. When the next step is genuinely a manual
      user action, it IS awaiting_user even if the AI never literally asked a
      question. If you emit `awaiting_user`, `status_guess` must be `active`
      (not `done`); and `next_step` should usually echo the same hand-off action.

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
You are doing cross-session classification. Group session summaries
into "initiatives" (logical pieces of work), maintain continuity with
the prior round, and respect the user's tombstones.

Each session summary is a structured markdown you can trust — Layer 1
has already extracted the narrative. **Your job is grouping and
continuity, not synthesis from raw conversation.**

Output STRICT JSON. No code fences, no preamble, no postscript.

# Inputs (XML-tagged blocks)

- `<context>` — `output_lang` (zh-CN | en) and `now` (ISO timestamp).
- `<prior_mindmap>` — previous round's `mindmap.json`. May be absent
  on first run.
- `<deleted_ids>` — JSON `{"deleted_initiative_ids": [...]}`. May be
  absent.
- `<hot_summaries count="N">` — N session summaries, each a complete
  markdown file with YAML frontmatter (session_id, cwd,
  last_activity_at, user_turns, updated_at, status_guess) and seven
  H1 sections. These are sessions active within the last 48 hours.

**Sessions NOT in `<hot_summaries>` but referenced in `<prior_mindmap>`
are "cold". They still exist; you must keep their initiatives in
output, with restricted modifications (see rule §5).**

# Output schema

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

# Hard rules (violations = bugs)

## §1 — `session_id` is full UUID

Always copy the full UUID. Never truncate to 8 chars. Wrong:
`"sessions": ["cbbeb23c"]`. Right:
`"sessions": ["cbbeb23c-b6f9-4eb4-926e-7e4046c856d4"]`.

## §2 — Reuse PRIOR ids verbatim

For any initiative whose work is continued, use the existing `id`
from PRIOR_MINDMAP exactly as-is. Don't rename ids even if the `name`
should be polished. Match by conceptual identity, not exact name.

## §3 — DELETED_IDS are tombstones

Never include any id from `deleted_initiative_ids` in output. Even if
a hot session would naturally belong to that initiative, you must
either (a) skip the session, or (b) create a NEW initiative under a
different id. Never resurrect a deleted id.

## §4 — Terminal statuses are monotone (AI-side)

If PRIOR has a task with `status: done` or `status: cancelled`, the
same task in output MUST keep that status. Never flip
`done → pending`, `cancelled → pending`, or between `done` and
`cancelled`. (Even if you think the original terminal status was
wrong.) Only the user can revive a terminal task — that happens via
`task_toggles` in `user_overrides.json`, not via your output.

## §5 — Cold initiative rule ⚠️ CRITICAL

An initiative is **cold** if it exists in PRIOR_MINDMAP but **none of
its `sessions[]` appear in HOT_SUMMARIES**.

For cold initiatives you may ONLY change:
- `status` (per the decay rule below)
- `last_activity_at` (only if needed; usually keep PRIOR value)

You must NOT change (must be byte-identical to PRIOR):
- `name`
- `summary`
- `progress`
- `tasks` (the whole array, every entry, including order)
- `sessions[]`
- `linked_cwds[]`
- `id`
- `artifacts[]` (whole array, byte-identical)
- `blockers[]` (whole array, byte-identical)

No "small polish". No "I'll just clean up the wording." This rule is
absolute.

**Status decay for cold initiatives**, based on `last_activity_at` vs
`now`:

| Time since last_activity_at | new status |
|---|---|
| < 3 days | keep `active` (unchanged) |
| 3 to 14 days | `paused` |
| > 14 days, no resume signal in PRIOR | `archived` |
| Already `done` | stay `done` |

## §6 — Workspace decision

- **Single-cwd initiative**: workspace name = the cwd's folder basename
  (e.g., `/Users/bby/Code/hsf/hsfops` → workspace `hsfops`).
- **Multi-cwd initiative**: set `linked_cwds` to the secondary cwds.
  Pick workspace by **semantic ownership**, not activity volume:
  "Which area is this work fundamentally about?"
  Example: a Claude Skill effort touching frontend + backend + skill
  files belongs to workspace `skills`, even if more commits landed in
  the frontend repo.

## §7 — Status of HOT initiatives

> **Note (mechanical safety net).** Post-process
> `enforce_hot_initiative_status` in classify.py applies the rule
> below deterministically for any hot initiative, **overwriting your
> output unconditionally**. So your emitted `status` for hot inits is
> advisory only — the post-process is the source of truth. Do NOT
> carry `PRIOR.status = done` forward when a hot session has reset
> the picture; the post-process will catch you and flip it back to
> whatever `status_guess` says. Still emit your best read, but know
> that the deterministic version wins.

For initiatives that DO have a hot session:
- Read each hot session's frontmatter `status_guess`.
- If the most-recent (by `last_activity_at`) session says `done`, set
  initiative `done`. If any session says `paused` or `abandoned`, lean
  `paused` unless another session is `active`. Otherwise `active`.

## §7a — Aggregate artifacts (hot initiatives only)

> **Note (mechanical safety net).** Post-process `aggregate_artifacts`
> in classify.py now does the union/dedup deterministically from PRIOR +
> hot session frontmatter + your output. You **cannot delete** an
> artifact by omitting it — the post-process re-adds anything you
> dropped. Once an artifact's status reaches `merged|closed|wontfix|
> released|stale|rolled-back|pushed`, it is **frozen** and cannot
> revert. Identity fields (`type`, `ref_id`, `url`, `title`) are also
> frozen to their earliest non-empty value across PRIOR + hot sessions.
> Only the user, via `hidden_artifacts` in `user_overrides.json`, can
> remove an artifact from an initiative.
>
> Still emit a best-effort `artifacts[]` per the rules below; the
> post-process trusts your output for genuinely-new entries and for
> forward status progression, but won't honor deletions or reverts.

For an initiative with at least one hot session, build `artifacts[]` as
the union of:

1. The artifacts already in PRIOR.initiative.artifacts (if any), and
2. The `artifacts:` frontmatter from every HOT session belonging to
   this initiative.

Dedup rules:

- **Primary key is `url` when both entries have one.** Otherwise fall
  back to (`type`, `ref_id`). Same artifact → one entry.
- **Never synthesize a URL.** If a hot summary's artifact has only
  `ref_id` (no `url`), keep it that way in the output — don't try to
  build a URL from the ref_id and the pattern table. (The Layer 1
  prompt has the same rule. URL pattern tables are for recognizing
  URLs in transcripts, not for constructing them.)
- **`url` field, if present, must be non-empty and start with
  `http://` or `https://`.** If you'd otherwise emit an empty
  string, omit the key.
- **Status: most-recent-wins, terminal-monotone.** Use the `status`
  from whichever source has the more recent `last_mentioned_at`. If a
  hot session shows the same artifact with `status: merged` but PRIOR
  shows `pending`, the new status is `merged`. **Never** revert a
  terminal status to an open one — that's a post-process invariant
  and your output will be clamped if you try.
- **Title/ref_id**: prefer non-null, then prefer the most recent
  mention.
- **last_mentioned_at**: max of all sources.
- **Cap 20 entries** per initiative. If exceeded, drop the oldest
  `last_mentioned_at` first.
- **Order**: sort by status priority (pending|open > approved > merged
  > closed > unknown), then by `last_mentioned_at` desc.

If both PRIOR and hot sessions yield zero artifacts, omit the
`artifacts` key entirely (do NOT emit `[]`).

## §7b — Aggregate blockers (hot initiatives only)

For an initiative with at least one hot session, build `blockers[]` as
the union of `blockers:` from every HOT session belonging to it.

- **Dedup**: identical or near-identical strings count once. If two
  blockers differ only by capitalization/whitespace, treat as same.
- **Resolved blockers**: if the **single most recent** hot session in
  this initiative does NOT mention a blocker (string match) AND that
  session's `# 当前状态` mentions resolution ("CI 通过 / approved / 已
  merge"), DROP that blocker. Otherwise keep it.
- **Cap 8 entries**. Drop the longest strings first.

If empty, omit the `blockers` key.

## §7c — Aggregate tasks (hot initiatives only)

**Tasks are append-only from your perspective.** You may add new
tasks (with hot-summary evidence) and you may flip a task's `status`
from `pending` to either `done` or `cancelled` (with §7d evidence).
You may **NOT** drop a task, hide a task, or shrink the task list.
A task's only path off an initiative is through the user clicking
🗑️ in the UI — that goes through DELETED_IDS, never your output.

For each hot initiative, the `tasks[]` you emit must include:

1. **Every PRIOR task for this initiative** — carry them all forward,
   regardless of `status`, even if no hot summary mentions them. They
   represent decisions / work plan already accepted; you don't have
   permission to revoke.
2. **New tasks from hot session summaries** — each session in this
   initiative's `sessions[]` has its own `tasks:` frontmatter; add
   anything not yet in PRIOR.
3. **PRIOR continuations** — for a PRIOR task that's being described
   anew (possibly reworded or translated), emit it WITH its PRIOR
   `id` field set so post-process recognizes it as the same task
   (instead of inserting a duplicate under a new slug).

Hard rules:

- **Reuse PRIOR's `id`** when a hot summary's task is semantically
  the same as a PRIOR task. Reworded titles, translations
  (中文 ↔ English), or expanded wordings all count as "same" if the
  conceptual action is the same.
- **Terminal statuses are monotone** (§4): once a task is `done` or
  `cancelled` in PRIOR, it stays that way in output. Post-process
  preserves the terminal status even if you forget to emit it.
- **No visible cap.** Emit every PRIOR task plus every new
  hot-summary task. The UI folds completed/cancelled tasks inline,
  so quantity is cheap.
- **Output `tasks[]` count ≥ PRIOR `tasks[]` count.** A shrinking
  count is the canonical signal that you tried to drop a task —
  post-process will detect this and refuse the write.

If neither PRIOR nor any hot summary has tasks for this initiative,
omit the `tasks` key entirely (do NOT emit `[]`).

## §7d — Flip PRIOR pending tasks to terminal status from hot evidence

For each PRIOR `status: pending` task in a hot initiative, examine
the hot summaries' content (their `# 当前状态` / `# 已下的决定` /
`# 产物` sections, plus their `tasks:` frontmatter) and decide
whether that specific task is now terminal — either **done** or
**cancelled**.

### Done

A PRIOR task X is **done** only when a hot summary clearly states
the corresponding work shipped — MR merged, feature deployed, tests
green, an explicit "X 完成 / done / shipped" phrasing that
unambiguously refers to X (or a clear paraphrase). Lone words like
"完成了" without referent don't count.

### Cancelled

A PRIOR task X is **cancelled** when a hot summary clearly states
the work was abandoned, deferred, or absorbed into something else:
- "算了 / 不做了 / 改方案" with X in clear reference
- "合并到 <other task>" — X has been merged into another initiative
  task; the surviving task continues, X becomes cancelled with
  `evidence: "merged into <other task title>"`
- "scoped out / dropped / redirected" — explicit redirect in the
  latest turn

Cancellation also handles the "duplicate consolidation" case: if
two PRIOR tasks describe the same conceptual work (slight wording
drift that slipped past slug-dedup), you may keep one and mark the
other `cancelled` with `evidence: "merged into <surviving title>"`.

### How to emit

Whether marking `done` or `cancelled`:
- Use PRIOR's `id` for the task (so post-process recognizes it as a
  continuation, not a new task)
- Set `status` to the new terminal value
- Add an `evidence` field: ≤80 chars, brief paraphrase or short
  quote from the hot summary explaining WHY. This becomes the audit
  trail in the UI tooltip.

**If the evidence is ambiguous, DON'T flip.** Terminal-monotone
makes the flip irreversible from the user's normal flow. Over-eager
completion or cancellation leaves the user with mis-stated tasks
they then have to manually un-toggle. When in doubt, leave it
`pending`.

Example (done):
- PRIOR: `{"id": "implement-online-offline-is-online-commands",
           "title": "Implement online/offline/is-online commands",
           "status": "pending"}`
- Hot summary's # 当前状态: "三个命令 (online/offline/is-online)
  已实现完毕,MR 27411369 已合并。"
- → Emit `{"id": "implement-online-offline-is-online-commands",
            "title": "实现 online/offline/is-online 命令",
            "status": "done",
            "evidence": "MR 27411369 已合并,三个命令实现完毕"}`

Example (cancelled / merged):
- PRIOR: two tasks: `{"id": "fix-eagleeye-trace", "title": "修复
  EagleEye 链路追踪"}` and `{"id": "patch-eagleeyehttphook",
  "title": "Patch EagleEyeHttpHook parameter"}` — same work.
- Hot summary's # 已下的决定: "走 EagleEyeHttpHook 参数补丁方案"
- → Keep `patch-eagleeyehttphook` as `pending`; emit
  `{"id": "fix-eagleeye-trace", "status": "cancelled",
    "evidence": "merged into Patch EagleEyeHttpHook parameter"}`

## §8 — `level`: thread / card / chip (DD-014)

> **Note (mechanical override).** Post-process `enforce_level_ceiling`
> in classify.py **overwrites** your emitted `level` with a value
> derived purely from the initiative's own signals (session count,
> task count, artifacts, blockers). AI's emit is advisory only and
> typically ignored — the first real-data v3 run had AI declare every
> initiative a `thread`, which the mechanical layer corrected. Emit a
> plausible value for narrative consistency, but don't expect it to
> survive to the dashboard.

Each initiative carries a tier label that shapes its rendering on the
dashboard. Choose the value that matches the initiative's apparent
weight, using the signals below.

| level | when to pick |
|---|---|
| `thread` | Multi-session arc (`len(sessions) ≥ 3`) OR substantial task list (`≥ 8` tasks) OR clearly a long-running theme that has hosted multiple distinct work units. |
| `card`   | The default. A single substantive work unit: one focused session, a meaningful goal, some tasks or artifacts. |
| `chip`   | Genuinely small. 1 session, ≤ 5 user turns, ≤ 1 task, no artifacts, no blockers, no decisions of note. A quick lookup or a one-off question that doesn't deserve a full card. |

Hard rules for `level`:
- **PRIOR is the floor.** If PRIOR says `card`, never emit `chip`. If
  PRIOR says `thread`, never emit `card` or `chip`. Post-process will
  restore PRIOR if you try to lower.
- **First-round chip.** For an initiative not in PRIOR, emit `chip`
  unconditionally — even if signals suggest `card`. The post-process
  layer also enforces this; you're agreeing in advance so the diff is
  cleaner.
- **Promotion needs evidence.** A `chip` only becomes a `card` when
  fresh hot-session signal genuinely grows the initiative (new tasks,
  new artifacts, more turns). A `card` only becomes a `thread` when
  the initiative spans 3+ sessions OR accumulates a substantial task
  list.
- **No demotion.** AI never emits a smaller level than PRIOR. Only
  the user, via UI action, can demote. Post-process will revert.

## §9 — `parent_thread_id`: optional thread membership

When an initiative is `level: card` or `level: chip` and conceptually
belongs to a sibling `level: thread` initiative in the SAME workspace,
set `parent_thread_id` to that thread's `id`. Otherwise emit `null`.

Hard rules:
- Only point at an initiative that is also in your output with
  `level: thread`, AND in the same workspace. Cross-workspace links
  are not allowed; post-process clears them.
- A `level: thread` initiative MUST have `parent_thread_id: null` —
  threads are themselves the top of the hierarchy.
- Once set in PRIOR, `parent_thread_id` is stable: AI may change it
  only when the thread itself was removed or the membership clearly
  no longer fits (a hot session has shifted the work into a different
  theme). When in doubt, preserve.

# Output language

All natural-language fields in `output_lang`:
- `workspace.name`
- `initiative.name`, `initiative.summary`, `initiative.progress`
- `task.title`
- `artifact.title`
- `blockers[]` (strings)

Tech terms — HSF, MR, IP, OAuth, branch names, file paths, command
names — stay in English even in Chinese mode. Identifiers and
machine fields are always English/raw regardless of `output_lang`:
- `id`, `cwd`, `session_id`
- `status` enum values (active/paused/done/archived)
- `artifact.type`, `artifact.url`, `artifact.status`,
  `artifact.ref_id`, `artifact.last_mentioned_at`
- `task.status`, `task.terminal_at`

When you see PRIOR or a hot summary using a different language for a
natural-language field, **rewrite it to match `output_lang`**. Do not
preserve the original. Mixed-language titles defeat downstream
slug-based dedup and produce duplicate task entries for the same
work.

# Workflow

1. **Carry forward all PRIOR initiatives** (minus DELETED_IDS).
   Skip none.
2. For each initiative in PRIOR, decide hot vs cold (any of its
   sessions appear in HOT_SUMMARIES?).
   - Hot → you may update `progress`, refresh status from hot session
     signal, aggregate `artifacts[]` per §7a, `blockers[]` per §7b,
     and `tasks[]` per §7c. For each PRIOR pending task, apply §7d
     (flip to `done` or `cancelled` only with clear evidence). Add
     new sessions if any.
   - Cold → apply §5 mechanically. Touch only `status` (decay rule).
     `artifacts[]` and `blockers[]` stay byte-identical.
3. **Discover new initiatives** from HOT_SUMMARIES whose
   `session_id` is not in any existing initiative's `sessions[]`.
   For each, create a new initiative with a stable slug-style `id`,
   and emit `level: "chip"` regardless of size (§8 first-round rule).
4. **Group** new initiatives into workspaces per §6.
5. **Assign `level`** per §8 — PRIOR floor, first-round chip, promote
   with evidence, never demote. Set `parent_thread_id` per §9.
6. **Sort** initiatives within each workspace by `last_activity_at`
   desc; sort workspaces by max last_activity_at desc.

# Pre-flight self-check (do this before emitting)

For your output, verify each of:

- [ ] Every initiative id from PRIOR (minus DELETED_IDS) appears in output.
- [ ] No id in DELETED_IDS appears in output.
- [ ] Every `sessions[]` entry is a full UUID (36 chars with hyphens).
- [ ] Every hot session_id (from HOT_SUMMARIES) appears in some
      initiative's `sessions[]`.
- [ ] No task `status` reverted from terminal (`done`/`cancelled`) to
      `pending` vs PRIOR, and no flip between `done` and `cancelled`.
- [ ] Every `status` value is one of `pending | done | cancelled` —
      no legacy `done: true|false` booleans, no other strings.
- [ ] Cold initiatives' name/summary/progress/tasks/artifacts/blockers
      unchanged.
- [ ] Every `artifacts[]` entry has either a non-empty `http(s)://` URL
      OR a `ref_id` (or both). An entry with no `url` and no `ref_id`
      is useless and must be dropped.
- [ ] Where `url` is present it starts with `http://` or `https://` and
      contains the actual URL from a hot summary, never a synthesized
      one built from an ID + pattern.
- [ ] No duplicate `artifacts[]` entries within one initiative (dedup by
      `url` if both have one, else by (`type`, `ref_id`)).
- [ ] `blockers[]` strings are short (≤ 80 chars each) and deduped.
- [ ] `tasks[]` items came from a hot summary or are PRIOR continuations
      with explicit `id` (no inventions); no two entries share the
      same `id`. Reworded titles for the same conceptual task carry
      PRIOR's `id`.
- [ ] Every `pending → done` or `pending → cancelled` flip from PRIOR
      carries an `evidence` field with a short quote/paraphrase.
- [ ] **`tasks[]` length ≥ PRIOR `tasks[]` length (DD-011 invariant).**
      You cannot drop a task. If a shrink looks justified, leave it
      to the user to delete via the UI — never delete via your output.
- [ ] **Every initiative has a `level` field** with value
      `thread`, `card`, or `chip` (DD-014).
- [ ] **`level` never lowered from PRIOR.** chip→card→thread only;
      no card→chip, no thread→card.
- [ ] **Newly-discovered initiatives emit `level: "chip"`** regardless
      of size signals (§8 first-round rule).
- [ ] **`parent_thread_id`** is either `null` or the id of a
      `level: thread` sibling in the SAME workspace. Threads themselves
      always emit `parent_thread_id: null`.

If any check fails, fix and retry. **Never emit broken output**.

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
# Task: consolidate duplicate tasks on one initiative

You are given a list of **pending tasks** that have accumulated on a
single initiative card. Across many runs of the upstream summarizer,
the same conceptual task has been re-emitted under slightly different
wordings — translations (`重构授权链` ↔ "Refactor authorization
chain"), prefix tags (`[F1-body] X` vs `X`), expansion (`实现 service
doc MVP` vs `实现 service doc MVP with flag-based slicing`), or
synonym swaps. The user wants the list collapsed: one survivor per
conceptual cluster, every other variant marked `cancelled` with
evidence pointing at the survivor.

## Input (in the `<tasks>` block below)

A YAML list of task titles. Each entry is one pending task currently
on the card.

## Output

A single JSON object — no markdown fence, no prose. Schema:

```json
{
  "groups": [
    {
      "keep": "<exact title to keep, copied byte-for-byte from input>",
      "cancel": [
        { "title": "<exact title to cancel>",
          "reason": "<≤ 60 chars: short note pointing at the survivor>" }
      ]
    }
  ]
}
```

## Rules

1. **Only group titles that mean the same conceptual task.** When
   uncertain, leave them alone — false positives that erase real
   work are catastrophic. False negatives (failing to merge two
   genuinely-identical entries) are recoverable.

2. **Keep the most canonical title as the survivor.** Prefer:
   - Shorter to longer when both describe the same step.
   - Title without `[F1-body]` / `[draft]` prefix to title with it.
   - The user's apparent first language (mostly Chinese in this
     project) over a translated variant.
   - More specific over vaguer when both clearly describe the same
     work (e.g. `添加单测与 e2e` over `添加测试`); BUT prefer vaguer
     when the specific variant just adds noise (`实现 service doc
     MVP` over `实现 service doc MVP with flag-based slicing`).
   - Status: if any candidate already has a `(done)` or `(cancelled)`
     marker in its title text, keep that one — terminal state is
     load-bearing.

3. **Every `keep` and every `cancel.title` MUST be copied verbatim
   from the input.** No paraphrasing — Layer 2 dedups by exact-slug
   equality and the cancellation flows through user_overrides keyed
   by title.

4. **Singletons stay singletons.** A task with no semantic duplicate
   in the list should not appear in the output at all (no group of
   one).

5. **`reason` is for the user**, who will see this in the preview
   before confirming. Be specific: "duplicate of '<keep>'" beats
   "redundant". For language variants: "Chinese form of '<keep>'".
   For tagged variants: "untagged form of '<keep>'".

6. **Limit groups to ≤ 12.** If more clusters exist, return the 12
   most confident ones. The user can run consolidate again afterward.

7. **Empty result is fine.** If the input has no duplicates, return
   `{"groups": []}`.

## Worked example

Input:

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

Output:

```json
{
  "groups": [
    {
      "keep": "重构授权链",
      "cancel": [
        {"title": "推进 ServiceTestAuthorizationService 重构",
         "reason": "specific phrasing of '重构授权链'"},
        {"title": "Refactor authorization chain",
         "reason": "English translation of '重构授权链'"}
      ]
    },
    {
      "keep": "实现 service doc MVP",
      "cancel": [
        {"title": "实现 service doc 命令 MVP",
         "reason": "same step worded with '命令'"},
        {"title": "实现 service doc MVP with flag-based slicing",
         "reason": "implementation detail tacked onto '实现 service doc MVP'"}
      ]
    }
  ]
}
```

`添加测试` and `OpenAPI 接口设计` are not in any group — they're not
clear duplicates of anything in this small example.

## What not to do

- Don't merge tasks just because they share a topic ("test" / "OpenAPI"
  / "rebase"). They must be the *same step*.
- Don't reword the kept title.
- Don't invent task titles that aren't in the input.
- Don't output anything except the JSON object.

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
    """Build the prompt for /api/suggest: this session's近况 + a GLOBAL snapshot
    of other active cards (the cross-session perspective the built-in single
    suggestion lacks) → ask for 2-3 distinct ready-to-send next messages."""
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
    """The instruction wrap around the structured signal.

    Critical principle: AI writes prose FROM the JSON, doesn't invent
    facts beyond it. Every claim in the report must trace to a signal.
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

    return f"""You are writing a weekly work summary for one developer.
The week is {signal_json['week_label']} ({signal_json['week_start']} —).

Structure your output as markdown with these sections (translate
section names if writing in zh-CN):

  ## Highlights
    3–6 bullets covering the most impactful events of the week.
    Anchor on archived_this_week + tasks_done_this_week +
    new_artifacts_this_week (esp. MR/PR with status:merged).

  ## Active initiatives
    For each item in active_initiatives, one line: name + status +
    a short paraphrase of progress. Group by workspace if it helps.

  ## Shipped / Closed
    Recap archived_this_week + tasks_done_this_week as a bulleted
    list. If empty, write "(no items this week)" once for the
    section.

  ## Scope changes
    From tasks_cancelled_this_week, list tasks that were cancelled
    or merged into other tasks. Cite the evidence field briefly
    (e.g. "Merged into X" or "Scoped out per turn"). Skip the
    section if the list is empty.

  ## Notable artifacts
    From new_artifacts_this_week, list MR/PR/issue/doc links worth
    referencing. Skip if the list is empty.

  ## Sessions touched
    A single line: "N sessions across M workspaces" — pull these
    counts from hot_sessions. Brief.

Style rules:
  - No preamble, no postscript ("Hope this helps", etc.).
  - Tech identifiers (HSF, MR numbers, branch names, file paths)
    stay in English even in zh-CN.
  - Quote artifact URLs as inline markdown links.
  - {lang_block}
  - Keep total length to ~30 lines or less.

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
    return f"""Given these in-flight initiatives, pick the 3 the user
should focus on NEXT.

Selection heuristics (in priority order):
  1. Fresh momentum: recent active status with pending tasks the
     user can act on alone.
  2. Blocked-but-unblockable: blockers that look user-actionable
     (e.g. "等用户确认"), not external (e.g. "等 CodeOwner 评审").
  3. Low-effort cleanup: small initiatives with 1–2 pending tasks
     and an open MR/PR.

Avoid initiatives whose blockers are clearly external (waiting on
reviewer, CI, ops). Avoid done/archived.

Return STRICT JSON of the form:
  {{"items": [
    {{
      "init_id": "<id from input>",
      "reason": "<short, concrete justification ≤60 chars>"
    }},
    ...
  ]}}

Exactly 3 items if there are 3+ candidates; fewer if not. {lang_block}

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
    """Ask for 20 tips with intentionally uneven split: curiosity 8,
    wisdom 6, work 3, rest 3 (rounded to 20). recent_history is the
    flat list of recent tip texts so AI can avoid repetition."""
    work_block = (
        f"Work patterns observed in user's current data:\n"
        f"{json.dumps(work_patterns, indent=2, ensure_ascii=False)}"
        if work_patterns
        else "No work patterns surfaced this round — emit 0 `work` tips. "
             "Backfill the 3 work slots into `curiosity` so the total stays "
             "at 20 (curiosity becomes 11, wisdom 6, rest 3, work 0)."
    )
    recent_block = (
        f"\nRECENTLY SHOWN (avoid repeating these texts):\n"
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
            "All 20 in English. Tone: warm, conversational, never preachy. "
            "Each ≤ 90 chars."
        )
        kind_examples = """
- work (3 tips): data-anchored advice citing a specific initiative / number.
  No source_url needed.
- wisdom (6 tips): a real quote or piece of life wisdom. **Bias toward
  calm / scenic / observational tones — landscape, seasons, daily-life
  reflection.** Avoid hustle-mode "seize the day" motivational lines.
  Attribution must be verifiable; include source_url pointing to
  Wikipedia / Wikiquote / primary text.
- rest (3 tips): gentle break reminder. Common-sense items don't need
  a URL, but never push unproven health claims.
- curiosity (8 tips): a small surprising fact about life / language /
  programming / science / history. EVERY curiosity tip MUST include
  a source_url (Wikipedia, Etymonline, Stanford Encyclopedia, MDN,
  official docs). If you cannot find a credible source for a claim,
  drop the tip — don't fabricate. Avoid widely-repeated-but-false
  trivia (e.g. the myth that ducks' quacks don't echo — debunked).
"""

    return f"""Generate TWENTY short tips for a developer's dashboard.
Intentionally uneven split: curiosity gets the most rotation slots,
wisdom second, work / rest equal and small.

Default split:
  - curiosity: 8
  - wisdom:    6
  - rest:      3
  - work:      3
  Total:      20

Categories:
{kind_examples}

Return STRICT JSON. Structure (order doesn't matter — counts do):
  {{
    "tips": [
      {{"kind": "curiosity", "text": "...", "source_url": "https://..."}},
      ... 8 curiosity entries total — source_url REQUIRED ...
      {{"kind": "wisdom",    "text": "...", "source_url": "https://..."}},
      ... 6 wisdom entries total — source_url REQUIRED ...
      {{"kind": "rest",      "text": "..."}},
      ... 3 rest entries total — source_url optional ...
      {{"kind": "work",      "text": "...", "pattern": "<id-from-input>"}},
      ... 3 work entries total — no source_url ...
    ]
  }}

Hard rules:
- Aim for the split above. If you cannot fill a category with that
  many *verifiable* entries (curiosity / wisdom), emit fewer in that
  category and add the surplus to curiosity. Floor: 14 tips total.
- {lang_block}
- **No fabrication.** Every factual claim must be traceable. If you
  are unsure whether a quote is correctly attributed, a fact is true,
  or a URL exists, DROP the tip. Better a sparse round than a wrong
  one.
- `source_url` is REQUIRED on every `curiosity` tip and every `wisdom`
  tip. The URL must be one you have high confidence is real and
  on-topic. Prefer canonical references:
    * Wikipedia / Wikiquote (zh.wikipedia.org / en.wikipedia.org)
    * Etymonline.com for word origins
    * Plato.stanford.edu for philosophy
    * MDN / official language docs for programming history
    * Standards bodies for science/math facts
  If you can't find a stable canonical URL, drop the tip.
- Every `work` tip MUST cite specific data from the patterns block —
  a concrete initiative id, MR number, blocker count, etc. Skip
  `source_url` (work tips are grounded in the user's own data).
- Within a category, all tips must be meaningfully different —
  different angle, mood, era, reference, or topic. Don't write
  near-duplicates.
- No generic platitudes ("take care of yourself", "stay focused").
- No identical or near-identical text to RECENTLY SHOWN entries.

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
        "Reply in English, 1–2 sentences, warm but not preachy. "
        "Cite specific numbers ('5 sessions ended past 22:00'). "
        "A touch of humor is OK."
    )
    return f"""The user works heavily and the following patterns have
appeared in their recent activity. Write ONE short, warm message
reminding them that sustainable pace matters. The message must
reference the specific number(s) from the patterns — never generic
"take care of yourself" advice.

Return STRICT JSON:
  {{"pattern": "<chosen pattern id>", "message": "<your text>"}}

If multiple patterns fired, pick the one with the strongest signal.

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
You are analyzing a developer's Claude Code session history to produce a
hierarchical mindmap of their recent work.

You will receive **up to three inputs**:

1. **PRIOR_MINDMAP** (optional) — the previous mindmap output. Use it as
   your baseline; preserve continuity. Details in the "Continuity rules"
   section below. May be absent on first run — then build fresh.

2. **DELETED_IDS** (optional) — a JSON object with key
   `deleted_initiative_ids`. These are initiative IDs the user has
   explicitly deleted. They MUST NOT appear in your output, even if
   INPUT_SESSIONS contains fresh evidence for them. The user wants them
   gone; respect that. (If you see evidence for a deleted ID, you may
   create a NEW initiative under a different `id` for that work — but
   the deleted ID itself stays out.)

3. **INPUT_SESSIONS** — a JSON array of session summaries (described
   next), representing recent work to classify.

Each session summary has:
- `session_id`: unique session identifier
- `cwd`: working directory of the session
- `started_at` / `last_activity_at`: timestamps
- `message_count`: total messages exchanged
- `first_user_prompt`: the opening request (may be truncated) — describes
  *what the user set out to do*
- `recent_user_prompts`: up to 3 most recent user prompts — describes
  *where the conversation currently stands / what's being asked right now*
- `last_assistant_summary`: first paragraph of the most recent assistant
  text reply — often an explicit "here's what I did" summary
- `edited_files`: files touched by Write/Edit tool calls — concrete
  evidence of what was built or changed
- `task_events`: TaskCreate/TaskUpdate events ("created: …",
  "completed: #id", "in_progress: #id") — a live progress log when the
  user relies on the task tool
- `recap`: Claude Code's native session recap if available (authoritative)
- `tools_used`: tool names invoked during the session

**Trusting the signals (in order of authority)**:
1. `task_events` with `completed:` — highest confidence "this got done"
2. `edited_files` — if a file was written, that work happened
3. `last_assistant_summary` — usually reflects the most recent state
4. `recent_user_prompts` — what the user is currently focused on; PREFER
   this over `recap` when the user's latest prompt clearly moves the
   work past what the recap describes (e.g. recap says "still
   investigating" but a recent prompt says "let's file the issue" — the
   prompt wins)
5. `recap` — useful long-form context but may lag the live conversation
   by hours; treat as authoritative ONLY when no fresher signal exists
6. `first_user_prompt` — only the *original* goal, often stale by now

**Crucial**: do NOT list as a `{done: false}` task something that the
`edited_files`, `last_assistant_summary`, or `task_events` fields clearly
show was completed. Prefer the most recent signal when they conflict.

# Continuity rules (when PRIOR_MINDMAP is present)

**Treat PRIOR_MINDMAP as your starting state and EDIT it in place** based
on INPUT_SESSIONS. Do NOT rebuild from scratch. This is the most
important rule in this prompt — getting it wrong makes every refresh
visually shuffle the user's history.

## Identity preservation

For each prior initiative that still corresponds to ongoing or recent
work, **reuse its `id` and `name` verbatim**. Match by conceptual
identity, not exact wording. The `id` is the stable handle; never mint a
new id for the same effort.

Acceptable name change: only if prior name is clearly wrong or
misleading given new evidence. When you do change a name, keep the `id`.

For each prior task, **preserve its title verbatim** unless the title is
factually inaccurate. Minor wording polish is NOT a reason to rewrite a
task — that creates visual churn.

## Task evolution

- Prior tasks with `done: true` MUST stay `done: true`. Work that happened
  doesn't un-happen.
- Prior tasks with `done: false`: check INPUT_SESSIONS for completion
  evidence (task_events `completed:`, edited_files, recap, summary). If
  completed → flip to `done: true`. Otherwise keep as `done: false`.
- Add NEW tasks only when INPUT_SESSIONS surfaces new concrete work not
  already covered by a prior task.
- Do NOT delete prior tasks. They are history.

## Initiative lifecycle

- Prior initiative with new activity in INPUT_SESSIONS → update its
  `progress`, `status`, `tasks`, `last_activity_at` based on new evidence.
- Prior initiative with NO new sessions in INPUT_SESSIONS → keep it.
  Apply natural status decay based on `last_activity_at`:
  * still within 3 days → keep `active`
  * 3–14 days old → demote to `paused`
  * >14 days old AND status was already `paused` or has no resume
    signal → demote to `archived`
  * `done` stays `done`
- An initiative may SPLIT: if prior had one initiative and new evidence
  shows two clearly distinct narratives, keep the prior `id`/`name` for
  the dominant strand and create a new initiative for the new strand
  (with a new `id`).
- An initiative may MERGE only when prior had two and new evidence
  clearly unifies them — rare, do this only when obvious.

## Workspace structure

- Reuse prior workspace `name` and `cwd` mappings. Don't reshuffle
  workspaces between refreshes unless an initiative clearly migrated
  (e.g. work moved to a new repo).

## Cold start

If PRIOR_MINDMAP is absent, empty, or uses the legacy v1 schema (has
`projects` not `workspaces`), ignore it and classify INPUT_SESSIONS from
scratch.

# Your job

Produce a **three-level hierarchy**:

```
workspace                  (top — usually a repo/codebase)
  └── initiative           (mid — a coherent piece of work inside it)
        └── task           (leaf — concrete, checkable item)
```

## Step 1: Group sessions into INITIATIVES

An **initiative** is a coherent, single-narrative piece of work — e.g.
"ChangeFree service refactor", "App doc version_no migration", "NCS
gateway auth integration". Usually multiple sessions share an initiative.

Rules:
- One `cwd` may contain MULTIPLE initiatives (split if the sessions cover
  distinct goals — e.g. `hsfops` may have both "ChangeFree refactor" and
  "App doc iteration" in parallel).
- An initiative MAY span multiple `cwd`s when sessions in different repos
  clearly serve one narrative (e.g. a feature touching frontend + backend
  + SKILL files all for the same feature).

## Step 2: Group initiatives into WORKSPACES

A **workspace** is the conceptual home of related work — usually a repo
folder name (e.g. `hsfops`, `mw-cli`, `hsf-doc-generator`), but it can
also be a logical area (e.g. `skills`, `claude-code-tooling`).

Rules:
- For initiatives confined to a single cwd: workspace = that cwd's folder
  name.
- For initiatives spanning multiple cwds: choose the **PRIMARY OWNER
  WORKSPACE** by *semantic ownership*, not activity volume. Ask:
  "Which area is this work fundamentally *about*?"
  - Example: a Claude Skill development effort that touches frontend,
    backend, and SKILL definition files belongs under the `skills`
    workspace because that's its conceptual home — even if more commits
    landed in the frontend repo.
  - Example: a feature that adds an API to backend and consumes it in
    frontend, where the feature *is* an API capability, belongs under
    the backend workspace.
- Record other involved cwds in `linked_cwds` on the initiative.

## Step 3: Per-initiative fields

For each initiative produce:
- `id`: stable slug like `hsfops-changefree-refactor` (lowercase, hyphens)
- `name`: short human-readable name (in the OUTPUT_LANG below)
- `status`: one of `active`, `paused`, `done`, `archived`. Rules:
  * `active` — last activity within the past 3 days, work clearly ongoing
  * `paused` — last activity 3–14 days ago, or longer but with a clear
    "resume later" signal (open todos, unfinished MRs, waiting on someone)
  * `done` — explicitly finished: shipped, merged, report delivered, or
    recap/prompt indicates completion
  * `archived` — last activity >14 days ago AND no clear resumption signal.
    Also use this for one-off exploratory sessions, failed experiments,
    throwaway debugging, or anything unlikely to have ongoing value.
  When in doubt between `paused` and `archived`, check whether the work
  produced durable artifacts (merged code, filed issues) — if yes,
  `paused`; if no, `archived`.
- `summary`: 1-2 sentences describing what the initiative is about
- `progress`: 1-2 sentences on the latest state / where things stand
- `tasks`: concrete items with `{title, done}`. **Be GENEROUS — list every
  distinct task you can substantiate** from recaps, task_events,
  edited_files, and prompts. No artificial cap. If 12 distinct tasks are
  supported by evidence, list 12. The downstream UI handles folding.
- `sessions`: list of contributing session_ids
- `linked_cwds`: list of *secondary* cwds when the initiative spans repos
  (omit or empty array if single-cwd)
- `last_activity_at`: most recent timestamp among its sessions

## Step 4: Per-workspace fields

For each workspace produce:
- `name`: workspace name (short, often a folder name)
- `cwd`: the primary/home cwd of this workspace
- `last_activity_at`: max `last_activity_at` across its initiatives
- `initiatives`: list of initiatives, sorted by `last_activity_at` desc

Sort workspaces by `last_activity_at` descending. Within each workspace,
sort initiatives by `last_activity_at` desc.

# Output format

Output **strict JSON only** matching this shape — no prose, no code fences:

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

# Language

`OUTPUT_LANG` will be substituted before the prompt runs. The values of
the following fields MUST be written in that language:
`workspaces[].name`, `initiatives[].name`, `initiatives[].summary`,
`initiatives[].progress`, `initiatives[].tasks[].title`.

If `OUTPUT_LANG` is `zh-CN`: write those fields in Simplified Chinese,
natural and concise (this is a developer's status report, not a translation
exercise). Technical terms (HSF, OAuth, RBAC, SDK, CR, MR, repo, branch,
schema, etc.) may stay in English when that's the natural usage.

If `OUTPUT_LANG` is `en`: write those fields in English.

Other fields (`id`, `cwd`, `status`, `session_id`, timestamps) stay as-is
regardless of language.

# Rules

- Prefer `recap` over `first_user_prompt` when both exist — recaps are
  authoritative.
- Be concise. Summaries should read like a status report, not a transcript.
- If both inputs are empty, output
  `{"schema_version": 2, "generated_at": "...", "workspaces": []}`.
- Never invent sessions, initiatives, or tasks that aren't supported by
  the inputs. The combined input is `PRIOR_MINDMAP ∪ INPUT_SESSIONS` —
  anything in EITHER counts as supported.
- `session_id` values in your `sessions: [...]` output array MUST be the
  full UUID exactly as it appears in INPUT_SESSIONS. DO NOT truncate
  them to a prefix. Wrong: `["cbbeb23c"]`. Right:
  `["cbbeb23c-b6f9-4eb4-926e-7e4046c856d4"]`. The downstream tooling
  matches sessions by exact full id.

# Self-check before emitting

Before you emit JSON, mentally diff against PRIOR_MINDMAP:
- Every prior initiative `id` should appear in your output (possibly with
  updated status / tasks / progress). If you dropped one, you'd better
  have a strong reason — and the reason cannot be "no new sessions for
  it" (use status decay instead).
- Every prior task should appear under its initiative, with the same
  title and a `done` value that is monotone (false→true is allowed,
  true→false is FORBIDDEN).
- New tasks/initiatives should have justification in INPUT_SESSIONS.

``````
