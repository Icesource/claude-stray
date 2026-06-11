"""DD-033 tests: the mechanical Layer-2 assembler (_assemble.assemble, pure).
Run: python3 tests/test_assemble.py   (or via bin/test / pytest)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _assemble  # noqa: E402

NOW = "2026-06-11T12:00:00Z"
HOT_LA = "2026-06-11T10:00:00Z"      # within 48h of NOW
COLD_LA = "2026-06-01T10:00:00Z"     # way outside 48h


def mk_summary(sid, *, la=HOT_LA, cwd="/repo/myproj", turns="5",
               sg="active", title="", tasks="", artifacts="", blockers="",
               next_step="", awaiting="", goal="修复 HSF 超时问题。细节略。",
               state="已定位根因,准备提 MR。"):
    fm = {"session_id": sid, "cwd": cwd, "last_activity_at": la,
          "user_turns": turns, "status_guess": sg}
    if title:
        fm["title"] = title
    if next_step:
        fm["next_step"] = next_step
    if awaiting:
        fm["awaiting_user"] = awaiting
    raw = f"session_id: {sid}\nlast_activity_at: {la}\n"
    raw += tasks + artifacts + blockers
    body = f"# 目标\n{goal}\n# 当前状态\n{state}\n"
    return (sid, fm, body, raw)


def run(summaries, prior=None, created=None, deleted_ids=None,
        archived_ids=None, tombs=None, hidden=None):
    return _assemble.assemble(
        summaries, prior, created or {}, deleted_ids or [],
        archived_ids or set(), tombs or {}, hidden or {}, NOW,
        hot_hours=48, min_turns=2)


def cards_of(mm):
    return [i for w in mm["workspaces"] for i in w["initiatives"]]


def test_basic_card_build():
    mm = run([mk_summary("s1", title="HSF 超时修复",
                         next_step="提 MR", awaiting="确认方案")])
    cards = cards_of(mm)
    assert len(cards) == 1, cards
    card = cards[0]
    assert card["id"] == "card::s1"
    assert card["name"] == "HSF 超时修复"
    assert card["status"] == "active"
    assert card["sessions"] == ["s1"]
    assert "修复 HSF 超时问题" in card["summary"]
    assert "已定位根因" in card["progress"]
    assert card["next_step"] == "提 MR"
    assert card["awaiting_user"] == "确认方案"
    assert card["level"] in ("chip", "card")
    assert mm["workspaces"][0]["name"] == "myproj"


def test_status_mapping():
    mm = run([mk_summary("s1", sg="done"), mk_summary("s2", sg="abandoned"),
              mk_summary("s3", sg="active")])
    by_sid = {c["sessions"][0]: c["status"] for c in cards_of(mm)}
    assert by_sid == {"s1": "done", "s2": "paused", "s3": "active"}


def test_name_precedence():
    # prior name wins over title
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "old-slug", "name": "老名字",
                              "sessions": ["s1"]}]}]}
    mm = run([mk_summary("s1", title="新起的名")], prior=prior)
    assert cards_of(mm)[0]["name"] == "老名字"
    # placeholder prior name upgrades to title (DD-030 好名字拷贝)
    prior2 = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
              "initiatives": [{"id": "subcard::s2", "name": "fix-timeout",
                               "sessions": ["s2"]}]}]}
    mm2 = run([mk_summary("s2", title="超时根因修复")], prior=prior2,
              created={"s2": {"parent": "p", "slug": "fix-timeout"}})
    assert cards_of(mm2)[0]["name"] == "超时根因修复"
    # no prior, no title → 目标 first sentence
    mm3 = run([mk_summary("s3", goal="排查 Diamond 推送丢失。然后别的。")])
    assert cards_of(mm3)[0]["name"] == "排查 Diamond 推送丢失"


def test_eligibility_gate():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "x", "name": "冷卡", "sessions": ["cold1"]}]}]}
    mm = run([
        mk_summary("cold1", la=COLD_LA),          # cold + prior → kept
        mk_summary("cold2", la=COLD_LA),          # cold + no prior → gate
        mk_summary("thin1", turns="1"),            # hot thin, no prior/created → gate
        mk_summary("thin2", turns="1"),            # hot thin but created → kept
    ], prior=prior, created={"thin2": {"parent": None, "slug": "t2"}})
    sids = {c["sessions"][0] for c in cards_of(mm)}
    assert sids == {"cold1", "thin2"}, sids


def test_session_tombstone():
    tombs = {"s1": "2026-06-11T11:00:00Z",   # after its la → dead
             "s2": "2026-06-11T09:00:00Z"}   # before its la → revived
    mm = run([mk_summary("s1"), mk_summary("s2")], tombs=tombs)
    sids = {c["sessions"][0] for c in cards_of(mm)}
    assert sids == {"s2"}, sids


def test_prior_id_tombstone_blocks_card():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "dead-slug", "name": "已删",
                              "sessions": ["s1"]}]}]}
    mm = run([mk_summary("s1")], prior=prior, deleted_ids=["dead-slug"])
    assert cards_of(mm) == []


def test_tasks_monotone_and_upgrade():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "x", "name": "n", "sessions": ["s1"],
                              "tasks": [
                {"id": "done-task", "title": "done task", "status": "done",
                 "terminal_at": "2026-06-01T00:00:00Z"},
                {"id": "open-task", "title": "open task", "status": "pending"},
             ]}]}]}
    tasks_fm = ("tasks:\n"
                "  - title: open task\n"
                "    status: done\n"
                "    evidence: 已合并\n"
                "  - title: brand new task\n"
                "    status: pending\n")
    mm = run([mk_summary("s1", tasks=tasks_fm)], prior=prior)
    tasks = {t["id"]: t for t in cards_of(mm)[0]["tasks"]}
    assert "done-task" in tasks                      # prior 不丢
    assert tasks["open-task"]["status"] == "done"    # pending → done 升级
    assert tasks["open-task"]["evidence"] == "已合并"
    assert "brand-new-task" in tasks                 # 新任务插入


def test_artifacts_filters_and_monotone():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "old-slug", "name": "n", "sessions": ["s1"],
                              "artifacts": [
                {"type": "mr", "ref_id": "100", "status": "merged"},
                {"type": "cr", "ref_id": "200", "status": "pending"},
             ]}]}]}
    arts_fm = ("artifacts:\n"
               "  - type: mr\n"
               "    ref_id: \"100\"\n"
               "    status: pending\n"          # terminal 不回退
               "  - type: commit\n"
               "    ref_id: \"abc123\"\n"        # commit 源头丢弃
               "  - type: doc\n"
               "    title: 本地文档\n"
               "    ref_id: docs/x.md\n"         # url-less doc 丢弃
               "  - type: issue\n"
               "    ref_id: \"300\"\n"
               "    status: open\n")
    hidden = {"old-slug": {"tid::cr::200"}}     # 用户隐藏按旧 id 也生效
    mm = run([mk_summary("s1", artifacts=arts_fm)], prior=prior, hidden=hidden)
    arts = cards_of(mm)[0]["artifacts"]
    by_key = {(a["type"], a.get("ref_id")): a for a in arts}
    assert by_key[("mr", "100")]["status"] == "merged"   # terminal-monotone
    assert ("commit", "abc123") not in by_key
    assert ("doc", "docs/x.md") not in by_key
    assert ("cr", "200") not in by_key                    # hidden
    assert ("issue", "300") in by_key


def test_blockers_parsed():
    blk = "blockers:\n  - 等 CodeOwner 评审\n  - \"等 CI: 红\"\n"
    mm = run([mk_summary("s1", blockers=blk)])
    assert cards_of(mm)[0]["blockers"] == ["等 CodeOwner 评审", "等 CI: 红"]


def test_worktree_groups_into_main_repo():
    mm = run([mk_summary("s1", cwd="/repo/myproj"),
              mk_summary("s2", cwd="/repo/myproj/.claude/worktrees/feat-x")])
    assert len(mm["workspaces"]) == 1
    ws = mm["workspaces"][0]
    assert ws["name"] == "myproj" and ws["cwd"] == "/repo/myproj"
    assert len(ws["initiatives"]) == 2


def test_ws_name_for_cwd():
    import classify
    f = classify._ws_name_for_cwd
    assert f("/Users/x/Code/myrepo/.claude/worktrees/authz") == "myrepo"
    assert f("/Users/x/Code/myrepo") == "myrepo"
    assert f("") == "misc"
    assert f(os.path.expanduser("~")) == "home"


def test_level_no_thread():
    big_tasks = "tasks:\n" + "".join(
        f"  - title: task number {i}\n    status: pending\n" for i in range(10))
    mm = run([mk_summary("s1", tasks=big_tasks), mk_summary("s2")])
    levels = {c["level"] for c in cards_of(mm)}
    assert "thread" not in levels
    assert levels <= {"chip", "card"}


def test_prior_sealed_carried_deleted_dropped():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [
                 {"id": "sealed::a", "name": "封存A", "sealed": True,
                  "sessions": [], "last_activity_at": COLD_LA},
                 {"id": "sealed::b", "name": "封存B", "sealed": True,
                  "sessions": [], "last_activity_at": COLD_LA},
             ]}]}
    mm = run([mk_summary("s1")], prior=prior, deleted_ids=["sealed::b"])
    ids = {c["id"] for c in cards_of(mm)}
    assert "sealed::a" in ids and "sealed::b" not in ids


def test_level_set_at_stable_when_unchanged():
    prior = {"workspaces": [{"name": "myproj", "cwd": "/repo/myproj",
             "initiatives": [{"id": "x", "name": "n", "sessions": ["s1"],
                              "level": "card", "level_set_at": "2026-06-01T00:00:00Z",
                              "artifacts": [{"type": "mr", "ref_id": "1",
                                             "status": "pending"}]}]}]}
    mm = run([mk_summary("s1")], prior=prior)
    card = cards_of(mm)[0]
    assert card["level"] == "card"        # has artifacts → card
    assert card["level_set_at"] == "2026-06-01T00:00:00Z"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback; traceback.print_exc()
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
