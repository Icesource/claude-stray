#!/usr/bin/env bash
# Refresh the claude-code-worktree cache.
# 1. Incrementally extract session summaries from ~/.claude/projects
# 2. Aggregate them; if content hash matches last run, skip the AI call
# 3. Otherwise feed to `claude -p` for cross-project classification
# 4. Write the structured result to cache/mindmap.json
#
# Concurrency: a single mkdir-based lock guards the whole pipeline.
# Every caller (hook, launchd, /mindmap-refresh, manual) funnels through it.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="$REPO_ROOT/cache"
PROMPT_FILE="$REPO_ROOT/prompts/classify.md"
OUTPUT_FILE="$CACHE_DIR/mindmap.json"
INPUT_FILE="$CACHE_DIR/aggregate_input.json"
HASH_FILE="$CACHE_DIR/last_input.sha256"
LOCK_DIR="$CACHE_DIR/refresh.lock.d"
# Tracks the epoch of the LAST SUCCESSFUL AI call. The cooldown gate
# reads this — using OUTPUT_FILE mtime instead causes a subtle bug:
# apply-overrides legitimately writes to OUTPUT_FILE, which would falsely
# "reset" the cooldown clock and starve AI runs forever.
AI_MARKER="$CACHE_DIR/last_ai_run.epoch"

# Stamp every invocation so the log shows exactly what fired when.
echo "[hook] $(date -Iseconds) refresh-bg fired (pid=$$)"

mkdir -p "$CACHE_DIR"

# --- Acquire global lock (applies to every refresh path) ------------------
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  # Stale lock recovery: >10 minutes old, assume crashed and reclaim.
  if [ -d "$LOCK_DIR" ]; then
    # Stale threshold must be > CLAUDE_TIMEOUT_SECS (600s) so the legit
    # slowest run finishes before any other caller reclaims the lock.
    # stat -f %m is macOS; stat -c %Y is Linux.
    lock_mtime=$(stat -f %m "$LOCK_DIR" 2>/dev/null || stat -c %Y "$LOCK_DIR" 2>/dev/null || echo 0)
    lock_age=$(( $(date +%s) - lock_mtime ))
    if [ "$lock_age" -gt 660 ]; then
      rm -rf "$LOCK_DIR"
      mkdir "$LOCK_DIR"
    else
      echo "[refresh] another refresh is running, skip"
      exit 0
    fi
  fi
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

# --- Apply user edits from cache/user_overrides.json + cache/archive/ -----
# This bakes user-marked task done/undone, deleted tasks, and archived
# initiatives into mindmap.json BEFORE classification, so the AI sees
# the user's intent in PRIOR_MINDMAP and respects it (done-monotone rule).
echo "[refresh] applying user overrides + archive removals..."
python3 - "$CACHE_DIR" <<'PY'
import json, os, pathlib, sys
cache = pathlib.Path(sys.argv[1])
mm_path = cache / "mindmap.json"
ov_path = cache / "user_overrides.json"
arc_dir = cache / "archive"
del_path = cache / "deleted_ids.json"

if not mm_path.exists():
    sys.exit(0)

try:
    mm = json.load(open(mm_path))
except Exception:
    sys.exit(0)

if mm.get("schema_version") != 2:
    sys.exit(0)  # legacy schema — skip overrides

changed = False

# 1) Apply user_overrides.json
if ov_path.exists():
    try:
        ov = json.load(open(ov_path))
    except Exception:
        ov = {}
    task_toggles = ov.get("task_toggles") or []
    deleted_tasks = ov.get("deleted_tasks") or []
    if task_toggles or deleted_tasks:
        toggle_idx = {(tt["init_id"], tt["task_title"]): tt["done"] for tt in task_toggles}
        del_set = {(dt["init_id"], dt["task_title"]) for dt in deleted_tasks}
        applied_tog = 0
        removed_tasks = 0
        for ws in mm.get("workspaces", []):
            for init in (ws.get("initiatives") or []):
                iid = init.get("id")
                new_tasks = []
                for t in (init.get("tasks") or []):
                    title = t.get("title")
                    if (iid, title) in del_set:
                        removed_tasks += 1
                        continue
                    if (iid, title) in toggle_idx:
                        if t.get("done") != toggle_idx[(iid, title)]:
                            t["done"] = toggle_idx[(iid, title)]
                            applied_tog += 1
                    new_tasks.append(t)
                init["tasks"] = new_tasks
        if applied_tog or removed_tasks:
            print(f"[refresh]   applied {applied_tog} task toggles, removed {removed_tasks} deleted tasks")
            changed = True
        # Clear the file: edits are now baked into mindmap.json
        json.dump({"version": 1, "task_toggles": [], "deleted_tasks": [], "consumed_at": ov.get("updated_at")},
                  open(ov_path, "w"), indent=2, ensure_ascii=False)

# 2) Remove archived initiatives from mindmap.json (data preserved in cache/archive/)
if arc_dir.is_dir():
    archived_ids = set()
    for f in arc_dir.glob("*/*.json"):
        archived_ids.add(f.stem)
    if archived_ids:
        removed = 0
        for ws in mm.get("workspaces", []):
            before = len(ws.get("initiatives") or [])
            ws["initiatives"] = [i for i in (ws.get("initiatives") or []) if i.get("id") not in archived_ids]
            removed += before - len(ws.get("initiatives") or [])
        # Drop workspaces left with no initiatives
        mm["workspaces"] = [w for w in mm.get("workspaces", []) if (w.get("initiatives") or [])]
        if removed:
            print(f"[refresh]   moved {removed} initiatives to archive (excluded from mindmap.json)")
            changed = True

# 3) Apply deleted_ids tombstones to mindmap.json (also exclude from future)
if del_path.exists():
    try:
        del_list = json.load(open(del_path)).get("initiatives") or []
    except Exception:
        del_list = []
    deleted_set = {x.get("id") for x in del_list if x.get("id")}
    if deleted_set:
        removed = 0
        for ws in mm.get("workspaces", []):
            before = len(ws.get("initiatives") or [])
            ws["initiatives"] = [i for i in (ws.get("initiatives") or []) if i.get("id") not in deleted_set]
            removed += before - len(ws.get("initiatives") or [])
        mm["workspaces"] = [w for w in mm.get("workspaces", []) if (w.get("initiatives") or [])]
        if removed:
            print(f"[refresh]   removed {removed} user-deleted initiatives")
            changed = True

if changed:
    json.dump(mm, open(mm_path, "w"), indent=2, ensure_ascii=False)
PY

# --- Pipeline --------------------------------------------------------------
echo "[refresh] $(date -Iseconds) extracting sessions..."
python3 "$REPO_ROOT/bin/extract.py"

echo "[refresh] building aggregation input..."
python3 "$REPO_ROOT/bin/aggregate.py" > "$INPUT_FILE"

n_sessions=$(python3 -c "import json; print(len(json.load(open('$INPUT_FILE'))))")

if [ "$n_sessions" -eq 0 ]; then
  echo '{"schema_version":2,"generated_at":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","workspaces":[]}' > "$OUTPUT_FILE"
  echo "[refresh] no sessions, wrote empty mindmap"
  exit 0
fi

# --- Skip AI when the aggregated input hasn't changed ---------------------
# extract.py is already incremental; aggregate.py is deterministic for a
# given session cache. So if the hash of aggregate_input.json matches the
# last successful run AND mindmap.json exists, nothing real has changed
# and we can just refresh the `generated_at` timestamp.
new_hash=$(shasum -a 256 "$INPUT_FILE" | awk '{print $1}')
if [ -f "$HASH_FILE" ] && [ -f "$OUTPUT_FILE" ] && [ "$(cat "$HASH_FILE")" = "$new_hash" ]; then
  python3 - "$OUTPUT_FILE" <<'PY'
import json, sys
from datetime import datetime, timezone
path = sys.argv[1]
data = json.load(open(path))
data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(data, open(path, "w"), indent=2, ensure_ascii=False)
PY
  python3 "$REPO_ROOT/bin/render-html.py" >/dev/null 2>&1 || true
python3 "$REPO_ROOT/bin/render-tree.py" >/dev/null 2>&1 || true
  echo "[refresh] input unchanged ($new_hash), reused cached mindmap ($n_sessions sessions)"
  exit 0
fi

# --- Cooldown: skip AI call if a real AI call ran recently ---------------
# Prevents runaway costs from frequent Stop hook triggers.
# Override with CLAUDE_WORKTREE_COOLDOWN_SECS or --force (set by mindmap --refresh).
#
# Important: we use a DEDICATED marker file (last_ai_run.epoch) instead of
# OUTPUT_FILE mtime, because OUTPUT_FILE is also written by the
# apply-overrides phase. Using mtime would let apply-overrides "reset" the
# cooldown clock, starving AI runs.
COOLDOWN_SECS="${CLAUDE_WORKTREE_COOLDOWN_SECS:-300}"
if [ "${CLAUDE_WORKTREE_FORCE:-}" != "1" ] && [ -f "$AI_MARKER" ]; then
  last_ai_epoch=$(cat "$AI_MARKER" 2>/dev/null | tr -dc 0-9 || echo 0)
  last_ai_epoch="${last_ai_epoch:-0}"
  ai_age=$(( $(date +%s) - last_ai_epoch ))
  if [ "$ai_age" -lt "$COOLDOWN_SECS" ]; then
    remain=$(( COOLDOWN_SECS - ai_age ))
    echo "[refresh] SKIP-COOLDOWN: last AI run was ${ai_age}s ago (<${COOLDOWN_SECS}s); next allowed in ${remain}s"
    exit 0
  fi
  echo "[refresh] cooldown cleared (last AI run ${ai_age}s ago, >=${COOLDOWN_SECS}s)"
fi

input_kb=$(( $(wc -c < "$INPUT_FILE") / 1024 ))
echo "[refresh] input changed, feeding $n_sessions sessions (${input_kb}KB) to claude -p..."

# Resolve output language: env var > config file > default zh-CN.
OUTPUT_LANG="${CLAUDE_WORKTREE_LANG:-}"
if [ -z "$OUTPUT_LANG" ] && [ -f "$CACHE_DIR/config.json" ]; then
  OUTPUT_LANG=$(python3 -c "import json; print(json.load(open('$CACHE_DIR/config.json')).get('lang',''))" 2>/dev/null || echo "")
fi
OUTPUT_LANG="${OUTPUT_LANG:-zh-CN}"

# Resolve prior mindmap: feed back v2 output as continuity baseline.
# Skip for v1 (legacy schema), missing file, or empty workspaces.
PRIOR_BLOCK=""
if [ -f "$OUTPUT_FILE" ]; then
  PRIOR_BLOCK=$(python3 - "$OUTPUT_FILE" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
if d.get("schema_version") != 2 or not d.get("workspaces"):
    sys.exit(0)
# Compact the prior to keep prompt small; drop generated_at and full sessions.
slim = {
    "schema_version": d.get("schema_version"),
    "workspaces": [
        {
            "name": w.get("name"),
            "cwd": w.get("cwd"),
            "last_activity_at": w.get("last_activity_at"),
            "initiatives": [
                {
                    "id": i.get("id"),
                    "name": i.get("name"),
                    "status": i.get("status"),
                    "summary": i.get("summary"),
                    "progress": i.get("progress"),
                    "tasks": i.get("tasks", []),
                    "sessions": i.get("sessions", []),
                    "linked_cwds": i.get("linked_cwds", []),
                    "last_activity_at": i.get("last_activity_at"),
                }
                for i in (w.get("initiatives") or [])
            ],
        }
        for w in d.get("workspaces", [])
    ],
}
print(json.dumps(slim, ensure_ascii=False))
PY
  )
fi

# Build the full prompt: instructions + input data.
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FULL_PROMPT_FILE="$CACHE_DIR/_prompt.txt"
{
  cat "$PROMPT_FILE"
  echo
  echo "OUTPUT_LANG: $OUTPUT_LANG"
  echo
  echo "CURRENT_TIME: $NOW_ISO"
  echo "(Use this as the reference point when computing session age.)"
  echo
  if [ -n "$PRIOR_BLOCK" ]; then
    echo "PRIOR_MINDMAP:"
    echo "$PRIOR_BLOCK"
    echo
  else
    echo "PRIOR_MINDMAP: (none — cold start, build fresh from sessions)"
    echo
  fi
  # Inject tombstones if any. AI must NEVER include these IDs in output.
  if [ -f "$CACHE_DIR/deleted_ids.json" ]; then
    DEL_BLOCK=$(python3 -c "
import json, sys
try:
    d = json.load(open('$CACHE_DIR/deleted_ids.json'))
    ids = [x.get('id') for x in (d.get('initiatives') or []) if x.get('id')]
    if ids:
        print(json.dumps({'deleted_initiative_ids': ids}, ensure_ascii=False))
except Exception:
    pass
" 2>/dev/null)
    if [ -n "$DEL_BLOCK" ]; then
      echo "DELETED_IDS:"
      echo "$DEL_BLOCK"
      echo "(These IDs are user-deleted tombstones. Do NOT include them in output even if INPUT_SESSIONS has evidence.)"
      echo
    fi
  fi
  echo "INPUT_SESSIONS:"
  cat "$INPUT_FILE"
} > "$FULL_PROMPT_FILE"

prompt_kb=$(( $(wc -c < "$FULL_PROMPT_FILE") / 1024 ))

# Run claude headless, with a timeout so a stuck run cannot block everyone.
# We use --output-format json to capture token usage metrics.
# macOS has no `timeout` binary; `perl -e 'alarm ...; exec'` is portable.
# We intentionally do NOT use --bare: that mode refuses to read the OAuth
# login from the keychain, and our whole plan is to reuse the user's
# existing Claude Code subscription auth.
# --disallowedTools keeps the model from spawning tools — we want a pure
# text-in/text-out classification.
CLAUDE_TIMEOUT_SECS="${CLAUDE_WORKTREE_TIMEOUT:-600}"
CLAUDE_MODEL="${CLAUDE_WORKTREE_MODEL:-claude-haiku-4-5-20251001}"
t_start=$(date +%s)
if ! perl -e 'alarm shift @ARGV; exec @ARGV' "$CLAUDE_TIMEOUT_SECS" \
    claude -p \
      --model "$CLAUDE_MODEL" \
      --output-format json \
      --disallowedTools "Bash Edit Write Read Glob Grep" \
      < "$FULL_PROMPT_FILE" \
      > "$CACHE_DIR/_raw_output.json"; then
  rc=$?
  t_elapsed=$(( $(date +%s) - t_start ))
  echo "[refresh] claude -p failed or timed out after ${t_elapsed}s (rc=$rc), abandoning" >&2
  echo "[refresh]   prompt=${prompt_kb}KB  sessions=$n_sessions" >&2
  # Log the failure to the cost log so day-by-day stats reflect dropped calls.
  python3 -c "
import sys
sys.path.insert(0, '$REPO_ROOT/bin')
from _cost_log import log_cost
log_cost(layer='classify', envelope=None, duration_s=$t_elapsed, ok=False)
" 2>/dev/null || true
  exit 1
fi
t_elapsed=$(( $(date +%s) - t_start ))

# Extract the text result and usage stats from JSON envelope, then parse
# the mindmap JSON from the model's text output. Also produce a diff
# against the prior mindmap so the log clearly shows what AI changed.
# REPO_ROOT is passed as $5 so the heredoc can import bin/_cost_log.py.
python3 - "$CACHE_DIR/_raw_output.json" "$OUTPUT_FILE" "$prompt_kb" "$t_elapsed" "$REPO_ROOT" <<'PY'
import json, re, sys
from pathlib import Path

envelope = json.load(open(sys.argv[1]))
prompt_kb = sys.argv[3]
elapsed = sys.argv[4]
repo_root = Path(sys.argv[5])

# Append a cost record for this call. Non-fatal if logging fails.
try:
    sys.path.insert(0, str(repo_root / "bin"))
    from _cost_log import log_cost
    log_cost(layer="classify", envelope=envelope, duration_s=float(elapsed), ok=True)
except Exception as e:
    print(f"[refresh] cost-log failed: {e}", file=sys.stderr)

# --- Log usage stats --------------------------------------------------------
usage = envelope.get("usage", {})
in_tok = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
cache_create = usage.get("cache_creation_input_tokens", 0)
out_tok = usage.get("output_tokens", 0)
cost = envelope.get("total_cost_usd", 0)
print(f"[refresh] usage: in={in_tok} (+{cache_create} cache-create) out={out_tok} "
      f"cost=${cost:.4f} prompt={prompt_kb}KB elapsed={elapsed}s")

# --- Snapshot prior for diff (before overwrite) -----------------------------
prior_index = {}  # id -> {name, status, task_count}
try:
    prior = json.load(open(sys.argv[2]))
    for ws in (prior.get("workspaces") or []):
        for i in (ws.get("initiatives") or []):
            prior_index[i.get("id")] = {
                "name": i.get("name"),
                "status": i.get("status"),
                "tasks": len(i.get("tasks") or []),
                "done": sum(1 for t in (i.get("tasks") or []) if t.get("done")),
            }
except Exception:
    prior_index = {}

# --- Extract mindmap JSON from model text -----------------------------------
raw = (envelope.get("result") or "").strip()
m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
if m:
    raw = m.group(1)
if not raw.startswith("{"):
    i, j = raw.find("{"), raw.rfind("}")
    if i != -1 and j != -1:
        raw = raw[i:j+1]
data = json.loads(raw)
from datetime import datetime, timezone
data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(data, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)

# --- Build the diff ---------------------------------------------------------
new_index = {}
for ws in (data.get("workspaces") or []):
    for i in (ws.get("initiatives") or []):
        new_index[i.get("id")] = {
            "name": i.get("name"),
            "status": i.get("status"),
            "tasks": len(i.get("tasks") or []),
            "done": sum(1 for t in (i.get("tasks") or []) if t.get("done")),
        }

added = sorted(set(new_index) - set(prior_index))
removed = sorted(set(prior_index) - set(new_index))
status_changed = [i for i in (set(new_index) & set(prior_index))
                  if new_index[i]["status"] != prior_index[i]["status"]]
task_progress = [i for i in (set(new_index) & set(prior_index))
                 if new_index[i]["done"] != prior_index[i]["done"]
                 or new_index[i]["tasks"] != prior_index[i]["tasks"]]

if "workspaces" in data:
    ws_n = len(data.get("workspaces", []))
    init_n = len(new_index)
    print(f"[refresh] wrote {sys.argv[2]}: {ws_n} workspaces, {init_n} initiatives")
else:
    print(f"[refresh] wrote {sys.argv[2]} with {len(data.get('projects', []))} projects (legacy)")

if added or removed or status_changed or task_progress:
    print(f"[refresh] DIFF vs prior:")
    if added:
        for i in added:
            print(f"  + NEW initiative: {i} — {new_index[i]['name']}")
    if removed:
        for i in removed:
            print(f"  - removed initiative: {i} — {prior_index[i]['name']}")
    for i in status_changed:
        print(f"  ~ status change: {i} {prior_index[i]['status']} → {new_index[i]['status']}  ({new_index[i]['name']})")
    for i in task_progress:
        po, pn = prior_index[i], new_index[i]
        print(f"  ~ task progress: {i} tasks {po['tasks']}→{pn['tasks']}, done {po['done']}→{pn['done']}  ({pn['name']})")
else:
    print(f"[refresh] DIFF vs prior: no structural change (only timestamps/wording may have moved)")
PY

# Record the hash only after a fully successful claude -p pass.
echo "$new_hash" > "$HASH_FILE"
# Mark this as a real AI run for the cooldown gate.
date +%s > "$AI_MARKER"

# Repair any truncated session_ids in AI output. The classifier sometimes
# emits 8-char prefixes instead of full UUIDs; once that lands in
# mindmap.json it propagates via PRIOR_MINDMAP. We undo it deterministically
# by prefix-matching against the aggregate_input (which always has full ids).
python3 - "$OUTPUT_FILE" "$INPUT_FILE" <<'PY'
import json, sys
mm_path, in_path = sys.argv[1], sys.argv[2]
try:
    mm = json.load(open(mm_path))
    agg = json.load(open(in_path))
except Exception:
    sys.exit(0)
full_ids = [e.get("session_id") for e in agg if e.get("session_id")]
# index by every prefix length we might encounter (4-12 chars)
prefix_to_full = {}
for fid in full_ids:
    for L in (4, 6, 8, 10, 12):
        prefix_to_full.setdefault(fid[:L], []).append(fid)

def repair(sid):
    if not sid: return sid
    if len(sid) >= 30: return sid  # already full UUID
    cands = prefix_to_full.get(sid, [])
    if len(cands) == 1: return cands[0]
    return sid  # ambiguous or no match — leave as-is

repaired = 0
for ws in (mm.get("workspaces") or []):
    for init in (ws.get("initiatives") or []):
        new = []
        for s in (init.get("sessions") or []):
            fixed = repair(s)
            if fixed != s: repaired += 1
            new.append(fixed)
        init["sessions"] = new
if repaired:
    json.dump(mm, open(mm_path, "w"), indent=2, ensure_ascii=False)
    print(f"[refresh] repaired {repaired} truncated session_ids")
PY

# Regenerate HTML view alongside the JSON so external viewers stay fresh.
# Non-fatal: if HTML generation fails, the JSON refresh still counts as success.
python3 "$REPO_ROOT/bin/render-html.py" >/dev/null 2>&1 || true
python3 "$REPO_ROOT/bin/render-tree.py" >/dev/null 2>&1 || true
