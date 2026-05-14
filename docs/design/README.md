# Design docs

中文版：[../zh-CN/design/README.md](../zh-CN/design/README.md)

Each non-trivial change gets a numbered design doc here BEFORE the code
lands. See [../CONTRIBUTING.md](../CONTRIBUTING.md#design-docs-dd-nnn)
for when to write one.

## Index

| ID | Title | Status |
|---|---|---|
| [DD-001](DD-001-two-pass-classification.md) | Two-pass classification: per-session AI summaries replace hard compression | Superseded by DD-002 |
| [DD-002](DD-002-ai-pipeline-redesign.md) | AI Pipeline redesign (three layers + hot/cold + dirty tracking + coalesce) | **Proposed** |

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
