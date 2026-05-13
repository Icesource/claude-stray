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
| P13 two-pass classification | Proposed | [DD-001](design/DD-001-two-pass-classification.md) |

## P11.0 — Concurrency lock for cache writes

**Why**: Multiple writers can touch the same cache file at once. Today:

| Writer | Files |
|---|---|
| `refresh.sh` apply-overrides phase | `mindmap.json`, `user_overrides.json` (read + clear) |
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
- [ ] `mindmap.json` final write uses atomic `tmp + rename` so concurrent
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
  `mindmap.json` (status=`active`, no sessions, user-supplied
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
   - **Troubleshooting** — decision tree mirroring `mindmap --diagnose`
     output so the Agent can walk the user through cooldown / extract
     / classification issues without running the diagnostic
   - **Examples** — sample user prompts and what the Agent should do

3. `bin/install-skill.sh`: copy `SKILL.md` → `~/.claude/skills/mindmap/`
   so it activates on the current machine

4. Hosted URL: publish at a stable raw URL (GitHub Pages or
   `raw.githubusercontent.com/Icesource/claude-code-worktree/main/SKILL.md`)
   so other machines can install with one prompt to their main Agent

### Optional companion: `SKILL.URL.txt`

Single-line file containing the URL. Lets the install pattern be:

```
The mindmap SKILL lives at $(curl -s https://example.com/SKILL.URL.txt) .
```

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
