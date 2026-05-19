# claude-code-worktree docs

Internal documentation. User-facing install/usage lives in the top-level
[`README.md`](../README.md). The Chinese mirror of the user README is
[README.zh-CN.md](README.zh-CN.md).

中文版本：[zh-CN/](zh-CN/README.md)

| Doc | What it's for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the system actually works: pipeline stages, cache file shapes, concurrency, invariants |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commit/PR conventions, doc conventions, when to write a design doc |
| [RELEASE.md](RELEASE.md) | Branch model (`main` / `stable` / topic), SemVer rules, release checklist, hotfix path |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Decision trees for "card didn't update", "hook didn't fire", "AI gave wrong output" — backed by `mindmap --diagnose` |
| [ROADMAP.md](ROADMAP.md) | Planned but not yet implemented work, with design rationale |
| [design/](design/) | Design documents (DD-NNN) for non-trivial changes. See [design/README.md](design/README.md) for the template |
| [../CHANGELOG.md](../CHANGELOG.md) | Per-release user-visible summary, Keep-a-Changelog format |
| [../PLAN.md](../PLAN.md) | Historical design notes (frozen — pre-v1 thinking) |

## Reading order

- New contributor → ARCHITECTURE.md → CONTRIBUTING.md → DD-001
- Debugging a stuck card → TROUBLESHOOTING.md
- Adding a feature → ROADMAP.md → design/README.md (write a DD if non-trivial)
