# Design docs

中文版：[../zh-CN/design/README.md](../zh-CN/design/README.md)

Each non-trivial change gets a numbered design doc here BEFORE the code
lands. See [../CONTRIBUTING.md](../CONTRIBUTING.md#design-docs-dd-nnn)
for when to write one.

## Index

| ID | Title | Status |
|---|---|---|
| [DD-001](DD-001-two-pass-classification.md) | Two-pass classification: per-session AI summaries replace hard compression | Superseded by DD-002 |
| [DD-002](DD-002-ai-pipeline-redesign.md) | AI Pipeline redesign (three layers + hot/cold + dirty tracking + coalesce) | Implemented (P14) |
| [DD-003](DD-003-card-detail-and-artifacts.md) | Card detail modal: artifact extraction (CR/issue/branch) + blocker tracking | Implemented (P15) |
| [DD-004](DD-004-circuit-breaker-and-alarm.md) | Cost circuit breaker + runaway alarm (daily cap, rate watchdog, dashboard banner) | **Proposed** |
| [DD-005](DD-005-lifecycle.md) | Lifecycle / opt-in operation model (pause/resume, serve-only mode) | **Proposed** |
| [DD-006](DD-006-card-derived-ai-features.md) | Card-derived AI features (weekly report, next-steps, tips, wellness) | **Proposed** |
| [DD-007](DD-007-agent-auto-runner.md) | Card-driven AI agent auto-runner | **Idea-stage, needs POC** |
| [DD-008](DD-008-task-aggregation-and-archive.md) | Task aggregation, dedup by slug, cap + archive | Superseded by DD-011 |
| [DD-009](DD-009-task-ownership-and-completion.md) | Session-bound task ownership + semantic dedup + AI-assisted completion | Superseded by DD-011 |
| [DD-010](DD-010-tasks-additive-only.md) | Tasks are AI-additive-only, user-deletable-only (post-2026-05-18 data-loss incident) | Superseded by DD-011 |
| [DD-011](DD-011-task-model-final.md) | Final task model: tri-state status (pending/done/cancelled), drop archive directory, AI may cancel with evidence | Accepted |

## Template

Copy this skeleton into `DD-NNN-<slug>.md` and fill in:

```markdown
# DD-NNN: <title>

**Status**: Proposed | Accepted | Implemented | Rejected | Superseded by DD-MMM
**Author**: <name>
**Date**: YYYY-MM-DD

## Problem

What's wrong today. Ground in concrete evidence: a failing case, a
metric, a user quote. Not "wouldn't it be nice if".

## Goals / non-goals

What success looks like. Bullets. What's explicitly out of scope.

## Proposal

The actual design. Diagrams welcome (text-based ASCII boxes).
Component-by-component. Be specific about file paths, function names,
schema fields.

## Changes by component

A table or list of every file that gets touched, with one-line summary
of what changes. Makes review tractable.

## Migration

If schemas change or invariants change, how do existing installs move
from old to new.

## Cost / risk

Token cost, latency, failure modes. Honest about what could go wrong.

## Alternatives considered

What you also looked at and why you rejected each. Future-you will
thank present-you for this section.
```

## Conventions

- **Numbers are monotone.** Don't recycle slots when a DD is rejected.
- **Status moves forward.** When a DD lands, change Status to
  `Implemented` and add a `commit: <sha>` line. Don't delete the doc.
- **Rejected DDs stay.** They're the institutional memory of "why we
  didn't do X."
- **Length is a smell.** A DD that's longer than the implementation is
  usually overthinking. Aim ≤ 500 lines.
