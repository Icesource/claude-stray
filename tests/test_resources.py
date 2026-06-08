"""DD-026 test: mechanical url resolution (backfill + reconstruct).
Run: python3 tests/test_resources.py   (or via bin/test / pytest)
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import _resources  # noqa: E402


def test_build_url_index():
    text = ("see https://code.alibaba-inc.com/grp/repo/codereview/27724957 and\n"
            "bug https://project.aone.alibaba-inc.com/v2/project/2078441/bug/82622043\n"
            "req https://project.aone.alibaba-inc.com/x/req/55 noise 99999")
    idx = _resources.build_url_index(text)
    assert idx["27724957"].endswith("/codereview/27724957"), idx
    assert idx["82622043"].endswith("/bug/82622043"), idx
    assert idx["55"].endswith("/req/55"), idx
    assert "99999" not in idx          # a bare number with no url is not indexed
    assert _resources.build_url_index("") == {}


def test_build_url_index_last_mention_wins():
    text = ("https://h/a/codereview/100\n... later re-mentioned ...\n"
            "https://h/b/codereview/100")
    assert _resources.build_url_index(text)["100"] == "https://h/b/codereview/100"


def test_web_base_from_remote():
    f = _resources.web_base_from_remote
    assert f("git@code.alibaba-inc.com:middleware-container/pandora-sar.git") \
        == "https://code.alibaba-inc.com/middleware-container/pandora-sar"
    assert f("https://code.alibaba-inc.com/grp/repo.git") \
        == "https://code.alibaba-inc.com/grp/repo"
    assert f("https://user@host/grp/repo") == "https://host/grp/repo"
    assert f("") == "" and f("file:///local/thing") == ""


def test_reconstruct_url():
    r = _resources.reconstruct_url
    remote = "git@code.alibaba-inc.com:grp/repo.git"
    assert r("mr", "27724957", remote) == "https://code.alibaba-inc.com/grp/repo/codereview/27724957"
    assert r("cr", "5", remote).endswith("/codereview/5")
    assert r("issue", "5", remote) == ""        # aone issue grammar needs a project id
    assert r("mr", "not-a-number", remote) == ""
    assert r("mr", "5", "") == ""               # no remote → can't build


def test_resolve_urls_backfill_beats_reconstruct():
    arts = [{"type": "mr", "ref_id": "27724957", "title": "x"}]          # no url
    text = "ran a1 ... https://code.alibaba-inc.com/REALrepo/codereview/27724957 ..."
    remote = "git@code.alibaba-inc.com:OTHERrepo/repo.git"
    n = _resources.resolve_urls(arts, jsonl_text=text, remote=remote)
    assert n == 1
    assert arts[0]["url"] == "https://code.alibaba-inc.com/REALrepo/codereview/27724957"
    assert arts[0]["url_source"] == "harvested"   # exact transcript url, NOT the remote guess


def test_resolve_urls_reconstruct_fallback():
    arts = [{"type": "cr", "ref_id": "999"}]                              # url nowhere in text
    n = _resources.resolve_urls(arts, jsonl_text="no url here", remote="git@h:g/r.git")
    assert n == 1 and arts[0]["url"] == "https://h/g/r/codereview/999"
    assert arts[0]["url_source"] == "reconstructed"


def test_resolve_urls_leaves_existing_and_urlless():
    arts = [
        {"type": "mr", "ref_id": "1", "url": "https://keep/codereview/1"},  # already has url
        {"type": "issue", "ref_id": "2"},                                   # no grammar, no text
        {"type": "branch", "ref_id": "feat/x"},                             # not a ref number
    ]
    n = _resources.resolve_urls(arts, jsonl_text="", remote="git@h:g/r.git")
    assert n == 0
    assert arts[0]["url"] == "https://keep/codereview/1"
    assert "url" not in arts[1] and "url" not in arts[2]


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
