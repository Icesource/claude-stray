#!/usr/bin/env python3
"""
Layer 2 of the AI pipeline (per DD-002).

Reads:
  - cache/summaries/*.md             (Layer 1 outputs)
  - cache/mindmap.json               (PRIOR_MINDMAP)
  - cache/deleted_ids.json           (DELETED_IDS)
  - cache/user_overrides.json        (applied to PRIOR before AI call)
  - cache/archive/<ws>/<id>.json     (used to strip archived ids from PRIOR)

Calls Haiku with prompts/classify-cross-session.md.

Writes:
  - cache/mindmap.json               (replaces; atomic tmp+rename)
  - cache/cost_log.jsonl             (via _cost_log helper)
  - cache/mindmap.html (regen)       (best-effort, non-fatal)
  - cache/mindmap-tree.html (regen)

Concurrency:
  - One process at a time. Use bin/layer2-trigger.sh to launch
    (coalesce pattern: if another instance is running, the trigger
    just touches a pending marker and exits; the running instance
    loops if pending exists after its current run finishes).

Usage:
  python3 bin/classify.py                 # do the thing
  python3 bin/classify.py --dry-run       # build prompt, don't call AI
  python3 bin/classify.py --output FILE   # write to FILE instead of mindmap.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
ARCHIVE_DIR = CACHE_DIR / "archive"
MINDMAP_FILE = CACHE_DIR / "mindmap.json"
DELETED_FILE = CACHE_DIR / "deleted_ids.json"
OVERRIDES_FILE = CACHE_DIR / "user_overrides.json"
CONFIG_FILE = CACHE_DIR / "config.json"
PROMPT_FILE = REPO_ROOT / "prompts" / "classify-cross-session.md"

# Hot/cold threshold (configurable via env)
HOT_HOURS = int(os.environ.get("CLAUDE_WORKTREE_HOT_HOURS", "48"))

# claude -p settings (mirror refresh.sh)
CLAUDE_TIMEOUT_SECS = int(os.environ.get("CLAUDE_WORKTREE_TIMEOUT", "600"))
CLAUDE_MODEL = os.environ.get("CLAUDE_WORKTREE_MODEL", "claude-haiku-4-5-20251001")


# ---------- helpers ---------------------------------------------------------


def get_lang() -> str:
    env = os.environ.get("CLAUDE_WORKTREE_LANG")
    if env:
        return env
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text()).get("lang", "zh-CN")
        except Exception:
            pass
    return "zh-CN"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse leading YAML frontmatter. Returns (dict, body)."""
    if not text.startswith("---"):
        return {}, text
    # Find the closing --- on its own line.
    m = re.search(r"^---\s*$", text[3:], flags=re.MULTILINE)
    if not m:
        return {}, text
    fm_text = text[3:3 + m.start()].strip()
    body = text[3 + m.end():].lstrip("\n")
    fm = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def collect_summaries() -> list[tuple[str, dict, str]]:
    """Return [(sid, frontmatter, body)] for all summary files."""
    if not SUMMARIES_DIR.is_dir():
        return []
    out = []
    for md in sorted(SUMMARIES_DIR.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = parse_frontmatter(text)
        out.append((md.stem, fm, body))
    return out


def is_hot(fm: dict, now: datetime) -> bool:
    la = fm.get("last_activity_at", "")
    if not la:
        return False
    try:
        t = datetime.fromisoformat(la.replace("Z", "+00:00"))
    except ValueError:
        return False
    return t >= now - timedelta(hours=HOT_HOURS)


def load_prior() -> dict | None:
    if not MINDMAP_FILE.exists():
        return None
    try:
        return json.loads(MINDMAP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_deleted_ids() -> list[str]:
    if not DELETED_FILE.exists():
        return []
    try:
        d = json.loads(DELETED_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [x.get("id") for x in (d.get("initiatives") or []) if x.get("id")]


def load_overrides() -> dict | None:
    if not OVERRIDES_FILE.exists():
        return None
    try:
        return json.loads(OVERRIDES_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def archived_ids_on_disk() -> set[str]:
    """Scan cache/archive/<ws>/<id>.json — those ids are user-archived
    and must NOT appear in PRIOR fed to AI (per DD-002 §6.2)."""
    out: set[str] = set()
    if not ARCHIVE_DIR.is_dir():
        return out
    for f in ARCHIVE_DIR.glob("*/*.json"):
        out.add(f.stem)
    return out


# ---------- apply user overrides (port from refresh.sh) --------------------


def apply_user_overrides_inplace(mindmap: dict) -> int:
    """Bake task_toggles + deleted_tasks from user_overrides.json into
    the in-memory mindmap. Returns count of changes."""
    overrides = load_overrides()
    if not overrides:
        return 0
    task_toggles = overrides.get("task_toggles") or []
    deleted_tasks = overrides.get("deleted_tasks") or []
    if not (task_toggles or deleted_tasks):
        return 0
    toggle_idx = {(tt["init_id"], tt["task_title"]): tt["done"] for tt in task_toggles}
    del_set = {(dt["init_id"], dt["task_title"]) for dt in deleted_tasks}
    applied_tog = 0
    removed_tasks = 0
    for ws in mindmap.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            iid = init.get("id")
            new_tasks = []
            for t in init.get("tasks") or []:
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
        print(f"[classify] applied {applied_tog} task toggles, "
              f"removed {removed_tasks} deleted tasks")
        # Clear the consumed overrides
        try:
            OVERRIDES_FILE.write_text(
                json.dumps({"version": 1, "task_toggles": [], "deleted_tasks": [],
                            "consumed_at": now_utc_iso()},
                           indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            print(f"[classify] warning: failed to clear overrides: {e}",
                  file=sys.stderr)
    return applied_tog + removed_tasks


def strip_archived_from_prior(mindmap: dict) -> int:
    """Remove initiatives whose id is in cache/archive/. They're user-
    archived; AI must never see them in PRIOR."""
    arc_ids = archived_ids_on_disk()
    if not arc_ids:
        return 0
    removed = 0
    for ws in mindmap.get("workspaces") or []:
        before = len(ws.get("initiatives") or [])
        ws["initiatives"] = [
            i for i in (ws.get("initiatives") or [])
            if i.get("id") not in arc_ids
        ]
        removed += before - len(ws.get("initiatives") or [])
    # Drop workspaces left empty
    mindmap["workspaces"] = [
        w for w in (mindmap.get("workspaces") or [])
        if (w.get("initiatives") or [])
    ]
    if removed:
        print(f"[classify] excluded {removed} archived initiatives from PRIOR")
    return removed


def strip_deleted_from_prior(mindmap: dict, deleted_ids: list[str]) -> int:
    """Remove initiatives whose id is in deleted_ids.json tombstones."""
    if not deleted_ids:
        return 0
    del_set = set(deleted_ids)
    removed = 0
    for ws in mindmap.get("workspaces") or []:
        before = len(ws.get("initiatives") or [])
        ws["initiatives"] = [
            i for i in (ws.get("initiatives") or [])
            if i.get("id") not in del_set
        ]
        removed += before - len(ws.get("initiatives") or [])
    mindmap["workspaces"] = [
        w for w in (mindmap.get("workspaces") or [])
        if (w.get("initiatives") or [])
    ]
    if removed:
        print(f"[classify] excluded {removed} deleted-id initiatives from PRIOR")
    return removed


# ---------- prompt build ----------------------------------------------------


def slim_prior(prior: dict | None) -> dict | None:
    """Keep everything AI needs for continuity (id, name, status,
    summary, progress, tasks, sessions, linked_cwds, last_activity_at)
    and drop noise (generated_at, schema_version stays)."""
    if not prior:
        return None
    return {
        "schema_version": prior.get("schema_version", 2),
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
            for w in (prior.get("workspaces") or [])
        ],
    }


def build_prompt(hot: list[tuple[str, dict, str]],
                 prior_slim: dict | None,
                 deleted_ids: list[str],
                 lang: str) -> str:
    instructions = PROMPT_FILE.read_text(encoding="utf-8")
    parts = [instructions, ""]
    parts.append("<context>")
    parts.append(f"  <output_lang>{lang}</output_lang>")
    parts.append(f"  <now>{now_utc_iso()}</now>")
    parts.append("</context>")
    parts.append("")

    if prior_slim and prior_slim.get("workspaces"):
        parts.append("<prior_mindmap>")
        parts.append(json.dumps(prior_slim, ensure_ascii=False, indent=2))
        parts.append("</prior_mindmap>")
    else:
        parts.append("<prior_mindmap>(none — first run)</prior_mindmap>")
    parts.append("")

    if deleted_ids:
        parts.append("<deleted_ids>")
        parts.append(json.dumps({"deleted_initiative_ids": deleted_ids},
                                ensure_ascii=False))
        parts.append("</deleted_ids>")
    else:
        parts.append("<deleted_ids>(none)</deleted_ids>")
    parts.append("")

    parts.append(f'<hot_summaries count="{len(hot)}">')
    for sid, fm, body in hot:
        # Re-emit the whole summary file (frontmatter + body) so AI sees the
        # exact structure Layer 1 wrote.
        parts.append(f'<summary sid="{sid}">')
        parts.append("---")
        for k, v in fm.items():
            parts.append(f"{k}: {v}")
        parts.append("---")
        parts.append(body.rstrip())
        parts.append("</summary>")
    parts.append("</hot_summaries>")

    return "\n".join(parts)


# ---------- AI call ---------------------------------------------------------


def call_claude(prompt: str) -> tuple[dict | None, str, int, float]:
    t_start = time.time()
    try:
        argv = [
            "perl", "-e", "alarm shift @ARGV; exec @ARGV",
            str(CLAUDE_TIMEOUT_SECS),
            "claude", "-p",
            "--model", CLAUDE_MODEL,
            "--output-format", "json",
            "--disallowedTools", "Bash Edit Write Read Glob Grep",
        ]
        result = subprocess.run(
            argv, input=prompt, capture_output=True, text=True,
            timeout=CLAUDE_TIMEOUT_SECS + 10,
        )
        duration = time.time() - t_start
        if result.returncode != 0:
            return None, result.stderr or "", result.returncode, duration
        try:
            env = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, result.stdout, 1, duration
        return env, env.get("result", "") or "", 0, duration
    except subprocess.TimeoutExpired:
        return None, "timeout", 124, time.time() - t_start
    except Exception as e:
        return None, str(e), 1, time.time() - t_start


def log_cost(envelope: dict | None, duration_s: float, ok: bool) -> None:
    try:
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from _cost_log import log_cost as _log
        _log(layer="classify", envelope=envelope, duration_s=duration_s,
             session_id=None, ok=ok)
    except Exception as e:
        print(f"[classify] cost-log failed: {e}", file=sys.stderr)


# ---------- output parse + repair ------------------------------------------


def parse_ai_output(raw: str) -> dict:
    raw = raw.strip()
    # Strip surrounding code fence if present
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    if not raw.startswith("{"):
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j != -1:
            raw = raw[i:j + 1]
    return json.loads(raw)


def enforce_cold_and_done_monotone(new_mm: dict, prior: dict,
                                    hot_sids: list[str]) -> int:
    """
    Belt-and-suspenders enforcement of two hard rules from
    prompts/classify-cross-session.md:

      §5 (Cold rule)        An initiative whose sessions[] in PRIOR has
                            NO overlap with the hot sids is "cold".
                            For cold initiatives, ONLY status and
                            last_activity_at may change; everything else
                            is reverted to PRIOR values.

      §4 (Done monotone)    Any task that was done=true in PRIOR must
                            remain done=true in the output.

    AI follows the prompt most of the time but sometimes drifts. This
    pass deterministically repairs drift so downstream readers can
    trust the invariants.

    Returns the number of repairs made (for logging).
    """
    hot_sids_set = set(hot_sids)
    prior_by_id: dict[str, dict] = {}
    for w in (prior.get("workspaces") or []):
        for i in (w.get("initiatives") or []):
            prior_by_id[i.get("id")] = i

    repairs = 0
    for ws in new_mm.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            iid = init.get("id")
            prior_init = prior_by_id.get(iid)
            if prior_init is None:
                continue  # genuinely new initiative — AI is free

            prior_sessions = set(prior_init.get("sessions") or [])
            is_cold = not (prior_sessions & hot_sids_set)

            if is_cold:
                # §5: restore every field except status + last_activity_at
                for field in ("name", "summary", "progress", "tasks",
                              "sessions", "linked_cwds"):
                    if field not in prior_init:
                        continue
                    if init.get(field) != prior_init.get(field):
                        init[field] = prior_init.get(field)
                        repairs += 1
            else:
                # §4: done monotone (only relevant when AI was allowed
                # to modify tasks). Walk PRIOR tasks; for any done=true
                # in PRIOR, force done=true in output if the same title
                # still exists. Add back tasks that AI dropped.
                prior_tasks = prior_init.get("tasks") or []
                new_tasks = init.get("tasks") or []
                new_by_title = {t.get("title"): t for t in new_tasks}
                for pt in prior_tasks:
                    title = pt.get("title")
                    if not pt.get("done"):
                        continue
                    nt = new_by_title.get(title)
                    if nt is None:
                        # AI dropped a done task — add it back at end
                        new_tasks.append({"title": title, "done": True})
                        repairs += 1
                    elif not nt.get("done"):
                        nt["done"] = True
                        repairs += 1
                init["tasks"] = new_tasks
    return repairs


def repair_short_session_ids(mindmap: dict, hot_sids: list[str]) -> int:
    """If AI emitted 8-char prefixes instead of full UUIDs, restore via
    exact-prefix match against the hot sids we know."""
    prefix_to_full: dict[str, list[str]] = {}
    for fid in hot_sids:
        for L in (4, 6, 8, 10, 12):
            prefix_to_full.setdefault(fid[:L], []).append(fid)

    def repair(sid: str) -> str:
        if not sid or len(sid) >= 30:
            return sid
        cands = prefix_to_full.get(sid, [])
        return cands[0] if len(cands) == 1 else sid

    repaired = 0
    for ws in mindmap.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            new = []
            for s in init.get("sessions") or []:
                fixed = repair(s)
                if fixed != s:
                    repaired += 1
                new.append(fixed)
            init["sessions"] = new
    return repaired


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def regen_html() -> None:
    """Best-effort HTML regeneration. Failures here don't fail the run."""
    for script in ("render-html.py", "render-tree.py"):
        try:
            subprocess.run(
                ["python3", str(REPO_ROOT / "bin" / script)],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass


# ---------- DIFF logging ---------------------------------------------------


def emit_diff(prior: dict | None, new: dict) -> None:
    """Print a structured DIFF for the log, same format as refresh.sh."""
    def index(d):
        out = {}
        for ws in (d.get("workspaces") or []):
            for i in (ws.get("initiatives") or []):
                out[i.get("id")] = {
                    "name": i.get("name"),
                    "status": i.get("status"),
                    "tasks_n": len(i.get("tasks") or []),
                    "tasks_done": sum(1 for t in (i.get("tasks") or []) if t.get("done")),
                }
        return out

    p = index(prior or {})
    n = index(new)
    added = sorted(set(n) - set(p))
    removed = sorted(set(p) - set(n))
    common = set(n) & set(p)
    status_changed = [i for i in common if p[i]["status"] != n[i]["status"]]
    name_changed = [i for i in common if p[i]["name"] != n[i]["name"]]
    task_progress = [
        i for i in common
        if p[i]["tasks_n"] != n[i]["tasks_n"]
        or p[i]["tasks_done"] != n[i]["tasks_done"]
    ]

    if not (added or removed or status_changed or name_changed or task_progress):
        print("[classify] DIFF vs prior: no structural change")
        return
    print("[classify] DIFF vs prior:")
    for i in added:
        print(f"  + NEW: {i} — {n[i]['name']}")
    for i in removed:
        print(f"  - REMOVED: {i} — {p[i]['name']}")
    for i in status_changed:
        print(f"  ~ status: {i} {p[i]['status']} → {n[i]['status']}  ({n[i]['name']})")
    for i in name_changed:
        print(f"  ~ name: {i}  {p[i]['name']!r} → {n[i]['name']!r}")
    for i in task_progress:
        print(f"  ~ tasks: {i} {p[i]['tasks_n']}→{n[i]['tasks_n']}, "
              f"done {p[i]['tasks_done']}→{n[i]['tasks_done']}  ({n[i]['name']})")


# ---------- main ------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer 2: cross-session classifier")
    ap.add_argument("--dry-run", action="store_true",
                    help="build prompt, print summary, do not call AI")
    ap.add_argument("--output", type=Path, default=None,
                    help=f"write result to FILE instead of {MINDMAP_FILE}")
    args = ap.parse_args()

    output_path = args.output or MINDMAP_FILE

    # ---- 1. Load + clean PRIOR ----
    prior = load_prior() or {"schema_version": 2, "workspaces": []}
    apply_user_overrides_inplace(prior)
    strip_archived_from_prior(prior)
    deleted_ids = load_deleted_ids()
    # Note: don't strip deleted from PRIOR if you want AI to see the
    # tombstones explicitly; instead we pass deleted_ids separately.
    # But we DO need to remove them from the AI's PRIOR view because
    # the prompt §3 says "never include deleted ids in output" — if AI
    # sees them in PRIOR it might preserve them out of continuity.
    strip_deleted_from_prior(prior, deleted_ids)
    prior_slim = slim_prior(prior)

    # ---- 2. Hot summaries ----
    all_summaries = collect_summaries()
    now = datetime.now(timezone.utc)
    hot = [(sid, fm, body) for sid, fm, body in all_summaries if is_hot(fm, now)]
    cold_count = len(all_summaries) - len(hot)

    print(f"[classify] summaries: {len(all_summaries)} total, "
          f"{len(hot)} hot (last {HOT_HOURS}h), {cold_count} cold")
    if not hot and (prior_slim is None or not prior_slim.get("workspaces")):
        print("[classify] nothing to classify (no hot summaries, no prior)",
              file=sys.stderr)
        return 0

    # ---- 3. Build prompt ----
    lang = get_lang()
    prompt = build_prompt(hot, prior_slim, deleted_ids, lang)
    prompt_kb = len(prompt.encode("utf-8")) / 1024

    if args.dry_run:
        print(f"[classify] dry-run: prompt={prompt_kb:.1f}KB, "
              f"{len(hot)} hot summaries")
        print(f"[classify] would write to {output_path}")
        # Optional: also dump prompt preview
        preview_path = CACHE_DIR / "_classify_prompt_preview.txt"
        preview_path.write_text(prompt, encoding="utf-8")
        print(f"[classify] prompt dumped to {preview_path}")
        return 0

    print(f"[classify] feeding {len(hot)} hot summaries to AI "
          f"(prompt={prompt_kb:.1f}KB)")

    # ---- 4. Call AI ----
    envelope, raw, rc, duration = call_claude(prompt)
    if rc != 0 or not raw.strip():
        print(f"[classify] AI call failed (rc={rc}, duration={duration:.1f}s)",
              file=sys.stderr)
        if raw:
            print(f"  output: {raw[:500]}", file=sys.stderr)
        log_cost(envelope, duration, ok=False)
        return 1

    # ---- 5. Parse + repair ----
    try:
        new_mm = parse_ai_output(raw)
    except json.JSONDecodeError as e:
        print(f"[classify] AI output is not parseable JSON: {e}", file=sys.stderr)
        print(f"  raw start: {raw[:500]}", file=sys.stderr)
        log_cost(envelope, duration, ok=False)
        return 1

    new_mm["generated_at"] = now_utc_iso()
    hot_sids = [s for s, _, _ in hot]
    repaired = repair_short_session_ids(new_mm, hot_sids)
    if repaired:
        print(f"[classify] repaired {repaired} truncated session_ids")
    rule_repairs = enforce_cold_and_done_monotone(new_mm, prior, hot_sids)
    if rule_repairs:
        print(f"[classify] enforced cold/done-monotone rules: {rule_repairs} repairs")

    # ---- 6. Write + diff + log ----
    atomic_write_json(output_path, new_mm)
    ws_n = len(new_mm.get("workspaces") or [])
    init_n = sum(len(w.get("initiatives") or []) for w in new_mm.get("workspaces") or [])
    print(f"[classify] wrote {output_path}: {ws_n} workspaces, {init_n} initiatives")
    emit_diff(prior, new_mm)
    log_cost(envelope, duration, ok=True)

    # ---- 7. Regen HTML (only when writing to canonical mindmap.json) ----
    if output_path == MINDMAP_FILE:
        regen_html()

    return 0


if __name__ == "__main__":
    sys.exit(main())
