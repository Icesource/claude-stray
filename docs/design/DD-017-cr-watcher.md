# DD-017 — CR/MR watcher: poll review state, sync to tasks, auto-triage comments to AI

**Status**: Proposed — idea-stage (needs API research + POC)
**Author**: Claude (with user)
**Date**: 2026-06-01
**Predecessors**: DD-003 (artifacts: CR/MR/issue extraction), DD-007
(card-driven AI auto-runner), DD-015 (attention cockpit: live signals)

> Trigger — user proposal 2026-06-01:
> "部分任务上挂着 CR,我想做一个功能就是定时去遍历 CR,如果 CR 状态
> 更新了,可以更新在任务上;如果 CR 有评论,可以自动在某个会话后让 AI
> 读评论、评估正确性、优化或者回复——这样就不会出现 CR 有人评论了,但
> 我一直没时间看就搁置的情况了。"

## 1 — The idea

Tasks already carry CR/MR links as artifacts (DD-003). Add a
**scheduled watcher** that, for every open CR/MR:

1. **Sync state → task.** Poll the CR's state (open / approved /
   merged / closed, pipeline result). When it changes, update the
   artifact + task status on the card automatically — no manual
   refresh.
2. **Triage new comments → AI.** When a CR gets new review comments,
   automatically feed them (with the CR diff + the originating
   session's context) to the AI to: **read the comments, evaluate
   their correctness, propose a fix/optimization, and draft a reply.**
   Surface the AI's assessment + draft on the card. The human approves
   / edits before anything is posted.

The pain it kills: **a reviewer comments on your CR, you're heads-down
elsewhere, you never see it, the work silently stalls.** That stalled-
on-unseen-feedback state is precisely the "搁置" the cockpit (DD-015)
exists to surface.

## 2 — Why this is worth doing (and why now)

- **It closes a real stall loop.** "CR commented → invisible → stalled"
  is the single most common way active work goes cold. A CR with
  unread comments is a perfect first-class **"等你 / 可推进"** signal —
  it feeds straight into DD-015's attention bands and `next_step`.
- **It's BOUNDED, unlike DD-007.** DD-007 (full auto-drive) is hard
  because the trigger and stop-condition are open-ended. Here the
  trigger is crisp (*new comment on a tracked CR*) and the action is
  scoped (*read → evaluate → draft reply*, human posts). That makes it
  the **best first POC for DD-007's "co-pilot mode"** (DD-007 §6 open
  question #4) — high value, low blast radius.
- **The inputs already exist.** Artifacts (CR/MR + ref_id + url) are
  already extracted and are the most stable signal we have (DD-015
  §Identity: artifacts as the trustworthy spine).

## 3 — Sketch (not a spec)

```
scheduled (cron / launchd / loop skill / hook)  every N min
  └─ for each open CR/MR artifact across all initiatives:
       ├─ fetch state + comments         (via `a1` CLI / platform API)
       ├─ diff vs cache/cr-watch/<ref_id>.json  (last-seen state + comment ids)
       ├─ state changed?  → update artifact.status + task; emit cockpit signal
       └─ new comments?   → build AI prompt (comments + diff + linked session)
                             run AI (claude -p --resume <session> or scoped call)
                             → {validity, suggested_fix, draft_reply}
                             → write to card as "⚠ 评审反馈待处理" (needs_you)
                             → human reviews; approves/edits; THEN posts (never auto)
```

- **Fetch**: the CR platform is internal (code.example.com). Likely
  integration path = the **`a1` CLI** (covers MR/代码评审/CR) or its
  API. Needs: list comments, get state, get diff. (Research item.)
- **State store**: `cache/cr-watch/<ref_id>.json` holds last-seen state
  + comment ids, so "new comment" detection is a simple diff.
- **AI-assist output** lands as a new attention item on the card
  ("评审反馈待处理:reviewer 提了 3 条,AI 评估 2 条成立、已起草回复"),
  i.e. it *creates* a `needs_you` signal rather than silently acting.

## 4 — Relationship to existing DDs

| DD | Relationship |
|---|---|
| DD-003 | CR/MR artifacts are the **input** this watches. |
| DD-015 | The **output** is a live attention signal: a CR state change or new-comment-ready becomes a cockpit `needs_you` row + `next_step`. "Stale CR with unread comments" is a first-class attention trigger. |
| DD-007 | This is a **bounded, co-pilot-mode instance** of the auto-runner. Recommended as DD-007's first POC. Inherits DD-007's safety posture: human-approval gate before posting, audit log, identity prefix on any posted reply. |
| DD-004 | AI calls per new comment must respect the budget circuit-breaker. |

## 5 — Risks / open questions (POC must answer)

- **API access**: does `a1` expose CR/MR comments + state + diff?
  Auth, rate limits, pagination. (Biggest unknown — research first.)
- **No auto-posting in V1.** Drafting a reply is assist; *posting* it
  under the user's identity is autonomy. V1 = draft + human posts.
  (Wrong auto-reply under your name is a real etiquette/identity risk.)
- **CR → session mapping**: which session/initiative to resume for
  context? The artifact already links to an initiative; pick its most
  recent session.
- **Comment dedup**: store last-seen comment ids; only act on genuinely
  new ones; don't re-evaluate the same comment each poll.
- **Hook recursion**: the AI-eval session would fire Stop hooks → must
  be flagged as automation (cf. DD-007 §2.4 `is_agent_run`).
- **Poll cadence vs cost vs freshness**: every 5 min? on dashboard
  open? Only while a CR is "awaiting review"? Budget-bounded.
- **Scope of the AI judgment**: "evaluate correctness" can be wrong —
  present it as a *suggestion to the human*, never as ground truth.

## 6 — Out of scope (V1)

- Auto-posting replies / approving / merging — assist only; human acts.
- Non-CR artifacts (issues, pipelines) — CR/MR comments first.
- Multi-platform — start with the one CR platform in use.

## 7 — Recommended next step

Fold this into DD-007's POC slot: pick **one** real CR with live
comments, wire a minimal poller (`a1` fetch → diff → one AI eval →
write a draft reply to a local file, no posting), and measure: can we
reliably detect new comments, does the AI's evaluation hold up, is the
drafted reply usable? That data decides whether this graduates to a
designed feature.
