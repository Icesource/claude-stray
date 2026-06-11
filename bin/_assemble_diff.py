#!/usr/bin/env python3
"""DD-033 acceptance diff: align OLD (AI) and NEW (mechanical) dashboards by
session and report differences per the DD-033 equivalence definition.

Usage: python3 bin/_assemble_diff.py cache/dashboard.json cache/dashboard.mech.json
"""
import json
import sys


def index(mm):
    live, sealed = {}, {}
    for w in mm.get("workspaces") or []:
        for i in (w.get("initiatives") or []):
            if i.get("sealed"):
                sealed[i.get("id")] = (w.get("name"), i)
                continue
            for s in (i.get("sessions") or []):
                live[s] = (w.get("name"), i)
    return live, sealed


def art_keys(init):
    sys.path.insert(0, "bin")
    import classify
    return {classify.artifact_key(a) for a in (init.get("artifacts") or [])} - {None}


def task_ids(init):
    return {t.get("id") for t in (init.get("tasks") or []) if t.get("id")}


def main():
    old = json.load(open(sys.argv[1]))
    new = json.load(open(sys.argv[2]))
    o_live, o_sealed = index(old)
    n_live, n_sealed = index(new)

    print(f"OLD: {len(o_live)} live sids, {len(o_sealed)} sealed")
    print(f"NEW: {len(n_live)} live sids, {len(n_sealed)} sealed")

    issues = 0
    for sid in sorted(set(o_live) - set(n_live)):
        ws, i = o_live[sid]
        print(f"  MISSING in new: sid={sid[:8]} [{ws}] {i.get('id')} — {i.get('name')}")
        issues += 1
    for sid in sorted(set(n_live) - set(o_live)):
        ws, i = n_live[sid]
        print(f"  EXTRA in new:   sid={sid[:8]} [{ws}] {i.get('id')} — {i.get('name')}")
        issues += 1
    for k in sorted(set(o_sealed) - set(n_sealed)):
        print(f"  MISSING sealed: {k} — {o_sealed[k][1].get('name')}")
        issues += 1

    for sid in sorted(set(o_live) & set(n_live)):
        o_ws, o_i = o_live[sid]
        n_ws, n_i = n_live[sid]
        tag = f"sid={sid[:8]} {o_i.get('name')!r}"
        if o_i.get("name") != n_i.get("name"):
            print(f"  NAME:   {tag} → {n_i.get('name')!r}")
            issues += 1
        if o_ws != n_ws:
            print(f"  WSPACE: {tag} [{o_ws}] → [{n_ws}]")
            issues += 1
        if o_i.get("status") != n_i.get("status"):
            print(f"  STATUS: {tag} {o_i.get('status')} → {n_i.get('status')}")
            issues += 1
        lost_t = task_ids(o_i) - task_ids(n_i)
        if lost_t:
            print(f"  TASKS LOST: {tag}: {sorted(lost_t)}")
            issues += 1
        lost_a = art_keys(o_i) - art_keys(n_i)
        if lost_a:
            print(f"  ARTIFACTS LOST: {tag}: {sorted(lost_a)}")
            issues += 1
        if (o_i.get("level") == "thread") != False and n_i.get("level") == "thread":
            print(f"  THREAD survived: {tag}")
            issues += 1

    print(f"\n{'EQUIVALENT (per DD-033 definition)' if not issues else f'{issues} difference(s)'}")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
