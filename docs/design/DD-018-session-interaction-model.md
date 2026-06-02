# DD-018: Session interaction model — companion (local) vs host (cockpit-native)

**Status**: Accepted (companion path) · Proposed (host path, long-term)
**Author**: Claude (with user)
**Date**: 2026-06-02
**Predecessors**: DD-015 (cockpit; Capability C web terminal)

## Problem

Letting the cockpit *act on* sessions accreted four overlapping mechanisms
(DD-015 Stage 3): read-view, `claude --resume` in a browser ttyd, `zellij
attach` in a browser ttyd, and `zellij write-chars` injection. Two of them
fight the environment:

- **attach (zellij)** mirrors the live session, but zellij forces ONE size
  across all attached clients (smallest wins), so a small browser terminal
  **shrank the user's real Ghostty session**. (Observed 2026-06-02.)
- **resume (`claude --resume`)** spawns a *separate* process — a fork, not a
  live view; the running interactive session never sees it, and both append
  to the same session.

Root cause: we were making the **browser the terminal for sessions that live
in the user's own terminal**. The friction is intrinsic to that mismatch.

## Decision — split by where the session lives

### A. Companion (local sessions — your terminal/zellij) — **this is the model now**

The session's home is your terminal. The cockpit does exactly three things,
none of which disturb it:

- **Observe** — read-only, auto-refreshing conversation from the session jsonl
  (`/api/transcript`). A live mirror with zero coupling: no resize, no fork.
- **Drive** — inject a message into the session's live zellij pane
  (`/api/send` → `zellij action write-chars` + Enter). Writes to the real
  interactive claude's stdin, so Ghostty *and* the read view both update —
  true two-way, **no attach, no resize**.
- **Jump** — focus the session's zellij pane (`/focus`), or open a new pane
  running `claude --resume` **in your zellij** (`/newpane`).

**Dropped: the browser attach-mirror.** Its only unique value over
observe+drive was "a full terminal in the browser," and it cannot be done
without resizing your real session (zellij limitation). Not worth it for
local sessions.

### B. Host (cockpit-native sessions) — **long-term direction**

A terminal that lives in the browser and is **not** tied to your Ghostty
zellij: the claude-stray server hosts the session in its own multiplexer
(a dedicated server-side zellij/tmux session or a tracked PTY); ttyd attaches
to *that*. Because the browser is the **sole client**, there is **no resize
clash** — the session sizes to the browser, which is correct (the browser is
its home). These sessions are persistent and reconnectable across reloads.

This is the clean place for "spin up / run a Claude Code session right here,"
independent of any local terminal. `POST /api/terminal` (ttyd, currently
resume-only) is the **seed**; the full host model (lifecycle, persistence via
a server multiplexer, listing/adopting, security/token) is future work.

### Unifying principle

Every session lives in *some* multiplexer. The cockpit **observes all** (read
jsonl) and shows them uniformly; it **drives by injection / jump** for local
ones, and (future) **owns the terminal fully** for host ones. No mechanism
ever tries to mirror a foreign terminal into the browser.

## Strategic posture

claude-stray stays **companion-first**: a situational-awareness + light-drive
cockpit over the sessions you run in your own terminal. The host model is an
*additive* capability ("a scratch/owned session in the browser"), not a pivot
to a web IDE. Maps to the north star: zero-cost switch-in = jump to your pane
(local) or open the embedded terminal (host).

## Changes by component (convergence, now)

| File | Change |
|---|---|
| `bin/serve.py` | `_handle_terminal` simplified to **resume-only** (drop the zellij-attach branch, env-strip, list-sessions detection). Kept dormant as the host-model seed (no cockpit button drives it). `/focus`, `/newpane`, `/api/send`, `/api/transcript` are the live local-path endpoints. |
| `bin/cockpit.html` | Remove the **在终端打开** (browser-terminal) action and its modal (`openTerminal`/`openTermModal`/`closeTerm`, term CSS, `/ping` capability fetch). Local detail actions become: **进入会话** (focus pane → new pane), **查看对话** (live read + send), 合并到…, 归档, 删除. |

## Cost / risk

- Convergence is mostly *removal* → less surface, less to break.
- Loses "full browser terminal" for local sessions; mitigated by observe+drive
  (covers the real need without resizing your terminal). The full browser
  terminal returns, done right, via the host model (B).

## Alternatives considered

- **Keep attach with a fix**: zellij has no per-client size / read-only attach;
  the resize is intrinsic. Rejected.
- **Go host-first (web IDE)**: bigger bet, off the companion identity; deferred
  to B as opt-in, not the default.

## References

- DD-015 — cockpit + Capability C (the four mechanisms this rationalizes).
- The 2026-06-02 session where attach-mirror shrank the user's Ghostty zellij.
