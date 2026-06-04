# Roadmap

中文版：[zh-CN/ROADMAP.md](zh-CN/ROADMAP.md)

Planned but not yet implemented. Captured here so the design decisions
behind them aren't lost between sessions.

For full design docs see [design/](design/).

| Item | Status | Doc |
|---|---|---|
| P11.0 cache lock | Proposed (below) | — |
| P11.1 CLI subcommands | Proposed (below) | — |
| P11.2 SKILL.md | Proposed (below) | — |
| P14 AI Pipeline redesign | Implemented | [DD-002](design/DD-002-ai-pipeline-redesign.md) |
| P15 Card detail + artifacts | Proposed | [DD-003](design/DD-003-card-detail-and-artifacts.md) |
| P16 Tips quiz (spaced reinforcement) | Proposed (below) | — |
| P17 Persona accretion ("digital twin" prompt) | Proposed (below) | — |
| P13 (historical) two-pass classification | Superseded | [DD-001](design/DD-001-two-pass-classification.md) |

## P11.0 — Concurrency lock for cache writes

**Why**: Multiple writers can touch the same cache file at once. Today:

| Writer | Files |
|---|---|
| `refresh.sh` apply-overrides phase | `dashboard.json`, `user_overrides.json` (read + clear) |
| `serve.py /api/save` | `user_overrides.json`, `deleted_ids.json`, `cache/archive/<ws>/*.json` |
| `record-location.py` | `session_locations.json` |
| (future) CLI `mindmap card/task ...` | same as `/api/save` |

`refresh.sh` already has a global `mkdir cache/refresh.lock.d` that
serializes refreshes, but it does NOT cover writes from `/api/save` or
the planned CLI. The dangerous race is **CLI/UI does a read-modify-write
on `user_overrides.json` while another writer hits the same file**.

### Design

Add `bin/_cache_lock.py` exposing one context manager:

```python
from contextlib import contextmanager
import fcntl
from pathlib import Path

@contextmanager
def cache_lock(name: str = "overrides"):
    """Acquire exclusive POSIX advisory lock on cache/.locks/<name>.lock.
    Block (not spin) until acquired. Release on context exit."""
    lock_dir = Path(__file__).resolve().parent.parent / "cache" / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{name}.lock"
    with open(lock_path, "w") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
```

All writers to `user_overrides.json` / `deleted_ids.json` / archive dir
take `cache_lock("overrides")`. Lock name spaces are kept separate from
the existing refresh lock so quick CLI writes don't queue behind a
running AI call.

### Adoption checklist

- [ ] Create `bin/_cache_lock.py`
- [ ] `serve.py /api/save` wraps writes in `cache_lock("overrides")`
- [ ] `refresh.sh` apply-overrides Python block uses the same lock name
- [ ] CLI commands (P11.1) use the same lock name
- [ ] `dashboard.json` final write uses atomic `tmp + rename` so concurrent
      readers never see a half-written file

### Out of scope

- Multi-host concurrency. Loopback-only.
- Lock timeouts. Operations are <100ms; blocking is fine.

## P11.1 — CLI subcommands

**Why**: Terminal-first users want shell parity with the HTML UI. Also
unblocks P11.2 (SKILL): a SKILL Agent can shell out to `mindmap` CLI
without learning the HTTP API.

### Subcommand inventory

```
mindmap ls [--status active|paused|done|archived|all]
mindmap show <init-id-or-name-prefix>
mindmap card add                       # interactive wizard
mindmap card archive <init-id>
mindmap card unarchive <init-id>
mindmap card delete <init-id>
mindmap task done <init-id> <title>
mindmap task undone <init-id> <title>
mindmap task add <init-id> <title>
mindmap task del <init-id> <title>
```

All write commands take `cache_lock("overrides")` from P11.0.

### "Create initiative" semantics

Use the **overrides-with-placeholder** strategy:
- `mindmap card add` writes a stub initiative directly into
  `dashboard.json` (status=`active`, no sessions, user-supplied
  summary/progress/tasks)
- Also adds a marker to `user_overrides.json` so refresh-time merge
  knows to keep the human-created node intact across AI runs
- Next AI refresh sees the placeholder in PRIOR_MINDMAP; per continuity
  rules it preserves id+name and only enriches metadata as evidence
  emerges

### Implementation notes

- Subcommand dispatcher in `bin/mindmap` (bash) routes to
  `bin/cli_commands.py` (Python)
- Use existing `effectiveStatus()` logic by mirroring it in Python
- Fuzzy-match initiative IDs by prefix or substring of name so users
  don't need to memorize ids
- Tab completion via `_mindmap_completion` (zsh/bash) is a bonus

## P11.2 — SKILL.md for Agent installation

**Why**: Goal pattern from user request:

```
Read https://<url>/SKILL.md and register on the platform.
```

A SKILL.md installed under `~/.claude/skills/mindmap/` makes the main
Claude Code Agent automatically aware of the mindmap tools — no need to
hand-explain commands each session.

### Deliverables

1. `SKILL.md` at repo root (or `skill/SKILL.md`) following the
   [Anthropic SKILL spec](https://docs.claude.com/en/docs/claude-code/skills).
   Frontmatter declares:
   - `name: mindmap`
   - `description`: when to activate (user asks about current work,
     project overview, where they left off, what they're working on)
   - `arguments`: not needed; SKILL describes how to invoke the CLI

2. SKILL body sections:
   - **What it does** — one paragraph about the mindmap tool
   - **Commands** — reference table of `mindmap` subcommands with use
     cases ("user asks 'what am I working on' → `mindmap ls`")
   - **How it works** — three-stage pipeline (extract → aggregate → AI
     classify), continuity model, where overrides live
   - **Troubleshooting** — decision tree mirroring `stray --diagnose`
     output so the Agent can walk the user through cooldown / extract
     / classification issues without running the diagnostic
   - **Examples** — sample user prompts and what the Agent should do

3. `bin/install-skill.sh`: copy `SKILL.md` → `~/.claude/skills/mindmap/`
   so it activates on the current machine

4. Hosted URL: publish at a stable raw URL (GitHub Pages or
   `raw.githubusercontent.com/Icesource/claude-stray/main/SKILL.md`)
   so other machines can install with one prompt to their main Agent

### Optional companion: `SKILL.URL.txt`

Single-line file containing the URL. Lets the install pattern be:

```
The mindmap SKILL lives at $(curl -s https://example.com/SKILL.URL.txt) .
```

## P16 — Tips quiz (spaced reinforcement)

**Why**: The tips bubble (DD-006, post-v0.5.0) cycles through 20
curated entries per batch — Tang/Song poems, etymology facts,
programming history, etc. The user's stated intent for tips was
"扩充知识面" (broaden general knowledge), but the current UX is purely
ambient: a tip flashes for 25 seconds, then rotates away. Without
any reinforcement loop, those quotes and facts don't stick.

This roadmap item adds a lightweight quiz/recall layer on top of the
tip pool so the content actually lands.

### Sketch

- **Persist every tip ever shown** to `cache/derived/tips/history.jsonl`
  (append-only). Today only the last `HISTORY_LIMIT` (6) rotations
  live in `latest.json`'s `history[]`; quiz needs a longer tail.
- **Generate a quiz every N days** (configurable, e.g. weekly). The
  source is a sample of past wisdom + curiosity entries (no work or
  rest tips — those aren't memorizable). Quiz formats AI picks per
  entry:
  - **Cloze**: hide a word/phrase, ask user to fill in. ("竹外桃花
    三两枝,___ 鸭先知。") for poems.
  - **Multiple choice**: who wrote it, what's the source, etymology.
  - **Free recall**: "What does CC0 mean?" with the persisted answer
    + source URL on reveal.
- **Quiz delivery**: a sidebar widget `📚 复习一下` that opens a
  small modal with one card at a time. User answers, sees the
  correct answer with the original source link, marks
  "remembered" / "forgot" — feeds a SuperMemo-2-style spacing
  curve so forgotten items resurface sooner.
- **Source URL is the trust anchor**: every quiz answer shows the
  same `↗` source the original tip had. The quiz can't drift into
  fabrication because every question is grounded in a previously-
  shown, source-verified tip.

### Open design questions (defer until implementation)

- One quiz per week or on-demand? Probably weekly default + manual
  "give me one now" button.
- How does the cat react? Pet sprite could play a different
  animation during quizzes ("教学姿势").
- Persistence schema for spaced-repetition state: per-tip
  `next_review_at` + `interval_days` + `streak`. Where to store —
  alongside history.jsonl or in a separate `quiz_state.json`?
- AI prompt for quiz generation: needs to handle Chinese poetry's
  cloze format separately from English-language curiosity facts.
- Cost: a quiz-generation call hits Haiku once a week with ~30 tip
  entries as context. Negligible compared to classify (~$0.02 / run).

### Why a roadmap entry, not a DD yet

The scope is one user-facing feature with a known shape (sidebar
widget + persistent history + weekly cron). It only crosses the
DD threshold (multi-file, schema change, prompt change) at
implementation time. Logged here so the design rationale survives
until then.

## P17 — Persona accretion ("digital twin" prompt)

**Why**: Every Stop hook today drives Layer 1 to summarize the session
for the work-mindmap. The same hook could, at near-zero extra cost,
also distill *how* the user worked — their tone, decision style,
favored phrasings, what frustrates them, what they double-check, the
shape of their corrections. Over hundreds of sessions this accretes
into a persona file rich enough to seed a "digital twin" prompt:
an AI agent that drafts in the user's voice and makes choices the way
the user would.

### Sketch

- **Trigger**: piggyback on the existing Layer 1 Stop-hook run, or on
  Layer 2 (so we see cross-session signal, not just one). A new prompt
  emits a tiny patch:
  ```yaml
  - trait: "prefers terse code, no docstrings unless asked"
    confidence: medium
    evidence: "session abc123 turn 4: '别写注释' explicit"
  - trait: "always verifies test passes before saying 'done'"
    confidence: high
    evidence: "12 sessions in last 30d, consistent"
  ```
- **Storage**: `cache/persona/traits.jsonl` (append-only), plus a
  derived `cache/persona/digest.md` regenerated periodically — a
  human-readable, deduplicated, ranked-by-confidence persona document.
- **Decay**: traits not reinforced in N weeks lose confidence (people
  change). The digest only surfaces traits above a confidence floor.
- **Output**: a `claude-stray persona` CLI subcommand prints the
  current digest, optionally as a system-prompt-ready block:
  ```
  $ claude-stray persona --as-system-prompt > /tmp/me.txt
  ```
  The user can then paste that into any new AI agent to seed it with
  their voice.

### Open design questions

- **Privacy boundary**: the persona file is intimate. Should it live
  in the regular `cache/` (gitignored) or in a separate
  `~/.claude/persona/` outside the project? Encryption at rest?
- **Drift detection**: how does the system mark "this trait used to
  be true but the last 20 sessions contradict it"? Probably a
  reinforcement score that decays on contradictory evidence.
- **Caricature risk**: AI summarizing a person tends toward stereotypes.
  Mitigation: confidence floor + evidence requirement + user can
  manually mark a trait `disputed`.
- **AI cost**: piggybacks on Layer 1 prompt — adding ~200 tokens of
  output per session, ~$0.001 per hook fire. Negligible.
- **Trust UI**: the dashboard probably needs a "what does my AI think
  about me" panel so the user can audit, edit, or wipe.

### Why a roadmap entry, not a DD yet

The privacy posture, schema, and dashboard surface need real product
thinking before we commit to a design. Captured here so the idea
isn't lost between sessions.

## Not in roadmap

These have been considered and rejected for now:

- **Incremental AI** (only feed new sessions to AI). Breaks the
  "AI sees everything, decides for itself" model that gives us
  cross-session initiative classification. Token cost is already low
  with Haiku + prompt caching.

- **Activity-aware cooldown adjustment** (shorten cooldown when many
  new sessions detected). Marginal benefit vs implementation complexity.
  Users can override `CLAUDE_WORKTREE_COOLDOWN_SECS` per-shell.

- **Server-side authoritative state** (move overrides to server, client
  sends deltas). Current "client owns full state, server is dumb
  storage" model is simpler and the race window is too small to matter
  for single-user.

- **Custom URL scheme** (e.g. `claude-mindmap://resume/<id>`) for
  cross-process jump. macOS-only, complex setup; the `/focus` and
  `/newpane` HTTP endpoints cover the actual need.
