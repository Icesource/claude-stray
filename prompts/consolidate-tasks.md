# Task: consolidate duplicate tasks on one initiative

You are given a list of **pending tasks** that have accumulated on a
single initiative card. Across many runs of the upstream summarizer,
the same conceptual task has been re-emitted under slightly different
wordings — translations (`重构授权链` ↔ "Refactor authorization
chain"), prefix tags (`[F1-body] X` vs `X`), expansion (`实现 service
doc MVP` vs `实现 service doc MVP with flag-based slicing`), or
synonym swaps. The user wants the list collapsed: one survivor per
conceptual cluster, every other variant marked `cancelled` with
evidence pointing at the survivor.

## Input (in the `<tasks>` block below)

A YAML list of task titles. Each entry is one pending task currently
on the card.

## Output

A single JSON object — no markdown fence, no prose. Schema:

```json
{
  "groups": [
    {
      "keep": "<exact title to keep, copied byte-for-byte from input>",
      "cancel": [
        { "title": "<exact title to cancel>",
          "reason": "<≤ 60 chars: short note pointing at the survivor>" }
      ]
    }
  ]
}
```

## Rules

1. **Only group titles that mean the same conceptual task.** When
   uncertain, leave them alone — false positives that erase real
   work are catastrophic. False negatives (failing to merge two
   genuinely-identical entries) are recoverable.

2. **Keep the most canonical title as the survivor.** Prefer:
   - Shorter to longer when both describe the same step.
   - Title without `[F1-body]` / `[draft]` prefix to title with it.
   - The user's apparent first language (mostly Chinese in this
     project) over a translated variant.
   - More specific over vaguer when both clearly describe the same
     work (e.g. `添加单测与 e2e` over `添加测试`); BUT prefer vaguer
     when the specific variant just adds noise (`实现 service doc
     MVP` over `实现 service doc MVP with flag-based slicing`).
   - Status: if any candidate already has a `(done)` or `(cancelled)`
     marker in its title text, keep that one — terminal state is
     load-bearing.

3. **Every `keep` and every `cancel.title` MUST be copied verbatim
   from the input.** No paraphrasing — Layer 2 dedups by exact-slug
   equality and the cancellation flows through user_overrides keyed
   by title.

4. **Singletons stay singletons.** A task with no semantic duplicate
   in the list should not appear in the output at all (no group of
   one).

5. **`reason` is for the user**, who will see this in the preview
   before confirming. Be specific: "duplicate of '<keep>'" beats
   "redundant". For language variants: "Chinese form of '<keep>'".
   For tagged variants: "untagged form of '<keep>'".

6. **Limit groups to ≤ 12.** If more clusters exist, return the 12
   most confident ones. The user can run consolidate again afterward.

7. **Empty result is fine.** If the input has no duplicates, return
   `{"groups": []}`.

## Worked example

Input:

```yaml
tasks:
  - "重构授权链"
  - "推进 ServiceTestAuthorizationService 重构"
  - "Refactor authorization chain"
  - "实现 service doc MVP"
  - "实现 service doc 命令 MVP"
  - "实现 service doc MVP with flag-based slicing"
  - "添加测试"
  - "OpenAPI 接口设计"
```

Output:

```json
{
  "groups": [
    {
      "keep": "重构授权链",
      "cancel": [
        {"title": "推进 ServiceTestAuthorizationService 重构",
         "reason": "specific phrasing of '重构授权链'"},
        {"title": "Refactor authorization chain",
         "reason": "English translation of '重构授权链'"}
      ]
    },
    {
      "keep": "实现 service doc MVP",
      "cancel": [
        {"title": "实现 service doc 命令 MVP",
         "reason": "same step worded with '命令'"},
        {"title": "实现 service doc MVP with flag-based slicing",
         "reason": "implementation detail tacked onto '实现 service doc MVP'"}
      ]
    }
  ]
}
```

`添加测试` and `OpenAPI 接口设计` are not in any group — they're not
clear duplicates of anything in this small example.

## What not to do

- Don't merge tasks just because they share a topic ("test" / "OpenAPI"
  / "rebase"). They must be the *same step*.
- Don't reword the kept title.
- Don't invent task titles that aren't in the input.
- Don't output anything except the JSON object.
