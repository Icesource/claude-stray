#!/usr/bin/env python3
"""
Layer 1 of the AI pipeline (per DD-002).

Reads:
  - cache/sessions/<sid>.json                 (machine signals from extract.py)
  - ~/.claude/projects/.../<sid>.jsonl tail   (last N user-assistant turns)

Calls Haiku with prompts/summarize-session.md.

Writes:
  - cache/summaries/<sid>.md                  (structured narrative markdown)

Locks:
  - cache/.locks/summary-<sid>.lock           (flock per-sid; concurrent
                                                across different sids)

Dirty check:
  - Skip if cache/summaries/<sid>.md mtime >= cache/sessions/<sid>.json mtime
  - Force via --force

Triggers Layer 2 after a successful write (to be implemented in
bin/layer2-trigger.sh; this script invokes it if present).

Usage:
  python3 bin/summarize.py <session_id>
  python3 bin/summarize.py <session_id> --force
  python3 bin/summarize.py <session_id> --dry-run   # build prompt, don't call AI
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
CACHE_DIR = REPO_ROOT / "cache"
SESSIONS_DIR = CACHE_DIR / "sessions"
SUMMARIES_DIR = CACHE_DIR / "summaries"
LOCKS_DIR = CACHE_DIR / ".locks"
CONFIG_FILE = CACHE_DIR / "config.json"
DASHBOARD_FILE = CACHE_DIR / "dashboard.json"
PROMPT_FILE = REPO_ROOT / "prompts" / "summarize-session.md"

# Tail size for the raw jsonl. We read the WHOLE jsonl in (it's local
# and small) but pass only the last N user-assistant turns to the AI,
# capped by characters.
MAX_TURNS = 12              # user+assistant pairs
MAX_CHARS_PER_TURN = 8000   # one turn text cap
MAX_TOTAL_TURNS_CHARS = 30000  # total budget for <turns> block

# Haiku invocation defaults
CLAUDE_TIMEOUT_SECS = int(os.environ.get("CLAUDE_WORKTREE_TIMEOUT", "120"))
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


def find_jsonl(sid: str) -> Path | None:
    """Find ~/.claude/projects/*/<sid>.jsonl. Returns None if missing."""
    for f in PROJECTS_DIR.glob(f"*/{sid}.jsonl"):
        return f
    return None


def extract_turn_text(rec: dict) -> str:
    """Extract user-visible text from one jsonl record.

    Returns "" if this record has no displayable text (e.g. pure tool_use
    blocks, system messages, tool_result pseudo-user wrappers).
    """
    t = rec.get("type")
    if t not in ("user", "assistant"):
        return ""
    msg = rec.get("message") or {}
    if not isinstance(msg, dict):
        return ""

    # user side: skip tool_result wrappers; keep real user text
    if t == "user" and rec.get("toolUseResult"):
        return ""

    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                txt = (block.get("text") or "").strip()
                if txt:
                    parts.append(txt)
            elif btype == "tool_use" and t == "assistant":
                name = block.get("name", "tool")
                inp = block.get("input") or {}
                # one-line description so the AI can tell what tool ran
                preview = ""
                if name in ("Bash",):
                    preview = (inp.get("command") or "")[:120]
                elif name in ("Write", "Edit", "NotebookEdit"):
                    preview = inp.get("file_path") or inp.get("notebook_path") or ""
                elif name in ("Read",):
                    preview = inp.get("file_path") or ""
                elif name in ("Grep", "Glob"):
                    preview = inp.get("pattern") or inp.get("query") or ""
                else:
                    preview = ""
                if preview:
                    parts.append(f"[tool: {name}] {preview}")
                else:
                    parts.append(f"[tool: {name}]")
        return "\n".join(parts).strip()
    return ""


def build_turns_block(jsonl_path: Path) -> tuple[str, int]:
    """Return (turns_text, count) — the last MAX_TURNS meaningful turns,
    capped at MAX_TOTAL_TURNS_CHARS."""
    turns: list[tuple[str, str, str]] = []   # (role, ts, text)
    try:
        with jsonl_path.open("rb") as f:
            for raw in f:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = rec.get("type")
                if t not in ("user", "assistant"):
                    continue
                text = extract_turn_text(rec)
                if not text:
                    continue
                turns.append((t, rec.get("timestamp", ""), text))
    except OSError as e:
        return f"(jsonl read error: {e})", 0

    if not turns:
        return "(no user-assistant turns found)", 0

    # Keep only the last MAX_TURNS
    selected = turns[-MAX_TURNS:]

    # Format
    lines: list[str] = []
    for role, ts, text in selected:
        if len(text) > MAX_CHARS_PER_TURN:
            text = text[:MAX_CHARS_PER_TURN] + "\n…[truncated]"
        ts_short = ts[:19] if ts else "?"
        lines.append(f"### {role} ({ts_short})")
        lines.append(text)
        lines.append("")

    block = "\n".join(lines).strip()
    if len(block) > MAX_TOTAL_TURNS_CHARS:
        # Trim from the START, keep tail
        block = "[older turns trimmed]\n\n" + block[-MAX_TOTAL_TURNS_CHARS:]
    return block, len(selected)


LOCK_PRUNE_SECS = 3600  # a held lock is re-touched <2min ago; older files are abandoned


def prune_stale_locks() -> None:
    """Delete leaked summary-*.lock files. flock RELEASES on process exit, but the
    FILE lingers — one per sid ever summarized (observed: 1863 piled up since May).
    Any lock whose mtime is older than LOCK_PRUNE_SECS can't be held (no summarize
    runs that long), so removing it is safe. Best-effort; never raises."""
    try:
        cutoff = time.time() - LOCK_PRUNE_SECS
        for f in LOCKS_DIR.glob("summary-*.lock"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
    except Exception:
        pass


def acquire_lock(sid: str):
    """flock per-sid. Returns the open file handle (caller keeps it open
    until done). Blocks until acquired."""
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCKS_DIR / f"summary-{sid}.lock"
    fh = open(lock_path, "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def release_lock(fh) -> None:
    try:
        fcntl.flock(fh, fcntl.LOCK_UN)
    finally:
        fh.close()


def atomic_write(path: Path, content: str) -> None:
    """tmp + rename, so readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ---------- prompt build ----------------------------------------------------


def load_prior_tasks_for_sid(sid: str) -> list[dict]:
    """Return the task list of any initiative whose `sessions[]` already
    contains this sid. Used by build_prompt to give Layer 1 stable
    wordings to reuse across reruns (DD-012).

    Returns [] when there's no dashboard.json yet (first run), or when
    no initiative has claimed this session yet. Returns up to ~30
    tasks across all matching initiatives — cap is defensive against
    a card that's already gone runaway; the prompt is the wrong place
    to dump 60 tasks worth of text.
    """
    if not DASHBOARD_FILE.exists():
        return []
    try:
        d = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    seen: dict[str, dict] = {}
    for ws in (d.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            if sid not in (init.get("sessions") or []):
                continue
            for t in (init.get("tasks") or []):
                title = (t.get("title") or "").strip()
                status = t.get("status") or "pending"
                if not title:
                    continue
                # Cancelled tasks aren't useful here — Layer 1
                # shouldn't be encouraged to reuse a wording the user
                # already abandoned. Same intent if the user wants
                # the work to come back, the new wording is fine.
                if status == "cancelled":
                    continue
                # Dedup against exact-title duplicates already on the
                # card. The card itself may carry duplicates (a card
                # in a runaway state has dozens) — handing all of
                # them to Layer 1 confuses the prompt. Keep one entry
                # per title; prefer the "done" status when both
                # variants exist (so Layer 1 doesn't accidentally
                # mark a finished task pending again).
                cur = seen.get(title)
                if cur is None:
                    seen[title] = {"title": title, "status": status}
                elif cur["status"] != "done" and status == "done":
                    cur["status"] = "done"
    return list(seen.values())[:30]


def load_prior_title_for_sid(sid: str) -> str:
    """DD-033: the name this session's card currently shows, fed back so
    Layer 1 keeps `title:` stable across reruns (same pattern as
    prior_tasks / prior_sealed_segments).

    Precedence: the dashboard card's `name` (covers user renames and
    legacy Layer-2-minted names) over this session's own previous
    summary `title:`. Returns "" when neither exists yet."""
    if DASHBOARD_FILE.exists():
        try:
            d = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
            for ws in (d.get("workspaces") or []):
                for init in (ws.get("initiatives") or []):
                    if init.get("sealed"):
                        continue
                    if sid in (init.get("sessions") or []):
                        name = (init.get("name") or "").strip()
                        if name:
                            return name
        except (OSError, json.JSONDecodeError):
            pass
    prior_md = SUMMARIES_DIR / f"{sid}.md"
    if prior_md.exists():
        try:
            for line in prior_md.read_text(encoding="utf-8").splitlines():
                if line.startswith("title:"):
                    return line.split(":", 1)[1].strip().strip('"').strip("'")
                if line.startswith("# "):  # past frontmatter — stop
                    break
        except OSError:
            pass
    return ""


def load_prior_sealed_segments_for_sid(sid: str) -> list[dict]:
    """Return the sealed_segments already minted FROM this session
    (DD-019 intra-session segmentation). A sealed initiative is a frozen
    historical card with `sessions: []` and `origin_session == sid`, born
    when Layer 1 detected that an earlier sub-effort of this session
    reached a terminal state and the session then pivoted.

    Feeding these back lets Layer 1 re-emit each sealed segment
    byte-for-byte (Rule 13), so the card doesn't flicker or duplicate
    across reruns. Returns [] before there's a dashboard or when this
    session has sealed nothing yet.
    """
    if not DASHBOARD_FILE.exists():
        return []
    try:
        d = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[dict] = []
    for ws in (d.get("workspaces") or []):
        for init in (ws.get("initiatives") or []):
            if not init.get("sealed"):
                continue
            if init.get("origin_session") != sid:
                continue
            out.append({
                "seg_id": init.get("seg_id") or init.get("id") or "",
                "title": init.get("name") or "",
                "status": "abandoned" if (init.get("status") == "archived")
                          else "done",
                "summary": init.get("summary") or "",
                "sealed_at": init.get("sealed_at")
                             or init.get("last_activity_at") or "",
                "artifacts": init.get("artifacts") or [],
            })
    return out


def _yq(s) -> str:
    """Quote a scalar for the hand-rolled YAML dump below. Always quote so
    colons / leading digits / unicode in titles never break the parser the
    model is asked to mirror."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_dump_sealed(segs: list[dict]) -> str:
    """Render sealed segments as a YAML list mirroring the Rule 13 schema,
    so Layer 1 can copy it verbatim. Hand-rolled (no yaml dep)."""
    lines: list[str] = []
    for seg in segs:
        lines.append(f"  - seg_id: {_yq(seg.get('seg_id', ''))}")
        lines.append(f"    title: {_yq(seg.get('title', ''))}")
        lines.append(f"    status: {seg.get('status', 'done')}")
        lines.append(f"    summary: {_yq(seg.get('summary', ''))}")
        if seg.get("sealed_at"):
            lines.append(f"    sealed_at: {seg['sealed_at']}")
        arts = seg.get("artifacts") or []
        if arts:
            lines.append("    artifacts:")
            for a in arts:
                first = True
                for k in ("type", "ref_id", "url", "status", "title",
                          "last_mentioned_at"):
                    v = a.get(k)
                    if v in (None, ""):
                        continue
                    val = _yq(v) if k in ("ref_id", "title", "url") else v
                    prefix = "      - " if first else "        "
                    lines.append(f"{prefix}{k}: {val}")
                    first = False
                if first:  # artifact had no renderable fields
                    lines.append("      - type: other")
    return "\n".join(lines)


def build_prompt(sid: str, meta: dict, turns_block: str, lang: str) -> str:
    """Concatenate prompts/summarize-session.md + XML context blocks."""
    instructions = PROMPT_FILE.read_text(encoding="utf-8")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    parts = [
        instructions,
        "",
        "<context>",
        f"  <output_lang>{lang}</output_lang>",
        f"  <now>{now_iso}</now>",
        "</context>",
        "",
        "<session_meta>",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "</session_meta>",
        "",
    ]

    # DD-033: surface the card name this session already shows, so Layer 1
    # re-emits `title:` byte-for-byte instead of re-wording it every rerun
    # (card names must not flicker across refreshes). See Rule 15.
    prior_title = load_prior_title_for_sid(sid)
    if prior_title:
        safe_pt = prior_title.replace('"', '\\"')
        parts.append("<prior_title>")
        parts.append("  <!-- The card name currently displayed for this session.")
        parts.append("    COPY IT BYTE-FOR-BYTE into your `title:` frontmatter")
        parts.append("    unless the session's goal has genuinely pivoted.")
        parts.append("    See Rule 15. -->")
        parts.append(f"  \"{safe_pt}\"")
        parts.append("</prior_title>")
        parts.append("")

    # DD-012: surface the task wordings that already exist on this
    # session's initiative(s), so Layer 1 reuses them verbatim instead
    # of inventing a synonym on every rerun (which silently exploded
    # task lists — see DD-012 §"Root cause"). Only present when there
    # is something to reuse.
    prior_tasks = load_prior_tasks_for_sid(sid)
    if prior_tasks:
        parts.append(f"<prior_tasks count=\"{len(prior_tasks)}\">")
        parts.append("  <!--")
        parts.append("    Below are the task titles already on this session's")
        parts.append("    initiative card. If your transcript analysis would")
        parts.append("    produce a task that is conceptually the same as one")
        parts.append("    of these, COPY ITS TITLE BYTE-FOR-BYTE in your")
        parts.append("    tasks: frontmatter (don't translate, retag, summarize,")
        parts.append("    or expand). Only emit a different title for genuinely")
        parts.append("    new work. See Rule 12.")
        parts.append("  -->")
        for t in prior_tasks:
            parts.append(f"  - status: {t['status']}")
            # Keep title quoted so newlines / colons inside don't break parsers
            safe_title = t["title"].replace('"', '\\"')
            parts.append(f"    title: \"{safe_title}\"")
        parts.append("</prior_tasks>")
        parts.append("")

    # DD-019: surface sealed segments already minted from this session, so
    # Layer 1 re-emits them byte-for-byte in its `sealed_segments:`
    # frontmatter (Rule 13) instead of dropping or re-slugging them on
    # rerun (which would flicker/duplicate the frozen historical card).
    prior_sealed = load_prior_sealed_segments_for_sid(sid)
    if prior_sealed:
        parts.append(f"<prior_sealed_segments count=\"{len(prior_sealed)}\">")
        parts.append("  <!--")
        parts.append("    Each entry below is a segment you SEALED on a prior")
        parts.append("    run. Re-emit every one VERBATIM in your")
        parts.append("    sealed_segments: frontmatter (seg_id, title, status,")
        parts.append("    summary, sealed_at, artifacts) — do not retranslate,")
        parts.append("    re-slug, reorder, or drop. See Rule 13.")
        parts.append("  -->")
        parts.append(yaml_dump_sealed(prior_sealed))
        parts.append("</prior_sealed_segments>")
        parts.append("")

    parts.extend([
        f"<turns count=\"{turns_block.count('### ')}\">",
        turns_block,
        "</turns>",
    ])
    return "\n".join(parts)


_NEXT_SENTINELS = {"(无明确)", "(nonestated)", "(none)", "(无)", "(待定)"}


def _guard_done_status(out: str, sid: str) -> str:
    """DD-013 mechanical guard: a session is NOT `done` while a concrete next
    step remains. Layer 1 sometimes marks an investigation `done` the moment it
    'locates a root cause', even though `下一步` lists open follow-ups (observed:
    HSF 地址发现诊断 — confirmed interface-level but not *why*, 4 next-steps, yet
    status_guess=done). If status_guess==done but the `下一步` section has real
    content (not the empty sentinel), downgrade to `active`. Mechanical, so it
    holds regardless of whether the model obeys the prompt."""
    import re as _re
    m = _re.search(r'(?m)^status_guess:\s*(\w+)\s*$', out)
    if not m or m.group(1).strip().lower() != "done":
        return out
    # Pull the `下一步` / `Next` H1 section body.
    nxt, grab = "", False
    for ln in out.splitlines():
        if ln.startswith("# "):
            if grab:
                break
            h = ln[2:].strip()
            grab = h.startswith("下一步") or h.lower().startswith("next")
            continue
        if grab:
            nxt += ln.strip()
    nxt_norm = nxt.replace(" ", "")
    if nxt_norm and nxt_norm not in _NEXT_SENTINELS:
        out = _re.sub(r'(?m)^(status_guess:\s*)done\s*$', r'\1active', out, count=1)
        print(f"[summarize] guard: {sid} status_guess done→active "
              f"(下一步 still has open items)", file=sys.stderr)
    return out


# ---------- AI call ---------------------------------------------------------


def call_claude(prompt: str) -> tuple[dict | None, str, int, float]:
    """Run claude -p with the given prompt. Returns (envelope, raw_text,
    rc, duration_s)."""
    t_start = time.time()
    try:
        # macOS lacks `timeout`; perl alarm is the portable trick.
        # --no-session-persistence prevents the nested call from being
        # logged as a new jsonl, which is what previously made extract.py
        # treat it as a fresh "user session" and re-summarize it on the
        # next hook — the self-recursion that ate $51 on 2026-05-14.
        # (We tried --bare too but it disables OAuth, requiring an
        # ANTHROPIC_API_KEY env var; not viable for OAuth-only setups.)
        # --max-budget-usd is a per-call hard ceiling; a normal summarize
        # is ~$0.03, $0.50 is generous and stops pathological blowups.
        argv = [
            "perl", "-e", "alarm shift @ARGV; exec @ARGV",
            str(CLAUDE_TIMEOUT_SECS),
            "claude", "--no-session-persistence", "-p",
            "--model", CLAUDE_MODEL,
            "--output-format", "json",
            "--max-budget-usd", "0.50",
            "--disallowedTools", "Bash Edit Write Read Glob Grep",
        ]
        result = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
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


# ---------- log cost --------------------------------------------------------


def log_cost(layer: str, envelope: dict | None, duration_s: float,
             session_id: str, ok: bool) -> None:
    """Append cost record via shared helper."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        from _cost_log import log_cost as _log
        _log(layer=layer, envelope=envelope, duration_s=duration_s,
             session_id=session_id, ok=ok)
    except Exception as e:
        print(f"[summarize] cost-log failed: {e}", file=sys.stderr)


# ---------- main ------------------------------------------------------------


def summarize_one(sid: str, *, force: bool = False, dry_run: bool = False) -> int:
    """Returns exit code: 0 success, 1 generic error, 2 not-dirty-skipped,
    3 input missing, 4 AI call failed."""

    extract_path = SESSIONS_DIR / f"{sid}.json"
    if not extract_path.exists():
        print(f"[summarize] extract not found: {extract_path}", file=sys.stderr)
        return 3

    try:
        meta = json.loads(extract_path.read_text())
    except json.JSONDecodeError as e:
        print(f"[summarize] extract unreadable: {e}", file=sys.stderr)
        return 3

    if meta.get("is_automation"):
        print(f"[summarize] skip {sid} (is_automation)")
        return 0

    jsonl_path = find_jsonl(sid)
    if not jsonl_path:
        print(f"[summarize] jsonl not found for {sid}", file=sys.stderr)
        return 3

    # Lock this sid
    lock = acquire_lock(sid)
    try:
        # Dirty check
        summary_path = SUMMARIES_DIR / f"{sid}.md"
        if not force and summary_path.exists():
            try:
                if summary_path.stat().st_mtime >= extract_path.stat().st_mtime:
                    print(f"[summarize] skip {sid} (not dirty)")
                    return 2
            except OSError:
                pass

        # Build prompt
        turns_block, n_turns = build_turns_block(jsonl_path)
        if n_turns == 0:
            print(f"[summarize] skip {sid} (no displayable turns)")
            return 2

        # Filter meta to machine-readable fields (forward-compat with the
        # slimmer extract.py that DD-002 §4.2 plans)
        slim_meta = {
            k: meta.get(k)
            for k in (
                "session_id", "cwd", "started_at", "last_activity_at",
                "user_message_count", "edited_files", "task_events",
                "tools_used",
            )
            if meta.get(k) is not None
        }
        # Rename to forward-compatible names
        slim_meta["user_turns"] = slim_meta.pop("user_message_count", 0)

        prompt = build_prompt(sid, slim_meta, turns_block, get_lang())
        prompt_kb = len(prompt.encode("utf-8")) / 1024

        if dry_run:
            print(f"[summarize] dry-run for {sid}, prompt={prompt_kb:.1f}KB, "
                  f"{n_turns} turns")
            print("--- PROMPT (first 2KB) ---")
            print(prompt[:2000])
            print("--- (...) ---")
            print(prompt[-1000:])
            return 0

        # Call AI
        print(f"[summarize] {sid} prompt={prompt_kb:.1f}KB turns={n_turns}")
        envelope, raw, rc, duration = call_claude(prompt)

        if rc != 0 or not raw.strip():
            print(f"[summarize] AI call failed for {sid} (rc={rc}, "
                  f"duration={duration:.1f}s)", file=sys.stderr)
            if raw:
                print(f"  stderr/output: {raw[:500]}", file=sys.stderr)
            log_cost("summarize", envelope, duration, sid, ok=False)
            return 4

        # Strip any markdown code fence wrapper if present
        out = raw.strip()
        if out.startswith("```"):
            # Drop first line (```markdown or ```) and last fence
            lines = out.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            out = "\n".join(lines)

        # Repair: Haiku occasionally emits ``` as the YAML frontmatter
        # close-fence instead of ---, because the prompt's example block
        # happens to be wrapped in a markdown code fence. If the output
        # starts with --- and the first ``` line appears BEFORE any other
        # --- line, swap that ``` for --- so parse_frontmatter works.
        if out.startswith("---\n"):
            lines = out.split("\n")
            for i in range(1, len(lines)):
                s = lines[i].rstrip()
                if s == "---":
                    break          # already correct
                if s == "```":
                    lines[i] = "---"
                    out = "\n".join(lines)
                    print(f"[summarize] repaired stray ``` fence in {sid} "
                          f"output", file=sys.stderr)
                    break

        # Basic sanity: should start with frontmatter
        if not out.startswith("---"):
            print(f"[summarize] WARN: output for {sid} doesn't start with "
                  f"YAML frontmatter; saving anyway", file=sys.stderr)

        out = _guard_done_status(out, sid)
        atomic_write(summary_path, out + "\n")
        log_cost("summarize", envelope, duration, sid, ok=True)
        cost_str = f"${envelope.get('total_cost_usd', 0):.4f}" if envelope else "?"
        print(f"[summarize] wrote {summary_path.name}  cost={cost_str} "
              f"duration={duration:.1f}s")

        # Trigger Layer 2 (best-effort; missing trigger script is fine)
        trigger = REPO_ROOT / "bin" / "layer2-trigger.sh"
        if trigger.exists():
            subprocess.Popen(["bash", str(trigger)],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return 0
    finally:
        release_lock(lock)


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    prune_stale_locks()   # sweep leaked summary-*.lock files (best-effort)
    sid = args[0]
    force = "--force" in args[1:]
    dry_run = "--dry-run" in args[1:]
    return summarize_one(sid, force=force, dry_run=dry_run)


if __name__ == "__main__":
    sys.exit(main())
