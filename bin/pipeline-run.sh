#!/usr/bin/env bash
# 3-layer pipeline orchestrator (per DD-002 §4). Called by:
#   - bin/refresh-bg.sh on every Stop / SessionStart hook
#   - bin/mindmap --refresh (with FORCE_CLASSIFY=1 to bypass dirty
#     gating on Layer 2)
#   - bin/mindmap --backfill (delegates to backfill mode here)
#
# Flow:
#   Layer 0: extract.py reads any new jsonl bytes into cache/sessions/
#   Layer 1: for each dirty session (extract newer than summary, or
#            current session passed as --sid), run summarize.py
#   Layer 2: if any Layer 1 actually wrote a new summary, fire
#            layer2-trigger.sh (which itself coalesces concurrent fires)
#
# Concurrency: every step uses its own lock (per-sid for Layer 1, global
# coalesce for Layer 2). No global pipeline lock — multiple pipeline-run
# invocations can interleave safely.
#
# Args:
#   --sid <session_id>      Restrict Layer 1 to just this session
#   --all-dirty             Sweep all dirty sessions (also default if
#                           no --sid given)
#   --backfill              Force re-summarize every session
#   --force-classify        Always trigger Layer 2 at the end, even if
#                           Layer 1 wrote nothing new

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/cache"
SESSIONS_DIR="$CACHE_DIR/sessions"
SUMMARIES_DIR="$CACHE_DIR/summaries"

# Args
SID=""
ALL_DIRTY=0
BACKFILL=0
FORCE_CLASSIFY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --sid) SID="$2"; shift 2 ;;
    --all-dirty) ALL_DIRTY=1; shift ;;
    --backfill) BACKFILL=1; ALL_DIRTY=1; shift ;;
    --force-classify) FORCE_CLASSIFY=1; shift ;;
    *) echo "[pipeline] unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Require explicit scope. We do NOT default to "all-dirty" because on
# a fresh install with N untracked sessions that would be a surprise
# spend of N × ~$0.04 (could be $5-10 silently).
if [ -z "$SID" ] && [ "$ALL_DIRTY" -eq 0 ] && [ "$BACKFILL" -eq 0 ]; then
  cat >&2 <<EOF
[pipeline] usage: pipeline-run.sh (one of)
    --sid <session_id>     summarize a specific session (hook-triggered)
    --all-dirty            sweep all sessions whose extract is newer
                           than its summary (rare; recovery mode)
    --backfill             force re-summarize every session (one-shot
                           migration; costs ~\$0.04 per session)
    --force-classify       additionally trigger Layer 2 at the end
EOF
  exit 2
fi

echo "[pipeline] $(date -Iseconds) starting"

# ---------- Layer 0: extract ------------------------------------------------

echo "[pipeline] Layer 0: extract.py"
python3 "$REPO_ROOT/bin/extract.py" || {
  echo "[pipeline] extract.py failed" >&2
  exit 1
}

# ---------- Layer 1: per-session summarize ---------------------------------

# Find dirty sessions via Python (mtime compare + filter is_automation).
# We do this in Python because shell glob + stat is platform-dependent.
DIRTY_SIDS_FILE=$(mktemp -t pipeline-dirty-XXXXXX)
trap "rm -f $DIRTY_SIDS_FILE" EXIT

# MAX_BATCH caps a single --all-dirty / --backfill sweep so a long-idle
# install that has hundreds of dirty sessions doesn't tie up the
# pipeline (and Haiku spend) for hours in one shot. Backfill uses a
# higher cap because the user explicitly opted in. The rest get picked
# up on subsequent sweeps. --sid is never capped — it's already one.
MAX_BATCH_REFRESH=${CLAUDE_WORKTREE_MAX_BATCH_REFRESH:-40}
MAX_BATCH_BACKFILL=${CLAUDE_WORKTREE_MAX_BATCH_BACKFILL:-200}

python3 - "$SESSIONS_DIR" "$SUMMARIES_DIR" "$SID" "$BACKFILL" \
         "$MAX_BATCH_REFRESH" "$MAX_BATCH_BACKFILL" \
         > "$DIRTY_SIDS_FILE" <<'PY'
import json, sys
from pathlib import Path

sessions_dir = Path(sys.argv[1])
summaries_dir = Path(sys.argv[2])
restrict_sid = sys.argv[3] or None
backfill = sys.argv[4] == "1"
max_batch_refresh = int(sys.argv[5])
max_batch_backfill = int(sys.argv[6])

if not sessions_dir.exists():
    sys.exit(0)

candidates = []
if restrict_sid:
    p = sessions_dir / f"{restrict_sid}.json"
    if p.exists():
        candidates = [p]
else:
    candidates = list(sessions_dir.glob("*.json"))

dirty = []  # (last_activity_at, sid)
for sj in candidates:
    sid = sj.stem
    try:
        d = json.loads(sj.read_text())
    except Exception:
        continue
    if d.get("is_automation"):
        continue
    if (d.get("user_message_count", 0) or 0) < 1:
        continue
    sm = summaries_dir / f"{sid}.md"
    if backfill or not sm.exists() or sj.stat().st_mtime > sm.stat().st_mtime:
        # Most-recent-first: prefer fresh work over historical backfill,
        # so the dashboard catches up to current reality first.
        dirty.append((d.get("last_activity_at") or "", sid))

dirty.sort(reverse=True)

if not restrict_sid:
    cap = max_batch_backfill if backfill else max_batch_refresh
    if len(dirty) > cap:
        print(f"# {len(dirty)} dirty; capping to {cap} (env CLAUDE_WORKTREE_MAX_BATCH_REFRESH)",
              file=sys.stderr)
        dirty = dirty[:cap]

for _, sid in dirty:
    print(sid)
PY

DIRTY_COUNT=$(wc -l < "$DIRTY_SIDS_FILE" | tr -d '[:space:]')
echo "[pipeline] Layer 1: $DIRTY_COUNT session(s) dirty"

WROTE_ANY=0
PROCESSED=0
while IFS= read -r sid; do
  [ -z "$sid" ] && continue
  PROCESSED=$((PROCESSED + 1))
  if [ "$BACKFILL" -eq 1 ] && [ "$DIRTY_COUNT" -gt 0 ]; then
    printf "[pipeline] Layer 1 [%d/%d]: %s\n" "$PROCESSED" "$DIRTY_COUNT" "$sid"
  else
    echo "[pipeline] Layer 1: summarize $sid"
  fi
  SUMMARIZE_ARGS=("$sid")
  [ "$BACKFILL" -eq 1 ] && SUMMARIZE_ARGS+=("--force")
  python3 "$REPO_ROOT/bin/summarize.py" "${SUMMARIZE_ARGS[@]}"
  rc=$?
  case "$rc" in
    0) WROTE_ANY=1 ;;
    2) ;;  # not dirty (race with another summarize)
    3) echo "[pipeline]   skip $sid: input missing" ;;
    4) echo "[pipeline]   AI call failed for $sid" >&2 ;;
    *) echo "[pipeline]   summarize $sid returned rc=$rc" >&2 ;;
  esac
done < "$DIRTY_SIDS_FILE"

# ---------- Layer 2: classify (coalesce) -----------------------------------

if [ "$WROTE_ANY" -eq 1 ] || [ "$FORCE_CLASSIFY" -eq 1 ]; then
  echo "[pipeline] Layer 2: firing layer2-trigger.sh"
  bash "$REPO_ROOT/bin/layer2-trigger.sh"
else
  echo "[pipeline] Layer 2: nothing new, skip"
fi

echo "[pipeline] done"
