"""父←子惰性信息同步:subcard-context 的 digest 纯逻辑。
Run: python3 tests/test_subcard_context.py
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
_spec = importlib.util.spec_from_file_location(
    "subcard_context", os.path.join(REPO, "bin", "subcard-context.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

DOC = {
    "t1": {"sid": "c1", "parent": "P", "name": "改鉴权", "initial_task": "修超时\n其他"},
    "t2": {"sid": "c2", "parent": "P", "name": "写文档"},
    "t3": {"sid": "x1", "parent": "OTHER", "name": "别人的"},
}


def test_new_children_announced_once():
    line, told = sc.digest("P", DOC, lambda s: "running", {})
    assert "新建「改鉴权」" in line and "修超时" in line and "写文档" in line
    assert "别人的" not in line                       # 只看自己的孩子
    line2, _ = sc.digest("P", DOC, lambda s: "running", told)
    assert line2 == ""                                # 已告知 → 不重复


def test_status_transition_announced_once():
    _, told = sc.digest("P", DOC, lambda s: "running", {})
    line, told = sc.digest("P", DOC, lambda s: "needs_you" if s == "c1" else "running", told)
    assert "「改鉴权」→ 等你确认" in line and "写文档" not in line
    line2, told = sc.digest("P", DOC, lambda s: "needs_you" if s == "c1" else "running", told)
    assert line2 == ""                                # 状态没再变 → 不重复
    line3, _ = sc.digest("P", DOC, lambda s: "done_unread" if s == "c1" else "running", told)
    assert "已完成待查看" in line3                     # 新转变 → 再告知


def test_closed_child_pruned_from_state():
    _, told = sc.digest("P", DOC, lambda s: "running", {})
    assert "c1" in told
    doc2 = {k: v for k, v in DOC.items() if k != "t1"}   # c1 被关闭/合并
    line, told2 = sc.digest("P", doc2, lambda s: "running", told)
    assert "c1" not in told2 and line == ""


def test_no_children_no_output():
    line, told = sc.digest("LONELY", DOC, lambda s: "running", {})
    assert line == "" and told == {}


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
