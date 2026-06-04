# DD-004 — Cost circuit breaker & runaway alarm

Status: **proposed** (not implemented)
Predecessor: DD-002 §12 (cost-aware operation), DD-003 (card surface)
Trigger: 2026-05-14 runaway incident (1700+ self-recursive `summarize.py`
calls in 4 hours, $51 lost) — see post-incident notes in
[`feedback_macos_portability`](../../../.claude/projects/-Users-bby-Code-claude-stray/memory/feedback_macos_portability.md)
and [`feedback_verify_before_claim`](../../../.claude/projects/-Users-bby-Code-claude-stray/memory/feedback_verify_before_claim.md).

## 1 — Problem

The pipeline can run cost-unbounded:
- Layer 1 fires per Stop hook; nothing caps daily / hourly spend.
- Failure modes invisible to user until they run `stray --cost`.
- 2026-05-14 root cause (self-recursive prompt marker miss) was
  fundamentally fixed in P15 (`--no-session-persistence` + matching
  marker list), but a future regression in any related layer can again
  silently burn budget. The system needs a budget guard *and* a way
  to surface anomalies to the user in real time.

## 2 — Goals

1. **Hard ceiling**: a per-day spend cap that, when exceeded, halts the
   pipeline and self-disables. Re-enable is manual (user removes the
   kill switch).
2. **Rate watchdog**: catch *fast* anomalies (e.g. 30 summarize calls
   in 5 minutes) before they exhaust the daily budget.
3. **Visibility**: the user must see "something is wrong" in the
   dashboard and in the `stray --serve` console — not only by running
   `stray --cost` after the fact.
4. **No false positives**: a healthy day (~10–30 calls / $1) must show
   green, not yellow.

Non-goals:
- Centralized alerting (Slack, email). Local-only.
- Predictive limits (forecast tomorrow's cost). Reactive is enough.
- Per-session quotas. Daily total is the unit.

## 3 — Design

### 3.1 — Configuration knobs (all env-overridable)

| Env var                            | Default | Meaning |
|------------------------------------|---------|---------|
| `CLAUDE_WORKTREE_DAILY_BUDGET_USD` | `5.00`  | Hard daily cap |
| `CLAUDE_WORKTREE_DAILY_WARN_USD`   | `2.00`  | Yellow-banner threshold |
| `CLAUDE_WORKTREE_RATE_WINDOW_S`    | `300`   | Rate watchdog window (5 min) |
| `CLAUDE_WORKTREE_RATE_LIMIT`       | `20`    | Max calls inside the window before halt |

### 3.2 — Where the gate lives

A new helper `bin/_budget.py`, called by `summarize.py` and
`classify.py` *before* the AI call:

```
status = check_budget()    # returns "ok" | "warn" | "halt:<reason>"
if status.startswith("halt:"):
    touch(KILL_SWITCH, reason=status)
    log_cost(layer, None, 0, ok=False, halted=True)
    return EXIT_HALTED
```

The check reads `cache/cost_log.jsonl`, computes:
- today's cumulative `cost_usd` → compare to daily budget / warn
- count of (layer == today's_layer) entries in last `RATE_WINDOW_S` →
  compare to rate limit

Cost: O(N) scan of cost_log per AI call, but `_budget.py` keeps an
in-process cache keyed by file mtime — typical cost is one cheap stat()
per call.

### 3.3 — Kill switch with reason

Extend the existing kill switch:
- Path: `cache/.refresh-disabled` (already used)
- Sidecar: `cache/.refresh-disabled.reason` — single line, written by
  `_budget.py`, contains: `<ISO8601>\t<reason>\t<measured>\t<limit>`
- `refresh-bg.sh` already checks the kill switch and exits 0 — no
  change needed there.

### 3.4 — Banner in the dashboard

`render-html.py` reads kill switch + today's cost at render time and
emits a banner at the top of `<body>` when warranted:

| Condition                                 | Banner level | Text |
|-------------------------------------------|--------------|------|
| Kill switch engaged                       | red          | `🚨 Pipeline halted: <reason> · re-enable with stray --enable` |
| Today's spend ≥ warn but < budget         | yellow       | `⚠ Spend today: $X.XX / $Y.YY` |
| Rate watchdog triggered without halt yet  | yellow       | `⚠ Burst: N calls in last Ms` |
| All clear                                 | (none)       | — |

Banner is a `position: sticky` strip at top of board, dismissible per
session via `sessionStorage`. Click for details → opens a small modal
with the last 20 cost_log entries (timestamp / layer / cost / status).

### 3.5 — serve.py console output

When `bin/serve.py` starts and on every `/api/data` poll, it computes
the same status (cheap — re-uses the same `_budget.py` helper) and
prints a single stderr line if non-OK:

```
[serve][WARN]  burst: 22 summarize in last 5min (limit 20)
[serve][HALT]  daily cap reached: $5.10 / $5.00 — kill switch engaged
```

Color-coded with ANSI when stderr is a TTY. Quiet when status is OK.

### 3.6 — JSON endpoint for the banner

`serve.py` exposes `GET /api/health` returning:
```json
{
  "kill_switch":  { "engaged": false, "reason": null },
  "spend_today":  { "usd": 0.42, "calls": 12 },
  "rate":         { "window_s": 300, "summarize": 3, "classify": 0 },
  "limits": {
    "daily_usd": 5.00, "warn_usd": 2.00,
    "rate_window_s": 300, "rate_limit": 20
  }
}
```

The page polls this every 30s and refreshes the banner in place.

### 3.7 — Re-enable flow

A new `stray --enable` command:
1. Reads `.refresh-disabled.reason` and prints it
2. Asks for confirmation (`Continue? [y/N]`)
3. On `y`: removes both `.refresh-disabled` and the sidecar
4. Optionally: runs `stray --refresh` to verify pipeline health

## 4 — Plan

| Phase | Work | Cost |
|-------|------|------|
| 0     | Write `bin/_budget.py` with the two checks; unit-test against fixtures of `cost_log.jsonl` | small |
| 1     | Wire into `summarize.py` and `classify.py` (call before `call_claude`) | small |
| 2     | Add `GET /api/health` to `serve.py` + console output | small |
| 3     | Add banner to `render-html.py` + sessionStorage dismiss logic | medium |
| 4     | Add `stray --enable` subcommand to `bin/mindmap` | tiny |
| 5     | Telemetry: add a test mode that forces halt to verify all surfaces light up | tiny |

## 5 — Out of scope (deliberate)

- **Cost per-session quotas** — premature; current bottleneck is daily.
- **Notifications outside the box** — too much friction for a personal
  tool; the user will see the banner the next time they open the page.
- **Predictive throttling** — Haiku is cheap enough that a single
  pathological day doesn't justify the complexity.
- **Anomaly detection by ML** — `cost_log` is small; rate + total are
  enough to catch every realistic failure mode.

## 6 — Open questions

1. Should the rate watchdog also halt the pipeline, or just warn? Lean
   toward *halt* — by the time you see "20 calls in 5 min" the cost is
   already ~$0.60, and the cause is almost certainly a regression that
   needs human attention.
2. Daily-budget reset semantics — calendar day in user's local TZ, or
   UTC? Lean local TZ for human predictability ("the budget resets at
   midnight" matches expectations).
3. Should `_budget.py` write to the cost_log when it halts (a synthetic
   "halt" row), or only to the sidecar? Lean toward both — cost_log is
   the audit trail; the sidecar is the immediate display surface.
