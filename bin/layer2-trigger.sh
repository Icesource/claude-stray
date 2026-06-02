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
# Lock path:   cache/.locks/layer2.lock.d/   (atomic mkdir; portable, no flock)
# Pending:     cache/.locks/layer2.pending   (touch marker)
# Stale lock:  if lock.d/ is older than $STALE_SECS, force-remove first
#
# Why mkdir-based locking and not flock(1):
#   `flock` is util-linux and absent from stock macOS. Bash on macOS would
#   silently fail this script (exit 127 from flock) and Layer 2 would
#   never run. mkdir(2) is atomic on POSIX, available everywhere.
#
# Exit codes:
#   0  ran one or more classify.py; or another instance is doing it
#   1  classify.py itself failed (logged)

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/cache"
LOCKS_DIR="$CACHE_DIR/.locks"
LOCK_DIR_PATH="$LOCKS_DIR/layer2.lock.d"
PENDING_FILE="$LOCKS_DIR/layer2.pending"
# Stale-lock threshold. The lock-holder also touches the lockdir mtime
# before each classify iteration (heartbeat), so this is the maximum
# time a SINGLE classify.py run is allowed to take without being
# considered hung. classify averages ~100s; bursts of pending-set →
# rerun can stretch one iteration to a few minutes (waiting on AI
# response). Bumped from 15min to 30min to leave generous headroom and
# avoid the 2026-05-15 race where a long catch-up burst ate its own
# lock and let a second classify run concurrently.
STALE_SECS=1800  # 30 min

mkdir -p "$LOCKS_DIR"

# Log destination (platform-aware, same as refresh-bg.sh)
if [ "$(uname)" = "Darwin" ]; then
  LOG="$HOME/Library/Logs/claude-stray.log"
else
  LOG="${XDG_STATE_HOME:-$HOME/.local/state}/claude-stray/refresh.log"
fi
mkdir -p "$(dirname "$LOG")"

# Corrupt-lock cleanup. The lock is a *directory* (atomic mkdir). If the
# path exists as a NON-directory (e.g. a 0-byte file left by an older or
# interrupted run), `mkdir` can never succeed and Layer 2 is blocked
# FOREVER — every trigger just sets the pending marker and exits, so
# classify.py never runs and dashboard.json goes permanently stale.
# (Observed 2026-06-02: a May-29 0-byte `layer2.lock.d` file froze Layer 2
# for days.) The stale-dir check below only fires for directories, so this
# non-dir case must be handled explicitly.
if [ -e "$LOCK_DIR_PATH" ] && [ ! -d "$LOCK_DIR_PATH" ]; then
  echo "[layer2-trigger] $(date -Iseconds) removing corrupt non-dir lock" >> "$LOG"
  rm -f "$LOCK_DIR_PATH" 2>/dev/null || true
fi

# Stale-lock cleanup. If a previous run was killed -9 the lockdir lingers
# and blocks all future runs. Use `find -mtime` since `stat` is non-portable.
if [ -d "$LOCK_DIR_PATH" ]; then
  if find "$LOCK_DIR_PATH" -maxdepth 0 -mmin +$((STALE_SECS / 60)) 2>/dev/null | grep -q .; then
    echo "[layer2-trigger] $(date -Iseconds) clearing stale lock (>${STALE_SECS}s)" >> "$LOG"
    rmdir "$LOCK_DIR_PATH" 2>/dev/null || true
  fi
fi

# Atomic acquire: mkdir succeeds iff dir doesn't already exist.
if ! mkdir "$LOCK_DIR_PATH" 2>/dev/null; then
  # Another instance is running. Mark that more work arrived; that
  # instance will see it after its current classify.py finishes.
  touch "$PENDING_FILE"
  echo "[layer2-trigger] $(date -Iseconds) busy → pending marker set" >> "$LOG"
  exit 0
fi

# Release the lock on any exit path (normal, signal, errexit).
trap 'rmdir "$LOCK_DIR_PATH" 2>/dev/null || true' EXIT INT TERM

# We own the lock. Loop until the pending marker is no longer set
# after a complete classify.py run.
rc=0
runs=0
while :; do
  # Clear pending BEFORE running so any trigger during the run gets
  # observed afterwards.
  rm -f "$PENDING_FILE"
  runs=$((runs + 1))

  # Heartbeat: refresh the lockdir mtime so the stale-lock cleanup
  # in concurrent layer2-trigger.sh invocations doesn't conclude that
  # we're hung just because our coalesce loop has been busy a while.
  touch "$LOCK_DIR_PATH" 2>/dev/null || true

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

# Lock released by EXIT trap. (DD-006 next_steps generation used to
# fire here; moved to the serve.py scheduler so it follows the lazy-
# refresh principle — regenerate only when the user has the dashboard
# open, not on every background classify.)
echo "[layer2-trigger] done ($runs runs, rc=$rc)" >> "$LOG"
exit $rc
