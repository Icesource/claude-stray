# DD-021: External resource collection + terminal-side resource panel

**Status**: In progress — principle settled 2026-06-05; slice ③a (install prompt) shipped
**Author**: Claude (with user)
**Date**: 2026-06-04 (principle settled 2026-06-05)
**Predecessors**: DD-003 (card detail + artifacts), DD-015 (cockpit), DD-018
(session interaction / embedded terminal), DD-020 (per-session attention model)

## Why (the user's words)

The cockpit's differentiator is per-session AI support (DD-020). A big slice of
that is **external resources**: a coding session creates an MR/ISSUE/CR, edits
docs, etc. Hunting down those pages/files afterwards costs attention. If the
cockpit **collects the resources a session produced and surfaces them right next
to that session's terminal**, the user jumps to the MR / doc in one click — a
direct attention saving. Two concrete problems to solve:

1. **Reliable capture.** Resource URLs only get collected if they actually
   appear in the transcript. Today that's hit-or-miss.
2. **Over-collection (active pain).** The current artifact pass grabs *every
   commit*, so a card ends up with a pile of commit hashes that **drown the
   genuinely useful MR/ISSUE/doc**. Signal lost in noise.

## Collection principle (decided 2026-06-05)

The over-collection pain (commits drowning the signal) is not a display bug — it
came from having **no definition of what a resource is**. Every artifact type was
collected equally. The fix is a definition, enforced at the source.

**A resource is a durable, externally-addressable, shareable handle that the user
will want to follow up on or hand off.** Three tests, all must pass:

1. **Has an external address** — a URL, or an ID that resolves to one. You can
   open it and paste it to a colleague.
2. **Is an outcome, not a step** — it represents a deliverable / follow-up
   endpoint (review, merge, deploy, read, reply), not an intermediate action.
3. **Lives outside the session** — on a server (GitLab / Aone / GitHub / Yuque),
   not just in the local repo.

Applying the tests sorts every artifact type into **two display groups** (kept
visually distinct in the UI) plus a **drop list**:

| Group | Types | Nature | Open action |
|---|---|---|---|
| **① External resources** | `mr` `pr` `cr` `issue` `deployment` `doc` | follow-up endpoints | → browser |
| **② Code location** | `branch` `tag` `worktree` | anchors to re-enter the work | branch/tag → copy name; worktree → terminal `cd` / file manager |

**Dropped at the source (never collected):**

- **`commit`** — passes test 1 but fails test 2: a commit is an internal step,
  not something you follow up on. This was the primary noise source. Rule 10
  must stop emitting `commit` artifacts entirely.
- **Local file paths** — a path to a file you edited fails tests 1 and 3, and is
  **unreliable**: switch a branch or remove a worktree and the path is a dead
  link. Collecting "every file touched" also floods (dozens of files per change,
  almost none worth surfacing). So local file/doc *paths* are **not collected at
  all**. This kills the earlier slice ③b idea.

Two clarifications the principle turns on:

- **`doc` means external URL only.** A Yuque / Confluence / Notion / wiki link is
  collected; a repo-local `docs/xxx.md` path is **not** (it's a local file path —
  see above). So "I wrote a design doc" only becomes a resource if it lives at a
  shareable URL.
- **A worktree directory is not a "local file path."** A file path is one
  artifact among dozens and goes stale; a worktree dir is the **single physical
  anchor of a branch's work** — one per branch, relatively stable, the entry
  point to "cd back and keep going." It belongs with `branch`/`tag` in group ②
  (code location), not with dropped file paths.

## Proposal

### A. Nudge Claude to print resource URLs (install-time global prompt) — ✅ shipped (slice ③a, commit 5ca97c7)

When the plugin installs, add a **global instruction** (e.g. a marked block in
`~/.claude/CLAUDE.md`, or a managed system-prompt include — TBD, must not
clobber the user's file) telling Claude: *when you create an external resource
via a CLI/skill (`gh`, `aone`/a1, etc.) — an MR/PR, ISSUE, CR, deployment — print
its **full URL** in your reply; when you create/edit a doc, print its **full
path**.* This makes the transcript reliably contain the resources, so
extract/summarize can harvest them. (Marked block so uninstall can remove it.)

### B. Enforce the principle at the source — kill commit + file-path noise

Per the principle above:

- **`summarize` Rule 10**: stop emitting `commit` artifacts; restrict `doc` to
  external URLs only (no local `.md` paths); add a `worktree` type (the work's
  directory, when stated). Local file paths are not emitted as artifacts.
- **`classify` aggregation**: tag each artifact with its group (①/②) so the
  render can separate them; commit/file-path types simply no longer arrive.
- **`cockpit` render**: split `RES_SIGNAL` into the two groups and render them as
  two distinct sections, not one flat list.

A card's resource list is then the handful of follow-up endpoints + the work's
code location, not every hash or every file touched.

### C. Resource panel beside the terminal

Floating tabs on the **right side of the embedded webterminal**, in **two
visually-distinct groups** (per the principle):

- **① External resources** (MR/ISSUE/CR/PR/deployment/doc-URL): click → open in
  browser.
- **② Code location** (branch/tag/worktree): branch/tag → copy the name;
  worktree dir → re-enter the work (terminal `cd` or open in file manager).

Local file paths are **not** shown (dropped at the source), so the earlier
`/api/open` "open any file with the default app" endpoint (old slice ③b) is **no
longer needed** — there are no local-file tabs to open. A worktree dir is the
only path-like thing surfaced, and it's a directory anchor, not an arbitrary file.

So while you work in the terminal, the endpoints you produced + where the work
lives accrue as clickable tabs next to it — no hunting, no noise.

## Open questions / risks

- **Global-prompt mechanism** — ✅ decided: `~/.claude/CLAUDE.md` marked block,
  idempotent install + symmetric uninstall removal (slice ③a, commit 5ca97c7).
- **Opening files from a browser** — ✅ moot: local file paths are not collected,
  so no `/api/open` endpoint is built. (Worktree-dir reopen is the only path
  action; revisit a narrow opener only if that proves needed.)
- **Capture without the prompt**: the nudge improves capture but isn't required —
  extraction still scrapes any URL present. Rule 10 forbids synthesizing URLs;
  keep that (only collect what's verbatim in turns).
- **Per-session scope**: resources hang off the session/card (DD-020: card =
  session), shown next to that card's terminal.

## Slices / status

- **③a — install-time global prompt**: ✅ shipped (commit 5ca97c7). Idempotent
  marked block in `~/.claude/CLAUDE.md`; uninstall removes it.
- **① — tighten collection at source** (Rule 10: drop commit, doc=URL-only, add
  worktree; classify groups): next.
- **② — two-group resource render** (cockpit `RES_SIGNAL` split + terminal-side
  tabs in two sections): after ①.
- ~~③b — local file-path collection + `/api/open`~~: **dropped** (paths
  unreliable; not collected per principle).
