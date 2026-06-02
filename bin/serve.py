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

PORTS = [9876, 9877, 9878]
BIND = "127.0.0.1"

LIVE_DIR = CACHE_DIR / "live"  # DD-015 Stage 1: per-session live status


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
        out[sid] = rec
    return out


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
            })
        if path == "/api/live":
            return self._reply(200, {"live": live_snapshot()})
        if path == "/api/events":
            return self._handle_sse()
        if path == "/api/data":
            data = {}
            try: data["mindmap"] = json.load(open(DASHBOARD_JSON))
            except Exception: data["mindmap"] = None
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
        self._reply(404, {"error": "not found", "path": path})

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
        cwd = body.get("cwd") or ""
        if not sid:
            return self._reply(400, {"error": "sid required"})
        if not has_zellij():
            return self._reply(503, {"error": "zellij not installed"})
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
    if not DASHBOARD_JSON.exists():
        empty = True
    else:
        try:
            data = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
            ws = data.get("workspaces") or []
            init_count = sum(len(w.get("initiatives") or []) for w in ws)
            empty = init_count == 0
        except (OSError, json.JSONDecodeError):
            empty = True
    if not empty:
        return False
    try:
        subprocess.Popen(
            ["bash", str(PIPELINE_RUN), "--all-dirty", "--force-classify"],
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("[serve] cache is empty — kicked first-time sync in background")
        return True
    except Exception as e:
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
