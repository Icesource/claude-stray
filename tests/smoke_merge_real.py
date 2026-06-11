"""DD-031 REAL smoke: a real `claude` merge agent resolves a real conflict.

NOT part of bin/test (costs subscription quota + leaves real sessions in
~/.claude/projects, which are deleted afterwards). Run explicitly:

    python3 tests/smoke_merge_real.py

Flow: temp repo → spawn a REAL sub-card claude that adds sub_feature() and
commits → main adds main_feature() in the same region (guaranteed conflict
with an unambiguous resolution: keep both) → /api/subcard-merge spawns a REAL
merge agent → it resolves + commits → /api/subcard-land → assert main carries
BOTH functions → full cleanup (worktrees/branches/tmux/jsonl + production
cards via the 9876 API if present).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = f"st-smoke-{os.getpid()}"
PROJECTS = Path.home() / ".claude" / "projects"


def log(msg):
    print(f"[smoke +{time.time() - T0:5.1f}s] {msg}", flush=True)


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd] + list(args),
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip()


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def post(port, path, body, timeout=30):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def wait(fn, timeout, msg, poll=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return
        time.sleep(poll)
    raise AssertionError(f"timeout: {msg}")


T0 = time.time()
tmp = Path(tempfile.mkdtemp(prefix="stray-smoke-")).resolve()
cache = tmp / "cache"; cache.mkdir()
repo = tmp / "repo"; repo.mkdir()
port = free_port()
sids = []          # real session ids created — deleted in cleanup
serve_proc = None
ok = False

# A REAL claude in a never-before-seen directory stops at the folder-trust
# dialog (--dangerously-skip-permissions does NOT waive it — verified
# 2026-06-11; this is also a real product edge: `stray spawn` in a repo the
# user never opened claude in will hang the same way). The smoke's repos are
# our own throwaway dirs created seconds earlier, so a watcher thread
# auto-accepts the dialog in any session on OUR private tmux socket.
import threading
_stop_clicker = threading.Event()

def _trust_clicker():
    while not _stop_clicker.is_set():
        try:
            r = subprocess.run(["tmux", "-L", SOCK, "list-sessions", "-F", "#{session_name}"],
                               capture_output=True, text=True, timeout=5)
            for name in r.stdout.split():
                cap = subprocess.run(["tmux", "-L", SOCK, "capture-pane", "-p", "-t", name],
                                     capture_output=True, text=True, timeout=5).stdout
                if "trust this folder" in cap or "Yes, I trust" in cap:
                    subprocess.run(["tmux", "-L", SOCK, "send-keys", "-t", name, "Enter"],
                                   capture_output=True, timeout=5)
                    log(f"accepted folder-trust dialog in tmux session {name}")
        except Exception:
            pass
        _stop_clicker.wait(3)


def dump_panes(reason):
    """Diagnostics: what is every claude on our socket actually showing?"""
    try:
        r = subprocess.run(["tmux", "-L", SOCK, "list-sessions", "-F", "#{session_name}"],
                           capture_output=True, text=True, timeout=5)
        for name in r.stdout.split():
            cap = subprocess.run(["tmux", "-L", SOCK, "capture-pane", "-p", "-t", name],
                                 capture_output=True, text=True, timeout=5).stdout
            tail = "\n".join([l for l in cap.splitlines() if l.strip()][-12:])
            print(f"---- pane {name} ({reason}) ----\n{tail}", file=sys.stderr)
    except Exception:
        pass
try:
    # ---- seed repo ----------------------------------------------------------
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "smoke@test")
    _git(repo, "config", "user.name", "smoke")
    (repo / "shared.py").write_text("VALUE = 1\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "seed")

    # ---- boot serve (isolated cache/port/socket; REAL projects dir) ---------
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("STRAY_", "CLAUDE_CODE", "CLAUDECODE", "ZELLIJ", "TMUX"))}
    env.update({"STRAY_CACHE_DIR": str(cache), "STRAY_PORTS": str(port),
                "STRAY_TMUX_SOCKET": SOCK, "STRAY_NO_BG": "1"})
    slog = open(tmp / "serve.log", "w")
    serve_proc = subprocess.Popen(
        [sys.executable, os.path.join(REPO, "bin", "serve.py"), "--no-open"],
        env=env, stdout=slog, stderr=subprocess.STDOUT)

    def ping():
        try:
            return urllib.request.urlopen(
                f"http://127.0.0.1:{port}/ping", timeout=2).status == 200
        except Exception:
            return False
    wait(ping, 20, "serve boot", poll=0.5)
    log(f"serve up on :{port}")
    threading.Thread(target=_trust_clicker, daemon=True).start()

    # ---- phase 1: REAL sub-card does real work ------------------------------
    st, j = post(port, "/api/new-session", {
        "cwd": str(repo), "worktree": True, "name": "sub-feature",
        "parent": "smoke-parent",
        "prompt": ("在 shared.py 文件末尾追加这个函数(原样,不要改其他内容):\n\n"
                   "def sub_feature():\n    return \"sub\"\n\n"
                   "然后执行 git add -A && git commit -m 'add sub_feature'。"
                   "只做这一件事,做完就停。")})
    assert st == 200 and j.get("ok"), (st, j)
    slug = j["worktree_name"]
    log(f"sub-card spawned: {slug} — waiting for the real claude to commit…")
    wait(lambda: _git(repo, "rev-list", "--count", f"main..worktree-{slug}")[1] not in ("", "0"),
         300, "sub-card claude never committed")
    log("sub-card committed its work")

    def sub_sid():
        # the unified created-cards registry (DD-030) is the only writer now
        try:
            reg = json.loads((cache / "created-cards.json").read_text())
            return next((e["sid"] for e in reg.values()
                         if e.get("worktree_name") == slug and e.get("sid")), None)
        except Exception:
            return None
    wait(lambda: sub_sid(), 60, "sub sid capture")
    sids.append(sub_sid())
    log(f"sub sid = {sids[-1]}")

    # ---- phase 2: conflicting change on main --------------------------------
    (repo / "shared.py").write_text("VALUE = 1\n\ndef main_feature():\n    return \"main\"\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "add main_feature")

    # ---- phase 3: DD-034 — the sub-card ITSELF resolves (LIVE tmux nudge) ---
    # the spawned interactive claude is still alive in its holder, so this
    # exercises the live send-keys injection path (e2e can't — fake exits).
    st, j = post(port, "/api/subcard-merge", {"sid": sids[0], "target": "main"})
    assert st == 200 and j.get("ok"), (st, j)
    log("merge instruction injected into the sub-card's LIVE session…")
    wait(lambda: _git(repo, "merge-base", "--is-ancestor",
                      "main", f"worktree-{slug}")[0] == 0,
         360, "sub-card never absorbed main (conflict unresolved?)")
    sub_wt = repo / ".claude" / "worktrees" / slug
    merged = (sub_wt / "shared.py").read_text()
    assert "<<<<<<<" not in merged, "conflict markers left behind!"
    assert "def sub_feature" in merged and "def main_feature" in merged, \
        f"sub dropped a side!\n{merged}"
    rc, dirty = _git(sub_wt, "status", "--porcelain", "-uno")
    assert not dirty.strip(), f"sub worktree not committed clean:\n{dirty}"
    log("conflict resolved by the sub-card itself (both functions kept)")

    # ---- phase 4: land — DD-034: card SURVIVES --------------------------------
    st, j = post(port, "/api/subcard-land", {"sub_sid": sids[0]})
    assert st == 200 and j.get("ok") and j.get("kept"), (st, j)
    landed = (repo / "shared.py").read_text()
    assert "def sub_feature" in landed and "def main_feature" in landed, landed
    assert _git(repo, "rev-parse", "--verify", "--quiet", f"worktree-{slug}")[0] == 0, \
        "DD-034: sub branch must SURVIVE landing"
    assert sub_wt.is_dir(), "DD-034: sub worktree must SURVIVE landing"
    assert json.loads((cache / "merge-jobs.json").read_text())["jobs"] == []
    log("landed: main carries both sides; sub-card kept alive (DD-034)")

    # ---- phase 5: explicit × close cleans up ----------------------------------
    st, j = post(port, "/api/subcard-close", {"sid": sids[0], "force": True})
    assert st == 200 and j.get("ok"), (st, j)
    wait(lambda: _git(repo, "rev-parse", "--verify", "--quiet", f"worktree-{slug}")[0] != 0,
         30, "close did not remove the sub branch")
    log("explicit close cleaned worktree+branch")
    ok = True
finally:
    # ---- cleanup -------------------------------------------------------------
    if not ok:
        dump_panes("at failure")
    _stop_clicker.set()
    log("cleanup…")
    if serve_proc:
        serve_proc.terminate()
        try:
            serve_proc.wait(timeout=10)
        except Exception:
            serve_proc.kill()
    subprocess.run(["tmux", "-L", SOCK, "kill-server"], capture_output=True)
    # ttyds for the temp cards (start_new_session → survive serve)
    try:
        for ent in json.loads((cache / "terminals.json").read_text()).values():
            try:
                os.kill(int(ent["pid"]), 15)
            except Exception:
                pass
    except Exception:
        pass
    # the real session transcripts of OUR OWN test sessions + their pipeline
    # artifacts in the PRODUCTION cache (authorized cleanup: leave no test cards)
    prod_cache = Path(os.environ.get("SMOKE_PROD_CACHE",
                                     str(Path.home() / "Code" / "claude-stray" / "cache")))
    for sid in [s for s in sids if s]:
        for f in PROJECTS.glob(f"*/{sid}.jsonl"):
            f.unlink(missing_ok=True); log(f"deleted transcript {f.name}")
        for sub in ("sessions", "summaries"):
            for f in (prod_cache / sub).glob(f"{sid}.*"):
                f.unlink(missing_ok=True); log(f"deleted prod {sub}/{f.name}")
    # delete any card the production dashboard already minted for these sids
    try:
        with urllib.request.urlopen("http://127.0.0.1:9876/api/data", timeout=5) as r:
            data = json.loads(r.read().decode())
        for ws in (data.get("mindmap") or {}).get("workspaces", []) or []:
            for init in ws.get("initiatives") or []:
                if set(init.get("sessions") or []) & set(sids):
                    st, j = post(9876, "/api/delete", {"id": init.get("id")})
                    log(f"deleted prod card {init.get('id')} -> {st}")
    except Exception as e:
        log(f"prod card sweep skipped ({e})")
    if ok:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"[smoke] FAILED — debris kept for inspection: {tmp}", file=sys.stderr)

print("\nSMOKE " + ("PASSED" if ok else "FAILED"))
sys.exit(0 if ok else 1)
