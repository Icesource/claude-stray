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
        if S._pending is not None:
            try:
                S._pending.register(str(S.PENDING_JSON), token, name=name, cwd=cwd,
                                  worktree_path=wt_path, worktree_name=wt_name, parent=parent or None)
            except Exception:
                pass
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

            def _capture():
                for _ in range(60):
                    time.sleep(1)
                    sid = S._subcards.find_session_by_cwd(str(S.PROJECTS_DIR), wt_path, since)
                    if sid:
                        try:
                            S._subcards.record(str(S.SUBCARDS_JSON), sid, parent, wt_name)
                        except Exception:
                            pass
                        if S._created is not None:
                            try:
                                S._created.capture_sid(str(S.CREATED_JSON), token, sid)
                            except Exception:
                                pass
                        if S._pending is not None:
                            try:
                                S._pending.capture_sid(str(S.PENDING_JSON), token, sid)
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
                        return
            threading.Thread(target=_capture, daemon=True).start()
        url = ("http://127.0.0.1:" + str(port) + "/") if port else None
        return (200, {"ok": True, "worktree_name": wt_name, "worktree": True,
                                 "parent": parent, "url": url, "token": token})


    def _subcard_close_blockers(self, sid: str, wt_path: str | None) -> dict:
        """Reasons NOT to silently destroy a sub-card's worktree. `git worktree
        remove --force` + `branch -D` are irreversible, so before doing it we check
        for live work the user almost certainly doesn't mean to nuke:
          - live:  the session is actively running, OR an embedded terminal (ttyd)
                   is still attached to it (= a claude is alive inside the worktree).
          - dirty: the worktree has uncommitted changes (would be lost forever).
        Returns {"live": bool, "dirty": bool, "reasons": [str], "hint": str};
        the caller turns a non-empty result into a 409 needs-confirm unless the
        client explicitly retries with force=True."""
        live = dirty = False
        reasons: list[str] = []
        try:
            if (S.live_snapshot().get(sid) or {}).get("status") == "running":
                live = True
                reasons.append("会话正在运行(AI 正在生成)")
        except Exception:
            pass
        try:
            ent = S._TERMINALS.get(sid)
            if ent and S._pid_alive(ent.get("pid")):
                live = True
                reasons.append("有一个嵌入终端正连着这个会话")
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
        return {"live": live, "dirty": dirty, "reasons": reasons,
                "hint": "；".join(reasons)}


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
            blk = self._subcard_close_blockers(sid, wt_path)
            if blk["live"] or blk["dirty"]:
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


    def _start_merge_job(self, job: dict):
        """Spawn the merge-agent sub-card for a queued job (on merge-<slug> off target,
        seeded with the merge task). Sets state=resolving + records merge_sid on capture."""
        sub_slug, target, main_repo = job["sub_slug"], job["target_branch"], job["main_repo"]
        merge_slug = job["merge_slug"]
        sub_branch = "worktree-" + sub_slug
        parent = self._parent_of_sid(job["sub_sid"]) or ""
        prompt = (
            "你是一个「合并 agent」。当前 worktree 在分支 " + merge_slug
            + "(基于目标分支 " + target + ")。任务:把子卡分支 " + sub_branch + " 合并进来。\n"
            "步骤:\n"
            "1) 运行: git merge " + sub_branch + "\n"
            "2) 若有冲突,逐个解决 —— 理解双方代码的语义,合出正确的结果(不是简单二选一)。\n"
            "3) 解决后: git add -A && git commit(默认合并提交信息即可)。\n"
            "4) 若某处冲突你拿不准怎么解才对,【停下来,把冲突点和你的疑问清楚地告诉用户,等用户回答】,不要瞎猜。\n"
            "5) 全部解决并 commit 后,告诉用户:「合并完成,可以落地了」。\n"
            "只做这一件事,不要改与本次合并无关的东西。")
        sub_sid = job["sub_sid"]
        code, payload = self._spawn_subcard(
            main_repo, "合并 ⊳ " + sub_slug, parent, prompt,
            wt_name=merge_slug, branch=merge_slug, base=target,
            on_capture=lambda msid: S._merge.update_job(str(S.MERGE_JOBS_JSON), sub_sid, merge_sid=msid))
        # merge_token: lets landing close the agent's terminal even if its sid
        # was never captured (capture polls ~1s; the agent may also die early).
        S._merge.update_job(str(S.MERGE_JOBS_JSON), sub_sid, state="resolving",
                            merge_token=(payload or {}).get("token"))
        return code


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
            self._start_merge_job(job)
        return self._reply(200, {"ok": True, "queued": not started, "target": target,
                                 "merge_slug": S._merge.merge_branch(sub_slug)})


    def _nudge_merge_agent(self, job: dict, text: str) -> bool:
        """Inject a catch-up instruction into the merge agent's live tmux
        holder (it runs interactive claude there). Returns False when the
        holder is gone — the caller falls back to a manual hint."""
        ent = (S._TERMINALS.get(job.get("merge_sid") or "") or {})
        holder = ent.get("name") or (
            "stray-" + job["merge_token"][:8] if job.get("merge_token") else "")
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
        """A landing that needs the merge agent to do more work first: nudge it
        automatically (DD-031 follow-up — the user shouldn't have to relay
        'git merge … 追上' by hand), then tell the UI what happened."""
        sent = self._nudge_merge_agent(job, instruction)
        return self._reply(409, {
            "error": reason, "catchup_sent": sent,
            "hint": ("已自动通知合并 agent 处理,完成后再点落地" if sent else
                     "合并 agent 会话已不在 —— 在驾驶舱打开它的终端,让它 "
                     + instruction.splitlines()[0])})

    def _handle_subcard_land(self, body: dict):
        """Fast-forward target to the conflict-free merge branch, auto-close the
        original sub-card + merge-agent, then start the next queued merge. DD-031."""
        if S._merge is None or S._worktree is None:
            return self._reply(503, {"error": "merge unavailable"})
        msid = (body.get("merge_sid") or "").strip()
        sub_sid = (body.get("sub_sid") or "").strip()
        force = bool(body.get("force"))
        job = S._merge.job_by_merge_sid(str(S.MERGE_JOBS_JSON), msid) if msid else None
        if not job and sub_sid:
            job = next((j for j in S._merge.load(str(S.MERGE_JOBS_JSON)).get("jobs", [])
                        if j.get("sub_sid") == sub_sid), None)
        if not job:
            return self._reply(404, {"error": "找不到合并任务"})
        main_repo, target, merge_slug = job["main_repo"], job["target_branch"], job["merge_slug"]
        if S._worktree._git(main_repo, "rev-parse", "--verify", "--quiet", merge_slug) is None:
            return self._reply(400, {"error": "合并分支还不存在(合并 agent 可能还没建好/没提交)"})
        # The sub-card may have NEW commits made after the agent merged — landing
        # now would silently drop them (the FF only carries the merge branch).
        # Block + auto-nudge the agent to re-merge the sub branch first.
        sub_branch = "worktree-" + (job.get("sub_slug") or "")
        if (S._worktree._git(main_repo, "rev-parse", "--verify", "--quiet", sub_branch) is not None
                and S._worktree._git(main_repo, "merge-base", "--is-ancestor",
                                     sub_branch, merge_slug) is None):
            return self._land_blocked_catchup(
                job, "子卡在合并之后又有新提交 —— 落地会丢掉它们,已先让合并 agent 重新合并",
                "子卡分支 " + sub_branch + " 在你上次合并之后有了新提交。请再次执行: "
                "git merge " + sub_branch + " ,解决冲突并 commit,完成后告诉用户可以重新落地。")
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
            out = S._worktree._git(main_repo, "merge", "--ff-only", merge_slug, timeout=40)
        else:  # ff_ref: target not checked out here → advance the ref (FF-enforced)
            out = S._worktree._git(main_repo, "push", ".", merge_slug + ":" + target, timeout=40)
        if out is None:
            # Almost always: target advanced after the agent merged → not a FF
            # anymore. Auto-nudge the agent to catch up instead of asking the
            # user to relay it by hand.
            return self._land_blocked_catchup(
                job, "目标分支已前进,这次合并不再是 fast-forward —— 已先让合并 agent 追上",
                "目标分支 " + target + " 已经前进了。请执行: git merge " + target
                + " ,解决冲突并 commit,完成后告诉用户可以重新落地。")
        self._teardown_worktree_card(job["sub_sid"], force=True)
        # The merge-agent card. Its sid is captured ASYNCHRONOUSLY (~1s poll),
        # so re-read the job — the land click can legitimately beat the capture.
        fresh = next((j for j in S._merge.load(str(S.MERGE_JOBS_JSON)).get("jobs", [])
                      if j.get("sub_sid") == job["sub_sid"]), None) or job
        if fresh.get("merge_sid"):
            self._teardown_worktree_card(fresh["merge_sid"], force=True)
        elif fresh.get("merge_token"):
            try:
                self._close_terminal(fresh["merge_token"])
            except Exception:
                pass
        # Deterministic sweep: the merge worktree/branch are named merge-<slug>
        # by construction — remove them by name so landing NEVER leaks them,
        # even when the sid was not captured (idempotent after the teardown).
        wt_dir = os.path.join(main_repo, ".claude", "worktrees", merge_slug)
        S._worktree._git(main_repo, "worktree", "remove", "--force", wt_dir, timeout=20)
        S._worktree._git(main_repo, "worktree", "prune", timeout=10)
        S._worktree._git(main_repo, "branch", "-D", merge_slug, timeout=10)
        S._merge.remove_job(str(S.MERGE_JOBS_JSON), job["sub_sid"])
        nxt = S._merge.next_queued(str(S.MERGE_JOBS_JSON))
        if nxt:
            try:
                self._start_merge_job(nxt)
            except Exception:
                pass
        threading.Thread(target=S.regenerate_html, daemon=True).start()
        return self._reply(200, {"ok": True, "target": target, "landed": merge_slug})

