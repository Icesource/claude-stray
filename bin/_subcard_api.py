"""Sub-card + merge-closure HTTP handlers (DD-025 / DD-030 / DD-031).

This is the hottest change surface in the server — every sub-card DD lands
here — so it lives outside serve.py to shrink merge conflicts and keep the
family reviewable in one place. It is a MIXIN on serve's Handler:

    class Handler(_subcard_api.SubcardAPI, BaseHTTPRequestHandler)

Cross-cutting helpers stay in serve (self._reply / self._close_terminal /
self._card_id_for_sid / self._tombstone_card resolve on the combined class);
serve-module globals (cache paths, sibling modules, terminal registry) are
reached through `S`, set once via install(serve_module) at import time.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

S = None  # the serve module, injected via install()


def install(serve_module) -> None:
    """Bind this mixin to the running serve module (its globals ARE the app
    state: cache paths, terminal registry, sibling modules)."""
    global S
    S = serve_module


_TRUST_MARKERS = ("trust this folder", "Yes, I trust")


def repo_probably_trusted(main_repo: str, projects: dict | None = None) -> bool:
    """Will a claude spawned under main_repo hit the folder-trust dialog?
    Observed rule (2026-06-11): the dialog fires only when ~/.claude.json has NO
    `projects` entry for the cwd, any ancestor, or any prior child path — the
    hasTrustDialogAccepted flag being False does NOT prompt by itself. This is
    a heuristic over internal behavior → ADVISORY ONLY, never blocks a spawn."""
    if projects is None:
        try:
            with open(os.path.expanduser("~/.claude.json")) as f:
                projects = json.load(f).get("projects") or {}
        except Exception:
            return True   # can't tell → stay quiet
    try:
        rp = os.path.realpath(main_repo)
        for k in projects:
            kp = os.path.realpath(k)
            if rp == kp or rp.startswith(kp + os.sep) or kp.startswith(rp + os.sep):
                return True
    except Exception:
        return True
    return False


class SubcardAPI:
    def _handle_subtasks(self):
        from urllib.parse import parse_qs
        parent = (parse_qs(urlparse(self.path).query).get("parent") or [""])[0]
        if not parent or S._created is None:
            return self._reply(200, {"parent": parent, "subcards": []})
        try:
            mm = json.load(open(S.DASHBOARD_JSON))
        except Exception:
            mm = {}
        try:
            S._attach_code_location(mm)   # populate worktree/branch on the cards
            S._attach_resource_urls(mm)   # DD-026: backfill/reconstruct MR/CR urls
        except Exception:
            pass

        def _jsonl(sid):
            import glob as _g
            hits = _g.glob(str(S.PROJECTS_DIR) + f"/*/{sid}.jsonl")
            return hits[0] if hits else None
        md = S._created.subtask_metadata(parent, mm,
                                       S._created.load(str(S.CREATED_JSON)), _jsonl)
        return self._reply(200, {"parent": parent, "subcards": md})
    def _spawn_subcard(self, cwd: str, name: str, parent: str, prompt: str,
                       *, wt_name=None, branch=None, base=None, on_capture=None):
        """DD-025: fan out a sub-card — run `claude -p --worktree <slug>` DETACHED.
        DD-031: wt_name/branch/base let a MERGE-AGENT spawn on `merge-<slug>` off the
        target branch; on_capture(sid) fires when the child sid is captured (the
        merge orchestration records merge_sid through it).
        It creates .claude/worktrees/<slug>/ + branch worktree-<slug> + a resumable
        session, runs the seeded task headless, then exits. A bg thread captures the
        child's session id (its first cwd == the worktree) and records the parent
        link. The cockpit shows it nested under the parent; "open terminal" resumes
        it (sole driver — the -p process already exited). No ttyd for the child."""
        if S._worktree is None:
            return (500, {"error": "worktree helper unavailable"})
        cl0 = S._worktree.compute_code_location(cwd)
        if not cl0 and parent:
            # UI spawn may not know the parent card's cwd — derive it from the
            # parent session itself (its jsonl's first cwd), then retry.
            cwd = S._resume_cwd_for(parent) or cwd
            cl0 = S._worktree.compute_code_location(cwd)
        if not cl0:
            return (400, {"error": "not a git repo",
                                     "hint": "子卡要在一个 git 仓库目录里 spawn"})
        if not prompt:
            return (400, {"error": "empty task", "hint": "子卡需要一个任务描述"})
        claude = shutil.which("claude")
        if not claude:
            return (503, {"error": "claude not found", "hint": "claude 不在 PATH 上"})
        import uuid as _uuid
        wt_name = wt_name or S._worktree.slugify(name) or ("task-" + _uuid.uuid4().hex[:6])
        # realpath so the captured child cwd (resolved, e.g. /tmp→/private/tmp) matches
        wt_path = os.path.realpath(os.path.join(
            cl0.get("main_repo") or cwd, ".claude", "worktrees", wt_name))
        # DD-025 (interactive substrate): no `claude -p`. Create the worktree, then run
        # INTERACTIVE claude (seeded with the task) in a DETACHED tmux session — it runs
        # immediately and stays alive, so you attach to it and DRIVE it (resume model),
        # and its sid is captured promptly. The cockpit "open terminal" attaches to this
        # same tmux (sole driver → single-driver safe, never a `--resume` fork).
        tmux = shutil.which("tmux")
        if not tmux:
            return (503, {"error": "tmux not found", "hint": "子卡交互式底层需要 tmux"})
        ttyd = shutil.which("ttyd")
        token = "new-" + _uuid.uuid4().hex[:8]
        holder = "stray-" + token[:8]
        main_repo = cl0.get("main_repo") or cwd
        branch = branch or ("worktree-" + wt_name)
        base_arg = (" " + shlex.quote(base)) if base else ""   # DD-031: branch off target
        child_env = {k: v for k, v in os.environ.items() if not k.startswith("ZELLIJ")}
        inner = ("git -C " + shlex.quote(main_repo) + " worktree add -b " + shlex.quote(branch)
                 + " " + shlex.quote(wt_path) + base_arg + " 2>/dev/null || git -C " + shlex.quote(main_repo)
                 + " worktree add " + shlex.quote(wt_path) + " 2>/dev/null ; cd "
                 + shlex.quote(wt_path) + " && exec " + shlex.quote(claude)
                 + " --dangerously-skip-permissions " + shlex.quote(prompt))
        try:
            if not S._TMUX_CONF.exists():
                S._TMUX_CONF.write_text("set -g status off\nset -g mouse off\nset -g escape-time 10\n")
        except Exception:
            pass
        try:
            subprocess.run([tmux, "-L", S._TMUX_SOCKET, "-f", str(S._TMUX_CONF), "new-session", "-d",
                            "-s", holder, "bash", "-lc", inner], env=child_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception as e:
            return (500, {"error": "tmux start failed: " + str(e)})
        # a ttyd that ATTACHES to that tmux when the cockpit opens the sub-card
        port = None
        if ttyd:
            import socket as _socket
            s = _socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
            attach = (shlex.quote(tmux) + " -L " + S._TMUX_SOCKET + " -f " + shlex.quote(str(S._TMUX_CONF))
                      + " new-session -A -s " + shlex.quote(holder))
            args = [ttyd, "-p", str(port), "-i", "127.0.0.1", "-W",
                    "-t", "titleFixed=" + wt_name, "-t", "rendererType=dom",
                    "-t", "rightClickSelectsWord=true"]
            idx = S._ttyd_patched_index()
            if idx:
                args += ["-I", idx]
            args += ["bash", "-lc", attach]
            try:
                tproc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         env=child_env, start_new_session=True)
                # "name": the tmux session is named after the TOKEN — keep it on
                # the entry, because after sid re-key a "stray-<sid[:8]>" guess
                # would miss it and leak the claude inside as a zombie.
                S._TERMINALS[token] = {"port": port, "pid": tproc.pid,
                                       "holder": "tmux", "name": holder}
                S._save_terminals()
            except Exception:
                port = None
        # DD-027/030: placeholder card the INSTANT it's created (shows "准备中" nested under parent)
        if S._created is not None:
            try:
                S._created.register(str(S.CREATED_JSON), token, name=name, cwd=cwd,
                                  worktree_path=wt_path, worktree_name=wt_name,
                                  parent=parent or None, initial_task=prompt or "")
            except Exception:
                pass
        # capture the child sid → record parent link + align placeholder + re-key terminal
        if S._subcards is not None:
            since = time.time() - 2

            def _probe_trust_dialog():
                """No sid after 15s → look at what the spawned claude is showing.
                A folder-trust dialog means it will NEVER produce a session —
                annotate the placeholder so the cockpit says so, actionably."""
                try:
                    cap = subprocess.run(
                        [tmux, "-L", S._TMUX_SOCKET, "capture-pane", "-p", "-t", holder],
                        capture_output=True, text=True, timeout=5).stdout
                    if any(m in cap for m in _TRUST_MARKERS):
                        print(f"[spawn] {wt_name}: child claude is stuck at the "
                              "folder-trust dialog", file=sys.stderr)
                        if S._created is not None:
                            S._created.annotate(str(S.CREATED_JSON), token, stuck_trust=True)
                except Exception:
                    pass

            def _capture():
                for i in range(60):
                    time.sleep(1)
                    sid = S._subcards.find_session_by_cwd(str(S.PROJECTS_DIR), wt_path, since)
                    if sid:
                        if S._created is not None:
                            try:
                                S._created.capture_sid(str(S.CREATED_JSON), token, sid)
                                S._created.annotate(str(S.CREATED_JSON), token, stuck_trust=False)
                            except Exception:
                                pass
                        try:
                            ent = S._TERMINALS.pop(token, None)
                            if ent:
                                S._TERMINALS[sid] = ent
                                S._save_terminals()
                        except Exception:
                            pass
                        if on_capture:                 # DD-031: record merge_sid
                            try:
                                on_capture(sid)
                            except Exception:
                                pass
                        # 父←子信息同步不在这里 push(send-keys 会触发父卡跑一轮、
                        # 污染 jsonl/live 状态、还可能在权限对话框上误触 Enter)——
                        # 改为惰性:bin/subcard-context.py 在父卡下一轮 UserPromptSubmit
                        # 时把子卡动态作为上下文带入(hook stdout)。
                        return
                    if i == 15:
                        _probe_trust_dialog()
            threading.Thread(target=_capture, daemon=True).start()
        url = ("http://127.0.0.1:" + str(port) + "/") if port else None
        payload = {"ok": True, "worktree_name": wt_name, "worktree": True,
                   "parent": parent, "url": url, "token": token}
        if not repo_probably_trusted(main_repo):
            payload["trust_warning"] = ("该仓库似乎还没被 Claude 信任过 —— 子卡可能停在 "
                                        "folder-trust 确认;若无进展,打开它的终端按一下回车")
        return (200, payload)


    def _subcard_close_blockers(self, sid: str, wt_path: str | None,
                                main_repo: str | None = None,
                                branch: str | None = None) -> dict:
        """Reasons NOT to silently destroy a sub-card's worktree. `git worktree
        remove --force` + `branch -D` are irreversible, so before doing it we
        check for work the user almost certainly doesn't mean to nuke:
          - live:    the session is ACTIVELY RUNNING (AI generating) — closing
                     now interrupts a turn in flight.
          - dirty:   the worktree has UNCOMMITTED changes (lost on remove).
          - unmerged: the branch has COMMITS not yet reachable from any other
                     branch (lost on `branch -D`). This is the real danger the
                     user cares about — committed work that never landed back.
        A merely-attached embedded terminal is NOT a blocker: the card you're
        driving always has one, and closing just tears the terminal down (no
        data loss). (2026-06-11: idle terminal used to gate close → every card
        you used refused to close; then refined dirty→unmerged per user.)
        Returns {live, dirty, unmerged, reasons, hint}; the caller turns any
        true flag into a 409 needs-confirm unless force=True."""
        live = dirty = unmerged = False
        reasons: list[str] = []
        try:
            if (S.live_snapshot().get(sid) or {}).get("status") == "running":
                live = True
                reasons.append("会话正在运行(AI 正在生成)")
        except Exception:
            pass
        if wt_path and os.path.isdir(wt_path):
            try:
                out = S._worktree._git(wt_path, "status", "--porcelain", timeout=10)
                if (out or "").strip():
                    dirty = True
                    reasons.append("worktree 有未提交的改动")
            except Exception:
                pass
        # unmerged: branch tip not contained in any OTHER branch → its commits
        # would vanish on `branch -D`. `git branch --contains <tip>` lists every
        # branch that already has this work; if only the branch itself shows up,
        # nothing has absorbed it yet.
        if main_repo and branch:
            try:
                tip = S._worktree._git(main_repo, "rev-parse", "--verify", "--quiet",
                                       branch, timeout=10)
                if tip:
                    out = S._worktree._git(main_repo, "branch", "--format=%(refname:short)",
                                           "--contains", tip, timeout=10) or ""
                    others = [b.strip() for b in out.splitlines()
                              if b.strip() and b.strip() != branch]
                    if not others:
                        unmerged = True
                        reasons.append("分支有提交还没合并回任何其它分支(关闭会丢失)")
            except Exception:
                pass
        return {"live": live, "dirty": dirty, "unmerged": unmerged,
                "reasons": reasons, "hint": "；".join(reasons)}


    def _handle_subcard_close(self, body: dict):
        """DD-025: close a sub-card — delete its git worktree + branch, unregister it
        from subcards.json, kill its terminal, and tombstone its card. (Merge-back is
        done by the user beforehand; this is the cleanup.) Body: {sid, id?, force?}.

        Live-guard: a sub-card whose session is still running / has a live terminal /
        has uncommitted changes is NOT destroyed on the first request — we return
        409 {needs_confirm} so the cockpit can hard-confirm; only force=True proceeds
        (and only force=True passes `--force` to `git worktree remove`)."""
        sid = (body.get("sid") or "").strip()
        iid = (body.get("id") or "").strip()
        force = bool(body.get("force"))
        if not sid:
            return self._reply(400, {"error": "sid required"})
        # resolve the worktree + main repo from the child's own cwd up front, so the
        # guard can inspect it and the removal below can reuse it.
        main_repo = wt_path = wt_branch = None
        try:
            cwd = S._resume_cwd_for(sid)
            cl = S._worktree.compute_code_location(cwd) if (cwd and S._worktree) else None
            if cl and cl.get("is_worktree") and cl.get("main_repo") and cl.get("worktree"):
                main_repo, wt_path = cl["main_repo"], cl["worktree"]
                wt_branch = cl.get("branch")   # the REAL branch (merge agents are
                # on merge-<slug>, not worktree-<slug> — guessing by slug missed it)
        except Exception:
            pass
        if not force:
            blk = self._subcard_close_blockers(sid, wt_path, main_repo, wt_branch)
            if blk["live"] or blk["dirty"] or blk["unmerged"]:
                return self._reply(409, {"needs_confirm": True, **blk})
        removed_wt = None
        # 1. kill its embedded terminal FIRST — so the claude inside isn't writing
        #    into a directory we're about to pull out from under it.
        try:
            self._close_terminal(sid)
        except Exception:
            pass
        # 2. remove the worktree + branch. Plain `remove` (no --force) when not
        #    confirmed: git itself refuses on a dirty/locked worktree — a backstop
        #    behind our own guard. force=True (user accepted the loss) → --force.
        try:
            if main_repo and wt_path:
                ent = (S._created.by_sid(S._created.load(str(S.CREATED_JSON))).get(sid)
                       if S._created else None) or {}
                slug = ent.get("worktree_name") or os.path.basename(wt_path.rstrip("/"))
                rm = ["worktree", "remove"] + (["--force"] if force else []) + [wt_path]
                S._worktree._git(main_repo, *rm, timeout=20)
                S._worktree._git(main_repo, "worktree", "prune", timeout=10)
                branch = wt_branch or ("worktree-" + slug if slug else "")
                if branch:
                    S._worktree._git(main_repo, "branch", "-D", branch, timeout=10)
                removed_wt = wt_path
        except Exception:
            pass
        # 3. unregister from the sub-card registry (legacy + unified)
        try:
            if S._subcards:
                S._subcards.remove(str(S.SUBCARDS_JSON), sid)
        except Exception:
            pass
        if S._created is not None:
            try:
                S._created.remove_by_sid(str(S.CREATED_JSON), sid)
            except Exception:
                pass
        # 4. tombstone the card id + drop it from the dashboard now
        if iid:
            try:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                try:
                    doc = json.loads(S.DELETED_JSON.read_text())
                    if not isinstance(doc, dict):
                        doc = {}
                except Exception:
                    doc = {}
                inits = doc.setdefault("initiatives", [])
                if not any(x.get("id") == iid for x in inits):
                    # DD-029: store the child sid so classify session-tombstones it
                    # (a closed sub-card whose summary lingers won't resurrect under
                    # a fresh id).
                    inits.append({"id": iid, "deleted_at": now, "sessions": [sid]})
                doc["version"] = 1
                doc["updated_at"] = now
                S.DELETED_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
                self._remove_from_dashboard(iid)
            except Exception:
                pass
        # 5. DD-031「中途放弃 → 手动关」:closing either side of a merge (the
        # merge AGENT card or the original sub-card) must CANCEL its job — a
        # stuck 'resolving' job holds the serial gate and blocks every future
        # merge. Sweep the agent's leftovers, then start the next queued merge.
        if S._merge is not None:
            try:
                job = next((j for j in S._merge.load(str(S.MERGE_JOBS_JSON)).get("jobs", [])
                            if sid in (j.get("merge_sid"), j.get("sub_sid"))), None)
                if job:
                    if sid == job.get("sub_sid") and job.get("merge_slug"):
                        # sub-card closed mid-merge → its agent is now pointless
                        wt_dir = os.path.join(job["main_repo"], ".claude",
                                              "worktrees", job["merge_slug"])
                        if job.get("merge_sid"):
                            self._teardown_worktree_card(job["merge_sid"], force=True)
                        S._worktree._git(job["main_repo"], "worktree", "remove",
                                         "--force", wt_dir, timeout=20)
                        S._worktree._git(job["main_repo"], "worktree", "prune", timeout=10)
                        S._worktree._git(job["main_repo"], "branch", "-D",
                                         job["merge_slug"], timeout=10)
                    S._merge.remove_job(str(S.MERGE_JOBS_JSON), job["sub_sid"])
                    nxt = S._merge.next_queued(str(S.MERGE_JOBS_JSON))
                    if nxt:
                        self._start_merge_job(nxt)
            except Exception as e:
                print(f"[subcard-close] merge-job cancel failed: {e}", file=sys.stderr)
        return self._reply(200, {"ok": True, "removed_worktree": removed_wt})

    # ---- DD-031: sub-card merge closure -----------------------------------


    def _parent_of_sid(self, sid: str) -> str:
        for mod, path, idx in ((S._created, S.CREATED_JSON, lambda d: S._created.by_sid(d)),
                               (S._subcards, S.SUBCARDS_JSON, lambda d: d)):
            try:
                if mod:
                    ent = (idx(mod.load(str(path))) or {}).get(sid)
                    if ent and ent.get("parent"):
                        return ent["parent"]
            except Exception:
                pass
        return ""


    def _teardown_worktree_card(self, sid: str, force: bool = True):
        """Remove a worktree card's worktree+branch, unregister, tombstone. Reused by
        merge auto-close (original sub-card AND the merge-agent)."""
        try:
            self._close_terminal(sid)
        except Exception:
            pass
        cl = None
        try:
            cwd = S._resume_cwd_for(sid)
            cl = S._worktree.compute_code_location(cwd) if (cwd and S._worktree) else None
        except Exception:
            cl = None
        removed = None
        if not (cl and cl.get("is_worktree") and cl.get("main_repo") and cl.get("worktree")):
            print(f"[teardown] {sid[:12]}: no worktree location resolved ({cl})",
                  file=sys.stderr)
        else:
            main_repo, wt, branch = cl["main_repo"], cl["worktree"], cl.get("branch")
            try:
                rm = ["worktree", "remove"] + (["--force"] if force else []) + [wt]
                if S._worktree._git(main_repo, *rm, timeout=20) is None:
                    print(f"[teardown] {sid[:12]}: worktree remove failed: {wt}",
                          file=sys.stderr)
                S._worktree._git(main_repo, "worktree", "prune", timeout=10)
                if branch and S._worktree._git(main_repo, "branch", "-D", branch,
                                             timeout=10) is None:
                    print(f"[teardown] {sid[:12]}: branch -D failed: {branch}",
                          file=sys.stderr)
                removed = wt
            except Exception as e:
                print(f"[teardown] {sid[:12]}: {e}", file=sys.stderr)
        try:
            if S._subcards:
                S._subcards.remove(str(S.SUBCARDS_JSON), sid)
        except Exception:
            pass
        try:
            if S._created:
                S._created.remove_by_sid(str(S.CREATED_JSON), sid)
        except Exception:
            pass
        self._tombstone_card(self._card_id_for_sid(sid), sid)
        return removed


    def _merge_instruction(self, target: str) -> str:
        return ("请把目标分支 " + target + " 合并进当前分支:运行 git merge " + target + " 。"
                "若有冲突,理解双方代码的语义合出正确结果(不是简单二选一),"
                "然后 git add -A && git commit(默认合并提交信息即可)。"
                "若某处冲突拿不准怎么解,停下来把冲突点和疑问清楚地告诉用户,等用户回答。"
                "全部解决并 commit 后告诉用户:「合并完成,可以在驾驶舱点落地了」。"
                "只做这一件事,不要改与合并无关的东西。")

    def _nudge_sub_session(self, sid: str, text: str) -> bool:
        """Deliver an instruction to the sub-card's OWN session if it's live in
        a tmux holder (spawned cards are token-named; resume terminals use
        stray-<sid8> — try both)."""
        ent = S._TERMINALS.get(sid) or {}
        for holder in dict.fromkeys([ent.get("name"), "stray-" + sid[:8]]):
            if holder and self._send_to_holder(holder, text):
                return True
        return False

    def _resume_sub_with(self, sid: str, text: str) -> bool:
        """The sub-card session is dead → resume it DETACHED in the standard
        holder, seeded with the instruction. It carries its full conversation
        context (it wrote the code — better at resolving its own conflicts than
        any fresh agent). The cockpit terminal later attaches to this SAME
        holder, so it stays single-driver."""
        cwd = S._resume_cwd_for(sid)
        if not cwd or not os.path.isdir(cwd):
            return False
        claude, tmux = shutil.which("claude"), shutil.which("tmux")
        if not (claude and tmux):
            return False
        holder = "stray-" + sid[:8]
        inner = ("cd " + shlex.quote(cwd) + " && exec " + shlex.quote(claude)
                 + " --dangerously-skip-permissions --resume " + shlex.quote(sid)
                 + " " + shlex.quote(text))
        try:
            if not S._TMUX_CONF.exists():
                S._TMUX_CONF.write_text("set -g status off\nset -g mouse off\nset -g escape-time 10\n")
        except Exception:
            pass
        try:
            r = subprocess.run([tmux, "-L", S._TMUX_SOCKET, "-f", str(S._TMUX_CONF),
                                "new-session", "-d", "-s", holder, "bash", "-lc", inner],
                               capture_output=True, timeout=20)
            return r.returncode == 0
        except Exception:
            return False

    def _start_merge_job(self, job: dict) -> bool:
        """DD-033: the sub-card IS its own merge agent — no extra card, no
        merge-<slug> branch. Inject the merge instruction into the sub-card's
        own session (live holder → send-keys; dead → detached resume); it runs
        `git merge <target>` on ITS OWN branch, then landing fast-forwards the
        target to the sub branch tip."""
        sub_sid, target = job["sub_sid"], job["target_branch"]
        text = self._merge_instruction(target)
        ok = self._nudge_sub_session(sub_sid, text) or self._resume_sub_with(sub_sid, text)
        if ok:
            S._merge.update_job(str(S.MERGE_JOBS_JSON), sub_sid, state="resolving")
        return ok


    def _handle_subcard_merge(self, body: dict):
        """Start (or queue) a merge of a sub-card back to a target branch. DD-031."""
        if S._merge is None or S._worktree is None:
            return self._reply(503, {"error": "merge unavailable"})
        sid = (body.get("sid") or "").strip()
        target = (body.get("target") or "").strip()
        force = bool(body.get("force"))
        if not sid:
            return self._reply(400, {"error": "sid required"})
        cwd = S._resume_cwd_for(sid)
        cl = S._worktree.compute_code_location(cwd) if cwd else None
        if not cl or not cl.get("is_worktree"):
            return self._reply(400, {"error": "不是子卡 worktree", "hint": "只有 worktree 子卡能合并"})
        main_repo, sub_wt, sub_branch = cl["main_repo"], cl["worktree"], cl.get("branch") or ""
        sub_slug = (sub_branch[len("worktree-"):] if sub_branch.startswith("worktree-")
                    else os.path.basename(sub_wt.rstrip("/")))
        if not target:
            target = (S._worktree._git(main_repo, "branch", "--show-current") or "").strip() or "main"
        target_exists = S._worktree._git(main_repo, "rev-parse", "--verify", "--quiet", target) is not None
        commits_ahead = 0
        if target_exists and sub_branch:
            try:
                commits_ahead = int((S._worktree._git(
                    main_repo, "rev-list", "--count", target + ".." + sub_branch) or "0") or "0")
            except (TypeError, ValueError):
                commits_ahead = 0
        sub_dirty = bool((S._worktree._git(sub_wt, "status", "--porcelain") or "").strip())
        dec = S._merge.evaluate_precheck(commits_ahead, sub_dirty, target_exists)
        if not dec["ok"]:
            return self._reply(400, {"error": dec["reason"]})
        if dec["warn"] and not force:
            return self._reply(409, {"needs_confirm": True, "warn": dec["warn"]})
        job, started = S._merge.add_job(str(S.MERGE_JOBS_JSON), sub_sid=sid, sub_slug=sub_slug,
                                      target_branch=target, main_repo=main_repo)
        if started and job.get("state") == "queued":
            if not self._start_merge_job(job):
                # can't reach the sub session (no holder, no resumable cwd) —
                # don't leave a stuck job holding the serial gate
                S._merge.remove_job(str(S.MERGE_JOBS_JSON), sid)
                return self._reply(500, {"error": "无法唤起子卡会话来执行合并",
                                         "hint": "打开这张子卡的终端再点合并"})
        return self._reply(200, {"ok": True, "queued": not started, "target": target})


    @staticmethod
    def _send_to_holder(holder: str, text: str) -> bool:
        """Inject one message into a live tmux holder's interactive claude
        (send-keys text + Enter). False when the holder is gone/dead."""
        if not holder:
            return False
        tmux = shutil.which("tmux")
        if not tmux:
            return False
        if subprocess.run([tmux, "-L", S._TMUX_SOCKET, "has-session", "-t", holder],
                          capture_output=True, timeout=5).returncode != 0:
            return False
        try:
            subprocess.run([tmux, "-L", S._TMUX_SOCKET, "send-keys", "-t", holder,
                            "-l", text], capture_output=True, timeout=5, check=True)
            time.sleep(0.3)   # let the TUI ingest the paste before submitting
            subprocess.run([tmux, "-L", S._TMUX_SOCKET, "send-keys", "-t", holder,
                            "Enter"], capture_output=True, timeout=5, check=True)
            return True
        except Exception:
            return False

    def _land_blocked_catchup(self, job: dict, reason: str, instruction: str):
        """A landing that needs the sub-card to do more merge work first: nudge
        its own session automatically (the user shouldn't have to relay
        'git merge … 追上' by hand), then tell the UI what happened."""
        sent = (self._nudge_sub_session(job["sub_sid"], instruction)
                or self._resume_sub_with(job["sub_sid"], instruction))
        return self._reply(409, {
            "error": reason, "catchup_sent": sent,
            "hint": ("已自动让子卡处理,完成后再点落地" if sent else
                     "子卡会话无法唤起 —— 打开它的终端,让它 "
                     + instruction.splitlines()[0])})

    def _handle_subcard_land(self, body: dict):
        """DD-033: fast-forward the target branch to the SUB-CARD branch tip
        (the sub merged the target into itself beforehand), then start the next
        queued merge. The sub-card SURVIVES landing — it may keep working; the
        user closes it with × when done."""
        if S._merge is None or S._worktree is None:
            return self._reply(503, {"error": "merge unavailable"})
        msid = (body.get("merge_sid") or "").strip()
        sub_sid = (body.get("sub_sid") or "").strip()
        force = bool(body.get("force"))
        job = S._merge.job_by_merge_sid(str(S.MERGE_JOBS_JSON), msid) if msid else None
        if not job and sub_sid:
            job = next((j for j in S._merge.load(str(S.MERGE_JOBS_JSON)).get("jobs", [])
                        if j.get("sub_sid") == sub_sid), None)
        if not job and msid:
            # DD-033: no separate agent sid anymore — the sub IS the agent, so a
            # legacy client passing merge_sid may actually mean the sub itself.
            job = next((j for j in S._merge.load(str(S.MERGE_JOBS_JSON)).get("jobs", [])
                        if j.get("sub_sid") == msid), None)
        if not job:
            return self._reply(404, {"error": "找不到合并任务"})
        main_repo, target = job["main_repo"], job["target_branch"]
        sub_branch = "worktree-" + (job.get("sub_slug") or "")
        if S._worktree._git(main_repo, "rev-parse", "--verify", "--quiet", sub_branch) is None:
            return self._reply(400, {"error": "子卡分支不存在:" + sub_branch})
        # Readiness = the sub branch CONTAINS the target (it merged target into
        # itself). Covers both "hasn't merged yet" and "target advanced since" —
        # either way, nudge the sub to (re-)merge. New sub commits made after
        # the merge are NOT a problem anymore: landing FFs to the sub TIP, so
        # they ride along instead of being dropped (the DD-031 gate is obsolete).
        if S._worktree._git(main_repo, "merge-base", "--is-ancestor",
                            target, sub_branch) is None:
            return self._land_blocked_catchup(
                job, "子卡还没合并目标分支(或目标又前进了)—— 已让子卡先 merge " + target,
                self._merge_instruction(target))
        cur = (S._worktree._git(main_repo, "branch", "--show-current") or "").strip()
        checked_out_here = (cur == target)
        # -uno: only TRACKED changes count as WIP. Untracked files (e.g. the
        # .claude/worktrees/ dir the spawn itself creates) are never touched by
        # a fast-forward — and if one would collide, git refuses the merge
        # itself. Without -uno every landing is forever "blocked_wip".
        main_dirty = bool((S._worktree._git(main_repo, "status", "--porcelain", "-uno") or "").strip())
        plan = S._merge.landing_plan(checked_out_here, main_dirty)
        if plan == "blocked_wip" and not force:
            return self._reply(409, {"needs_confirm": True,
                                     "reason": "主卡有未提交改动 —— 先 commit/stash 再落地(或强制)"})
        if plan == "ff_here" or (plan == "blocked_wip" and force):
            out = S._worktree._git(main_repo, "merge", "--ff-only", sub_branch, timeout=40)
        else:  # ff_ref: target not checked out here → advance the ref (FF-enforced)
            out = S._worktree._git(main_repo, "push", ".", sub_branch + ":" + target, timeout=40)
        if out is None:
            # race: target advanced between the readiness check and the FF
            return self._land_blocked_catchup(
                job, "目标分支刚刚前进了,这次落地不再是 fast-forward —— 已让子卡追上",
                self._merge_instruction(target))
        # DD-033(用户决策): the sub-card SURVIVES landing. It may keep working
        # on the same branch; the user closes it with × when truly done. No
        # teardown, no auto-close — just clear the job and advance the queue.
        S._merge.remove_job(str(S.MERGE_JOBS_JSON), job["sub_sid"])
        nxt = S._merge.next_queued(str(S.MERGE_JOBS_JSON))
        if nxt:
            try:
                self._start_merge_job(nxt)
            except Exception:
                pass
        threading.Thread(target=S.regenerate_html, daemon=True).start()
        return self._reply(200, {"ok": True, "target": target, "landed": sub_branch,
                                 "kept": True,
                                 "hint": "子卡保留,可继续使用;不需要时点 × 关闭"})

