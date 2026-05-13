# Troubleshooting

中文版：[zh-CN/TROUBLESHOOTING.md](zh-CN/TROUBLESHOOTING.md)

Decision trees for the failure modes we've actually seen. First stop:

```bash
mindmap --diagnose [session_id]    # auto-picks most recent if omitted
```

It walks the pipeline stage by stage and tells you which one dropped
the session. Most of this doc is "what to do given that output."

## "My new task / fix / decision isn't showing in the mindmap"

### Step 1: identify your session id

In the Zellij pane where you did the work:

```bash
mindmap --diagnose
```

It picks the most recently modified jsonl. Confirm the session id and
the first prompt look like yours. If not, find your session manually:

```bash
ls -lt ~/.claude/projects/$(pwd | sed 's|/|-|g')/*.jsonl | head
```

### Step 2: read the diagnose output

| `--diagnose` reports | Likely cause | Fix |
|---|---|---|
| Stage 1 (extract) `summary missing` | Hook didn't run for this session, or extract hasn't been called | `python3 bin/extract.py` |
| Stage 2 (aggregate) not in list, `is_automation=true` | Session opened with the classifier prompt itself (rare, self-referential) | Wait for next session OR manually delete `cache/sessions/<sid>.json` and re-extract |
| Stage 2 (aggregate) not in list, `user_message_count<1` | Pure tool-call session, no user prompts | Expected. Mindmap intentionally excludes these |
| Stage 3 (mindmap) `session_id NOT in any initiative` AND last AI run < session activity | AI hasn't run since session was extracted | `mindmap --refresh` |
| Stage 3 says session IS classified but card content is stale | Extract's compression is hiding the latest content | See ["Card content lags actual work"](#card-content-lags-actual-work) |
| Stage 5 `in cooldown` | A real AI run happened recently; the next hook-triggered run is gated | Wait, or `mindmap --refresh` to force |

### Step 3: force a real run

```bash
mindmap --refresh    # sets CLAUDE_WORKTREE_FORCE=1 inside refresh.sh
```

Watch the log:

```bash
tail -f ~/Library/Logs/claude-code-worktree.log    # macOS
tail -f ~/.local/state/claude-code-worktree/refresh.log    # Linux
```

A successful run ends with `[refresh] wrote ... N workspaces, M
initiatives` and a `DIFF vs prior` summary.

## Card content lags actual work

Symptom: the card exists, the session_id is in it, but progress text /
tasks reflect an OLD state of the work.

Root cause: `extract.py` hard-compresses each session to ~1.5KB before
the AI sees it. Long sessions or sessions whose latest turn starts with
a stock preamble ("Good question, let me think") can lose the real
content.

### Quick fixes

- Bump signal limits temporarily (env vars NOT yet implemented; you'd
  edit `extract.py` constants and re-extract that one session). Limits
  today: `RECENT_PROMPT_LIMIT=5`, `SUMMARY_TRIM=1500`, `PROMPT_TRIM=400`
- Force re-extraction of one session:
  ```bash
  rm cache/sessions/<sid>.json
  python3 -c "
  import json
  s = json.load(open('cache/state.json'))
  key = '/Users/.../<sid>.jsonl'
  s.pop(key, None)
  json.dump(s, open('cache/state.json','w'), indent=2)"
  python3 bin/extract.py
  mindmap --refresh
  ```

### Structural fix

This is the problem
[DD-001](design/DD-001-two-pass-classification.md) addresses: replace
hard compression with a per-session AI summary.

## "Hook is firing but nothing changes"

Symptom: `tail -f` log shows `[hook] ... refresh-bg fired` lines but
the mindmap.json mtime/content doesn't move.

### Diagnose

```bash
mindmap --diagnose
# Look at section [5] "Last real AI run" and [6] "Recent hook outcomes"
```

| `[6]` shows | What it means |
|---|---|
| `OK ran AI` (with DIFF inlined) | AI actually ran this turn |
| `SKIP cooldown` | last_ai_run.epoch is too recent (default 300s window) |
| `skip hash-same` | aggregate_input.json didn't change; AI rightfully skipped |
| `skip locked` | another refresh was in progress; second invocation just exits |
| `skip no-sessions` | aggregate_input.json was empty (rare) |
| `FAIL` | `claude -p` failed or timed out; check log for `claude -p failed` line |

### Historical bug: false cooldown

Before commit `9f01447` the cooldown gate used `mindmap.json` mtime. The
apply-overrides phase writes to that file, so any user UI edit would
falsely reset the clock and starve AI runs forever. If you see this
symptom on a setup that hasn't been updated, pull and reinstall.

## "I clicked a task done in the UI but the change disappeared after refresh"

This shouldn't happen — the apply-overrides phase bakes the toggle into
mindmap.json BEFORE the AI sees PRIOR_MINDMAP, and the prompt has a
strict done-monotone rule.

If it does:

1. Check `cache/user_overrides.json` right after the click — your toggle
   should be there
2. Wait for one hook-driven refresh, then check again — file should be
   cleared (consumed) and `cache/mindmap.json` should show the task done
3. If after a refresh the task is back to undone:
   - Either `apply-overrides` didn't run (check log for `applied N task
     toggles`)
   - Or AI overrode it despite the monotone rule (check `DIFF vs prior`
     in log; if you see `done 1→0` for that initiative, file a bug)

## "Archived items reappear after refresh"

Should not happen for items archived via the UI — those are physically
removed from `mindmap.json` and the data lives in `cache/archive/<ws>/
<id>.json`. `render-html.py` re-reads that directory, so they remain
visible in the archive zone.

If you archived something and it came back as a normal initiative:

1. Check `cache/archive/<ws>/<id>.json` exists
2. Check `cache/mindmap.json` does NOT have that id under any workspace
3. If both are correct but the card still shows in a workspace, restart
   the server (HTML may be cached). `mindmap --serve` regenerates HTML
   on each GET when mindmap.json is newer than mindmap.html

## "`mindmap --serve` won't shut down with Ctrl-C"

Fixed in commit `9f01447`. The old code called `httpd.shutdown()`
synchronously from the SIGINT handler, deadlocking against
`serve_forever()` in the main thread. The new code shuts down via a
worker thread + `daemon_threads=True`. If you see the old behavior,
pull.

## Where logs live

| Platform | Path |
|---|---|
| macOS | `~/Library/Logs/claude-code-worktree.log` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/claude-code-worktree/refresh.log` |

Every `[hook] <ISO timestamp>` line opens one invocation; everything
after until the next `[hook]` line is that invocation's output.

## When in doubt: nuke and refresh

```bash
rm -rf cache/sessions/ cache/state.json cache/last_input.sha256 \
       cache/last_ai_run.epoch
mindmap --refresh
```

Keeps user edits (`user_overrides.json`, archive dir, deleted_ids,
session_locations). Rebuilds the extract+AI pipeline from scratch.
Costs one Haiku call (~$0.20).
