# DD-033: 子卡自己是自己的合并 agent —— 砍掉「合并 ⊳」卡

**Status**: Accepted & Implemented (2026-06-11)
**Author**: Claude (with user)
**Supersedes**: DD-031 的「合并 agent 子卡」机制(Q2/Q3/Q4 部分);保留其
串行队列、三道闸门、FF 落地、人类一闸。
**触发**: 真实使用一夜后的复盘。DD-031 上线当晚,连它的作者都绕过了它 ——
活着的子卡会话直接自己 merge 比 spawn 一张新卡自然得多;用户随即指出流程
冗余,并补了关键一刀:**落地后子卡不该被自动清除**。

## 为什么 DD-031 的合并 agent 是冗余的

DD-031 预设「子卡已做完、会话已歇」,所以需要新 agent 干合并脏活。但实际:
1. **活着的子卡自己就是最好的合并 agent** —— 它对自己的改动有完整上下文,
   解冲突比空降的新 agent 更准。
2. **死了的子卡可以 `claude --resume` 唤回**,连同全部对话上下文 —— 仍然
   比 fresh agent 强。
3. 合并 agent 卡带来的代价:多一类卡、多一个 worktree、多一个 `merge-<slug>`
   分支、多一次 claude 成本、UI 多一行噪声、外加一整族清理 bug(僵尸终端、
   漏删分支、job 卡死串行锁 —— 都是 2026-06-11 实测修掉的)。

## 新设计

```
点「合并」 ─▶ 把合并指令注入子卡自己的会话
              ├─ 活卡:tmux send-keys 到它的 holder
              └─ 死卡:detached resume(标准 holder 名,驾驶舱终端后续
                 attach 的是同一个 —— 单驾驶不破)
          子卡在【自己的分支】上 git merge <target>、解冲突、commit
点「落地」 ─▶ readiness = target 是子卡分支的祖先(已把目标合进来了)
              ├─ 否 → 409 + 自动再注入追赶指令(无需人工中继)
              └─ 是 → FF 目标分支到【子卡分支 tip】
          落地后【子卡保留】:卡、worktree、分支、会话全不动,
          toast 提示「可继续使用,不需要时点 × 关闭」
```

## 相对 DD-031 的语义变化

| | DD-031 | DD-033 |
|---|---|---|
| 谁解冲突 | 新 spawn 的合并 agent 卡 | 子卡自己(活卡注入/死卡 resume) |
| 合并方向 | sub → merge-<slug>(目标的副本) | target → 子卡自己的分支 |
| 落地 FF 到 | merge-<slug> tip | 子卡分支 tip |
| 落地后 | 自动关原子卡 + agent 卡 | **子卡保留**,用户手动 ×(用户决策) |
| 落地后子卡的新提交 | 危险:会被静默丢弃(需闸门拦) | 天然随落地带走(闸门作废) |
| 概念数 | 合并 agent 卡 / merge 分支 / merge_sid·token | 全部消失 |

## 保留的不变量(DD-031 的安全核,实测有价值)
- **落地只 FF**,目标分支只前进;主卡 WIP(-uno,只看已跟踪)拦截不变。
- **串行队列**:同时只处理一个合并,每次从最新目标起步。
- **落地人类一闸**:agent 说「合并完成」后仍由你点落地。
- **中途放弃 = 关卡即取消 job** 并推进队列(防串行锁卡死)。
- pre-check 三闸门(无可合并 / 未提交警告 / 目标不存在)不变。

## 实现
- `_subcard_api.py`:`_start_merge_job` 改为注入式(`_nudge_sub_session` /
  `_resume_sub_with`);land 的 readiness 改 `target is-ancestor-of sub`;
  落地不再 teardown;`/api/data` 暴露 `merge_jobs`。
- cockpit:子卡行按 job 状态渲染 合并/排队中/落地▸ 三态;落地 toast 提示
  卡保留。
- e2e 六场景重写并通过(含「自动追赶全闭环」:落地被拦 → 自动 resume 子卡
  re-merge → 重试落地成功)。
