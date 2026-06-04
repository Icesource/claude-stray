# DD-021: External resource collection + terminal-side resource panel

**Status**: Proposed (recorded; not yet implemented)
**Author**: Claude (with user)
**Date**: 2026-06-04
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

## Proposal

### A. Nudge Claude to print resource URLs (install-time global prompt)

When the plugin installs, add a **global instruction** (e.g. a marked block in
`~/.claude/CLAUDE.md`, or a managed system-prompt include — TBD, must not
clobber the user's file) telling Claude: *when you create an external resource
via a CLI/skill (`gh`, `aone`/a1, etc.) — an MR/PR, ISSUE, CR, deployment — print
its **full URL** in your reply; when you create/edit a doc, print its **full
path**.* This makes the transcript reliably contain the resources, so
extract/summarize can harvest them. (Marked block so uninstall can remove it.)

### B. Tighten collection — kill the commit noise

Re-rank/filter `artifacts` so the panel shows **signal**: prioritize
`mr | pr | cr | issue | deployment | doc`; **demote or drop `commit`** by default
(collapse under a "N commits" count at most, or exclude entirely). A card's
resource list should be the handful of things worth revisiting, not every hash.
(Touches `summarize` Rule 10 emphasis + `classify` artifact aggregation / the
cockpit render.)

### C. Resource panel beside the terminal

Floating tabs on the **right side of the embedded webterminal** listing this
session's collected resources:

- **URLs** (MR/ISSUE/CR/PR/deployment): click → open in browser.
- **Files/docs** (full path): click → open with the OS default handler —
  code/dirs via the user's editor (`code <path>`), `.html` etc. via browser.
  Needs a small serve endpoint (e.g. `POST /api/open {path}`) that shells
  `open`/`xdg-open`/`code` — localhost-trust, same model as `/terminal`/`/newpane`.

So while you work in the terminal, the things you produced accrue as clickable
tabs next to it — no hunting.

## Open questions / risks

- **Global-prompt mechanism**: `~/.claude/CLAUDE.md` marked block vs an
  output-style vs a plugin-provided system-prompt include — pick the least
  invasive, cleanly uninstallable one.
- **Opening files from a browser**: `/api/open` is a localhost action that runs
  a local opener — keep it 127.0.0.1-only, validate the path.
- **Capture without the prompt**: the nudge improves capture but shouldn't be
  required — extraction should still scrape any URL/path present (Rule 10 already
  forbids synthesizing URLs; keep that — only collect what's verbatim in turns).
- **Per-session scope**: resources hang off the session/card (DD-020: card =
  session), shown next to that card's terminal.

## Status

Recorded ahead of implementation. Next feature to build after the
docs/install/first-use review for colleague tryout.
