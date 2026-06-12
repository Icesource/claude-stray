"""sealed 卡名字冻结:重铸必须用 PRIOR 的卡(逐字节),绝不用 Layer-1 重新生成的段标题。
真实案例:「HSF app-doc strip-group 清洗」被重铸成会话黑话「step 0 strip-group 探索及退出」。
Run: python3 tests/test_sealed_name_freeze.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import classify  # noqa: E402

RAW_FM = """\
sealed_segments:
  - seg_id: seg-1
    title: step 0 strip-group 探索及退出
    status: abandoned
    summary: 重新生成的、漂掉的总结
    sealed_at: 2026-06-06T06:36:32Z
    artifacts:
      - type: cr
        ref_id: "27665330"
        status: closed
"""

PRIOR_CARD = {
    "id": "sealed::tid::cr::27665330",
    "name": "HSF app-doc strip-group 清洗(探索后弃用)",
    "status": "archived", "level": "card", "sealed": True,
    "summary": "原始总结", "progress": "原始总结",
    "tasks": [], "sessions": [], "linked_cwds": [],
    "artifacts": [{"type": "cr", "ref_id": "27665330"}],
    "origin_session": "S1", "seg_id": "seg-1",
    "last_activity_at": "2026-06-06T06:36:32Z", "sealed_at": "2026-06-06T06:36:32Z",
}


def _mint(new_mm, prior):
    summaries = [("S1", {"cwd": "/r/dev-cli", "last_activity_at": "2026-06-06T06:36:32Z"},
                  "", RAW_FM)]
    return classify.mint_sealed_initiatives(new_mm, summaries, [], prior)


def test_dropped_sealed_resurrects_with_prior_name():
    prior = {"workspaces": [{"name": "dev-cli", "initiatives": [PRIOR_CARD]}]}
    new_mm = {"workspaces": [{"name": "dev-cli", "cwd": "/r/dev-cli", "initiatives": []}]}
    n = _mint(new_mm, prior)
    assert n == 1
    cards = [i for w in new_mm["workspaces"] for i in w["initiatives"]]
    assert len(cards) == 1
    assert cards[0]["name"] == "HSF app-doc strip-group 清洗(探索后弃用)"   # prior 名,不是段标题
    assert cards[0]["summary"] == "原始总结"


def test_existing_sealed_left_frozen():
    prior = {"workspaces": [{"name": "dev-cli", "initiatives": [PRIOR_CARD]}]}
    new_mm = {"workspaces": [{"name": "dev-cli", "cwd": "/r/dev-cli",
                              "initiatives": [dict(PRIOR_CARD)]}]}   # 已 carry-forward
    n = _mint(new_mm, prior)
    assert n == 0                                  # 不重铸、不重复
    cards = [i for w in new_mm["workspaces"] for i in w["initiatives"]]
    assert len(cards) == 1 and cards[0]["name"].startswith("HSF app-doc")


def test_brand_new_segment_uses_layer1_title():
    new_mm = {"workspaces": [{"name": "dev-cli", "cwd": "/r/dev-cli", "initiatives": []}]}
    n = _mint(new_mm, prior=None)                  # 没有 prior → 全新铸造
    assert n == 1
    cards = [i for w in new_mm["workspaces"] for i in w["initiatives"]]
    assert cards[0]["name"] == "step 0 strip-group 探索及退出"   # 新段照常用段标题


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok   {fn.__name__}")
        except Exception as e:
            failed += 1; print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
