"""DD-033 end-to-end: migration → mechanical assembly → real serve, zero AI.

Drives the REAL binaries as subprocesses against a throwaway cache
(STRAY_* isolation, same contract as test_merge_e2e):

  1. seed a cache: Layer-1 summaries (hot/thin/cold/tombstoned) + a prior
     dashboard with a legacy slug-id card and an AI corpse (empty sessions)
     + a pending user task-toggle + a session tombstone
  2. python3 bin/_migrate_card_ids.py --cache <tmp>   (id unification)
  3. python3 bin/classify.py  (STRAY_CACHE_DIR=<tmp>) (mechanical assembly)
  4. boot bin/serve.py on an ephemeral port → GET /api/data

Asserts the DD-033 contract across the whole chain: canonical ids, prior
name inheritance, Layer-1 title naming, eligibility gate, tombstones,
override consumption, monotone tasks — and that a second assembly run is
stable (no churn).

Run: python3 tests/test_assemble_e2e.py   (or via bin/test / pytest)
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NOW_HOT = "2026-06-11T10:00:00Z"
COLD = "2026-05-01T10:00:00Z"


def _iso_now_minus(hours):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")


def summary_md(sid, *, la, cwd, turns=5, sg="active", title="", tasks=""):
    fm = [f"session_id: {sid}", f"cwd: {cwd}", f"last_activity_at: {la}",
          f"user_turns: {turns}", f"status_guess: {sg}"]
    if title:
        fm.append(f'title: "{title}"')
    body = ("# 目标\n推进这项工作。\n# 当前状态\n进行中。\n")
    return "---\n" + "\n".join(fm) + ("\n" + tasks if tasks else "") + \
        "\n---\n" + body


def seed_cache(cache):
    sumdir = os.path.join(cache, "summaries")
    os.makedirs(sumdir)
    hot_la = _iso_now_minus(2)
    # s-prior: hot, already carded in PRIOR under a slug id
    open(os.path.join(sumdir, "s-prior.md"), "w").write(summary_md(
        "s-prior", la=hot_la, cwd="/work/alpha",
        tasks="tasks:\n  - title: follow-up item\n    status: pending"))
    # s-new: hot + Layer-1 title → fresh card named by title
    open(os.path.join(sumdir, "s-new.md"), "w").write(summary_md(
        "s-new", la=hot_la, cwd="/work/alpha", title="新功能开发"))
    # s-thin: hot but 1 turn → gated
    open(os.path.join(sumdir, "s-thin.md"), "w").write(summary_md(
        "s-thin", la=hot_la, cwd="/work/alpha", turns=1))
    # s-cold: cold, never carded → gated
    open(os.path.join(sumdir, "s-cold.md"), "w").write(summary_md(
        "s-cold", la=COLD, cwd="/work/alpha"))
    # s-dead: hot but user-deleted (session tombstone) → gated
    open(os.path.join(sumdir, "s-dead.md"), "w").write(summary_md(
        "s-dead", la=_iso_now_minus(30), cwd="/work/alpha"))

    prior = {"schema_version": 3, "workspaces": [{
        "name": "alpha", "cwd": "/work/alpha", "last_activity_at": hot_la,
        "initiatives": [
            {"id": "legacy-slug-card", "name": "继承的老名字",
             "status": "active", "sessions": ["s-prior"],
             "last_activity_at": hot_la,
             "tasks": [{"id": "old-done", "title": "old done",
                        "status": "done",
                        "terminal_at": "2026-06-01T00:00:00Z"},
                       {"id": "new-work-item", "title": "new work item",
                        "status": "pending"}]},
            {"id": "ai-corpse", "name": "尸体卡", "status": "active",
             "sessions": [], "last_activity_at": hot_la},
        ]}]}
    json.dump(prior, open(os.path.join(cache, "dashboard.json"), "w"),
              ensure_ascii=False)
    json.dump({"version": 1, "initiatives": [
        {"id": "whatever", "deleted_at": _iso_now_minus(1),
         "sessions": ["s-dead"]}]},
        open(os.path.join(cache, "deleted_ids.json"), "w"))
    json.dump({"version": 1, "deleted_tasks": [], "hidden_artifacts": [],
               "task_toggles": [{"init_id": "legacy-slug-card",
                                 "task_title": "new work item",
                                 "status": "done"}]},
              open(os.path.join(cache, "user_overrides.json"), "w"))


def run_bin(script, env, *args):
    r = subprocess.run([sys.executable, os.path.join(REPO, "bin", script)]
                       + list(args), env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, f"{script} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def cards_by_id(cache):
    d = json.load(open(os.path.join(cache, "dashboard.json")))
    return {i["id"]: i for w in d["workspaces"] for i in w["initiatives"]}


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="stray-dd033-e2e-"))
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)
    seed_cache(cache)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("STRAY_", "CLAUDE"))}
    env.update({"STRAY_CACHE_DIR": cache, "STRAY_NO_BG": "1",
                "STRAY_PROJECTS_DIR": os.path.join(tmp, "projects")})
    os.makedirs(env["STRAY_PROJECTS_DIR"])
    proc = None
    try:
        # ---- 1. migration unifies ids + handles the corpse ----
        out = run_bin("_migrate_card_ids.py", env, "--cache", cache)
        assert "legacy-slug-card  →  card::s-prior" in out, out
        assert any(d.startswith("cache.bak-") for d in os.listdir(tmp)), \
            "backup dir missing"
        cards = cards_by_id(cache)
        assert "card::s-prior" in cards and "legacy-slug-card" not in cards
        # the corpse adopted the only uncarded eligible hot session (s-new)
        assert cards.get("card::s-new", {}).get("name") == "尸体卡", cards.keys()

        # ---- 2. mechanical assembly (real classify.py CLI) ----
        run_bin("classify.py", env)
        cards = cards_by_id(cache)
        # eligibility gate: thin / cold / tombstoned sessions are not carded
        for absent in ("card::s-thin", "card::s-cold", "card::s-dead"):
            assert absent not in cards, f"{absent} should be gated"
        prior_card = cards["card::s-prior"]
        assert prior_card["name"] == "继承的老名字"        # name inherited
        tasks = {t["id"]: t for t in prior_card["tasks"]}
        assert tasks["old-done"]["status"] == "done"       # monotone carry
        assert tasks["new-work-item"]["status"] == "done"  # toggle applied
        assert tasks["follow-up-item"]["status"] == "pending"  # summary merge
        ov = json.load(open(os.path.join(cache, "user_overrides.json")))
        assert ov["task_toggles"] == [], "canonical run must consume toggles"
        # corpse card was adopted onto s-new pre-assembly; its name survives
        assert cards["card::s-new"]["name"] == "尸体卡"
        assert all(k.startswith(("card::", "sealed::")) for k in cards)

        # ---- 3. second run is stable (no churn) ----
        before = {k: {f: v for f, v in c.items()} for k, c in cards.items()}
        run_bin("classify.py", env)
        after = cards_by_id(cache)
        assert before == after, "second assembly run must be byte-stable"

        # ---- 4. real serve renders it ----
        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()
        env["STRAY_PORTS"] = str(port)
        log = open(os.path.join(tmp, "serve.log"), "w")
        proc = subprocess.Popen(
            [sys.executable, os.path.join(REPO, "bin", "serve.py"),
             "--no-open"], env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.time() + 15
        data = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/data", timeout=2) as r:
                    data = json.loads(r.read().decode())
                break
            except Exception:
                time.sleep(0.3)
        assert data, "serve did not answer /api/data"
        names = {i.get("name") for w in (data["mindmap"]["workspaces"] or [])
                 for i in w["initiatives"]}
        assert {"继承的老名字", "尸体卡"} <= names, names
        print("  ok   e2e: migrate → assemble → stable rerun → serve api")
        return 0
    finally:
        if proc:
            proc.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
