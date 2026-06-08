"""DD-026: mechanical URL resolution for collected resources.

An internal MR/CR/issue is identified by a `ref_id` whose full URL is structurally
derivable. Layer-1 (summarize) often captures the ref_id but NOT the url — the url
only appears in earlier turns or in bash *output*, both outside summarize's
last-N-turns / no-tool-result window. So a real MR shows as a dead grey chip.

We resolve it mechanically, two layers (exact wins, reconstruct is fallback):
  1. backfill    — the exact url DID appear somewhere in the session jsonl → harvest it
  2. reconstruct — build it from the session repo's git remote + the ref_id grammar
                   (this is the 内网生态 moat: Agent View can't build an Aone link
                   from repo+id; we can).

Pure + injectable so it unit-tests without serve.py / git / disk.
"""
import re

# URL shapes whose trailing numeric id IS the resource ref_id. Order = priority
# within one mention; finditer order means a LATER (more recent) mention wins.
_URL_REF_PATTERNS = [
    re.compile(r"https?://[^\s\"'<>)\]]+/codereview/(\d+)"),
    re.compile(r"https?://[^\s\"'<>)\]]+/bug/(\d+)"),
    re.compile(r"https?://[^\s\"'<>)\]]+/req/(\d+)"),
    re.compile(r"https?://[^\s\"'<>)\]]+/issues?/(\d+)"),
]

_CODEREVIEW_TYPES = {"mr", "cr", "pr"}


def build_url_index(text):
    """Scan transcript text once → {ref_id: full_url}, last mention wins. {} if empty."""
    idx = {}
    if not text:
        return idx
    for pat in _URL_REF_PATTERNS:
        for m in pat.finditer(text):
            idx[m.group(1)] = m.group(0)
    return idx


def web_base_from_remote(remote):
    """git remote url → https web base, '' if unrecognized.
        git@host:group/repo.git        → https://host/group/repo
        https://[user@]host/grp/repo.git → https://host/grp/repo
    """
    if not remote:
        return ""
    remote = remote.strip()
    m = re.match(r"git@([^:]+):(.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.match(r"https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return ""


def reconstruct_url(art_type, ref_id, remote):
    """Build a codereview URL from the repo remote + ref_id, for mr/cr/pr only.
    '' for types whose grammar needs info we lack (aone issue needs a project id).
    A reconstructed url CAN 404 for a cross-repo MR — callers prefer backfill first."""
    t = (art_type or "").strip().lower()
    ref = str(ref_id or "").strip()
    if t not in _CODEREVIEW_TYPES or not ref.isdigit():
        return ""
    base = web_base_from_remote(remote)
    return f"{base}/codereview/{ref}" if base else ""


def resolve_urls(artifacts, jsonl_text="", remote="", reconstruct=True):
    """Fill missing http urls on artifacts IN PLACE. Returns count filled.
    Tags each with url_source = 'harvested' (exact) | 'reconstructed' (from repo)."""
    if not artifacts:
        return 0
    idx = build_url_index(jsonl_text)
    n = 0
    for a in artifacts:
        if not isinstance(a, dict):
            continue
        u = (a.get("url") or "").strip()
        if u.startswith("http://") or u.startswith("https://"):
            continue
        ref = str(a.get("ref_id") or "").strip()
        if not ref:
            continue
        url, src = idx.get(ref), "harvested"
        if not url and reconstruct:
            url, src = reconstruct_url(a.get("type"), ref, remote) or None, "reconstructed"
        if url:
            a["url"] = url
            a["url_source"] = src
            n += 1
    return n
