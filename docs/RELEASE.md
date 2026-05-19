# Release & versioning

中文版：[zh-CN/RELEASE.md](zh-CN/RELEASE.md)

How we ship changes without breaking the dashboard that's actively
running on the maintainer's own machine.

## Why this exists

Up through v0.5.0 every change landed straight on `main`. That meant a
mid-iteration commit could break the dashboard the maintainer was
*currently using*. This doc fixes that by separating "what's running"
from "what's being changed."

## Branch model

```
 main      ●──●──●──●──●──●──●──●     dev trunk (always WIP)
            │            │     │
            │  topic    │  topic
            ●──●──●     │  ●──●──●
                  │     │        │
                  ▼     ▼        ▼
                merge / squash to main

 stable  ●──────────────●──────────●  what the maintainer runs
         ↑              ↑          ↑
         v0.5.0       v0.6.0    v0.7.0
         (tag)        (tag)     (tag)
```

| Branch          | Purpose                                                                     |
|-----------------|------------------------------------------------------------------------------|
| `main`          | Dev trunk. Everything in flight. May be temporarily broken between commits. |
| `stable`        | What the maintainer's local install runs. Only ever advances on a release.   |
| `topic` (`feat/...`, `fix/...`, `chore/...`, `docs/...`) | Per-feature scratch space. Branches off `main`, merges back into `main`. Delete after merge. |

**Daily use** runs `stable`:

```bash
git checkout stable
python3 bin/serve.py     # or whatever the runtime entry is
```

**Iteration** happens on `main` (and topic branches off it):

```bash
git checkout main
git pull
git switch -c feat/short-name
# ... edit, commit incrementally (see CONTRIBUTING.md), test ...
git switch main && git merge feat/short-name && git branch -d feat/short-name
git push
```

When `main` is good enough to be the new "what I run":

```bash
# from main, after the changes are tested and CHANGELOG entry is in
git checkout stable
git merge --ff-only main          # or non-ff if you want a merge commit
git tag -a vMAJOR.MINOR.PATCH -m "vMAJOR.MINOR.PATCH"
git push origin stable --tags
```

The maintainer's local checkout then runs:

```bash
git checkout stable && git pull
# restart serve.py if running
```

## Versioning — SemVer (loose pre-1.0)

`vMAJOR.MINOR.PATCH`, following [Semantic Versioning](https://semver.org)
with the standard 0.x relaxation:

| Bump   | When                                                                                              |
|--------|---------------------------------------------------------------------------------------------------|
| MAJOR  | Breaking change to a user-visible contract: cache schema removed, CLI flag renamed, hook output changed. Pre-1.0 a *minor* bump may still ship breaking changes (see "0.x rule" below). |
| MINOR  | New feature, new DD landed, new derived widget, etc.                                              |
| PATCH  | Bug fix, copy tweak, doc-only change.                                                             |

**0.x rule**: while the project is < 1.0, breaking changes are still
allowed in MINOR bumps. We're not promising compatibility yet. Bump
MINOR with a clear CHANGELOG entry; reserve MAJOR (→ 1.0) for the moment
we believe outside users could depend on us.

**Tag format**: `vMAJOR.MINOR.PATCH`, always with the `v` prefix.
Annotated tags only (`git tag -a`), not lightweight — annotated tags
carry a message and survive `git fetch --tags` cleanly.

## CHANGELOG.md

Every release adds an entry to `CHANGELOG.md` in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format.
Sections: `Added` / `Changed` / `Deprecated` / `Removed` / `Fixed`
/ `Security` — drop sections that are empty.

`[Unreleased]` is the work-in-progress section at the top. Add lines
as you go (don't wait for release day — easy to forget). At release
time, rename `[Unreleased]` to `[vX.Y.Z] — YYYY-MM-DD`, then re-add an
empty `[Unreleased]` skeleton at the top.

## Release checklist

1. **Sanity** — current `main` is green: regression tests pass
   (`python3 bin/_test_task_persistence.py` etc.), HTML re-renders
   cleanly, server starts.
2. **CHANGELOG** — `[Unreleased]` has the user-visible summary of
   what's about to be tagged. Rename it to `[vX.Y.Z] — <today>`.
3. **Commit the CHANGELOG rename** on `main`.
4. **Fast-forward merge** `main → stable` (no merge commit unless the
   history needs it).
5. **Tag** `stable` with `git tag -a vX.Y.Z -m vX.Y.Z`.
6. **Push** `git push origin stable main --tags`.
7. **Reopen** `[Unreleased]` block at the top of CHANGELOG for the
   next iteration.

## Hotfix path

If `stable` has a bug that can't wait for the next regular release:

```bash
git checkout stable
git switch -c hotfix/short-name
# fix + commit + add CHANGELOG entry under a new [vX.Y.Z+1] block
git switch stable && git merge --ff-only hotfix/short-name
git tag -a vX.Y.Z+1 -m vX.Y.Z+1
git push origin stable --tags
# back-merge into main so the fix isn't lost
git switch main && git merge stable && git push
git branch -d hotfix/short-name
```

## Aren't tags + a branch overkill for a solo tool?

Tags alone would work — `git checkout v0.5.0` puts you in detached
HEAD and you can run from there. The `stable` branch exists because
detached HEAD is a state most editors / IDEs mark as "weird," and
`git pull` on `stable` is muscle memory the maintainer already has.

If we ever want to drop `stable` later, the migration is trivial
(`git checkout` the latest tag and delete the branch). The doc here
is the source of truth, not the branch name.
