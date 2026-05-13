#!/usr/bin/env bash
# Fire-and-forget wrapper for refresh.sh (claude-code-worktree).
# Returns immediately so it never blocks the Stop/SessionStart hook.
#
# Also captures the current session's terminal location (Zellij pane id,
# cwd, etc.) into cache/session_locations.json — used by the HTML UI to
# jump back to the right pane via P5's mindmap --serve helper.
#
# Concurrency for refresh.sh is handled inside refresh.sh itself
# (mkdir-based lock), so this wrapper just records location and detaches
# the refresh fork.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Platform-aware log location.
if [ "$(uname)" = "Darwin" ]; then
  LOG="$HOME/Library/Logs/claude-code-worktree.log"
else
  LOG="${XDG_STATE_HOME:-$HOME/.local/state}/claude-code-worktree/refresh.log"
fi

mkdir -p "$(dirname "$LOG")"

# Hooks pipe a JSON payload on stdin (session_id, cwd, etc.). We must
# consume it BEFORE detaching, since after fork the FD may close.
# record-location.py reads stdin with a small timeout and is non-fatal.
python3 "$REPO_ROOT/bin/record-location.py" 2>>"$LOG" || true

(
  echo "[$(date -Iseconds)] refresh-bg invoked" >> "$LOG"
  bash "$REPO_ROOT/bin/refresh.sh" >> "$LOG" 2>&1
  echo "[$(date -Iseconds)] refresh-bg finished" >> "$LOG"
) </dev/null >/dev/null 2>&1 &

disown 2>/dev/null || true
exit 0
