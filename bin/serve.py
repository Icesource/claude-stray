#!/usr/bin/env python3
"""
Unified local server for claude-code-worktree.

Listens on 127.0.0.1:9876 (falls back to 9877, 9878 if busy):

  GET  /                  -> serves cache/mindmap.html
  GET  /mindmap-tree.html -> serves cache/mindmap-tree.html
  GET  /cache/...         -> serves files from cache/ (json data, etc.)
  GET  /ping              -> health check + capabilities
  GET  /api/data          -> current mindmap.json + locations + overrides + lifecycle
  GET  /api/task-history  -> per-initiative full task archive (DD-008)
                             query: ?init_id=<initiative-id>
  POST /api/save          -> persist user overrides (task toggles, archive, delete)
  POST /api/refresh       -> trigger background AI refresh
  POST /api/lifecycle     -> pause / resume the pipeline (DD-005)
                             body: {"action": "pause"|"resume", "reason": "..."}
  POST /focus             -> body {pane, session?} -> zellij focus-pane-id
  POST /newpane           -> body {sid, cwd?}      -> zellij run -- claude --resume

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
HTML_FILE = CACHE_DIR / "mindmap.html"
TREE_FILE = CACHE_DIR / "mindmap-tree.html"
MINDMAP_JSON = CACHE_DIR / "mindmap.json"
LOCATIONS_JSON = CACHE_DIR / "session_locations.json"
OVERRIDES_JSON = CACHE_DIR / "user_overrides.json"
DELETED_JSON = CACHE_DIR / "deleted_ids.json"
ARCHIVE_DIR = CACHE_DIR / "archive"
RENDER_HTML = REPO_ROOT / "bin" / "render-html.py"
RENDER_TREE = REPO_ROOT / "bin" / "render-tree.py"
PIPELINE_RUN = REPO_ROOT / "bin" / "pipeline-run.sh"
TASK_ARCHIVE_DIR = CACHE_DIR / "task_archive"
DERIVED_DIR = CACHE_DIR / "derived"

PORTS = [9876, 9877, 9878]
BIND = "127.0.0.1"


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
# - tips: run once on serve startup, then every 6h
#         (tips.py also has its own 6h debounce, this is belt+suspenders)
# - weekly_report: every Friday after 12:00 local, if this week's
#         report hasn't been generated yet
# - wellness: piggybacks on the tips tick — signal-gated, costs
#         nothing when no late-nights / consecutive-days signal fires

_TIPS_INTERVAL_SECS = 6 * 3600
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
                print("[sched] tips: 6h elapsed", file=sys.stderr)
                _run_derived("tips.py")
                _run_derived("wellness.py")
        else:
            _run_derived("tips.py")

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
            if not MINDMAP_JSON.exists():
                return
            data_mtime = MINDMAP_JSON.stat().st_mtime
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

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index", "/index.html", "/mindmap.html"):
            return self._serve_file(HTML_FILE, "text/html")
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
                "service": "claude-code-worktree", "version": 2,
                "has_zellij": has_zellij(),
                "can_write_disk": True,  # the server CAN write to cache/
            })
        if path == "/api/data":
            data = {}
            try: data["mindmap"] = json.load(open(MINDMAP_JSON))
            except Exception: data["mindmap"] = None
            try: data["locations"] = json.load(open(LOCATIONS_JSON))
            except Exception: data["locations"] = None
            # Archived items from cache/archive/<ws>/<id>.json — these are
            # outside mindmap.json so we surface them explicitly so the
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
        if path == "/api/task-history":
            # Per-initiative task archive (DD-008). Read-only.
            qs = parse_qs(urlparse(self.path).query)
            init_id = (qs.get("init_id") or [""])[0]
            if not init_id:
                return self._reply(400, {"error": "missing init_id"})
            # Resolve the same safe-filename derivation that classify.py uses.
            import re as _re
            safe = _re.sub(r"[^\w\-]", "_", init_id)[:120]
            p = TASK_ARCHIVE_DIR / f"{safe}.json"
            if not p.exists():
                return self._reply(404, {"error": "no archive for this initiative"})
            try:
                rec = json.loads(p.read_text())
            except Exception as e:
                return self._reply(500, {"error": f"archive corrupt: {e}"})
            return self._reply(200, rec)
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
        self._reply(404, {"error": "not found", "path": path})

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
        inner = "claude --resume " + shlex.quote(sid)
        if cwd:
            inner = "cd " + shlex.quote(cwd) + " && " + inner
        argv = ["zellij", "run", "-f", "--", "bash", "-lc", inner]
        rc, out, err = run_cmd(argv, background=True)
        if rc != 0:
            return self._reply(500, {"error": err.strip() or "newpane failed"})
        return self._reply(200, {"ok": True})

    # ---- Save overrides directly to cache/ --------------------------------

    def _handle_save(self, body: dict):
        """
        Body shape:
          {
            task_toggles: [{init_id, task_title, done, at}],
            deleted_tasks: [{init_id, task_title, at}],
            archived: [init_id, ...],
            archived_data: { init_id: {ws_name, ws_cwd, init} },   // payload to write under archive/
            deleted: [init_id, ...]
          }
        """
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

            # 1) user_overrides.json
            ov = {
                "version": 1,
                "task_toggles": body.get("task_toggles") or [],
                "deleted_tasks": body.get("deleted_tasks") or [],
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

            # Regenerate HTML so a reload reflects the save (mindmap.json is
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


def serve(open_browser: bool = True):
    # Regenerate HTML before serving so it's fresh.
    regenerate_html()
    last_error = None
    for port in PORTS:
        try:
            httpd = ThreadingHTTPServer((BIND, port), Handler)
        except OSError as e:
            last_error = e
            continue
        # Daemon threads so any in-flight handlers don't block process exit.
        httpd.daemon_threads = True

        url = f"http://{BIND}:{port}/"
        print(f"\n  ▸ {url}\n")
        print(f"[serve] endpoints:")
        print(f"        GET  /            (mindmap dashboard)")
        print(f"        GET  /mindmap-tree.html  (markmap export view)")
        print(f"        GET  /ping        /api/data    /api/task-history?init_id=<id>")
        print(f"        POST /api/save    /api/refresh  /api/lifecycle  /focus  /newpane")
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
        print("[serve] derived scheduler: tips every 6h, weekly Fri noon",
              file=sys.stderr)

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
