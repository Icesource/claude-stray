# Architecture

中文版：[zh-CN/ARCHITECTURE.md](zh-CN/ARCHITECTURE.md)

How `claude-code-worktree` actually works as of commit `9f01447`.

## 30-second pitch

Reads `~/.claude/projects/**/*.jsonl` (Claude Code's session log), feeds
a compressed view to a headless `claude -p` call, gets back a structured
mindmap of the user's recent work, renders it as ASCII / HTML / markmap.

## Pipeline

```
~/.claude/projects/*/*.jsonl
        │
        ▼ extract.py — incremental jsonl reader, stateful
cache/sessions/<sid>.json   (one summary per session)
        │
        ▼ aggregate.py — filter & compact, sorts by recency, caps 200
cache/aggregate_input.json  (one JSON array, ~300KB)
        │
        ▼ refresh.sh — orchestrator
        │   1. apply user_overrides.json
        │   2. remove cache/archive/ ids from mindmap.json
        │   3. apply deleted_ids.json
        │   4. hash check (skip AI if input unchanged)
        │   5. cooldown gate (uses cache/last_ai_run.epoch)
        │   6. build prompt: classify.md + OUTPUT_LANG + PRIOR_MINDMAP
        │                  + DELETED_IDS + INPUT_SESSIONS
        │   7. claude -p --model haiku-4.5  (one-shot, no tools)
        │   8. parse AI JSON, write mindmap.json
        │   9. repair truncated session_ids by prefix match
        │  10. write cache/last_ai_run.epoch
        │  11. regenerate mindmap.html + mindmap-tree.html
        ▼
cache/mindmap.json
        │
        ├─ render.py             → stdout ANSI tree
        ├─ render-html.py        → cache/mindmap.html (cards)
        └─ render-tree.py        → cache/mindmap-tree.html (markmap)
```

## Triggers

Anything that wants a fresh mindmap calls `refresh.sh`. Sources:

| Source | When | Path |
|---|---|---|
| Claude Code `Stop` hook | After every assistant response | `refresh-bg.sh` (fork+detach) |
| Claude Code `SessionStart` hook | On session open/resume | same |
| macOS LaunchAgent | Every 2 hours | same |
| `mindmap --refresh` | User-triggered | inline, sets `CLAUDE_WORKTREE_FORCE=1` to bypass cooldown |
| `POST /api/refresh` | UI button | same as `--refresh` |

`refresh.sh` is gated by:
- A global mkdir lock (`cache/refresh.lock.d`) — serializes concurrent calls
- A hash check — skip AI if `aggregate_input.json` content unchanged
- A cooldown — skip AI if `cache/last_ai_run.epoch` < `$COOLDOWN_SECS` ago
  (default 300s; was 900s; use a separate marker because OUTPUT_FILE mtime
  is bumped by apply-overrides and would falsely reset the clock)

## Cache file inventory

All under `cache/`. The whole directory is gitignored.

| File | Owner | Purpose |
|---|---|---|
| `mindmap.json` | refresh.sh + apply-overrides + post-repair | Canonical state; schema v2 = workspaces > initiatives > tasks |
| `aggregate_input.json` | aggregate.py | Compressed input to AI; one JSON array of session summaries |
| `sessions/<sid>.json` | extract.py | Per-session summary; built incrementally from jsonl byte offsets |
| `state.json` | extract.py | Per-jsonl byte offsets so re-runs are incremental |
| `last_input.sha256` | refresh.sh | Hash of aggregate_input from last *successful* AI run |
| `last_ai_run.epoch` | refresh.sh | Epoch of last successful AI call. Cooldown gate reads this |
| `user_overrides.json` | serve.py /api/save (or planned CLI) | task done flips, deleted tasks; consumed by refresh.sh apply-overrides |
| `deleted_ids.json` | serve.py /api/save | Tombstone list of user-deleted initiatives. AI is told to skip these |
| `archive/<ws>/<id>.json` | serve.py /api/save | User-archived initiatives, full payload preserved; AI never sees these |
| `session_locations.json` | record-location.py (hook) | session_id → ZELLIJ_PANE_ID + cwd + timestamps |
| `config.json` | install.sh | `{lang: zh-CN}` |
| `mindmap.html` | render-html.py | Card dashboard, single-file |
| `mindmap-tree.html` | render-tree.py | Markmap export, single-file |
| `refresh.lock.d/` | refresh.sh | mkdir-based global lock |

## Components

```
bin/
  install.sh         — one-shot install: --lang flag, slash commands,
                       wrapper symlink, hooks, launchd
  install-hook.sh    — re-install just the hooks (idempotent)
  refresh-bg.sh      — fork-and-detach wrapper for refresh.sh;
                       also calls record-location.py before forking
  refresh.sh         — orchestrator (see Pipeline)
  extract.py         — jsonl reader → cache/sessions/<sid>.json
  aggregate.py       — sessions/*.json → aggregate_input.json
  record-location.py — hook → cache/session_locations.json
  render.py          — mindmap.json → ANSI tree (stdout)
  render-html.py     — mindmap.json + archive/ + locations → cache/mindmap.html
  render-tree.py     — mindmap.json → cache/mindmap-tree.html (markmap)
  serve.py           — local HTTP server on 127.0.0.1:9876
                       Static: GET / serves mindmap.html
                       API:   GET /api/data, POST /api/save, POST /api/refresh
                       Helper:POST /focus, POST /newpane (zellij action ...)
  diagnose.py        — walks pipeline for one session_id, reports stage status
  mindmap            — user-facing CLI dispatcher
  uninstall.sh       — reverse install.sh
prompts/
  classify.md        — the AI prompt for cross-session classification
```

## Modes

The HTML can be loaded two ways. Both work; only persistence differs.

| Mode | URL | Save path | When user grants permission |
|---|---|---|---|
| `mindmap --open` | `file:///.../mindmap.html` | File System Access API (Chrome/Edge only); falls back to "download patch" | Once per session |
| `mindmap --serve` (recommended) | `http://127.0.0.1:9876/` | `POST /api/save` writes directly to cache/ | Never — loopback only |

HTML detects `location.protocol` and dispatches to the right path at boot.

## Continuity model (the part that makes the mindmap useful)

The AI doesn't reclassify from scratch each run. `PRIOR_MINDMAP` is fed
back as a baseline. Rules in `prompts/classify.md`:

1. Initiative `id` is stable — AI must reuse the same id for the same
   conceptual work, even if the name slightly evolves
2. Task `done: true` is monotone — once done, never un-done by AI
   (only user actions via `user_overrides.json` can flip)
3. Status decays with inactivity — `active` → `paused` after 3 days, →
   `archived` after 14
4. New initiatives only when new evidence in INPUT_SESSIONS justifies
5. `DELETED_IDS` is a tombstone — AI must not recreate even if new
   evidence appears

User edits propagate to AI via PRIOR_MINDMAP:
- User toggles task done in UI → `user_overrides.json` →
  refresh.sh apply-overrides → mindmap.json → PRIOR_MINDMAP carries
  `done: true` → next AI run can't un-do it

## Concurrency

Today's locking is minimal but sufficient for single-user, single-host.

| Risk | Mitigation |
|---|---|
| Two refreshes overlap | `cache/refresh.lock.d` mkdir lock at top of refresh.sh |
| serve.py /api/save races against apply-overrides | None today; relies on /api/save being POSIX-atomic file writes and refresh.sh apply happening at the top before AI |
| Multiple browser tabs each POST /api/save | None; last-write-wins. Acceptable for single user |
| Reader sees half-written `mindmap.json` | None; json.dump is not atomic. Risk window <100ms. Planned: atomic tmp+rename (see ROADMAP P11.0) |

Planned hardening lives in [ROADMAP.md → P11.0](ROADMAP.md#p110--concurrency-lock-for-cache-writes).

## Invariants you can rely on

These are enforced by code or prompt. Violations are bugs.

1. `cache/mindmap.json` schema_version == 2 (or legacy fallback in render.py)
2. Every initiative has a non-empty `id` and `sessions[]`
3. `sessions[]` entries are full UUIDs (refresh.sh post-process repairs truncation)
4. A task once marked `done: true` stays `done: true` across refreshes
   (unless the user explicitly un-checks in UI)
5. Archived initiatives are NEVER in PRIOR_MINDMAP (refresh.sh strips them
   before building the prompt)
6. `cache/last_ai_run.epoch` is bumped iff a real `claude -p` call succeeded
7. `aggregate.py` skips sessions where `is_automation=true` — protects
   against self-referential loops (the classifier seeing its own prompt)

## What this architecture is NOT good at

- **Information density for the per-session understanding.** `extract.py`
  hard-compresses each session to ~1.5KB. The classifier never sees full
  conversation context. Symptom: "card progress text lags actual work."
  Fix in [DD-001](design/DD-001-two-pass-classification.md).

- **Real-time per-session updates.** Cooldown (5min default) is a single
  global gate; you can't bump a single card without re-classifying all 200
  sessions. Same fix.

- **Cross-host / multi-user.** Loopback-only by design.
