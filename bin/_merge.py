"""DD-031: sub-card merge-closure orchestration (pure + path-injectable).

The merge of a sub-card back to trunk is itself done by a spawned MERGE-AGENT
sub-card (own worktree on `merge-<slug>`, runs `git merge` + resolves conflicts,
asks the user when stuck). stray only orchestrates: a SERIAL queue (one merge at a
time, each off the CURRENT target so there's never a stale base), and the final
fast-forward LAND step. This module is the pure brain of that — git I/O lives in
serve; here are the queue, the pre-check decision, the branch naming, and the
landing plan. Mirrors _subcards/_created: fcntl-locked, atomic, unit-testable.

cache/merge-jobs.json: {"jobs": [job, ...]}
  job = {sub_sid, sub_slug, target_branch, merge_slug, merge_token, merge_sid,
         main_repo, wt_path, state, created_at}
  state: queued → resolving → awaiting_land → (landed=removed) / failed
Only ONE job is non-queued at a time (the serial invariant).
"""
import contextlib
import json
import os
import time

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

ACTIVE_STATES = ("resolving", "awaiting_land")


def merge_branch(sub_slug):
    """The merge-agent's branch/worktree name for a sub-card slug."""
    return "merge-" + (sub_slug or "subcard")


def evaluate_precheck(commits_ahead, sub_dirty, target_exists):
    """Decide whether a sub-card can be merged. Pure. Returns
    {ok, reason, warn}: ok=False blocks (reason); warn is a non-blocking heads-up
    (uncommitted work won't be in the merge — proceed-anyway is the caller's call)."""
    if not target_exists:
        return {"ok": False, "reason": "目标分支不存在", "warn": ""}
    if (commits_ahead or 0) <= 0:
        return {"ok": False, "reason": "无可合并(子卡分支相对目标没有新提交)", "warn": ""}
    warn = ""
    if sub_dirty:
        warn = "子卡有未提交改动,不会被合并 —— 先去子卡里 commit,或就合已提交的部分"
    return {"ok": True, "reason": "", "warn": warn}


def landing_plan(target_checked_out_here, main_repo_dirty):
    """How to fast-forward the target branch to the conflict-free merge branch.
    Pure decision; caller runs the git. The merge branch is ALWAYS a FF of target
    (the agent built it off target), so this never conflicts — it only has to land
    the ref safely w.r.t. the parent's live working tree.
      - 'ff_here'    : target is checked out in main_repo & clean → `merge --ff-only`.
      - 'blocked_wip': target checked out here but main_repo has WIP → refuse, the
                       user must commit/stash first (we never touch their WIP).
      - 'ff_ref'     : target not checked out here → advance the ref via `push .`
                       (FF-enforced), no working tree touched."""
    if target_checked_out_here:
        return "blocked_wip" if main_repo_dirty else "ff_here"
    return "ff_ref"


# ---------- persistent serial queue ----------------------------------------

@contextlib.contextmanager
def _locked(path):
    if fcntl is None:
        yield
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fh = open(path + ".lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) and isinstance(d.get("jobs"), list) else {"jobs": []}
    except Exception:
        return {"jobs": []}


def _dump(path, doc):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def has_active(path):
    """Is a merge already running/awaiting-land? (the serial gate)."""
    return any(j.get("state") in ACTIVE_STATES for j in load(path).get("jobs", []))


def add_job(path, *, sub_sid, sub_slug, target_branch, main_repo, _now=None):
    """Enqueue a merge. Idempotent per sub_sid (re-clicking focuses the existing
    job, doesn't duplicate). Returns (job, started): started=True if it may begin
    now (no other active job), else it's queued behind."""
    with _locked(path):
        doc = load(path)
        existing = next((j for j in doc["jobs"] if j.get("sub_sid") == sub_sid), None)
        if existing:
            return existing, existing.get("state") in ACTIVE_STATES
        active = any(j.get("state") in ACTIVE_STATES for j in doc["jobs"])
        job = {
            "sub_sid": sub_sid, "sub_slug": sub_slug, "target_branch": target_branch,
            "merge_slug": merge_branch(sub_slug), "merge_token": None, "merge_sid": None,
            "main_repo": main_repo, "wt_path": None,
            "state": "queued", "created_at": _now if _now is not None else time.time(),
        }
        doc["jobs"].append(job)
        _dump(path, doc)
        return job, not active


def update_job(path, sub_sid, **fields):
    with _locked(path):
        doc = load(path)
        job = next((j for j in doc["jobs"] if j.get("sub_sid") == sub_sid), None)
        if not job:
            return None
        job.update(fields)
        _dump(path, doc)
        return dict(job)


def remove_job(path, sub_sid):
    with _locked(path):
        doc = load(path)
        n = len(doc["jobs"])
        doc["jobs"] = [j for j in doc["jobs"] if j.get("sub_sid") != sub_sid]
        if len(doc["jobs"]) != n:
            _dump(path, doc)
            return True
        return False


def job_by_merge_sid(path, merge_sid):
    return next((j for j in load(path).get("jobs", []) if j.get("merge_sid") == merge_sid), None)


def next_queued(path):
    """The front queued job (to start once the active one lands). None if a job is
    still active (serial) or the queue is empty."""
    doc = load(path)
    if any(j.get("state") in ACTIVE_STATES for j in doc["jobs"]):
        return None
    return next((j for j in doc["jobs"] if j.get("state") == "queued"), None)
