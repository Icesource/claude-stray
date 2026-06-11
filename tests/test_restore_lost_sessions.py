"""sessions 不许被 AI 掏空:restore_lost_sessions 安全网。
真实案例:「HSF app-doc 身份规范化与去重索引」某轮 classify 后 sessions:[],
会话没被任何卡持有、没墓碑 —— 卡变成进不去的死卡(终端需要 sid)。
Run: python3 tests/test_restore_lost_sessions.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import classify  # noqa: E402


def _mm(cards):
    return {"workspaces": [{"name": "w", "initiatives": cards}]}


def test_emptied_card_gets_sessions_back():
    prior = _mm([{"id": "A", "sessions": ["s1"]}])
    new = _mm([{"id": "A", "sessions": []}])
    assert classify.restore_lost_sessions(new, prior) == 1
    assert new["workspaces"][0]["initiatives"][0]["sessions"] == ["s1"]


def test_claimed_elsewhere_not_stolen_back():
    prior = _mm([{"id": "A", "sessions": ["s1"]}])
    new = _mm([{"id": "A", "sessions": []},
               {"id": "B", "sessions": ["s1"]}])      # 会话合法迁给了 B
    assert classify.restore_lost_sessions(new, prior) == 0
    assert new["workspaces"][0]["initiatives"][0]["sessions"] == []


def test_sealed_and_nonempty_untouched():
    prior = _mm([{"id": "A", "sessions": ["s1"]}, {"id": "C", "sessions": ["s3"]}])
    new = _mm([{"id": "A", "sessions": [], "sealed": True},   # sealed 本就空
               {"id": "C", "sessions": ["s9"]}])              # 已有会话不动
    assert classify.restore_lost_sessions(new, prior) == 0
    assert new["workspaces"][0]["initiatives"][1]["sessions"] == ["s9"]


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
