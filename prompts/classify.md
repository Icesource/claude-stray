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
"ChangeFlow service refactor", "App doc version_no migration", "NCS
gateway auth integration". Usually multiple sessions share an initiative.

Rules:
- One `cwd` may contain MULTIPLE initiatives (split if the sessions cover
  distinct goals — e.g. `ops-portal` may have both "ChangeFlow refactor" and
  "App doc iteration" in parallel).
- An initiative MAY span multiple `cwd`s when sessions in different repos
  clearly serve one narrative (e.g. a feature touching frontend + backend
  + SKILL files all for the same feature).

## Step 2: Group initiatives into WORKSPACES

A **workspace** is the conceptual home of related work — usually a repo
folder name (e.g. `ops-portal`, `dev-cli`, `doc-generator`), but it can
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
- `id`: stable slug like `ops-portal-changeflow-refactor` (lowercase, hyphens)
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
