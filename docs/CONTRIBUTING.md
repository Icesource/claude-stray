# Contributing

中文版：[zh-CN/CONTRIBUTING.md](zh-CN/CONTRIBUTING.md)

Conventions for changes in this repo. Aimed at future-me, not strangers.

## Doc conventions

| Doc type | Where it lives | When to add |
|---|---|---|
| User-facing install/usage | `README.md` (root), `docs/README.zh-CN.md` | Any user-visible flag, command, or workflow change |
| How the system works | `docs/ARCHITECTURE.md` | New pipeline stage, new cache file, new component |
| Operational playbook | `docs/TROUBLESHOOTING.md` | New failure mode or new diagnostic capability |
| Future plans | `docs/ROADMAP.md` | Decision to defer; record rationale |
| Non-trivial design | `docs/design/DD-NNN-slug.md` | Anything that affects multiple files OR changes a data shape OR changes an external contract (hooks, prompts, API) |
| Release / branching | `docs/RELEASE.md` | Anything about branch model, version bumps, the release checklist itself |
| User-visible changes per release | `CHANGELOG.md` (root) | Every change as you make it — add to the `[Unreleased]` block, don't wait for release day |

**Bias toward concise.** Each doc should pass the "scannable in 60s"
test. If a doc would help five future readers but make the seven non-
readers grumpy, prefer a 1-line entry in TROUBLESHOOTING with a
`grep`-able tag over a whole new doc.

## Design docs (DD-NNN)

Write one BEFORE coding when:

- The change spans 3+ files
- The change touches the AI prompt OR the cache JSON schema
- The change introduces a new IPC surface (hook, HTTP endpoint, CLI sub)
- You found a bug whose root cause needs explaining (this is a "post-
  mortem DD" — useful for non-obvious gotchas)

Template lives at [design/README.md](design/README.md). Number is
monotone: next available is whatever `ls design/DD-*.md | tail -1 | sed
's/DD-\([0-9]*\).*/\1/'` + 1.

## Commit messages

Follow the existing style — see `git log --oneline`. In short:

- Subject line: imperative present tense, lowercase verb, no trailing
  period, **stays under 72 chars**.
  Good: `Fix stale card content and truncated session_ids`
  Bad:  `Fixed the bug where cards weren't updating properly.`
- Body wraps at 72. Explain WHY, not WHAT (the diff already shows what).
- For multi-purpose commits, prefer splitting. If you must bundle, the
  body should explain why bundled.
- No `Co-Authored-By: Claude` trailer — keep the log clean. The
  attribution gets too noisy across many commits.

## When to commit

The default is **commit at the end of every logical unit of work**, not
at the end of a multi-hour session. If you find yourself with 5+ files
dirty across 3 features, you should have committed twice already.

Exception: an explicit "I'll review and commit together at the end"
agreement with the user. Even then, prefer splitting at commit time
(see `git add -p`) over a mega-commit.

## Adding a flag to `bin/mindmap`

The dispatcher parses flags up front into `DO_*` booleans, then dispatches
in a fixed priority order. Pattern:

1. Add the flag to `for arg in "$@"; do case "$arg" in ...`
2. Update the help text in the `-h|--help` branch
3. If the flag delegates to a Python script, dispatch via `exec
   python3 "$REPO_ROOT/bin/<script>.py"` after the parse loop
4. Smoke test: `bash bin/mindmap --your-flag` and `bash bin/mindmap
   --help`

## Adding a `serve.py` endpoint

1. Decide GET vs POST. GET for reads/static, POST for writes/actions
2. Add handler method `_handle_<name>` in `Handler` class
3. Wire route in `do_GET` or `do_POST`
4. CORS is already set in `_cors()` — call it before `end_headers()`
5. Use `self._reply(code, dict)` for JSON responses
6. Document the endpoint in `ARCHITECTURE.md` (cache file table or
   server section)

## Changing the AI prompt

`prompts/classify.md` is the single source of truth for the
classifier. Two failure modes to defend against:

- **Drift**: the prompt grows organically until it contradicts itself.
  Re-read top-to-bottom before adding a section
- **Underspecified outputs**: AI returns short ids, omits required
  fields, uses wrong language. Add a self-check section AND a
  post-process repair in `refresh.sh` for any invariant you care about
  (belt + suspenders)

After any prompt change, force a real refresh and inspect the DIFF
output (`mindmap --refresh && tail Library/Logs/claude-stray.log`).
If `DIFF vs prior` shows initiative `id`s being renamed or `done` flipping
back to `false`, the prompt change broke continuity.

## Cache file changes

The cache is gitignored — schema changes are silent. Migration is the
contributor's problem:

- Bumping `mindmap.json.schema_version` requires a fallback path in
  `render.py` and `render-html.py` for at least one release
- New fields: prefer optional, defaulting to safe values in code rather
  than requiring full migration
- Removing fields: deprecate first (still write them, just don't
  consume), drop after a few weeks

## Testing

There's no unit test suite. The signal hierarchy for "is it broken":

1. `python3 bin/render.py` runs without exception on current
   `cache/mindmap.json`
2. `bash bin/refresh.sh` exits cleanly (force or hash-skip both fine)
3. `mindmap --diagnose` reports green for an active session
4. `mindmap --serve` starts, serves `/`, accepts `/api/save`, exits
   cleanly on Ctrl-C
5. Playwright smoke test against `http://127.0.0.1:9876/`
   (`/tmp/playwright-test-*.js`)

Run all five before pushing a refactor.
