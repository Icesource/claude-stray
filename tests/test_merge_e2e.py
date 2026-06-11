"""DD-031 slice 5: end-to-end integration tests for the sub-card merge closure.

Boots a REAL serve.py per scenario, fully isolated via the STRAY_* env
overrides (throwaway cache, fake projects dir, ephemeral port, private tmux
socket) against a REAL git repo — with a FAKE `claude` on PATH so zero AI is
involved and nothing touches the production instance:

  - sub-card spawn: the fake claude writes a session jsonl (so serve's sid
    capture finds the "session") and executes `DO:<shell>` lines found in its
    seeded prompt — the test scripts the sub-card's work through the prompt.
  - merge agent: the fake claude executes the `git merge <branch>` named in
    its prompt; on conflict it keeps BOTH sides and commits — playing the
    DD-031 merge-agent contract without AI.

Scenarios (the DD-031 verification baseline):
  1. single sub-card: merge → land → target FF'd, both worktrees + branches
     cleaned up, queue empty
  2. conflict: agent resolves + commits; landed target carries both sides
  3. serial queue: second merge stays queued until the first lands
  4. WIP gate: dirty main checkout blocks landing (409); clean → lands

Requires tmux (the sub-card substrate). Skips cleanly when absent.
Run: python3 tests/test_merge_e2e.py   (or via bin/test / pytest)
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMUX = shutil.which("tmux")

FAKE_CLAUDE = r"""#!/bin/bash
# Fake `claude` for integration tests — no AI.
#  1. registers a session jsonl so serve's sid-capture finds this "session"
#  2. runs `DO:<shell>` lines from its prompt (scripted sub-card work)
#  3. plays the merge agent: runs the `git merge <branch>` named in the
#     prompt; on conflict keeps BOTH sides, then commits.
PROMPT="${!#}"
SID="fake$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
PROJ="$STRAY_PROJECTS_DIR/e2e"
mkdir -p "$PROJ"
python3 - "$PROJ/$SID.jsonl" "$PWD" <<'PY'
import json, sys
open(sys.argv[1], "w").write(json.dumps({"cwd": sys.argv[2]}) + "\n")
PY
while IFS= read -r line; do
  case "$line" in DO:*) bash -c "${line#DO:}" ;; esac
done <<EOF_PROMPT
$PROMPT
EOF_PROMPT
BR=$(printf '%s\n' "$PROMPT" | grep -oE 'git merge [^[:space:]]+' | head -1 | awk '{print $3}')
if [ -n "$BR" ]; then
  if ! git merge --no-edit "$BR" >/dev/null 2>&1; then
    git diff --name-only --diff-filter=U | while IFS= read -r f; do
      grep -vE '^(<<<<<<<|=======|>>>>>>>)' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
      git add -- "$f"
    done
    git commit -m "merge: conflicts resolved by fake agent" >/dev/null 2>&1
  fi
fi
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd] + list(args),
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.strip()


class Harness:
    """One isolated serve + user repo per scenario."""

    def __init__(self, name):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix=f"stray-e2e-{name}-"))
        self.cache = os.path.join(self.dir, "cache")
        self.projects = os.path.join(self.dir, "projects")
        self.shim = os.path.join(self.dir, "shim")
        self.repo = os.path.join(self.dir, "repo")
        self.sock = f"st-e2e-{os.getpid()}-{name}"
        for d in (self.cache, self.projects, self.shim, self.repo):
            os.makedirs(d)
        fake = os.path.join(self.shim, "claude")
        with open(fake, "w") as f:
            f.write(FAKE_CLAUDE)
        os.chmod(fake, 0o755)
        os.symlink(TMUX, os.path.join(self.shim, "tmux"))
        # seed repo: main branch with one commit
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "e2e@test")
        _git(self.repo, "config", "user.name", "e2e")
        with open(os.path.join(self.repo, "shared.txt"), "w") as f:
            f.write("line-one\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "seed")
        self.port = _free_port()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("TMUX", "ZELLIJ", "STRAY_", "CLAUDE"))}
        env.update({
            "PATH": self.shim + ":/usr/bin:/bin",
            "HOME": self.dir,
            "STRAY_CACHE_DIR": self.cache,
            "STRAY_PROJECTS_DIR": self.projects,
            "STRAY_PORTS": str(self.port),
            "STRAY_TMUX_SOCKET": self.sock,
            "STRAY_NO_BG": "1",
        })
        self.log = open(os.path.join(self.dir, "serve.log"), "w")
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(REPO, "bin", "serve.py"), "--no-open"],
            env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self._wait(lambda: self._ping(), 15, "serve did not boot")

    # ---- http ----
    def _ping(self):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/ping", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def post(self, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    # ---- waiting ----
    def _wait(self, fn, timeout, msg):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if fn():
                return
            time.sleep(0.5)
        self.dump_log()
        raise AssertionError(f"timeout: {msg}")

    def dump_log(self):
        self.log.flush()
        try:
            with open(self.log.name) as f:
                print("---- serve.log tail ----\n" + "".join(f.readlines()[-30:]),
                      file=sys.stderr)
        except Exception:
            pass

    # ---- scenario primitives ----
    def spawn_subcard(self, name, do_cmds):
        """Fan out a scripted sub-card; returns its captured sid."""
        prompt = "task " + name + "\n" + "\n".join("DO:" + c for c in do_cmds)
        st, j = self.post("/api/new-session", {
            "cwd": self.repo, "worktree": True, "name": name,
            "parent": "parent-e2e", "prompt": prompt})
        assert st == 200 and j.get("ok"), (st, j)
        slug = j["worktree_name"]
        sid = {}

        def captured():
            try:
                reg = json.load(open(os.path.join(self.cache, "subcards.json")))
            except Exception:
                return False
            for s, e in reg.items():
                if e.get("slug") == slug:
                    sid["v"] = s
                    return True
            return False
        self._wait(captured, 30, f"sub-card {slug} sid never captured")
        return sid["v"], slug

    def jobs(self):
        try:
            return json.load(open(os.path.join(self.cache, "merge-jobs.json")))["jobs"]
        except Exception:
            return []

    def wait_merge_ready(self, slug):
        """The human gate: wait until the merge agent's branch contains the
        sub-card branch (i.e. it merged + committed)."""
        def ready():
            rc, _ = _git(self.repo, "merge-base", "--is-ancestor",
                         "worktree-" + slug, "merge-" + slug)
            return rc == 0
        self._wait(ready, 40, f"merge-{slug} never absorbed worktree-{slug}")

    def branch_exists(self, name):
        rc, _ = _git(self.repo, "rev-parse", "--verify", "--quiet", name)
        return rc == 0

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()
        subprocess.run([TMUX, "-L", self.sock, "kill-server"],
                       capture_output=True, timeout=10)
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def _scenario(name):
    def deco(fn):
        def wrapped():
            h = Harness(name)
            try:
                fn(h)
            except Exception:
                h.dump_log()
                raise
            finally:
                h.close()
        wrapped.__name__ = fn.__name__
        return wrapped
    return deco


@_scenario("single")
def test_single_subcard_merge_and_land(h):
    sid, slug = h.spawn_subcard("alpha", [
        "echo from-alpha > alpha.txt",
        "git add -A && git commit -q -m alpha-work",
    ])
    # wait for the scripted work to be committed in the sub worktree
    h._wait(lambda: h.branch_exists("worktree-" + slug) and _git(
        h.repo, "rev-list", "--count", "main..worktree-" + slug)[1] == "1",
        30, "sub-card work never committed")
    st, j = h.post("/api/subcard-merge", {"sid": sid, "target": "main"})
    assert st == 200 and j.get("ok") and not j.get("queued"), (st, j)
    h.wait_merge_ready(slug)
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 200 and j.get("ok"), (st, j)
    # target FF'd: the work is on main, in the main checkout
    assert os.path.exists(os.path.join(h.repo, "alpha.txt"))
    rc, _ = _git(h.repo, "merge-base", "--is-ancestor", "HEAD", "main")
    assert rc == 0
    # both worktrees + branches cleaned, queue empty
    h._wait(lambda: not h.branch_exists("worktree-" + slug)
            and not h.branch_exists("merge-" + slug), 20, "branches not cleaned")
    wts = os.path.join(h.repo, ".claude", "worktrees")
    assert not os.path.isdir(os.path.join(wts, slug)), "sub worktree not removed"
    assert not os.path.isdir(os.path.join(wts, "merge-" + slug)), "merge worktree not removed"
    assert h.jobs() == [], h.jobs()


@_scenario("conflict")
def test_conflict_resolved_by_agent(h):
    sid, slug = h.spawn_subcard("beta", [
        "printf 'line-one-sub\\n' > shared.txt",
        "git add -A && git commit -q -m beta-conflicting",
    ])
    h._wait(lambda: _git(h.repo, "rev-list", "--count",
                         "main..worktree-" + slug)[1] == "1",
            30, "sub-card work never committed")
    # main advances on the SAME line → guaranteed conflict
    with open(os.path.join(h.repo, "shared.txt"), "w") as f:
        f.write("line-one-main\n")
    _git(h.repo, "add", "-A")
    _git(h.repo, "commit", "-q", "-m", "main-conflicting")
    st, j = h.post("/api/subcard-merge", {"sid": sid, "target": "main"})
    assert st == 200 and j.get("ok"), (st, j)
    h.wait_merge_ready(slug)
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 200 and j.get("ok"), (st, j)
    landed = open(os.path.join(h.repo, "shared.txt")).read()
    assert "line-one-main" in landed and "line-one-sub" in landed, landed


@_scenario("serial")
def test_serial_queue(h):
    sid1, slug1 = h.spawn_subcard("gamma", [
        "echo g > gamma.txt", "git add -A && git commit -q -m gamma"])
    sid2, slug2 = h.spawn_subcard("delta", [
        "echo d > delta.txt", "git add -A && git commit -q -m delta"])
    for slug in (slug1, slug2):
        h._wait(lambda s=slug: _git(h.repo, "rev-list", "--count",
                                    "main..worktree-" + s)[1] == "1",
                30, f"{slug} work never committed")
    st, j = h.post("/api/subcard-merge", {"sid": sid1, "target": "main"})
    assert st == 200 and not j.get("queued"), (st, j)
    st, j = h.post("/api/subcard-merge", {"sid": sid2, "target": "main"})
    assert st == 200 and j.get("queued"), ("second merge must queue", st, j)
    states = {x["sub_sid"]: x["state"] for x in h.jobs()}
    assert states[sid1] == "resolving" and states[sid2] == "queued", states
    assert not h.branch_exists("merge-" + slug2), "queued merge must not start"
    h.wait_merge_ready(slug1)
    st, j = h.post("/api/subcard-land", {"sub_sid": sid1})
    assert st == 200 and j.get("ok"), (st, j)
    # landing #1 auto-starts #2, off the CURRENT main (which has gamma)
    h.wait_merge_ready(slug2)
    st, j = h.post("/api/subcard-land", {"sub_sid": sid2})
    assert st == 200 and j.get("ok"), (st, j)
    assert os.path.exists(os.path.join(h.repo, "gamma.txt"))
    assert os.path.exists(os.path.join(h.repo, "delta.txt"))
    assert h.jobs() == [], h.jobs()


@_scenario("catchup")
def test_land_blocked_until_agent_catches_up(h):
    """DD-031 follow-up: landing must not silently drop sub-card commits made
    AFTER the agent merged, nor pretend a non-FF is the user's problem — both
    block with 409 {catchup_sent} (the agent is auto-nudged when alive)."""
    sid, slug = h.spawn_subcard("zeta", [
        "echo z1 > zeta.txt", "git add -A && git commit -q -m zeta-1"])
    h._wait(lambda: _git(h.repo, "rev-list", "--count",
                         "main..worktree-" + slug)[1] == "1",
            30, "sub-card work never committed")
    st, j = h.post("/api/subcard-merge", {"sid": sid, "target": "main"})
    assert st == 200, (st, j)
    h.wait_merge_ready(slug)
    # the sub-card keeps working AFTER the agent merged
    wt = os.path.join(h.repo, ".claude", "worktrees", slug)
    with open(os.path.join(wt, "zeta.txt"), "w") as f:
        f.write("z2\n")
    _git(wt, "add", "-A"); _git(wt, "commit", "-q", "-m", "zeta-2-late")
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 409 and "catchup_sent" in j, (st, j)
    assert h.branch_exists("merge-" + slug), "blocked landing must not tear down"
    assert h.jobs(), "job must survive a blocked landing"
    # simulate the agent catching up (the fake agent's session is gone), land OK
    mwt = os.path.join(h.repo, ".claude", "worktrees", "merge-" + slug)
    _git(mwt, "merge", "--no-edit", "worktree-" + slug)
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 200 and j.get("ok"), (st, j)
    assert open(os.path.join(h.repo, "zeta.txt")).read().strip() == "z2"
    # the other catch-up shape: target advances after merge-ready → non-FF
    sid2, slug2 = h.spawn_subcard("eta", [
        "echo e1 > eta.txt", "git add -A && git commit -q -m eta-1"])
    h._wait(lambda: _git(h.repo, "rev-list", "--count",
                         "main..worktree-" + slug2)[1] == "1",
            30, "second sub-card never committed")
    st, j = h.post("/api/subcard-merge", {"sid": sid2, "target": "main"})
    assert st == 200, (st, j)
    h.wait_merge_ready(slug2)
    with open(os.path.join(h.repo, "advance.txt"), "w") as f:
        f.write("x\n")
    _git(h.repo, "add", "-A"); _git(h.repo, "commit", "-q", "-m", "target-advances")
    st, j = h.post("/api/subcard-land", {"sub_sid": sid2})
    assert st == 409 and "catchup_sent" in j, (st, j)
    mwt2 = os.path.join(h.repo, ".claude", "worktrees", "merge-" + slug2)
    _git(mwt2, "merge", "--no-edit", "main")
    st, j = h.post("/api/subcard-land", {"sub_sid": sid2})
    assert st == 200 and j.get("ok"), (st, j)


@_scenario("wip")
def test_wip_blocks_landing(h):
    sid, slug = h.spawn_subcard("epsilon", [
        "echo e > epsilon.txt", "git add -A && git commit -q -m epsilon"])
    h._wait(lambda: _git(h.repo, "rev-list", "--count",
                         "main..worktree-" + slug)[1] == "1",
            30, "sub-card work never committed")
    st, j = h.post("/api/subcard-merge", {"sid": sid, "target": "main"})
    assert st == 200, (st, j)
    h.wait_merge_ready(slug)
    # dirty the MAIN checkout → landing must refuse (never touch user WIP)
    with open(os.path.join(h.repo, "shared.txt"), "a") as f:
        f.write("uncommitted-wip\n")
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 409 and j.get("needs_confirm"), (st, j)
    # user stashes/cleans → lands fine
    _git(h.repo, "checkout", "--", ".")
    st, j = h.post("/api/subcard-land", {"sub_sid": sid})
    assert st == 200 and j.get("ok"), (st, j)
    assert os.path.exists(os.path.join(h.repo, "epsilon.txt"))


if __name__ == "__main__":
    if not TMUX:
        print("  skip (tmux not found — sub-card substrate unavailable)")
        sys.exit(0)
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        t0 = time.time()
        try:
            fn()
            print(f"  ok   {fn.__name__} ({time.time() - t0:.1f}s)")
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
