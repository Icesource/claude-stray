#!/usr/bin/env python3
"""
Unified local server for claude-stray.

Listens on 127.0.0.1:9876 (falls back to 9877, 9878 if busy):

  GET  /                  -> serves cache/dashboard.html
  GET  /mindmap-tree.html -> serves cache/mindmap-tree.html
  GET  /cache/...         -> serves files from cache/ (json data, etc.)
  GET  /ping              -> health check + capabilities
  GET  /api/data          -> current dashboard.json + locations + overrides + lifecycle
  POST /api/save          -> persist user overrides (task toggles, archive, delete)
  POST /api/refresh       -> trigger background AI refresh
  POST /api/lifecycle     -> pause / resume the pipeline (DD-005)
                             body: {"action": "pause"|"resume", "reason": "..."}
  POST /focus             -> body {pane, session?} -> zellij focus-pane-id
  POST /newpane           -> body {sid, cwd?}      -> zellij run -- claude --dangerously-skip-permissions --resume

Only loopback (127.0.0.1) is bound. CORS allows any origin so file:// HTML
still works as a fallback. No authentication beyond loopback binding — fine
for a local desktop helper, do NOT expose to the network.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import shlex
import signal
import time
from datetime import datetime, timezone
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "cache"
HTML_FILE = CACHE_DIR / "dashboard.html"
TREE_FILE = CACHE_DIR / "mindmap-tree.html"
DASHBOARD_JSON = CACHE_DIR / "dashboard.json"
LOCATIONS_JSON = CACHE_DIR / "session_locations.json"
OVERRIDES_JSON = CACHE_DIR / "user_overrides.json"
DELETED_JSON = CACHE_DIR / "deleted_ids.json"
ARCHIVE_DIR = CACHE_DIR / "archive"
COCKPIT_FILE = REPO_ROOT / "bin" / "cockpit.html"  # DD-015 cockpit (live, real data)
RENDER_HTML = REPO_ROOT / "bin" / "render-html.py"
RENDER_TREE = REPO_ROOT / "bin" / "render-tree.py"
PIPELINE_RUN = REPO_ROOT / "bin" / "pipeline-run.sh"
DERIVED_DIR = CACHE_DIR / "derived"
SUMMARIES_DIR = CACHE_DIR / "summaries"  # Layer-1 per-session summaries
SYNC_STATUS_JSON = CACHE_DIR / "sync_status.json"  # first-sync health for the UI
SYNC_LOG = CACHE_DIR / "sync.log"

PORTS = [9876, 9877, 9878]
BIND = "127.0.0.1"

LIVE_DIR = CACHE_DIR / "live"  # DD-015 Stage 1: per-session live status
# sid -> {"port":int,"pid":int}. ttyd procs are spawned start_new_session so a
# serve restart (Ctrl-C) does NOT kill them — the embedded terminals (and the
# claude sessions in them) survive. The map is persisted so a restarted serve
# reconnects to the still-alive ttyds instead of forking a second resume.
_TERMINALS: dict = {}
TERMINALS_JSON = CACHE_DIR / "terminals.json"


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _save_terminals() -> None:
    try:
        TERMINALS_JSON.write_text(json.dumps(_TERMINALS))
    except Exception:
        pass


def _load_terminals() -> None:
    """On startup, recover ttyds that survived a previous serve (their pid is
    still alive); drop the dead ones."""
    global _TERMINALS
    try:
        d = json.loads(TERMINALS_JSON.read_text())
        _TERMINALS = {sid: e for sid, e in d.items()
                      if isinstance(e, dict) and _pid_alive(e.get("pid"))}
    except Exception:
        _TERMINALS = {}
    _save_terminals()


_JSONL_PATH_CACHE: dict = {}


def _session_jsonl_path(sid: str):
    """Cached path to a session's transcript jsonl (stable for a session)."""
    if sid in _JSONL_PATH_CACHE:
        return _JSONL_PATH_CACHE[sid]
    p = None
    try:
        p = json.loads((CACHE_DIR / "sessions" / f"{sid}.json").read_text()).get("source_file")
    except Exception:
        p = None
    if not p or not os.path.exists(p):
        try:
            hits = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"))
            p = str(hits[0]) if hits else None
        except Exception:
            p = None
    _JSONL_PATH_CACHE[sid] = p
    return p


def live_snapshot() -> dict:
    """Per-session live status for the cockpit, keyed by session_id.
    Light staleness handling: a 'running' record untouched for >6h is
    likely a crashed turn (-> unknown); 'ended' records >1h old drop out."""
    import time
    out: dict = {}
    if not LIVE_DIR.is_dir():
        return out
    now = time.time()
    for f in LIVE_DIR.glob("*.json"):
        try:
            rec = json.loads(f.read_text())
        except Exception:
            continue
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id") or f.stem
        try:
            age = now - f.stat().st_mtime
        except Exception:
            age = 0
        status = rec.get("status")
        if status == "ended" and age > 3600:
            continue
        if status == "running" and age > 6 * 3600:
            rec = {**rec, "status": "unknown"}
        if status == "done_unread" and age > 16 * 3600:
            rec = {**rec, "status": "idle"}  # stale unread -> you've moved on
        # Transcript-mtime override: the event model has a gap — answering an
        # elicit / approving a permission / a missed UserPromptSubmit doesn't fire
        # a `running` event, so a session can stay stuck on needs_you / idle while
        # actually working. If the jsonl was written AFTER that event and within
        # the last 45s, the session is actively working → show running.
        st2 = rec.get("status")
        if st2 in ("needs_you", "idle"):
            jp = _session_jsonl_path(sid)
            if jp:
                try:
                    jm = os.path.getmtime(jp)
                except Exception:
                    jm = 0
                try:
                    ss_ep = datetime.fromisoformat(
                        (rec.get("status_since") or "").replace("Z", "+00:00")).timestamp()
                except Exception:
                    ss_ep = 0
                if jm > ss_ep + 5 and (now - jm) < 45:
                    rec = {**rec, "status": "running", "_inferred": "jsonl-fresh"}
        out[sid] = rec
    return out


_TMUX_CONF = CACHE_DIR / "tmux-stray.conf"


def _terminal_holder() -> str | None:
    """The detach/reattach session holder to run claude inside, so the session
    survives ttyd WS drops (page refresh). MUST replay the screen on reattach
    (tmux/screen maintain a terminal buffer; abduco does NOT — it leaves a TUI
    black on reattach, so it's deliberately excluded). Optional — None = run
    directly (re-resumes on refresh)."""
    for h in ("tmux", "screen"):
        if shutil.which(h):
            return h
    return None


def _wrap_in_holder(sid: str, inner: str) -> tuple[str, str | None]:
    """Wrap the resume command in a screen-buffering holder so claude survives a
    page refresh: the holder keeps the session AND repaints on reattach, so a
    refresh re-attaches to the SAME claude with its UI intact. Returns
    (command, holder_session_name|None). No holder installed → run `inner`
    directly (re-resumes on refresh; still fully functional — progressive
    enhancement, not required)."""
    h = _terminal_holder()
    name = "stray-" + sid[:8]
    if h == "tmux":
        try:
            if not _TMUX_CONF.exists():
                _TMUX_CONF.write_text("set -g status off\nset -g mouse on\n"
                                      "set -g escape-time 10\n")
        except Exception:
            pass
        return ("tmux -L stray -f " + shlex.quote(str(_TMUX_CONF))
                + " new-session -A -s " + shlex.quote(name)
                + " bash -lc " + shlex.quote(inner), h)
    if h == "screen":
        # -d -R: attach-or-create; -e ^Tt remaps the command key off Ctrl-a
        # (which a TUI uses for beginning-of-line) to Ctrl-t so screen doesn't
        # swallow it. Fallback only — tmux is preferred + better tested.
        return ("screen -e ^Tt -d -R -S " + shlex.quote(name)
                + " bash -lc " + shlex.quote(inner), h)
    return (inner, None)


def _ttyd_patched_index():
    """Path to a cached copy of ttyd's index.html with the browser context menu
    suppressed, or None. Right-click inside the terminal otherwise pops the
    page's default menu over the selection; xterm's rightClickSelectsWord does
    NOT stop it. ttyd's index is a single self-contained file, so we fetch it
    once from a throwaway ttyd, inject a contextmenu preventDefault, cache it,
    and pass it via `-I`. Regenerated when the ttyd version changes. Any failure
    → None (caller launches ttyd without -I, unchanged behavior)."""
    ttyd = shutil.which("ttyd")
    if not ttyd:
        return None
    out = CACHE_DIR / "ttyd-index.html"
    stamp = CACHE_DIR / "ttyd-index.ver"
    try:
        r = subprocess.run([ttyd, "--version"], capture_output=True, text=True)
        ver = (r.stdout + r.stderr).strip()
    except Exception:
        ver = ""
    try:
        if out.exists() and stamp.exists() and stamp.read_text().strip() == ver:
            return str(out)
    except Exception:
        pass
    import socket as _socket, urllib.request as _ureq
    proc = None
    try:
        s = _socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        proc = subprocess.Popen([ttyd, "-p", str(port), "-i", "127.0.0.1", "bash", "-lc", "sleep 6"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(0.6)
        html = _ureq.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read().decode("utf-8", "replace")
        inject = ("<script>window.addEventListener('contextmenu',"
                  "function(e){e.preventDefault();},true);</script>")
        html = html.replace("</body>", inject + "</body>", 1) if "</body>" in html else html + inject
        out.write_text(html)
        stamp.write_text(ver)
        return str(out)
    except Exception:
        return None
    finally:
        if proc is not None:
            try: proc.terminate()
            except Exception: pass


def _resume_cwd_for(sid: str) -> str:
    """The cwd `claude --resume <sid>` MUST run from. claude resolves a session
    by the project dir derived from the *current* cwd, and a session's jsonl is
    stored under the project dir of its START cwd. session_locations.json records
    the *latest* cwd — if the user cd'd into a subdir mid-session, that subdir
    resolves to a different project and `--resume` fails with "No conversation
    found". So read the authoritative cwd from the session's own jsonl (its
    first `cwd` entry == its project dir); fall back to session_locations."""
    try:
        for f in (Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"):
            try:
                with f.open(encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            c = json.loads(line).get("cwd")
                        except Exception:
                            continue
                        if c:
                            return c
            except Exception:
                pass
    except Exception:
        pass
    try:
        return (json.loads(LOCATIONS_JSON.read_text()).get("by_session_id", {})
                .get(sid) or {}).get("cwd") or ""
    except Exception:
        return ""


try:
    import _worktree  # DD-022-A: mechanical worktree/branch from cwd (serve.py is in bin/)
except Exception:
    _worktree = None
try:
    import _subcards  # DD-025: parent↔child sub-card registry
except Exception:
    _subcards = None
SUBCARDS_JSON = CACHE_DIR / "subcards.json"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _attach_code_location(mindmap: dict) -> int:
    """DD-022-A: set init['code_location'] = {worktree, branch, is_worktree, main_repo}
    mechanically from each card's session cwd (git, cached) — replaces AI-guessed
    worktree/branch. Best-effort; absent git / non-repo cwd just leaves it unset."""
    if _worktree is None or not mindmap:
        return 0
    n = 0
    for w in mindmap.get("workspaces", []) or []:
        for init in w.get("initiatives", []) or []:
            sids = init.get("sessions") or (
                [init["origin_session"]] if init.get("origin_session") else [])
            if not sids:
                continue
            cwd = _resume_cwd_for(sids[0])
            cl = _worktree.code_location_for_cwd(cwd) if cwd else None
            if cl:
                init["code_location"] = cl
                n += 1
    # DD-025: tag cards that are registered sub-cards with their parent_session_id.
    if _subcards is not None:
        try:
            _subcards.link(mindmap, _subcards.load(str(SUBCARDS_JSON)))
        except Exception:
            pass
    return n


def _summary_section(body: str, *titles: str) -> str | None:
    """Extract one H1 section body (e.g. '当前状态') from a Layer-1 summary.
    Returns the trimmed text up to the next '# ' header, or None."""
    lines = body.splitlines()
    want = {t.strip() for t in titles}
    grab, buf = False, []
    for ln in lines:
        if ln.startswith("# "):
            if grab:
                break
            grab = ln[2:].strip() in want
            continue
        if grab:
            buf.append(ln)
    text = "\n".join(buf).strip()
    return text or None


def _freshen_progress_from_summaries(mindmap: dict) -> int:
    """Real-time overlay: when a card's bound session has a Layer-1 summary
    written AFTER the dashboard was generated, overlay that summary's
    '当前状态' onto the card's progress (and bump last_activity_at) so the
    cockpit reflects your latest turn within summarize latency (~30s) instead
    of waiting for the full classify pass.

    Display-only — mutates the in-memory dict we're about to serve, never
    writes dashboard.json, so it cannot race classify. Gated on file mtime so
    in steady state (no summary newer than the dashboard) it does zero reads
    of summary bodies. Sealed cards (DD-019, frozen) are skipped."""
    if not mindmap:
        return 0
    try:
        dash_mtime = DASHBOARD_JSON.stat().st_mtime
    except Exception:
        return 0
    n = 0
    for ws in mindmap.get("workspaces") or []:
        for init in ws.get("initiatives") or []:
            if init.get("sealed"):
                continue
            best = None  # (mtime, last_activity, cur_state)
            for sid in (init.get("sessions") or []):
                sp = SUMMARIES_DIR / f"{sid}.md"
                try:
                    st = sp.stat()
                except Exception:
                    continue
                if st.st_mtime <= dash_mtime:
                    continue  # classify already current for this session
                try:
                    txt = sp.read_text(encoding="utf-8")
                except Exception:
                    continue
                fm, _, body = txt.partition("\n---")
                # fm is everything before the closing '---'; pull the scalars.
                la = nxt = await_u = ""
                for fl in fm.splitlines():
                    if fl.startswith("last_activity_at:"):
                        la = fl.split(":", 1)[1].strip()
                    elif fl.startswith("next_step:"):
                        nxt = fl.split(":", 1)[1].strip()
                    elif fl.startswith("awaiting_user:"):
                        await_u = fl.split(":", 1)[1].strip()
                cur = _summary_section(body, "当前状态", "Current state",
                                       "Current Status")
                if best is None or st.st_mtime > best[0]:
                    best = (st.st_mtime, la, cur, nxt, await_u)
            if best and best[2]:
                init["progress"] = best[2]
                if best[1]:
                    init["last_activity_at"] = best[1]
                # DD-020: overlay the attention fields too, so 需要你 / 下一步
                # are real-time, not stale until the next classify.
                init["next_step"] = best[3] or None
                init["awaiting_user"] = best[4] or None
                init["_fresh"] = True  # cockpit shows a subtle 实时 marker
                n += 1
    return n


def _recent_turns(sid: str, n: int = 8) -> list[dict]:
    """Last n user/assistant turns (text only) for a session, newest-last."""
    sf = None
    meta = CACHE_DIR / "sessions" / f"{sid}.json"
    try:
        sf = json.loads(meta.read_text()).get("source_file")
    except Exception:
        sf = None
    if not sf or not os.path.exists(sf):
        try:
            hits = list((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"))
            sf = str(hits[0]) if hits else None
        except Exception:
            sf = None
    if not sf or not os.path.exists(sf):
        return []
    out: list[dict] = []
    try:
        with open(sf, encoding="utf-8") as f:
            for ln in f:
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                t = o.get("type")
                if t not in ("user", "assistant"):
                    continue
                content = (o.get("message") or {}).get("content")
                if isinstance(content, str):
                    txt = content
                elif isinstance(content, list):
                    txt = "\n".join(c.get("text", "") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text")
                else:
                    txt = ""
                txt = txt.strip()
                if txt:
                    out.append({"role": t, "text": txt})
    except Exception:
        return []
    return out[-n:]


def _suggest_prompt(sid: str) -> str | None:
    """Build the prompt for /api/suggest: this session's近况 + a GLOBAL snapshot
    of other active cards (the cross-session perspective the built-in single
    suggestion lacks) → ask for 2-3 distinct ready-to-send next messages."""
    card, others = None, []
    try:
        mm = json.loads(DASHBOARD_JSON.read_text())
    except Exception:
        mm = {}
    for ws in mm.get("workspaces") or []:
        for it in ws.get("initiatives") or []:
            if it.get("sealed"):
                continue
            if sid in (it.get("sessions") or []):
                card = it
            elif it.get("awaiting_user") or it.get("status") == "active":
                others.append((ws.get("name"), it))
    turns = _recent_turns(sid, 8)
    if not turns and not card:
        return None
    L = ["你是一个「注意力驾驶舱」的助手。用户在并行推进多件 Claude Code 编码工作。",
         "请基于【全局其它工作】+【这条会话近况】,推荐用户**接下来可以发给这条会话的 2-3 条不同的下一句话**。",
         "要求:每条都可直接发送、具体(用户口吻、祈使句、中文);彼此角度不同(如 继续推进 / 先验证 / 换方向或追问);贴合这条会话当前状态与下一步;不要寒暄、不要解释。",
         '只输出一个 JSON 数组,形如 ["…","…","…"],不要任何额外文字。']
    if others:
        L.append("\n<全局其它工作>")
        for nm, it in others[:8]:
            aw = it.get("awaiting_user")
            L.append(f"- [{nm}] {it.get('name')}: {(it.get('progress') or '')[:80]}"
                     + (f" [等你:{aw}]" if aw else ""))
        L.append("</全局其它工作>")
    if card:
        L.append("\n<这条会话>")
        L.append(f"名称: {card.get('name')}")
        if card.get("progress"):
            L.append(f"当前进展: {str(card['progress'])[:220]}")
        if card.get("next_step"):
            L.append(f"已判断的下一步: {card['next_step']}")
        if card.get("awaiting_user"):
            L.append(f"在等你: {card['awaiting_user']}")
        bl = card.get("blockers") or []
        if bl:
            L.append("卡点: " + "; ".join(bl[:3]))
        L.append("</这条会话>")
    if turns:
        L.append("\n<最近对话>")
        for t in turns:
            who = "我" if t["role"] == "user" else "Claude"
            L.append(f"### {who}\n{t['text'][:600]}")
        L.append("</最近对话>")
    return "\n".join(L)


def _parse_suggestions(txt: str) -> list[str]:
    txt = (txt or "").strip()
    if txt.startswith("```"):
        txt = "\n".join(l for l in txt.splitlines() if not l.strip().startswith("```"))
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            out = [str(x).strip() for x in arr if str(x).strip()]
            if out:
                return out[:3]
        except Exception:
            pass
    out = []
    for l in txt.splitlines():
        l = re.sub(r"^[-*\d.)\s]+", "", l.strip()).strip().strip('"').strip()
        if len(l) >= 4:
            out.append(l)
    return out[:3]


def _claude_suggest(prompt: str, timeout: int = 70) -> list[str]:
    """One headless claude call for next-message suggestions. --no-session-
    persistence so it leaves no jsonl (no re-ingestion / recursion); no tools."""
    model = os.environ.get("CLAUDE_WORKTREE_MODEL", "claude-haiku-4-5-20251001")
    argv = ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout),
            "claude", "--no-session-persistence", "-p",
            "--model", model, "--output-format", "json",
            "--max-budget-usd", "0.30",
            "--disallowedTools", "Bash Edit Write Read Glob Grep"]
    try:
        res = subprocess.run(argv, input=prompt, capture_output=True,
                             text=True, timeout=timeout + 10)
    except Exception:
        return []
    if res.returncode != 0:
        return []
    try:
        env = json.loads(res.stdout)
    except Exception:
        return []
    return _parse_suggestions(env.get("result", "") or "")


def has_zellij() -> bool:
    return shutil.which("zellij") is not None


def run_cmd(argv: list[str], background: bool = False) -> tuple[int, str, str]:
    try:
        if background:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0, "", ""
        p = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)


def regenerate_html() -> None:
    """Re-run render-html.py + render-tree.py. Called after data writes."""
    try:
        subprocess.run([sys.executable, str(RENDER_HTML)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        subprocess.run([sys.executable, str(RENDER_TREE)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass


def safe_dir_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in "_.-" else "_" for c in (s or "unknown"))


# Cost-alarm state for "emit on worsening only" — module-level so it
# survives across requests.
_LEVEL_ORDER = {"ok": 0, "warn": 1, "halt": 2}
_last_alarm_level = "ok"
_last_alarm_lock = threading.Lock()


def _emit_cost_alarm_if_worsened(snap: dict) -> None:
    """Print a stderr line only when level transitioned to a worse state.
    No-op when level stayed the same or improved (improvement is good
    news, no need to spam logs)."""
    global _last_alarm_level
    new_level = snap.get("level", "ok")
    with _last_alarm_lock:
        if _LEVEL_ORDER.get(new_level, 0) > _LEVEL_ORDER.get(_last_alarm_level, 0):
            try:
                from _cost_alarm import format_console_line
                print(format_console_line(snap), file=sys.stderr)
            except Exception:
                pass
        # Always update last-seen so a sustained 'warn' eventually re-emits
        # only if it climbs to 'halt' (or back to warn after a brief 'ok').
        _last_alarm_level = new_level


# ---------- DD-006 derived scheduler --------------------------------------
#
# Triggered from inside serve() so it lives only while the dashboard is
# being served (matches the user's expectation: "AI works while I'm
# looking; doesn't run silently in the background forever").
#
# - tips: run once on serve startup, then every 2h
#         (tips.py also has its own 2h debounce, this is belt+suspenders)
# - weekly_report: every Friday after 12:00 local, if this week's
#         report hasn't been generated yet
# - wellness: piggybacks on the tips tick — signal-gated, costs
#         nothing when no late-nights / consecutive-days signal fires

_TIPS_INTERVAL_SECS = 2 * 3600
_SCHED_TICK_SECS = 60          # check every minute
_WEEKLY_TRIGGER_HOUR = 12      # local time
_WEEKLY_TRIGGER_WEEKDAY = 4    # Mon=0 ... Fri=4

def _run_derived(script_name: str, extra_args: list[str] | None = None) -> None:
    """Spawn a derived feature script in a worker process, log result.
    Non-blocking from the scheduler's POV — we fire-and-wait inside the
    scheduler thread, but the thread itself is detached from serve's
    main loop."""
    argv = ["python3", str(REPO_ROOT / "bin" / "derived" / script_name)]
    if extra_args:
        argv.extend(extra_args)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=400)
        if proc.returncode == 0:
            # Last line of stderr is usually the "wrote ... cost=..." note
            tail = proc.stderr.strip().splitlines()[-1:] if proc.stderr else []
            for line in tail:
                print(f"[sched] {script_name}: {line}", file=sys.stderr)
        elif proc.returncode == 2:
            pass   # skipped (debounced / no signal); no spam
        else:
            print(f"[sched] {script_name}: rc={proc.returncode}; "
                  f"{(proc.stderr or '').strip()[:200]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[sched] {script_name}: timeout", file=sys.stderr)
    except Exception as e:
        print(f"[sched] {script_name}: spawn failed: {e}", file=sys.stderr)


def _is_friday_noon_window(now: datetime, last_weekly_iso: str | None) -> bool:
    """True if it's after 12:00 on Friday AND this week's report hasn't
    been generated yet. The week is identified by ISO week, so a single
    successful Friday-afternoon run satisfies the whole week."""
    local = now.astimezone()
    if local.weekday() != _WEEKLY_TRIGGER_WEEKDAY:
        return False
    if local.hour < _WEEKLY_TRIGGER_HOUR:
        return False
    if not last_weekly_iso:
        return True
    try:
        last = datetime.fromisoformat(last_weekly_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    last_local = last.astimezone()
    # Same ISO week → already generated
    return local.isocalendar()[:2] != last_local.isocalendar()[:2]


def _read_last_run(feature: str) -> str | None:
    p = CACHE_DIR / "derived" / feature.split(".")[-1] / ".last_run.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text()).get("at")
    except Exception:
        return None


def _mindmap_mtime() -> float:
    """Return dashboard.json mtime, or 0 if missing."""
    try:
        return DASHBOARD_JSON.stat().st_mtime
    except OSError:
        return 0.0


def _derived_scheduler_loop(stop_event) -> None:
    """Tick every minute; respect each feature's gating."""
    # On startup: kick off tips immediately if it's overdue.
    last_tips_at = _read_last_run("derived.tips")
    if last_tips_at is None or (
        datetime.now(timezone.utc)
        - datetime.fromisoformat(last_tips_at.replace("Z", "+00:00"))
    ).total_seconds() >= _TIPS_INTERVAL_SECS:
        print("[sched] tips: due at startup", file=sys.stderr)
        _run_derived("tips.py")
    # Wellness piggybacks on the tips tick (cheap; signal-gated).
    _run_derived("wellness.py")
    # next_steps: regenerate on startup so the sidebar is current.
    _run_derived("next_steps.py")
    last_mindmap_mtime = _mindmap_mtime()

    while not stop_event.is_set():
        # Sleep in small slices so we can exit promptly on shutdown.
        if stop_event.wait(_SCHED_TICK_SECS):
            return
        now = datetime.now(timezone.utc)

        # Tips: every 6h since last successful run.
        last_tips_at = _read_last_run("derived.tips")
        if last_tips_at:
            try:
                dt = datetime.fromisoformat(last_tips_at.replace("Z", "+00:00"))
                elapsed = (now - dt).total_seconds()
            except ValueError:
                elapsed = _TIPS_INTERVAL_SECS
            if elapsed >= _TIPS_INTERVAL_SECS:
                print("[sched] tips: 2h elapsed", file=sys.stderr)
                _run_derived("tips.py")
                _run_derived("wellness.py")
        else:
            _run_derived("tips.py")

        # next_steps: regenerate when dashboard.json was updated (a fresh
        # classify ran in the background). next_steps.py has its own
        # 30-minute debounce so noisy mindmap rewrites don't burst the
        # AI call.
        current_mtime = _mindmap_mtime()
        if current_mtime > last_mindmap_mtime:
            print(f"[sched] next_steps: dashboard.json changed "
                  f"({current_mtime:.0f} > {last_mindmap_mtime:.0f})",
                  file=sys.stderr)
            _run_derived("next_steps.py")
            last_mindmap_mtime = current_mtime

        # Weekly: Friday 12:00 local, once per ISO week.
        last_weekly_at = _read_last_run("derived.weekly_report")
        if _is_friday_noon_window(now, last_weekly_at):
            print("[sched] weekly_report: Friday noon window",
                  file=sys.stderr)
            _run_derived("weekly_report.py", ["--week", "0"])


class Handler(BaseHTTPRequestHandler):
    server_version = "ccw-helper/2"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[serve] {self.address_string()} {fmt % args}\n")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _reply(self, code: int, body: dict | None = None):
        payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _maybe_regen_html(self, path: Path) -> None:
        """If serving mindmap.html / mindmap-tree.html, regenerate it when
        the source JSON is newer. Keeps the page automatically in sync
        with the underlying data even if the pipeline bumped the JSON
        without re-running render-html."""
        try:
            if not DASHBOARD_JSON.exists():
                return
            data_mtime = DASHBOARD_JSON.stat().st_mtime
            if path == HTML_FILE or path == TREE_FILE:
                html_mtime = path.stat().st_mtime if path.exists() else 0
                if data_mtime > html_mtime:
                    regenerate_html()
        except Exception:
            pass

    def _serve_file(self, path: Path, content_type: str | None = None):
        self._maybe_regen_html(path)
        if not path.exists() or not path.is_file():
            self._reply(404, {"error": "not found", "path": str(path)})
            return
        ctype = content_type or (mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "json" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        # Discourage browser caching so a re-render is immediately visible on reload.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_sse(self):
        """Server-Sent Events stream of live session status (DD-015 Stage 1).
        ThreadingHTTPServer gives each request its own thread, so this
        blocking loop does not starve other requests."""
        import time
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_sig = None
        last_keepalive = time.time()
        try:
            while True:
                snap = live_snapshot()
                sig = json.dumps(snap, sort_keys=True, ensure_ascii=False)
                now = time.time()
                if sig != last_sig:
                    self.wfile.write(("data: " + sig + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    last_sig = sig
                    last_keepalive = now
                elif now - last_keepalive > 15:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_keepalive = now
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            return

    def _handle_transcript(self):
        """Read-only recent conversation for a session (DD-015 Stage 3a).
        Locates the jsonl via cache/sessions/<sid>.json's source_file, parses
        the last N user/assistant turns into {role, text, at}."""
        from urllib.parse import parse_qs as _pqs
        qs = _pqs(urlparse(self.path).query)
        sid = (qs.get("sid") or [""])[0]
        try:
            n = max(1, min(60, int((qs.get("n") or ["14"])[0])))
        except Exception:
            n = 14
        if not sid or "/" in sid or ".." in sid:
            return self._reply(400, {"error": "bad sid"})
        meta = CACHE_DIR / "sessions" / f"{sid}.json"
        try:
            sf = json.loads(meta.read_text()).get("source_file")
        except Exception:
            sf = None
        if not sf or not os.path.exists(sf):
            return self._reply(404, {"error": "transcript not found"})
        turns = []
        try:
            with open(sf, encoding="utf-8") as f:
                for ln in f:
                    try:
                        o = json.loads(ln)
                    except Exception:
                        continue
                    t = o.get("type")
                    if t not in ("user", "assistant"):
                        continue
                    content = (o.get("message") or {}).get("content")
                    if t == "user":
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            parts = [c.get("text", "") for c in content
                                     if isinstance(c, dict) and c.get("type") == "text"]
                            if not parts:
                                continue  # tool_result feedback, not a real user message
                            text = "\n".join(parts)
                        else:
                            continue
                        turns.append({"role": "user", "text": text, "at": o.get("timestamp")})
                    else:
                        if not isinstance(content, list):
                            continue
                        texts, tools = [], []
                        for c in content:
                            if not isinstance(c, dict):
                                continue
                            if c.get("type") == "text" and (c.get("text") or "").strip():
                                texts.append(c["text"])
                            elif c.get("type") == "tool_use":
                                tools.append(c.get("name") or "")
                        text = "\n".join(texts)
                        if not text and tools:
                            text = "[使用工具: " + ", ".join(t for t in tools if t) + "]"
                        if not text:
                            continue
                        turns.append({"role": "assistant", "text": text, "at": o.get("timestamp")})
        except Exception as e:
            return self._reply(500, {"error": str(e)})
        turns = turns[-n:]
        for t in turns:
            if len(t["text"]) > 2000:
                t["text"] = t["text"][:2000] + " …(截断)"
        return self._reply(200, {"sid": sid, "turns": turns})

    @staticmethod
    def _parse_weekly_report(text):
        """从 DD-006 周报 markdown 提取 (一句话总结, [亮点标题...])。
        总结优先取「已交付」段导语,回退到亮点标题拼接;亮点取各 bullet
        的 **加粗** 标题。纯字符串解析,不依赖 re。"""
        section = None
        highlights, delivered = [], []
        for ln in text.splitlines():
            s = ln.strip()
            if s.startswith("## "):
                h = s[3:]
                section = "hl" if "亮点" in h else ("deliver" if "交付" in h else "other")
                continue
            if section == "hl" and s.startswith("- ") and "**" in s:
                body = s[2:].strip()
                a = body.find("**"); b = body.find("**", a + 2)
                if b > a and body[a + 2:b].strip():
                    highlights.append(body[a + 2:b].strip())
            elif section == "deliver" and s and not s.startswith(("#", "-")):
                delivered.append(s)
        lead = None
        if delivered:
            lead = delivered[0].rstrip("：: ").replace("**", "").strip()
        elif highlights:
            lead = "、".join(highlights[:3])
        return lead, highlights[:5]

    def _handle_archive_weeks(self):
        """Completed/archived work grouped by ISO week, for the cockpit's 归档
        view. Sources: cache/archive/<ws>/<id>.json + status==done initiatives.
        Each week gets a derived one-line summary (+ a weekly-report snippet if
        DD-006 generated one)."""
        items = []
        if ARCHIVE_DIR.is_dir():
            for ws_dir in ARCHIVE_DIR.iterdir():
                if not ws_dir.is_dir():
                    continue
                for f in ws_dir.glob("*.json"):
                    try:
                        rec = json.loads(f.read_text())
                    except Exception:
                        continue
                    init = rec.get("initiative") or {}
                    items.append({"name": init.get("name") or init.get("id"),
                                  "ws": rec.get("from_workspace") or ws_dir.name,
                                  "kind": "archived",
                                  "when": rec.get("archived_at") or init.get("last_activity_at")})
        try:
            d = json.loads(DASHBOARD_JSON.read_text())
            for w in d.get("workspaces", []):
                for i in (w.get("initiatives") or []):
                    if i.get("status") == "done":
                        items.append({"name": i.get("name"), "ws": w.get("name"),
                                      "kind": "done", "when": i.get("last_activity_at")})
        except Exception:
            pass
        weeks = {}
        for it in items:
            iso = (it.get("when") or "")[:10]
            try:
                y, wk, _ = datetime.strptime(iso, "%Y-%m-%d").isocalendar()
            except Exception:
                continue
            key = f"{y}-W{wk:02d}"
            weeks.setdefault(key, []).append(it)
        cur_y, cur_wk, _ = datetime.now(timezone.utc).isocalendar()
        out = []
        for key in sorted(weeks, reverse=True):
            its = sorted(weeks[key], key=lambda x: x.get("when") or "", reverse=True)
            try:
                y, w = int(key[:4]), int(key[6:])
                delta = (cur_y - y) * 52 + (cur_wk - w)
                label = {0: "本周", 1: "上周"}.get(delta, f"{delta} 周前" if delta > 1 else key)
            except Exception:
                label = key
            names = [it["name"] for it in its if it.get("name")]
            tally = f"完成/归档 {len(its)} 项:" + "、".join(names[:4]) + ("…" if len(names) > 4 else "")
            rep = DERIVED_DIR / "reports" / f"{key}.md"
            lead, highlights, has_report = None, [], False
            if rep.exists():
                try:
                    lead, highlights = self._parse_weekly_report(rep.read_text())
                    has_report = True
                except Exception:
                    pass
            out.append({"week": key, "label": label, "count": len(its),
                        "summary": lead or tally, "tally": tally,
                        "highlights": highlights, "has_report": has_report,
                        "items": its})
        return self._reply(200, {"weeks": out})

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index", "/index.html", "/cockpit", "/cockpit.html"):
            return self._serve_file(COCKPIT_FILE, "text/html")  # cockpit is the default page now
        if path in ("/dashboard.html", "/classic"):
            return self._serve_file(HTML_FILE, "text/html")  # legacy card dashboard
        if path == "/mindmap-tree.html":
            return self._serve_file(TREE_FILE, "text/html")
        if path == "/favicon.ico":
            # Return a 1x1 transparent SVG so browsers stop asking.
            svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><text y="13" font-size="14">\xf0\x9f\x97\x82\xef\xb8\x8f</text></svg>'
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
            return
        if path == "/ping":
            return self._reply(200, {
                "service": "claude-stray", "version": 2,
                "has_zellij": has_zellij(),
                "can_write_disk": True,  # the server CAN write to cache/
                "terminal": shutil.which("ttyd") is not None,
                "ttyd": shutil.which("ttyd") is not None,
            })
        if path == "/api/live":
            return self._reply(200, {"live": live_snapshot()})
        if path == "/api/events":
            return self._handle_sse()
        if path == "/api/transcript":
            return self._handle_transcript()
        if path == "/api/archive-weeks":
            return self._handle_archive_weeks()
        if path == "/api/subtasks":
            from urllib.parse import parse_qs
            parent = (parse_qs(urlparse(self.path).query).get("parent") or [""])[0]
            if not parent or _subcards is None:
                return self._reply(200, {"parent": parent, "subcards": []})
            try:
                mm = json.load(open(DASHBOARD_JSON))
            except Exception:
                mm = {}
            try:
                _attach_code_location(mm)   # populate worktree/branch on the cards
            except Exception:
                pass

            def _jsonl(sid):
                import glob as _g
                hits = _g.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
                return hits[0] if hits else None
            md = _subcards.subtask_metadata(parent, mm,
                                            _subcards.load(str(SUBCARDS_JSON)), _jsonl)
            return self._reply(200, {"parent": parent, "subcards": md})
        if path == "/api/data":
            data = {}
            try: data["mindmap"] = json.load(open(DASHBOARD_JSON))
            except Exception: data["mindmap"] = None
            # DD-016 safety net: never serve same-session duplicate cards, even if
            # a stale/racy classify wrote them (the file is fixed on the next run).
            try:
                if data.get("mindmap"):
                    sys.path.insert(0, str(REPO_ROOT / "bin"))
                    import classify
                    classify.dedup_by_session(data["mindmap"])
            except Exception:
                pass
            # Real-time: overlay the freshest Layer-1 当前状态 onto cards whose
            # session was re-summarized after the dashboard was written, so the
            # active card reflects your latest turn without waiting for classify.
            try:
                _freshen_progress_from_summaries(data.get("mindmap"))
            except Exception:
                pass
            try:
                _attach_code_location(data.get("mindmap"))  # DD-022-A: real worktree/branch
            except Exception:
                pass
            # Sync health for the empty/first-run state: is the background
            # analysis running / done / failed, and is claude even available.
            data["sync"] = _read_sync_status()
            data["claude_ok"] = bool(shutil.which("claude"))
            try: data["locations"] = json.load(open(LOCATIONS_JSON))
            except Exception: data["locations"] = None
            # Archived items from cache/archive/<ws>/<id>.json — these are
            # outside dashboard.json so we surface them explicitly so the
            # browser's hot-refresh shows newly archived items immediately.
            archived = []
            if ARCHIVE_DIR.is_dir():
                for ws_dir in sorted(ARCHIVE_DIR.iterdir()):
                    if not ws_dir.is_dir(): continue
                    for f in sorted(ws_dir.glob("*.json")):
                        try:
                            rec = json.loads(f.read_text())
                        except Exception:
                            continue
                        init = rec.get("initiative")
                        if isinstance(init, dict) and init.get("id"):
                            archived.append({
                                "ws_name": rec.get("from_workspace") or ws_dir.name,
                                "ws_cwd": None,
                                "init": init,
                                "archived_at": rec.get("archived_at"),
                            })
            data["archived"] = archived
            sys.path.insert(0, str(REPO_ROOT / "bin"))
            # Lifecycle state so the dashboard banner can hot-refresh.
            try:
                from _lifecycle import status as _lifecycle_status
                data["lifecycle"] = _lifecycle_status()
            except Exception as e:
                data["lifecycle"] = {"paused": False, "_err": str(e)}
            # Cost-alarm snapshot. Always include in response (future DD-004
            # banner reads this). Console emits only when level WORSENS
            # (avoids spam from repeated polls at the same level).
            try:
                from _cost_alarm import snapshot as _cost_snap, format_console_line
                snap = _cost_snap()
                data["cost_alarm"] = snap
                _emit_cost_alarm_if_worsened(snap)
            except Exception as e:
                data["cost_alarm"] = {"level": "ok", "_err": str(e)}
            return self._reply(200, data)
        if path == "/api/derived":
            # DD-006 derived feature payloads, all in one shot for the
            # sidebar widgets. Each entry is the latest.json of that
            # feature, or null if it hasn't been generated yet.
            out = {}
            for feat in ("suggestions", "tips", "wellness"):
                f = DERIVED_DIR / feat / "latest.json"
                try:
                    out[feat] = json.loads(f.read_text()) if f.exists() else None
                except Exception:
                    out[feat] = None
            # Weekly report: list available reports + most recent
            weekly: dict = {"latest": None, "available": []}
            reports_dir = DERIVED_DIR / "reports"
            if reports_dir.is_dir():
                md_files = sorted(reports_dir.glob("*.md"), reverse=True)
                weekly["available"] = [f.stem for f in md_files][:12]
                if md_files:
                    weekly["latest"] = {
                        "week": md_files[0].stem,
                        "generated_at": json.loads(
                            (reports_dir / ".last_run.json").read_text()
                        ).get("at") if (reports_dir / ".last_run.json").exists() else None,
                    }
            out["weekly"] = weekly
            return self._reply(200, out)
        if path == "/api/weekly-report":
            from urllib.parse import parse_qs as _pqs
            qs = _pqs(urlparse(self.path).query)
            week = (qs.get("week") or [""])[0]
            if not re.match(r"^\d{4}-W\d{2}$", week):
                return self._reply(400, {"error": "week must be YYYY-Www"})
            md_path = DERIVED_DIR / "reports" / f"{week}.md"
            if not md_path.exists():
                return self._reply(404, {"error": "report not generated"})
            return self._reply(200, {
                "week": week,
                "markdown": md_path.read_text(),
            })
        if path == "/api/version":
            # Last-known update snapshot (written by startup check + the
            # 24h background recheck thread). Browser polls this for the
            # update banner; we never block on a fresh fetch here.
            try:
                import _updates
                snap = _updates.read_state()
            except Exception as e:
                snap = {"error": str(e)}
            return self._reply(200, snap or {})
        # Static file passthrough from cache/ (limited to known whitelist below)
        if path.startswith("/cache/"):
            rel = path[len("/cache/"):]
            if ".." in rel or rel.startswith("/"):
                return self._reply(403, {"error": "forbidden"})
            return self._serve_file(CACHE_DIR / rel)
        self._reply(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return self._reply(400, {"error": "bad json"})

        if path == "/focus":     return self._handle_focus(body)
        if path == "/newpane":   return self._handle_newpane(body)
        if path == "/api/save":  return self._handle_save(body)
        if path == "/api/refresh": return self._handle_refresh(body)
        if path == "/api/lifecycle": return self._handle_lifecycle(body)
        if path == "/api/consolidate-tasks": return self._handle_consolidate(body)
        if path == "/api/update": return self._handle_update(body)
        if path == "/api/merge": return self._handle_merge(body)
        if path == "/api/delete": return self._handle_delete(body)
        if path == "/api/archive": return self._handle_archive(body)
        if path == "/api/terminal": return self._handle_terminal(body)
        if path == "/api/new-session": return self._handle_new_session(body)
        if path == "/api/terminal-close": return self._handle_terminal_close(body)
        if path == "/api/send": return self._handle_send(body)
        if path == "/api/suggest": return self._handle_suggest(body)
        self._reply(404, {"error": "not found", "path": path})

    def _handle_send(self, body: dict):
        """Inject a message into a session's LIVE zellij pane — writes to the
        real interactive claude's stdin, so Ghostty + the read-only view both
        update (true two-way, NO attach/resize). Needs a known live pane."""
        sid = (body.get("sid") or "").strip()
        text = body.get("text") or ""
        if not sid or not text.strip():
            return self._reply(400, {"error": "sid and text required"})
        if not has_zellij():
            return self._reply(503, {"error": "zellij not installed"})
        try:
            loc = json.loads(LOCATIONS_JSON.read_text()).get("by_session_id", {}).get(sid) or {}
        except Exception:
            loc = {}
        zsess, zpane = loc.get("zellij_session"), loc.get("zellij_pane_id")
        if not zsess or not zpane:
            return self._reply(409, {"error": "no live pane",
                                     "hint": "该会话不在已知的 zellij pane 里(可能已结束)"})
        rc, out, _ = run_cmd(["zellij", "list-sessions"])
        alive = rc == 0 and any(
            (re.sub(r"\x1b\[[0-9;]*m", "", l).strip().split() or [""])[0] == zsess and "EXITED" not in l
            for l in (out or "").splitlines())
        if not alive:
            return self._reply(409, {"error": "zellij session not alive"})
        base = ["zellij", "--session", zsess, "action"]
        # SAFETY: session_locations.json is never pruned, so a long-dead session
        # still "remembers" its old pane id. If focus-pane-id fails (pane gone),
        # the follow-up write-chars would type into whatever pane is CURRENTLY
        # focused — your message + Enter land in the WRONG window. So check the
        # focus rc and refuse to write when the target pane no longer exists.
        rcf, _, _ = run_cmd(base + ["focus-pane-id", str(zpane)])
        if rcf != 0:
            return self._reply(409, {"error": "pane_gone",
                "hint": "原窗格已关闭。用卡片上的『终端』resume 这个会话,而不是注入。"})
        rc, _, err = run_cmd(base + ["write-chars", text])
        if rc != 0:
            return self._reply(500, {"error": err.strip() or "write-chars failed"})
        run_cmd(base + ["write", "13"])  # Enter (CR) to submit the prompt
        return self._reply(200, {"ok": True})

    def _handle_suggest(self, body: dict):
        """B (DD-020): AI-recommended next messages for a session, with a GLOBAL
        cross-session view. Returns 2-3 ready-to-send candidates; the cockpit
        lets you click one to inject (/api/send) or copy."""
        sid = (body.get("sid") or "").strip()
        if not sid:
            return self._reply(400, {"error": "sid required"})
        if not shutil.which("claude"):
            return self._reply(503, {"error": "claude CLI not found"})
        prompt = _suggest_prompt(sid)
        if not prompt:
            return self._reply(404, {"error": "no context",
                                     "hint": "这条会话还没有可用的上下文"})
        sugg = _claude_suggest(prompt)
        if not sugg:
            return self._reply(502, {"error": "suggest failed",
                                     "hint": "AI 没给出建议,稍后再试"})
        return self._reply(200, {"suggestions": sugg})

    def _handle_terminal_close(self, body: dict):
        """Kill the ttyd spawned for a session (called when the cockpit closes
        the terminal modal) so claude/ttyd processes don't pile up."""
        sid = (body.get("sid") or "").strip()
        ent = _TERMINALS.pop(sid, None)
        if ent:
            try:
                os.kill(int(ent["pid"]), signal.SIGTERM)  # ttyd
            except Exception:
                pass
            hn = ent.get("holder")
            if hn:
                # End the holder session too — otherwise claude keeps running
                # detached (ttyd dying only detaches the holder client).
                name = "stray-" + sid[:8]
                if hn == "tmux":
                    run_cmd(["tmux", "-L", "stray", "kill-session", "-t", name])
                elif hn == "screen":
                    run_cmd(["screen", "-S", name, "-X", "quit"])
                else:
                    run_cmd(["pkill", "-f", name])
            _save_terminals()
        return self._reply(200, {"ok": True})

    def _handle_terminal(self, body: dict):
        """DD-015 Stage 3: spawn a localhost ttyd running `claude --resume <sid>`
        and return its URL. Needs ttyd (localhost-trust model, same as /newpane
        which already runs `claude --dangerously-skip-permissions`); degrades
        gracefully — the cockpit falls back to a zellij pane when ttyd absent."""
        ttyd = shutil.which("ttyd")
        if not ttyd:
            return self._reply(503, {"error": "ttyd not installed", "hint": "brew install ttyd"})
        sid = (body.get("sid") or "").strip()
        if not sid:
            return self._reply(400, {"error": "sid required"})
        ex = _TERMINALS.get(sid)
        # Reuse a live ttyd (survives serve restart) — but ONLY if its holder
        # type still matches what we'd spawn now. A stale terminal from an older
        # holder (e.g. the abduco era, which left TUIs black) is dropped so we
        # respawn a fresh, correct one instead of reusing a broken black screen.
        if ex and _pid_alive(ex.get("pid")) and ex.get("holder") == _terminal_holder():
            return self._reply(200, {"url": f"http://127.0.0.1:{ex['port']}/", "reused": True})
        if ex:  # stale/mismatched — tear it down before respawning
            try:
                os.kill(int(ex["pid"]), signal.SIGTERM)
            except Exception:
                pass
            run_cmd(["pkill", "-f", "stray-" + sid[:8]])
            _TERMINALS.pop(sid, None)
            _save_terminals()
        # Single-driver gate (DD-018): never `claude --resume <sid>` a session
        # that already has a live process elsewhere. Two resumes fork the
        # session jsonl (uuid/parentUuid chain): the two agents diverge, can't
        # see each other, race the same repo, and the next resume orphans one
        # branch. So gate on live status:
        #   running              -> hard refuse (it's actively working).
        #   idle/done_unread/... -> a process may still be parked in a pane;
        #                           require explicit ?force after a UI confirm.
        #   ended / no record    -> safe: this resume is the sole driver.
        lst = (live_snapshot().get(sid) or {}).get("status")
        if lst in ("running", "idle", "done_unread", "needs_you") and not body.get("force"):
            # WARN, don't block: the session looks live elsewhere (e.g. open in
            # ghostty). Opening it here resumes a SECOND copy, and two
            # `claude --resume` writing one jsonl can conflict. But it's the
            # user's call — confirm and proceed.
            run = lst == "running"
            return self._reply(409, {"error": "maybe_live", "state": lst,
                "need_force": True,
                "hint": ("这条会话正在另一个终端里运行(比如 ghostty)。" if run
                         else "这条会话可能还在某个终端里开着。")
                        + "在驾驶舱打开会 resume 一个独立副本,两边同时写同一条会话历史可能冲突。确认仍要打开吗?"})
        # Use the session's project cwd (from its jsonl), NOT the latest cwd in
        # session_locations — otherwise `claude --resume` fails "No conversation
        # found" when the user cd'd into a subdir during the session.
        cwd = _resume_cwd_for(sid)
        # DD-018: resume-only. This browser terminal is the SEED for the future
        # host model (server-owned sessions); it is intentionally NOT wired into
        # the converged local path (observe/inject/jump). We never `zellij
        # attach` a local session — that resizes the user's real terminal.
        mode = "resume"
        inner = "claude --dangerously-skip-permissions --resume " + shlex.quote(sid)
        if cwd:
            inner = "cd " + shlex.quote(cwd) + " && " + inner
        # Run inside a holder (abduco/tmux) if available, so a page refresh
        # re-attaches to the SAME claude instead of re-resuming. Graceful
        # fallback to direct resume when no holder is installed.
        inner, holder_name = _wrap_in_holder(sid, inner)
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        # Strip ZELLIJ* env: serve.py itself runs inside a zellij session, so a
        # child would inherit ZELLIJ_SESSION_NAME and `zellij attach <that>`
        # would panic with "trying to attach to the current session". Clearing
        # it makes ttyd's shell a fresh client that can attach/mirror.
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
        # rendererType=dom → terminal is real selectable DOM text (canvas/webgl
        #   is pixels → unselectable). Enables drag-select + ⌘C / right-click Copy.
        # rightClickSelectsWord=true → right-click selects the word under cursor.
        # -I patched index → suppresses the browser's own context menu so it no
        #   longer pops over the selection (the rightClickSelectsWord option alone
        #   does NOT stop it). Falls back to no -I if patching fails.
        args = [ttyd, "-p", str(port), "-i", "127.0.0.1", "-W",
                "-t", "titleFixed=" + sid[:8],
                "-t", "rendererType=dom",
                "-t", "rightClickSelectsWord=true"]
        idx = _ttyd_patched_index()
        if idx:
            args += ["-I", idx]
        args += ["bash", "-lc", inner]
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env,
                start_new_session=True)  # detach: serve Ctrl-C must NOT kill the terminal
        except Exception as e:
            return self._reply(500, {"error": str(e)})
        _TERMINALS[sid] = {"port": port, "pid": proc.pid, "holder": holder_name}
        _save_terminals()
        time.sleep(0.4)  # let ttyd bind before the browser connects
        return self._reply(200, {"url": f"http://127.0.0.1:{port}/", "mode": mode})

    def _handle_new_session(self, body: dict):
        """Start a FRESH claude session in a chosen directory, in an embedded
        terminal — the 'new card from scratch' action. claude mints a brand-new
        session_id; once the user does work, the Stop/SessionStart hooks surface
        it as a card automatically. Body: {cwd}. There's no sid yet, so the
        terminal is keyed by an ephemeral token; a holder keeps it alive across a
        page refresh just like a resumed one."""
        ttyd = shutil.which("ttyd")
        if not ttyd:
            return self._reply(503, {"error": "ttyd not installed", "hint": "brew install ttyd"})
        cwd = (body.get("cwd") or "").strip()
        cwd = os.path.expanduser(cwd) if cwd else os.path.expanduser("~")
        if not os.path.isdir(cwd):
            return self._reply(400, {"error": "not a directory", "hint": cwd})
        # DD-022-B: optionally start the session in a NEW git worktree (semantic
        # name). We reuse Claude Code's native `claude --worktree <slug>` (creates
        # .claude/worktrees/<slug>/), so we inherit its conventions instead of
        # rebuilding worktree management.
        want_wt = bool(body.get("worktree"))
        wt_name = _worktree.slugify(body.get("name") or "") if _worktree else ""
        parent = (body.get("parent") or "").strip()        # DD-025: parent session id
        prompt = (body.get("prompt") or "").strip()        # DD-025: seed the child's task
        import uuid as _uuid
        token = "new-" + _uuid.uuid4().hex[:8]
        wt_path = ""   # the worktree dir we expect claude to create (for sid capture)
        if want_wt:
            cl0 = _worktree.compute_code_location(cwd) if _worktree else None
            if not cl0:
                return self._reply(400, {"error": "not a git repo",
                                         "hint": "新建 worktree 需要在一个 git 仓库目录里"})
            # ensure a slug so we know the worktree path (to capture the child sid)
            if not wt_name:
                wt_name = "task-" + _uuid.uuid4().hex[:6]
            # realpath: the child session records its cwd resolved (e.g. /tmp →
            # /private/tmp on macOS), so the prefix we match against must be too.
            wt_path = os.path.realpath(os.path.join(
                cl0.get("main_repo") or cwd, ".claude", "worktrees", wt_name))
            parts = ["claude", "--worktree", wt_name, "--name", wt_name,
                     "--dangerously-skip-permissions"]
            if prompt:
                parts += [prompt]
            inner = "cd " + shlex.quote(cwd) + " && " + " ".join(shlex.quote(p) for p in parts)
        else:
            parts = ["claude", "--dangerously-skip-permissions"] + ([prompt] if prompt else [])
            inner = "cd " + shlex.quote(cwd) + " && " + " ".join(shlex.quote(p) for p in parts)
        inner, holder_name = _wrap_in_holder(token, inner)
        import socket as _socket
        s = _socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
        args = [ttyd, "-p", str(port), "-i", "127.0.0.1", "-W",
                "-t", "titleFixed=new", "-t", "rendererType=dom",
                "-t", "rightClickSelectsWord=true"]
        idx = _ttyd_patched_index()
        if idx:
            args += ["-I", idx]
        args += ["bash", "-lc", inner]
        try:
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    env=child_env, start_new_session=True)
        except Exception as e:
            return self._reply(500, {"error": str(e)})
        _TERMINALS[token] = {"port": port, "pid": proc.pid, "holder": holder_name}
        _save_terminals()
        # DD-025: if this is a parent-spawned sub-card, capture the child's new
        # session id (it appears in the worktree's project dir within a few seconds)
        # and record the parent↔child link. Background thread — never blocks/raises.
        if parent and want_wt and wt_path and _subcards is not None:
            since = time.time() - 2

            def _capture():
                for _ in range(20):
                    time.sleep(1)
                    sid = _subcards.find_session_by_cwd(str(PROJECTS_DIR), wt_path, since)
                    if sid:
                        try:
                            _subcards.record(str(SUBCARDS_JSON), sid, parent, wt_name)
                        except Exception:
                            pass
                        return
            threading.Thread(target=_capture, daemon=True).start()
        time.sleep(0.4)
        return self._reply(200, {"url": f"http://127.0.0.1:{port}/", "token": token,
                                 "cwd": cwd, "worktree": want_wt,
                                 "worktree_name": wt_name if want_wt else None,
                                 "parent": parent or None})

    def _handle_merge(self, body: dict):
        """DD-016: record a user-declared merge into initiative_links.json and
        apply it to dashboard.json immediately. Body:
            {sessions: [sid...], canonical_id?: str, name?: str}
        The merge is durable — classify.apply_initiative_links re-applies it on
        every future run, so re-clustering can never re-split it."""
        try:
            sessions = [s for s in (body.get("sessions") or []) if s]
            if len(sessions) < 2:
                return self._reply(400, {"error": "need >= 2 sessions"})
            links = CACHE_DIR / "initiative_links.json"
            try:
                doc = json.loads(links.read_text())
                if not isinstance(doc, dict):
                    doc = {}
            except Exception:
                doc = {}
            doc.setdefault("version", 1)
            groups = doc.setdefault("groups", [])
            sset = set(sessions)
            # fold into any existing group that shares a session
            target = next((g for g in groups if sset.intersection(g.get("sessions") or [])), None)
            if target is None:
                target = {"sessions": []}
                groups.append(target)
            target["sessions"] = sorted(set((target.get("sessions") or []) + sessions))
            if body.get("canonical_id"):
                target["canonical_id"] = body["canonical_id"]
            if body.get("name"):
                target["name"] = body["name"]
            links.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
            # apply immediately + regen HTML
            sys.path.insert(0, str(REPO_ROOT / "bin"))
            import classify
            d = json.loads(DASHBOARD_JSON.read_text())
            n = classify.apply_initiative_links(d)
            classify.atomic_write_json(DASHBOARD_JSON, d)
            threading.Thread(target=regenerate_html, daemon=True).start()
            return self._reply(200, {"ok": True, "merged": n})
        except Exception as e:
            return self._reply(500, {"error": str(e)})

    def _handle_lifecycle(self, body: dict):
        """Pause / resume the pipeline (DD-005). Body:
            {"action": "pause" | "resume", "reason": "..." (optional)}
        Returns the new state."""
        action = (body.get("action") or "").lower()
        if action == "pause":
            reason = (body.get("reason") or "via dashboard").strip()
            from _lifecycle import pause
            state = pause(reason=reason, by="dashboard")
            return self._reply(200, state)
        if action == "resume":
            from _lifecycle import resume
            state = resume()
            return self._reply(200, state)
        return self._reply(400, {"error": "action must be 'pause' or 'resume'"})

    # ---- Zellij actions ----------------------------------------------------

    def _handle_focus(self, body: dict):
        pane = str(body.get("pane") or "")
        sess = body.get("session") or ""
        if not pane:
            return self._reply(400, {"error": "pane required"})
        if not has_zellij():
            return self._reply(503, {"error": "zellij not installed"})
        argv = ["zellij"]
        if sess:
            argv += ["--session", str(sess)]
        argv += ["action", "focus-pane-id", pane]
        rc, out, err = run_cmd(argv)
        err_msg = (err or "").strip()
        if rc != 0 and "already focused" in err_msg.lower():
            return self._reply(200, {"ok": True, "noop": True, "note": "already-focused"})
        if rc != 0 and ("not found" in err_msg.lower() or "no such" in err_msg.lower()):
            return self._reply(404, {"error": "pane_gone", "detail": err_msg})
        if rc != 0:
            return self._reply(500, {"error": err_msg or "focus failed"})
        return self._reply(200, {"ok": True})

    def _handle_newpane(self, body: dict):
        sid = (body.get("sid") or "").strip()
        if not sid:
            return self._reply(400, {"error": "sid required"})
        if not has_zellij():
            return self._reply(503, {"error": "zellij not installed"})
        # Resolve the session's project cwd so `claude --resume` finds it (the
        # latest cwd from session_locations may be a subdir → "No conversation
        # found"). Fall back to whatever the client passed.
        cwd = _resume_cwd_for(sid) or (body.get("cwd") or "")
        if cwd.startswith("~"):
            cwd = os.path.expanduser(cwd)
        inner = "claude --dangerously-skip-permissions --resume " + shlex.quote(sid)
        if cwd:
            inner = "cd " + shlex.quote(cwd) + " && " + inner
        argv = ["zellij", "run", "-f", "--", "bash", "-lc", inner]
        rc, out, err = run_cmd(argv, background=True)
        if rc != 0:
            return self._reply(500, {"error": err.strip() or "newpane failed"})
        return self._reply(200, {"ok": True})

    # ---- Per-item delete / archive (append, not overwrite) ----------------

    def _remove_from_dashboard(self, iid: str):
        """Drop an initiative from dashboard.json now + regen, so the cockpit
        reflects a delete/archive immediately (classify also honors it via
        deleted_ids.json / the archive dir on the next run)."""
        try:
            d = json.loads(DASHBOARD_JSON.read_text())
            for ws in d.get("workspaces", []):
                ws["initiatives"] = [i for i in (ws.get("initiatives") or []) if i.get("id") != iid]
            d["workspaces"] = [w for w in d.get("workspaces", []) if (w.get("initiatives") or [])]
            sys.path.insert(0, str(REPO_ROOT / "bin"))
            import classify
            classify.atomic_write_json(DASHBOARD_JSON, d)
            threading.Thread(target=regenerate_html, daemon=True).start()
        except Exception:
            pass

    def _handle_delete(self, body: dict):
        iid = (body.get("id") or "").strip()
        if not iid:
            return self._reply(400, {"error": "id required"})
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            try:
                doc = json.loads(DELETED_JSON.read_text())
                if not isinstance(doc, dict): doc = {}
            except Exception:
                doc = {}
            inits = doc.setdefault("initiatives", [])
            if not any(x.get("id") == iid for x in inits):
                inits.append({"id": iid, "deleted_at": now})
            doc["version"] = 1
            doc["updated_at"] = now
            DELETED_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
            self._remove_from_dashboard(iid)
            return self._reply(200, {"ok": True})
        except Exception as e:
            return self._reply(500, {"error": str(e)})

    def _handle_archive(self, body: dict):
        iid = (body.get("id") or "").strip()
        if not iid:
            return self._reply(400, {"error": "id required"})
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            d = json.loads(DASHBOARD_JSON.read_text())
            found = fws = None
            for ws in d.get("workspaces", []):
                for i in (ws.get("initiatives") or []):
                    if i.get("id") == iid:
                        found, fws = i, ws; break
                if found:
                    break
            if not found:
                return self._reply(404, {"error": "not found"})
            ws_name = fws.get("name") or "unknown"
            ws_dir = ARCHIVE_DIR / safe_dir_name(ws_name)
            ws_dir.mkdir(parents=True, exist_ok=True)
            payload = {"archived_at": now, "archived_by": "user",
                       "from_workspace": ws_name, "initiative": found}
            (ws_dir / f"{iid}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            self._remove_from_dashboard(iid)
            return self._reply(200, {"ok": True})
        except Exception as e:
            return self._reply(500, {"error": str(e)})

    # ---- Save overrides directly to cache/ --------------------------------

    def _handle_save(self, body: dict):
        """
        Body shape:
          {
            task_toggles: [{init_id, task_title, status, at}],   # DD-011
            deleted_tasks: [{init_id, task_title, at}],
            archived: [init_id, ...],
            archived_data: { init_id: {ws_name, ws_cwd, init} },   // payload to write under archive/
            deleted: [init_id, ...]
          }

        `status` is the new tri-state field (`pending|done|cancelled`).
        Pre-DD-011 clients may still send `done: bool`; classify.py's
        apply_user_overrides_inplace coerces both shapes.
        """
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # 1) user_overrides.json — task_toggles + deleted_tasks are
            # consumed by classify (cleared after applying). hidden_artifacts
            # is a persistent suppression list: it stays in the file across
            # classify runs so a user-deleted MR / PR / etc. never reappears
            # even when Layer 1 keeps re-emitting it from session frontmatter.
            ov = {
                "version": 1,
                "task_toggles": body.get("task_toggles") or [],
                "deleted_tasks": body.get("deleted_tasks") or [],
                "hidden_artifacts": body.get("hidden_artifacts") or [],
                "updated_at": now,
            }
            OVERRIDES_JSON.write_text(json.dumps(ov, indent=2, ensure_ascii=False))

            # 2) deleted_ids.json
            del_ids = body.get("deleted") or []
            del_doc = {
                "version": 1,
                "initiatives": [{"id": i, "deleted_at": now} for i in del_ids],
                "updated_at": now,
            }
            DELETED_JSON.write_text(json.dumps(del_doc, indent=2, ensure_ascii=False))

            # 3) archive/<ws>/<init_id>.json — write any archived entries we have
            archived_data = body.get("archived_data") or {}
            for init_id, rec in archived_data.items():
                if not init_id or not isinstance(rec, dict):
                    continue
                ws_name = rec.get("ws_name") or "unknown"
                ws_dir = ARCHIVE_DIR / safe_dir_name(ws_name)
                ws_dir.mkdir(parents=True, exist_ok=True)
                payload = {
                    "archived_at": now,
                    "archived_by": "user",
                    "from_workspace": ws_name,
                    "initiative": rec.get("init"),
                }
                (ws_dir / f"{init_id}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))

            # Regenerate HTML so a reload reflects the save (dashboard.json is
            # untouched until next refresh; the HTML uses overrides to compute
            # the effective view at runtime, so this regen mainly ensures any
            # nav/initial state is fresh).
            threading.Thread(target=regenerate_html, daemon=True).start()
            return self._reply(200, {"ok": True})
        except Exception as e:
            return self._reply(500, {"error": str(e)})

    def _handle_refresh(self, body: dict):
        """Kick off the AI pipeline in the background. Non-blocking.
        Sweeps any dirty sessions through Layer 1 and forces Layer 2 to
        run — manual-refresh semantics: the user clicked the button, they
        want a fresh classification."""
        if not PIPELINE_RUN.exists():
            return self._reply(503, {"error": "pipeline-run.sh missing"})
        argv = ["bash", str(PIPELINE_RUN), "--all-dirty", "--force-classify"]
        try:
            subprocess.Popen(
                argv, env=os.environ.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return self._reply(202, {"ok": True,
                                     "note": "pipeline started in background"})
        except Exception as e:
            return self._reply(500, {"error": str(e)})

    def _handle_consolidate(self, body: dict):
        """One-shot AI dedup for a single initiative's pending tasks
        (DD-012 tail).

        Body: {"init_id": "..."}
        Returns: {"ok": true, "groups": [{"keep": "...", "cancel": [{"title": ..., "reason": ...}]}]}

        Synchronous: blocks the request until Haiku replies (~5-15 s).
        Does NOT mutate state — the response is a *plan*; the frontend
        previews it and the user has to confirm. Confirmation flows
        through the existing task_toggles override path (set status to
        cancelled with evidence), so DD-011's user-only-deletion stays
        intact."""
        init_id = (body.get("init_id") or "").strip()
        if not init_id:
            return self._reply(400, {"error": "init_id required"})

        # Gather pending tasks for this init (dedup'd, capped — same
        # logic Layer 1 uses in summarize.load_prior_tasks_for_sid).
        if not DASHBOARD_JSON.exists():
            return self._reply(404, {"error": "dashboard.json missing — run refresh first"})
        try:
            d = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return self._reply(500, {"error": f"dashboard.json unreadable: {e}"})

        titles: list[str] = []
        init_name: str | None = None
        for ws in (d.get("workspaces") or []):
            for init in (ws.get("initiatives") or []):
                if init.get("id") != init_id:
                    continue
                init_name = init.get("name") or init_id
                seen: set[str] = set()
                for t in (init.get("tasks") or []):
                    title = (t.get("title") or "").strip()
                    if not title or title in seen:
                        continue
                    if t.get("status") != "pending":
                        continue
                    seen.add(title)
                    titles.append(title)
        if init_name is None:
            return self._reply(404, {"error": f"initiative not found: {init_id}"})
        if len(titles) < 4:
            return self._reply(200, {"ok": True, "groups": [],
                                     "note": "fewer than 4 pending tasks — nothing to consolidate"})

        # Build the prompt: instructions + the task list as a tiny
        # YAML block.
        prompt_file = REPO_ROOT / "prompts" / "consolidate-tasks.md"
        if not prompt_file.exists():
            return self._reply(500, {"error": "consolidate-tasks.md prompt missing"})
        instructions = prompt_file.read_text(encoding="utf-8")
        yaml_block_lines = ["tasks:"]
        for title in titles:
            safe = title.replace('"', '\\"')
            yaml_block_lines.append(f'  - "{safe}"')
        prompt = "\n".join([
            instructions,
            "",
            f"<initiative id=\"{init_id}\" name=\"{init_name}\">",
            f"<tasks count=\"{len(titles)}\">",
            "\n".join(yaml_block_lines),
            "</tasks>",
            "</initiative>",
        ])

        # Mirror the call style from bin/classify.py call_claude.
        model = os.environ.get("CLAUDE_WORKTREE_MODEL",
                                "claude-haiku-4-5-20251001")
        # Haiku takes ~90-100s end-to-end for ~40 titles producing the
        # structured JSON plan. Comfortable headroom for outliers (no
        # one is waiting on this synchronously beyond a single click,
        # and the UI shows a "scanning…" spinner the whole time).
        timeout = 240
        argv = [
            "perl", "-e", "alarm shift @ARGV; exec @ARGV",
            str(timeout),
            "claude", "--no-session-persistence", "-p",
            "--model", model,
            "--output-format", "json",
            "--max-budget-usd", "0.20",
            "--disallowedTools", "Bash Edit Write Read Glob Grep",
        ]
        try:
            res = subprocess.run(argv, input=prompt, capture_output=True,
                                  text=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            return self._reply(504, {"error": "consolidate AI call timed out"})
        except Exception as e:
            return self._reply(500, {"error": f"AI invocation failed: {e}"})
        if res.returncode != 0:
            return self._reply(502, {"error": "AI call non-zero exit",
                                     "stderr": (res.stderr or "")[:500]})

        try:
            env = json.loads(res.stdout)
            raw = (env.get("result") or "").strip()
            # Tolerate AI wrapping the JSON in a code fence.
            m = re.search(r"\{[\s\S]*\}", raw)
            if not m:
                raise ValueError("no JSON object in response")
            plan = json.loads(m.group(0))
        except Exception as e:
            return self._reply(502, {"error": f"could not parse AI output: {e}",
                                     "raw": (res.stdout or "")[:800]})

        # Sanitize: every keep + cancel.title MUST appear in the input
        # titles list (the prompt insists on byte-for-byte reuse, but
        # if Haiku misbehaves we don't want to ship fake titles to the
        # client — they would silently no-op against task_toggles since
        # no matching task exists).
        title_set = set(titles)
        groups_out = []
        for g in (plan.get("groups") or []):
            keep = (g.get("keep") or "").strip()
            if keep not in title_set:
                continue
            cancels = []
            for c in (g.get("cancel") or []):
                t = (c.get("title") or "").strip()
                if t and t != keep and t in title_set:
                    cancels.append({"title": t,
                                    "reason": (c.get("reason") or "").strip()[:120]})
            if cancels:
                groups_out.append({"keep": keep, "cancel": cancels})

        return self._reply(200, {"ok": True, "groups": groups_out,
                                 "total_pending": len(titles)})

    def _handle_update(self, body: dict):
        """Dashboard 'Update now' button. Runs git pull --ff-only and
        returns the result. The client then prompts the user to
        restart `stray --serve` to load the new code (we can't hot-
        reload Python modules cleanly, and serve.py itself may have
        changed). Throttled implicitly by `_updates.is_dirty()`."""
        try:
            import _updates
            result = _updates.pull_latest()
            return self._reply(200 if result.get("ok") else 409, result)
        except Exception as e:
            return self._reply(500, {"ok": False, "error": str(e)})


def _dashboard_empty() -> bool:
    try:
        data = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
        return sum(len(w.get("initiatives") or [])
                   for w in (data.get("workspaces") or [])) == 0
    except Exception:
        return True


def _write_sync_status(state: str, reason: str = "", log_tail: str = "") -> None:
    try:
        SYNC_STATUS_JSON.write_text(json.dumps(
            {"state": state, "reason": reason, "log_tail": log_tail,
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ensure_ascii=False))
    except Exception:
        pass


def _read_sync_status() -> dict:
    try:
        return json.loads(SYNC_STATUS_JSON.read_text())
    except Exception:
        return {}


def _maybe_kick_first_sync() -> bool:
    """Trigger a background pipeline run iff the cache is empty.

    First-time users install + `stray --serve` and would otherwise see
    a blank dashboard until their next Claude Code session ends (when
    the Stop hook fires the pipeline). This kicks the pipeline once on
    behalf of the user when there's nothing to show — costs roughly the
    same as one `stray --refresh` and disappears after first run.

    Returns True if a sync was started, False otherwise. The dashboard
    polls /api/data every 8 s and will pick up cards as classify
    produces them; no need for serve.py to block.
    """
    if not PIPELINE_RUN.exists():
        return False
    if not _dashboard_empty():
        return False
    # claude availability is a PRECONDITION for the background analysis. If it's
    # missing we can't sync at all — surface that to the page instead of leaving
    # a silent blank dashboard.
    if not shutil.which("claude"):
        _write_sync_status("failed",
            "未找到 claude CLI —— 后台分析无法进行。确认已装 Claude Code、`claude` 在 PATH 且已登录(试 `claude -p hi`)。")
        print("[serve] first-sync: claude CLI not found", file=sys.stderr)
        return False
    _write_sync_status("running", "正在分析你最近的会话(首次约 1–2 分钟)…")

    def _runner():
        try:
            with open(SYNC_LOG, "w") as log:
                subprocess.run(
                    ["bash", str(PIPELINE_RUN), "--all-dirty", "--force-classify"],
                    env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
        except Exception as e:
            _write_sync_status("failed", f"后台同步启动失败:{e}")
            return
        if not _dashboard_empty():
            _write_sync_status("ok")
            return
        tail = ""
        try:
            tail = "\n".join(SYNC_LOG.read_text(errors="replace").splitlines()[-12:])
        except Exception:
            pass
        # Ran but produced nothing → almost always claude not logged in / AI call
        # failing, or simply no sessions in the last 48h.
        _write_sync_status("failed",
            "后台同步跑完但没产出卡片 —— 多半是 `claude` 未登录或 AI 调用失败(试 `claude -p hi`),也可能近 48h 内没有会话(全量历史跑 `stray --backfill`)。",
            tail)

    try:
        threading.Thread(target=_runner, daemon=True).start()
        print("[serve] cache is empty — kicked first-time sync in background")
        return True
    except Exception as e:
        _write_sync_status("failed", f"后台同步启动失败:{e}")
        print(f"[serve] first-sync kick failed: {e}", file=sys.stderr)
        return False


def _check_updates_interactive() -> None:
    """Run on serve startup. If a new tagged release is available
    AND the user hasn't recently dismissed an update prompt AND stdin
    is a TTY, print version info and prompt y/N to upgrade. On 'y'
    runs git pull and continues serving the new code. On 'n' marks
    the prompt as dismissed for 24h. Silently skipped when offline,
    not-a-git-repo, or non-interactive."""
    try:
        import _updates
    except Exception:
        return
    # Throttle: respect 24h window AND the user's recent "no, thanks".
    if not _updates.should_check(force=False):
        return
    if _updates.user_dismissed_recently():
        return
    snap = _updates.check(force=False)
    if not snap.get("ok") or not snap.get("behind"):
        return
    local, remote = snap.get("local"), snap.get("remote")
    print(f"\n[stray] update available:  {local} → {remote}")
    changes = _updates.summarize_changes(local, "origin/main")
    if changes:
        for c in changes[:6]:
            print(f"        · {c}")
        if len(changes) > 6:
            print(f"        … +{len(changes) - 6} more")
    if not sys.stdin.isatty():
        print(f"[stray] non-interactive shell — keeping current version.")
        print(f"[stray] run `stray --update` later to install.\n")
        return
    try:
        answer = input(f"[stray] update now and continue? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer in ("", "y", "yes"):
        result = _updates.pull_latest()
        if result.get("ok"):
            print(f"[stray] updated  {result['before']} → {result['after']}.")
            print("[stray] continuing with the new version (no restart needed "
                  "for static assets; if behavior looks stale, Ctrl-C and "
                  "re-run `stray --serve`).\n")
        else:
            print(f"[stray] update failed: {result.get('error')}")
            print("[stray] continuing with current version.\n")
    else:
        _updates.mark_user_dismissed()
        print("[stray] skipping update. Next prompt in 24h. "
              "Run `stray --update` to install on demand.\n")


def _update_recheck_loop(stop_event) -> None:
    """Daemon thread: re-run the update check every 24h while serve
    is alive. Silent — updates `cache/update_state.json` only. The
    dashboard polls /api/version to surface the banner."""
    import _updates
    # First wake at +24h; the startup path already did the initial check.
    while not stop_event.wait(_updates.CHECK_INTERVAL.total_seconds()):
        try:
            _updates.check(force=True, offline_ok=True)
        except Exception:
            pass  # state is best-effort; never let a flake kill serve


def serve(open_browser: bool = True):
    # Regenerate HTML before serving so it's fresh.
    regenerate_html()
    # First-time bootstrap: if the user just installed and the cache is
    # still empty, kick off one pipeline run so they see cards within a
    # minute or two instead of an empty dashboard.
    _maybe_kick_first_sync()
    # Recover embedded terminals that survived a previous serve (start_new_session
    # detaches them from our process group, so Ctrl-C restart doesn't kill them).
    _load_terminals()
    if _TERMINALS:
        print(f"[serve] recovered {len(_TERMINALS)} live terminal(s) across restart")
    # If a new release is out and the user is running interactively,
    # offer to upgrade in place before binding the port.
    _check_updates_interactive()
    class QuietServer(ThreadingHTTPServer):
        # A browser dropping a connection (closing a tab, aborting an SSE
        # stream) raises ConnectionResetError/BrokenPipeError deep in the
        # handler; the default handle_error dumps an alarming traceback. These
        # are benign — swallow them, surface everything else.
        def handle_error(self, request, client_address):
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
                return
            super().handle_error(request, client_address)

    last_error = None
    for port in PORTS:
        try:
            httpd = QuietServer((BIND, port), Handler)
        except OSError as e:
            last_error = e
            continue
        # Daemon threads so any in-flight handlers don't block process exit.
        httpd.daemon_threads = True

        url = f"http://{BIND}:{port}/"
        print(f"\n  ▸ {url}\n")
        print(f"[serve] endpoints:")
        print(f"        GET  /            (dashboard)")
        print(f"        GET  /mindmap-tree.html  (markmap export view)")
        print(f"        GET  /ping        /api/data    /api/version")
        print(f"        POST /api/save    /api/refresh  /api/lifecycle  /api/update  /focus  /newpane")
        print(f"[serve] Ctrl-C to stop.\n")

        # Cost-alarm snapshot at startup — prints to stderr only if not 'ok'
        # (avoids noisy "all green" logs on healthy boots).
        try:
            from _cost_alarm import snapshot as _cost_snap, format_console_line
            _snap = _cost_snap()
            if _snap["level"] != "ok":
                print(format_console_line(_snap), file=sys.stderr)
        except Exception as e:
            print(f"[serve] cost-alarm init failed: {e}", file=sys.stderr)

        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        # Shutdown handler must run in a worker thread. Calling
        # httpd.shutdown() synchronously from the signal handler deadlocks:
        # shutdown() waits for serve_forever() to exit, but serve_forever()
        # is on the main thread that's currently inside the signal handler,
        # so it never gets to check the shutdown flag.
        shutdown_started = {"flag": False}
        def trigger_shutdown(_sig, _frm):
            if shutdown_started["flag"]:
                return  # idempotent — second Ctrl-C shouldn't re-print
            shutdown_started["flag"] = True
            print("\n[serve] shutting down…")
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        signal.signal(signal.SIGINT, trigger_shutdown)
        signal.signal(signal.SIGTERM, trigger_shutdown)

        # Background scheduler for DD-006 derived features.
        # Lives for the lifetime of serve — when serve dies, the
        # scheduler dies with it. Daemon thread so it can't keep the
        # process alive past httpd.shutdown().
        stop_scheduler = threading.Event()
        sched_thread = threading.Thread(
            target=_derived_scheduler_loop,
            args=(stop_scheduler,),
            daemon=True,
            name="ccw-derived-sched",
        )
        sched_thread.start()
        print("[serve] derived scheduler: tips every 2h, weekly Fri noon",
              file=sys.stderr)

        # Background update-checker. Updates cache/update_state.json
        # every 24h; the dashboard polls /api/version for the banner.
        update_thread = threading.Thread(
            target=_update_recheck_loop,
            args=(stop_scheduler,),  # reuse the same stop event
            daemon=True,
            name="ccw-update-check",
        )
        update_thread.start()

        try:
            httpd.serve_forever()
        finally:
            stop_scheduler.set()
            httpd.server_close()
            print("[serve] stopped")
        return 0
    print(f"[serve] all ports {PORTS} are in use: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    # --no-open suppresses auto-opening the browser.
    open_browser = "--no-open" not in sys.argv
    sys.exit(serve(open_browser=open_browser))
