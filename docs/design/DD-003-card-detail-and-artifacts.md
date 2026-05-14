# DD-003: Card Detail — Artifact Extraction & Blocker Tracking

**Status**: Proposed
**Author**: bby
**Date**: 2026-05-14
**Depends on**: [DD-002](DD-002-ai-pipeline-redesign.md) (Layer 1/2 architecture)

中文版（更详细）：[../zh-CN/design/DD-003-card-detail-and-artifacts.md](../zh-CN/design/DD-003-card-detail-and-artifacts.md)

> Make clicking a card reveal that initiative's key artifacts
> (CR/issue/branch links), blockers, decisions, files, and related
> sessions. **Primary problem**: CR links get buried in long
> conversations; users can't find them.

---

## Contents

- [1. Problem](#1-problem)
- [2. Goals](#2-goals)
- [3. What to show in the detail panel](#3-what-to-show-in-the-detail-panel)
- [4. Data model](#4-data-model)
- [5. URL pattern extraction](#5-url-pattern-extraction)
- [6. Status tracking (AI + user hybrid)](#6-status-tracking-ai--user-hybrid)
- [7. UI design (Modal)](#7-ui-design-modal)
- [8. Layer 1 prompt changes](#8-layer-1-prompt-changes)
- [9. Layer 2 prompt changes](#9-layer-2-prompt-changes)
- [10. Phased rollout](#10-phased-rollout)
- [11. Risks](#11-risks)
- [12. Open questions](#12-open-questions)

---

## 1. Problem

### 1.1 Pain point

A typical 1-hour Claude Code debug session ends with several **key
artifacts**:

- Opened a CR `https://code.alibaba-inc.com/.../codereview/27369464`
- Linked issue `#82052410`
- Pushed branch `bugfix/hsf/eagleeye-mtop-server-ip`
- Blocked on: CI + 1 reviewer approve + CodeOwner approve

All these live in the session jsonl, but when the user works across
many sessions, they can't get back to this info. Real workflow today:

```
1. Open HTML dashboard → see card "waiting on CI"
2. Where's the CR link? Card doesn't show it.
3. Resume the session, scroll back through 100+ turns
4. Find the MR number, copy, open in browser
5. (Repeat for each blocked session)
```

### 1.2 Concrete case (EagleEye)

Last week's HSF EagleEye trace IP=null session:

| Info | Where it lives | Card shows it today |
|---|---|---|
| MR number `27369464` | ~80th AI reply in the session | ❌ |
| Full MR URL | same | ❌ (mentioned once in Layer 1 summary "Artifacts" prose) |
| Issue `#82052410` | ~85th turn | ❌ |
| Branch name | ~75th turn | ❌ |
| Blocker list (CI/reviewer/CodeOwner) | Layer 1 "Open questions" | ✅ but requires unfolding the summary |

3/4 critical pieces are **invisible**. Layer 1 already extracted them
but HTML doesn't render them.

### 1.3 Why Layer 1 summary alone isn't enough

`cache/summaries/<sid>.md`'s "Artifacts" section does mention the MR
URL, but:

- It's **free text**; HTML can't render it as clickable link
- No notion of "status" — is the CR pending / approved / merged?
- Embedded in a prose paragraph; high scanning cost

---

## 2. Goals

| Dimension | Goal |
|---|---|
| **Discoverable** | Click card → all CRs/issues/branches visible within 1s |
| **Clickable** | Links are real `<a>` tags, one click opens in browser |
| **Trackable** | CR state pending → approved → merged is explicit |
| **Closable** | User can manually mark state (doesn't depend on AI later sensing) |
| **Extensible** | Adding GitHub PR / Gitlab MR / Jira issue later doesn't change architecture |

**Non-goals**:

- No external API integration (aone API needs tokens + cross-org deploy hard)
- No CR-comment summary / review-progress viz (out of scope)
- No notification system ("your CR was reviewed" push)

---

## 3. What to show in the detail panel

8 categories of info, ranked by value:

| # | Category | Source | Example |
|---|---|---|---|
| 1 | **🚨 Blockers** | Layer 1 extraction + user toggle | "waiting on CI", "waiting for reviewer" |
| 2 | **🔗 Artifacts** (links) | URL pattern + AI tagging | CR #27369464, Issue #82052410 |
| 3 | **🎯 Next step** | Layer 1 summary "Next step" | "wait for CI + 1 approve, then merge" |
| 4 | **🌿 Branch / commit** | URL pattern + extraction | branch name, commit sha, tag |
| 5 | **📄 In-flight files** | extract.py edited_files | EagleEyeHttpHook.java |
| 6 | **🧠 Key decisions** | Layer 1 summary "Decisions" | "skip local UT, commit+push+MR" |
| 7 | **📜 Tasks** | Existing tasks field | 4/8 done |
| 8 | **💬 Related sessions** | initiative.sessions (existing) | + pane info + resume command |

MVP covers 1-3 + 5 + 7 + 8 (mostly reorganizing existing data); 4 falls
out of URL pattern matching; 6 reuses existing summary section.

---

## 4. Data model

### 4.1 Layer 1 summary frontmatter extension

`cache/summaries/<sid>.md` YAML frontmatter gains two new sections:

```yaml
---
# existing fields (unchanged)
session_id: cbbeb23c-…
cwd: /Users/bby/Code/pandora/pandora-sar/hsf
last_activity_at: 2026-05-13T11:10:20Z
user_turns: 21
updated_at: 2026-05-14T12:13:02Z
status_guess: paused

# new fields
artifacts:
  - type: cr
    title: "EagleEye remoteIp fix"
    ref_id: "27369464"
    url: "https://code.alibaba-inc.com/middleware-container/pandora-sar/codereview/27369464"
    status: pending
    inferred: true              # AI guess
    first_mentioned_at: "2026-05-13T10:50:00Z"
    last_mentioned_at: "2026-05-13T11:10:00Z"
  - type: issue
    title: "EagleEye trace IP null"
    ref_id: "82052410"
    url: "https://aone.alibaba-inc.com/v2/project/.../req/82052410"
    status: open
    inferred: true
  - type: branch
    title: "bugfix/hsf/eagleeye-mtop-server-ip"
    status: pushed
    inferred: true

blockers:
  - "waiting for CI to pass"
  - "waiting for at least 1 reviewer approve"
  - "waiting for CodeOwner approve"
---

# Goal
(unchanged)
...
```

**Field semantics**:

- `artifacts[].type`: `cr` | `mr` | `pr` | `issue` | `branch` | `commit` | `tag` | `deployment` | `doc` | `other`
- `artifacts[].ref_id`: platform-specific short id (CR number, issue id, commit sha); for display + dedup
- `artifacts[].url`: full URL when known; may be omitted (e.g., local branch)
- `artifacts[].status`: type-specific enum (see §4.3)
- `artifacts[].inferred`: AI guesses → `true`; user-confirmed sets `false`
- `blockers[]`: free-text strings (not over-structured)

### 4.2 mindmap.json `initiative.artifacts[]` aggregation

Layer 2 unions all artifacts across the initiative's sessions
(dedupe by `url` or `(type, ref_id)`) into:

```json
{
  "id": "hsf-eagleeye-ip-null-issue",
  "name": "HSF EagleEye trace IP-null investigation",
  "status": "paused",
  ...,
  "artifacts": [
    {
      "type": "cr",
      "title": "EagleEye remoteIp fix",
      "ref_id": "27369464",
      "url": "https://code.alibaba-inc.com/.../27369464",
      "status": "pending",
      "inferred": true,
      "user_confirmed": false,
      "source_sessions": ["cbbeb23c-…"],
      "first_seen": "2026-05-13T10:50:00Z",
      "last_seen": "2026-05-13T11:10:00Z"
    }
  ],
  "blockers": [
    "waiting for CI to pass",
    "waiting for at least 1 reviewer approve",
    "waiting for CodeOwner approve"
  ]
}
```

- `source_sessions[]`: which sessions mentioned this artifact (union when
  multiple)
- `user_confirmed`: set true after user manual toggle; AI cannot override

### 4.3 status enums per type

| type | allowed status |
|---|---|
| `cr` / `mr` / `pr` | `pending` / `approved` / `merged` / `closed` / `unknown` |
| `issue` | `open` / `in_progress` / `resolved` / `closed` / `unknown` |
| `branch` | `pushed` / `merged` / `deleted` / `unknown` |
| `commit` / `tag` | `created` / `unknown` |
| `deployment` | `pending` / `succeeded` / `failed` / `unknown` |
| `doc` / `other` | `draft` / `published` / `unknown` |

`unknown` is the default fallback, allowed everywhere; AI is never
forced to produce a non-unknown status.

### 4.4 User override model

`cache/user_overrides.json` gains an `artifact_states[]` field:

```json
{
  "version": 1,
  "task_toggles": [...],
  "deleted_tasks": [...],
  "artifact_states": [
    {
      "initiative_id": "hsf-eagleeye-ip-null-issue",
      "artifact_key": "cr:27369464",
      "status": "merged",
      "dismissed": false,
      "set_at": "2026-05-14T15:00:00Z"
    }
  ]
}
```

- `artifact_key`: `<type>:<ref_id>` or hash(url); stable dedup key
- `status`: overrides AI judgment; on apply, inferred becomes false and
  user_confirmed becomes true
- `dismissed: true`: user marks "not relevant"; UI hides

classify.py applies overrides at the start of each run.
**user_confirmed always beats AI judgment**.

---

## 5. URL pattern extraction

Supported platforms (extensible):

| Platform | Regex | Extracts |
|---|---|---|
| aone codereview | `code.alibaba-inc.com/[^/]+/[^/]+/codereview/(\d+)` | `type=cr`, `ref_id=<id>` |
| aone request | `aone.alibaba-inc.com/v2/project/[^/]+/req/(\d+)` | `type=issue`, `ref_id=<id>` |
| aone task | `aone.alibaba-inc.com/v2/project/[^/]+/task/(\d+)` | `type=issue`, `ref_id=<id>` |
| GitHub PR | `github.com/([^/]+/[^/]+)/pull/(\d+)` | `type=pr`, `ref_id=<id>` |
| GitHub issue | `github.com/([^/]+/[^/]+)/issues/(\d+)` | `type=issue`, `ref_id=<id>` |
| GitLab MR | `gitlab.com/([^/]+/[^/]+)/-/merge_requests/(\d+)` | `type=mr`, `ref_id=<id>` |
| git branch | `(commit|push.*to)\s+([a-zA-Z0-9/_-]+)` | heuristic |
| git commit | `commit\s+([a-f0-9]{7,40})` | `type=commit`, `ref_id=<sha>` |

Strategy:

- **Regex post-process in summarize.py**: after the AI output, scan the
  raw jsonl tail for URLs, ensure no URL is missed.
- **AI fills type / title / status**: Layer 1 prompt tells AI to
  describe URLs it sees in the artifacts frontmatter section.
- **Dedup**: if a regex-found URL matches an AI-found one (by url or
  (type, ref_id)), merge (AI fields preferred).

---

## 6. Status tracking (AI + user hybrid)

### 6.1 AI auto-sensing

Layer 1 prompt addendum:

> When an artifact URL/ref_id appears in the jsonl, look at the
> surrounding turns (±5) for these status signals; update the
> artifact's status accordingly:
>
> - "merged" / "已合入" / "shipped" → status=`merged`
> - "approved" / "approve 了" / "通过了" → status=`approved`
> - "closed" / "abandoned" / "abandon 了" → status=`closed`
> - Otherwise keep prior or default `pending`
>
> Always emit `inferred: true`.

### 6.2 User toggle

HTML modal shows action buttons next to each artifact:

```
CR #27369464  pending  [view↗]  [✓ mark merged]  [✗ dismiss]
```

Behavior:

- `mark merged` → write `cache/user_overrides.json` artifact_states
  `{status: "merged"}`
- `dismiss` → write `{dismissed: true}`; artifact hidden in UI

Next classify.py run applies overrides, sets `user_confirmed: true`
in mindmap.json. AI is now barred from changing this artifact's
status, even if it sees contradicting signals later.

### 6.3 Conflict resolution

```
displayed status = (
    user_confirmed_state if present else
    ai_inferred_state if present else
    "unknown"
)
```

---

## 7. UI design

UI is in two layers:

- **Card surface** — at-a-glance badges/preview line. No click needed.
- **Modal** — click the card to expand into full artifact/blocker/decision
  detail.

### 7.0 Card surface — badges + top-blocker preview

After the status badge in the card header, append:

```
● HSF EagleEye trace IP null investigation  [paused]  23h ago
  🚨 3 blockers  ·  🔗 1 pending CR
```

Rules:

| Badge | Shown when | Form |
|---|---|---|
| `🚨 N blockers` | `blockers.length > 0` | small red chip, N = count |
| `🔗 N pending` | count of `artifacts` with `status ∈ {pending, open, unknown}` AND `type ∈ {cr, mr, pr, issue}` > 0 | small blue chip |
| `✅ N merged` | optional, hidden by default (no longer needs attention) | gray, opt-in |

**Additionally**: under the card's **progress** paragraph, add one line of
"**top-blocker preview**" (when any blocker exists):

```
Progress: …(existing content)

⚠ Blocker (top 1): waiting on CI to pass
```

Show only `blockers[0]` (highest priority). Clicking the badge or this
line → open modal and scroll to the corresponding section (intra-modal
URL anchor).

Rationale: the card is a status-summary surface. Blockers are more urgent
than next-step text and deserve equal visual weight with status/age.

### 7.1 Modal layout

Clicking the card's empty area → centered modal (semi-transparent
overlay + rounded 600px wide, max-height 80vh, scrollable):

```
┌─────────────────────────────────────────────────────────┐
│                                                  [✕]    │
│  HSF EagleEye trace IP null investigation                │
│  📁 pandora/pandora-sar/hsf · ⏸ paused · 23h ago        │
│                                                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  🚨 Blockers (3)                                         │
│    • waiting for CI to pass                              │
│    • waiting for at least 1 reviewer approve             │
│    • waiting for CodeOwner approve                       │
│                                                          │
│  🔗 Key links                                            │
│    📋 CR #27369464  pending  [view↗] [✓merged] [✗]     │
│       EagleEye remoteIp fix                              │
│    🎫 Issue #82052410  open  [view↗]  [✗]               │
│       EagleEye trace IP null                             │
│    🌿 bugfix/hsf/eagleeye-mtop-server-ip  pushed         │
│                                                          │
│  🎯 Next step                                            │
│    wait for CI + reviewer approve, then merge to master  │
│                                                          │
│  📄 Files in flight                                      │
│    • EagleEyeHttpHook.java                              │
│    • /tmp/aone-issue-hsf-eagleeye.md                    │
│                                                          │
│  🧠 Key decisions                                        │
│    • skip local UT, direct commit+push+MR (low risk)     │
│    • commit msg per RELEASE.md §1 to auto-link work item │
│                                                          │
│  📜 Tasks (4/8 done)                                     │
│    ✓ identify root cause                                 │
│    ✓ implement fix                                       │
│    ✓ commit + push                                       │
│    ✓ create MR via a1                                    │
│    ○ CI green                                            │
│    ○ reviewer approve                                    │
│    ○ merge to master                                     │
│    ○ backport to release                                 │
│                                                          │
│  💬 Sessions (1)                                         │
│    cbbeb23c… @ pane 27 (main)                            │
│    [🎯 resume] [📋 copy command]                         │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Interactions

- Click card empty area (excluding existing buttons) → open modal
- Click overlay or ESC → close
- Click artifact `view↗` → open URL in new tab (`target="_blank"`)
- Click `✓ mark merged` → POST `/api/save` artifact_states → toast
- Click `✗ dismiss` → hide artifact, persist
- Click task checkbox → reuse existing task toggle logic
- Click session `resume` → reuse existing Zellij jump

### 7.3 Empty-state degradation

If an initiative has no artifacts or no blockers, the corresponding
section is omitted (not shown as "(none)"). Modal always shows at
least name + status + sessions.

### 7.4 Field priority on tight height

Per §3 priority: blockers first, artifacts second, next step third,
etc.

---

## 8. Layer 1 prompt changes

Append to `prompts/summarize-session.md`:

```
# Frontmatter extras (artifacts + blockers)

In addition to the existing fields, frontmatter MUST include:

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
  - "merged" / "已合入" / "shipped"  → merged (cr/mr/pr)
  - "approved" / "approve 了"        → approved (cr/mr/pr)
  - "closed" / "abandoned"            → closed
  - "Fixed" / "resolved"              → resolved (issue)
  - "merged" near a branch name       → merged (branch)

Always emit inferred: true. The user can override later.
```

Regex post-process in `bin/summarize.py` ensures no URL is missed:
after the AI call, scan the jsonl tail for URLs. If the AI's
artifacts list doesn't cover one, append a minimal-info artifact
(type classified by regex, status=unknown).

---

## 9. Layer 2 prompt changes

Append to `prompts/classify-cross-session.md`:

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

`bin/classify.py`'s `enforce_cold_and_done_monotone` is extended:

- artifacts, blockers arrays for cold initiatives forcibly restored to
  PRIOR
- for hot initiatives, any artifact with `user_confirmed: true` is
  protected from AI overwrite

---

## 10. Phased rollout

### Phase 1 — Layer 1 extraction (smallest commit)

- Modify `prompts/summarize-session.md`: add §8 instructions
- Modify `bin/summarize.py`: YAML emit new fields, regex post-process
- Don't touch HTML, don't touch Layer 2
- Validate: re-run summarize on EagleEye session, confirm `artifacts:`
  populated correctly

**Ship condition**: 3 real sessions produce subjectively good artifacts.

### Phase 2 — Layer 2 aggregation

- Modify `prompts/classify-cross-session.md`: add §9 instructions
- Modify `bin/classify.py`: serialize artifacts/blockers into
  mindmap.json; enforce cold immutability for new fields
- HTML unchanged (mindmap.json grows two fields; old render-html.py
  ignores them)

**Ship condition**: EagleEye initiative in mindmap.json shows
artifacts array.

### Phase 3 — HTML Modal (read-only)

- `bin/render-html.py`: embed artifacts/blockers data
- Add modal HTML + CSS + JS
- Click card → open modal, render all fields
- Artifacts are clickable external links (`<a target="_blank">`); **no
  mark buttons yet**

**Ship condition**: clicking EagleEye card in browser shows CR
#27369464 link.

### Phase 4 — User toggle (artifact_states)

- Modal gains `✓ mark merged` / `✗ dismiss` buttons
- POST `/api/save` writes `cache/user_overrides.json` artifact_states
- `bin/classify.py` apply_user_overrides includes artifact_states
- Display priority: user_confirmed > inferred

**Ship condition**: UI mark merged → next classify, user_confirmed
persisted, AI can't overwrite.

### Phase 5 — AI auto-sensing (optional; defer until Phase 4 in use)

- Add §8 end's status inference signals to Layer 1 prompt
- After Phase 4 has run for a week, decide whether AI auto-sensing is
  worth the prompt complexity

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| AI misses URL | Regex post-process backstop catches everything |
| AI status wrong | Always `inferred:true`; user can override; UI distinguishes |
| Too many artifacts (>20) | Modal groups by status, collapses; pending first |
| Data bloat (mindmap.json grows) | ~3-5 artifacts × 200 bytes × 200 inits ~ 200 KB. Acceptable |
| Cross-session duplicates | (type, ref_id) dedup; source_sessions records origin |
| User toggle then AI overrides it | Enforce step protects user_confirmed |
| URL pattern coverage gaps | First version covers aone + GitHub + GitLab; rest fall to `type=other` |

---

## 12. Open questions

1. **Modal position**: centered modal vs in-card expansion? Chosen
   modal (user input).
2. **artifacts first_mentioned_at**: jsonl timestamp or AI-inferred?
   Proposed: jsonl timestamp (accurate).
3. **Dismissed artifacts shown grayed or hidden?** Proposed: hidden
   by default, modal-top toggle "show dismissed" for recovery.
4. **CR `view↗` triggers auto-mark prompt?** E.g., 5 min after click,
   ask "did the status change?". Possibly overkill, skip.
5. **External API integration**: GitHub status sync via PAT — defer
   as a separate DD-002 §12.3-compliant extension.
6. **Blockers as checkable tasks?** Like marking "waiting for CI"
   done. Feels like it conflates tasks and blockers. Skip for now.

---

## 13. Relationship to other DDs

- **DD-002 §12.3 contract**: this design **extends trunk data schema**
  (mindmap.json + summaries gain fields), so per the contract this
  requires a DD-N. This is it.
- **DD-002 §12.5 anti-patterns**: we **observe** single-writer principle
  — mindmap.json still written only by classify.py; summaries only by
  summarize.py; artifact_states writes to user_overrides.json (existing
  writer: serve.py /api/save).
- **Optional future extensions** (e.g., GitHub status sync API) follow
  DD-002 §12.3 contract: own script, own data product, no trunk
  touches.

---

## 14. Next

Pending approval. Implement Phase 1 → Phase 4 sequentially. Estimated
1-2 days of coding + a few days of observation.

Phase 5 (AI auto-sensing) is optional, gated on observed pain after
Phase 4 ships.
