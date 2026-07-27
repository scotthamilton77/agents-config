# dispatching-subagents — trigger-eval record

The description decides whether the body ever loads, so it gets tested directly. This is the
record of that test. `trigger-eval.json` beside this file is the query set; re-run it against the
deployed skill list whenever any neighbouring description changes.

## Method

Sixteen queries — eight that should route to `dispatching-subagents`, eight near-misses that
should route elsewhere. Near-misses share vocabulary with the skill (review, round, agent,
delegate, hand off) but have a better home, which is what makes them worth running; trivially
irrelevant negatives test nothing.

Each query went to a subagent judging **only** from a list of skill names and descriptions — the
deployed set plus this one — with no access to any skill body. Judges were told to decide each
query in isolation and that there was no intended balance of answers.

## Round 1 — 16/16, with one contested boundary

Every should-trigger query routed here; every near-miss routed to its correct competitor
(`review-panel`, `openrouter-claude-subagent`, `grilling`, `writing-skills`, `review-verdict`,
`handoff`, `to-spec`, `review-panel`).

Two hits came back **medium** confidence — q5 and q13, both loop-diagnosis questions — and both
named the same runner-up for the same reason. Re-running just those at 3 replicates found the
defect a single pass had hidden:

- **q5 split 2-of-3.** One judge routed it to `review-verdict`.
- Every judge, including those that routed it correctly, named the same collision:
  `review-verdict`'s *"deciding whether a round is complete and a change is terminal-clean"*
  against this skill's *"judge whether a review loop has converged."* Those are the same sentence
  to a router.

## The fix

The two skills answer different questions and the descriptions did not say so:

| Skill | Question it answers |
| --- | --- |
| `review-verdict` | Is **this round's artifact** complete and terminal-clean? |
| `dispatching-subagents` | Should the **loop** run another round, or stop? |

The description now says *"decide whether to run another round or stop"* — unambiguously
multi-round process, not artifact validation — adds a symptom clause with no vocabulary overlap
(*"rounds keep finding defects and you cannot tell whether the change or your own earlier fixes
are producing them"*), and closes with an explicit exclusion: *"Not for validating a single
round's verdict artifact."*

## Round 2 — boundary clean

Re-tested at 3 replicates, including `q10` to check the sharpened wording had not over-corrected
and started stealing `review-verdict`'s own query:

| Query | Expected | Result |
| --- | --- | --- |
| q5 — "how do i know when to call it done" | `dispatching-subagents` | **3/3** (was 2/3) |
| q13 — "is that normal or is my process broken" | `dispatching-subagents` | **3/3** |
| q10 — "the round verdict json isnt validating" | `review-verdict` | **3/3**, unmoved |

## Honest limits

- Round 1 ran at 1 replicate per query; only the contested queries got 3. A one-pass green is
  weaker evidence than it looks, which is exactly how q5 nearly shipped as a clean sweep.
- Judges were a mid-tier model reading a description list, not the routing path a live session
  uses. It tests the description against its real competitors, which is the part that fails.
- The body was not pressure-tested. Its rules come from an eight-round production run where each
  was violated at least once and the cost was recorded; that run is the baseline this skill was
  written against.
