# Codex re-review path — design

**Bead:** `agents-config-abn9.44`
**Status:** draft

## Problem

The PR review loop cannot summon the only active review bot, and cannot recognise
its clean verdict.

Copilot's review budget is exhausted until 2026-08-01, and
`chatgpt-codex-connector[bot]` is now a trusted bot-reviewer in
`project-config.toml`. Two defects follow.

**D1 — the re-review ask reaches nobody.** `request-rereview.sh` hard-codes the
`@copilot` remove-and-re-add reviewer dance. Codex does not respond to
reviewer-request events at all. Both callers — `wait-for-pr-comments` Phase 6 and
merge-guard's one-ask retry — therefore issue an ask that silently reaches no
reviewer, consume their one-ask cap on the no-op, and hand off to a human.

**D2 — a clean pass reads as silence.** `check-merge-eligibility.sh` derives
`bot_clean_review_at_head` exclusively from submitted review objects pinned to
head by `commit_id`. A no-findings Codex pass submits no review object. The fact
evaluates false, the `bot-quiescence` merge rule stays unmet, and merge-guard
hands off to a human — on precisely the pull requests with nothing wrong with
them.

## Observed Codex behaviour

Established empirically on probe pull requests #305, #306 and #309 on
2026-07-18. Recorded here because the vendor's own documentation is incomplete on
two of these points and wrong on a third.

### Triggers

Codex reviews on pull-request open, on mark-draft-ready, on an `@codex review`
issue comment, and **on push of a new head**. A reviewer-request event is not a
trigger. The `@codex review` comment works on draft pull requests.

Codex does not deduplicate by commit: an explicit ask against an already-reviewed
unchanged head produces a fresh review. This is what makes merge-guard's one-ask
retry viable.

### Signal matrix

| Head state | Artifact emitted | Bound to head by |
| --- | --- | --- |
| Findings, any trigger | Review object (`COMMENTED`) plus inline comments | `commit_id` |
| Clean, explicit `@codex review` | `+1` reaction on the PR body, plus an issue comment stamped `**Reviewed commit:** <10-char-sha>` | SHA prefix |
| Clean, auto or push trigger | `+1` reaction on the PR body only | Tear-down/re-earn invariant |

The findings-bearing row already satisfies `bot_clean_review_at_head` through the
existing review path. Only the clean rows need new handling.

### Reaction lifecycle

The reaction is torn down and re-earned per head. On a push:

```
t+0s    push of new head
t+10s   prior head's +1 removed; eyes appears
t+70s   new +1 earned (or a review object, if findings)
```

A `+1` is therefore not a stale artifact carried forward across pushes. The
`eyes` reaction is the in-flight marker and appears within roughly 14 seconds of
a trigger; it is the Codex analogue of Copilot's `copilot_work_started` event.

### Reviewer quality

Codex is a genuine reviewer, not a rubber stamp. Against three unlabelled
defects it filed a P1 for an off-by-one slice and a P2 for a bare `except`
suppressing malformed configuration, missing only an unguarded division on empty
input. Against the *same* defects in a file whose docstring announced them as
deliberate and disposable, it correctly declined to file findings.

## Design

### Component 1 — per-bot request dispatch

`request-rereview.sh` gains `--bot-reviewers <json-array>`, matching the flag and
validation convention `poll-copilot-review.sh` already uses, and dispatches on
exact reviewer identity:

| Identity | Mechanism |
| --- | --- |
| `Copilot`, `copilot-pull-request-reviewer[bot]` | remove-and-re-add reviewer (existing behaviour) |
| `chatgpt-codex-connector[bot]` | post an `@codex review` issue comment |

Identity matching is exact and case-insensitive, never substring — consistent
with the allowlist discipline elsewhere in the merge gate.

An identity with no known mechanism warns on stderr and is skipped; it does not
abort dispatch to its siblings. The script exits 0 when at least one ask
succeeded and 1 when none did. Omitting `--bot-reviewers` preserves today's
Copilot-only behaviour, so existing callers continue to work unchanged.

The script's header comment, which currently describes it as Copilot-specific,
is rewritten to describe the dispatch table.

### Component 2 — clean-pass fact

`check-merge-eligibility.sh` extends `bot_clean_review_at_head` to a disjunction.
It is true when **either**:

- **(a)** the existing review path holds — the latest non-dismissed review at
  `HEAD_OID` from an allowlisted identity is `APPROVED` or `COMMENTED`; **or**
- **(b)** the reaction path holds — all of:
    1. a `+1` reaction exists on the pull-request body — endpoint
       `repos/{owner}/{repo}/issues/{n}/reactions` — from an identity in the
       `bot_reviewers` allowlist (exact match), **and**
    2. that reaction's `created_at` is strictly later than the head commit's
       `commit.committer.date` — endpoint
       `repos/{owner}/{repo}/commits/{HEAD_OID}` — **and**
    3. no `eyes` reaction from that identity is currently present.

Condition 3 excludes a review that is still in flight. Condition 2 is the
head-binding guard, discussed below.

Every element must be present. A missing head-commit date, an absent reaction, or
an unparseable timestamp yields false — the fact fails closed in every direction,
and a false negative merely hands off to a human.

A companion fact `bot_clean_signal_source` is emitted with value `review`,
`reaction` or `none`, so that a hand-off is diagnosable rather than mysterious.

### Component 3 — handshake accounting

The `eyes` reaction is exposed to the re-review poll path so the one-ask cap can
distinguish *the ask never reached a reviewer* from *the ask reached a reviewer
that is still working*. Conflating those is what currently burns the cap and
forces a hand-off.

## Why the reaction is accepted without a commit binding

A review object carries `commit_id` and is provable against head. A reaction
carries only `created_at`.

The alternative considered was to parse the SHA-stamped issue comment that a
clean pass emits when explicitly asked, giving a true commit binding. It was
rejected: it requires the gate to always issue an explicit ask even when a free
auto-review has already produced a verdict, and it takes a dependency on the
bot's prose — which was observed to vary between runs, one clean pass reading
"Already looking forward to the next diff." and another ":tada:". A merge gate
that breaks when a vendor rewords a sentence is a worse failure mode than the one
it fixes.

The reaction is safe to trust because it is torn down and re-earned per head
rather than accumulating, so its presence reflects a verdict on the current head.

### Known bound

The timestamp guard anchors on the head commit's **committer date**, which
records when the commit was created rather than when it was pushed. In the
agent-driven fix loop these are seconds apart, because the agent commits and
pushes in immediate succession.

They diverge when a commit is authored well before it is pushed — a cherry-pick,
or a branch that sat locally. In that window a `+1` earned by the *previous* head
can satisfy condition (b)(2) for the *current* head, admitting a clean signal for
unreviewed code.

This bound is accepted rather than closed. GitHub exposes no cheap "when did this
head become head" timestamp; the conservative substitute, `head.repo.pushed_at`,
is repository-wide and can be newer than the push in question, producing false
negatives. Those fail closed to a human, so the substitute is safe but noisy. If
the bound is ever observed to bite, that substitute is the remedy.

## Testing

`request-rereview_test.sh` extends the existing fake-`gh`-on-`PATH` shim, which
already isolates the script from the network. New cases:

- each known identity dispatches its own mechanism, asserted by recording the
  argv the fake `gh` receives;
- an unknown identity warns and is skipped without aborting its siblings;
- exit 0 when at least one ask succeeds, exit 1 when none do;
- omitting `--bot-reviewers` still performs the Copilot dance;
- `--bot-reviewers` rejects a non-array, an empty array, and non-string members,
  matching `poll-copilot-review.sh`'s validation.

`check-merge-eligibility_test.sh` covers the fact as a truth table over fixture
payloads: review path alone, reaction path alone, both, neither, a reaction
predating the head commit, a reaction from an identity outside the allowlist, an
`eyes` reaction in flight, and a missing head-commit date. Each asserts both
`bot_clean_review_at_head` and `bot_clean_signal_source`.

## Delivery

Two pull requests, because the components sit in different skills and Component 1
is independently valuable — it is the part that is currently broken outright.

1. Components 1 and 3 and their tests, in `wait-for-pr-comments` — both the
   dispatch table and the handshake marker live in that skill's helper scripts,
   and merge-guard's retry calls those helpers directly.
2. Component 2 and its tests, in `merge-guard`.

Both touch `src/**` and therefore floor to the HEAVY completion gate regardless
of diff size.

## Continuations

- `agents-config-abn9.8.51` — prgroom: `state.reviewers` is never populated
  (filed; blocks the item below)
- `agents-config-abn9.8.52` — prgroom: support Codex as a review bot (filed)

prgroom reimplements its own merge gate and never reads reactions, so it needs
this predicate independently. It must adopt the predicate in Component 2 verbatim
rather than deriving its own: `prsession/legacy_export.py` already bridges
prgroom's state into merge-guard's inventory format, and two divergent
definitions of "clean at head" in one pipeline would be pathological to debug.
