#!/usr/bin/env bash
# Coalescing wrapper around classify.py (Layer 2 per DD-002 §7.2).
#
# Pattern:
#   - At most one classify.py instance runs at a time.
#   - Concurrent calls drop a "pending" marker and exit immediately.
#   - The running instance, when done, checks the marker — if present
#     it loops and re-runs (with all summaries written during the
#     previous run now in scope).
#
# Result: a burst of N triggers collapses to ≤ 2 actual classify runs,
# while every trigger is guaranteed to be reflected in some run's
# output. No cooldown, no lost work.
#
# Lock path:   cache/.locks/layer2.lock      (flock -nx fd 9)
# Pending:     cache/.locks/layer2.pending   (touch marker)
#
# Exit codes:
#   0  ran one or more classify.py; or another instance is doing it
#   1  classify.py itself failed (logged)

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/cache"
LOCKS_DIR="$CACHE_DIR/.locks"
LOCK_FILE="$LOCKS_DIR/layer2.lock"
PENDING_FILE="$LOCKS_DIR/layer2.pending"

mkdir -p "$LOCKS_DIR"

# Log destination (platform-aware, same as refresh-bg.sh)
if [ "$(uname)" = "Darwin" ]; then
  LOG="$HOME/Library/Logs/claude-code-worktree.log"
else
  LOG="${XDG_STATE_HOME:-$HOME/.local/state}/claude-code-worktree/refresh.log"
fi
mkdir -p "$(dirname "$LOG")"

# Try to acquire the Layer 2 lock non-blocking.
exec 9>"$LOCK_FILE"
if ! flock -n 9 2>/dev/null; then
  # Another instance is running. Mark that more work arrived; that
  # instance will see it after its current classify.py finishes.
  touch "$PENDING_FILE"
  echo "[layer2-trigger] $(date -Iseconds) busy → pending marker set" >> "$LOG"
  exit 0
fi

# We own the lock. Loop until the pending marker is no longer set
# after a complete classify.py run.
rc=0
runs=0
while :; do
  # Clear pending BEFORE running so any trigger during the run gets
  # observed afterwards.
  rm -f "$PENDING_FILE"
  runs=$((runs + 1))

  echo "[layer2-trigger] $(date -Iseconds) classify run #$runs" >> "$LOG"
  python3 "$REPO_ROOT/bin/classify.py" >> "$LOG" 2>&1
  this_rc=$?
  if [ "$this_rc" -ne 0 ]; then
    echo "[layer2-trigger] classify.py exited $this_rc" >> "$LOG"
    rc=$this_rc
    # Don't loop on failure (would just retry the same broken state
    # forever; safer to surface and let next trigger try)
    break
  fi

  # If a trigger arrived during the run, do another pass.
  if [ -f "$PENDING_FILE" ]; then
    echo "[layer2-trigger] pending set during run, looping" >> "$LOG"
    continue
  fi
  break
done

# flock auto-releases on exec close.
echo "[layer2-trigger] done ($runs runs, rc=$rc)" >> "$LOG"
exit $rc
