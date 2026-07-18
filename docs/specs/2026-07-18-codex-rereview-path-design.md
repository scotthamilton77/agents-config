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
them. A second face of the same defect: on the explicit-ask path a clean pass
*does* post an issue comment, and the untriaged-feedback blocker treats that
comment as unhandled reviewer feedback, so the clean-pass announcement itself
blocks the merge it announces.

## Scope of the guarantee

This predicate serves a cooperative loop: the pushes it examines come from this
repo's own agents and CI, not from untrusted contributors. It defends against
**staleness** — reading a verdict earned by an earlier head as covering the
current one — not against an adversary forging git metadata. Client-written
committer dates are acceptable inputs for the common case, where an agent
commits and pushes within seconds; the two ways a committer date diverges from
push receipt are handled separately — force-push to an older existing commit by
a server-side timeline signal in Component 2, and an ordinary push of a
previously-prepared commit in the Accepted residual section. False negatives
hand off to a human and are always acceptable.

## Observed Codex behaviour

Established empirically on probe pull requests #305, #306 and #309 on
2026-07-18. Recorded here because Codex's in-product help text ("If Codex has
suggestions, it will comment; otherwise it will react with 👍") is incomplete:
it omits the `eyes` handshake and the SHA-stamped comment on explicit asks.

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
| Clean, auto or push trigger | `+1` reaction on the PR body only | Reaction lifecycle plus the recency guard below |

The findings-bearing row already satisfies `bot_clean_review_at_head` through the
existing review path. Only the clean rows need new handling — and the reaction is
the **only artifact present on every clean pass**. The SHA-stamped comment exists
solely on explicit asks, so a design that treated it as the primary signal would
have to post a redundant `@codex review` on every PR whose free auto-review
already came back clean.

### Reaction lifecycle

The reaction is torn down and re-earned per head. On a push:

```
t+0s    push of new head
t+10s   prior head's +1 removed; eyes appears
t+70s   new +1 earned (or a review object, if findings)
```

The `eyes` reaction is the in-flight marker and appears within roughly 14 seconds
of a trigger; it is the Codex analogue of Copilot's `copilot_work_started` event.
The tear-down is an action Codex performs, not a platform invariant — if Codex is
down or rate-limited after a push, a stale `+1` persists. The recency guard below
is therefore the load-bearing check, with the lifecycle as corroboration.

### Reviewer quality, and a limitation

Codex is a genuine reviewer. Against three unlabelled defects it filed a P1 for
an off-by-one slice and a P2 for a bare `except` suppressing malformed
configuration, missing only an unguarded division on empty input.

Against the *same* defects in a file whose docstring declared them deliberate
and disposable, it filed nothing. For an unattended gate this is a limitation to
record, not a virtue: prose in the diff can suppress findings. It is inherent to
using a language-model reviewer at all and is accepted under the bot-quiescence
policy's existing opt-in; it is one of the reasons the policy remains a
deliberate, named choice rather than a default.

## Design

### Component 1 — per-bot request dispatch

`request-rereview.sh` gains `--bot-reviewers <json-array>`, matching the flag and
validation convention `poll-copilot-review.sh` already uses (non-empty JSON array
of strings, rejected otherwise), and dispatches on reviewer identity:

| Identity | Mechanism |
| --- | --- |
| `Copilot`, `copilot-pull-request-reviewer[bot]` | remove-and-re-add reviewer (existing behaviour) |
| `chatgpt-codex-connector[bot]` | post an `@codex review` issue comment |

An identity with no known mechanism warns on stderr and is skipped; it does not
abort dispatch to its siblings. Exit codes: 0 when at least one ask succeeded,
1 when none did, 2 reserved for usage errors as today. Omitting
`--bot-reviewers` preserves today's Copilot-only behaviour — a standalone
compatibility default only, not how the loop runs. The script's header comment,
which currently describes it as Copilot-specific, is rewritten to describe the
dispatch table.

**Both existing callers are updated to pass the flag** — the helper's new
capability is inert until they do, which would leave D1 unfixed on any repo
whose active reviewer is Codex. `wait-for-pr-comments` Phase 6 step 1 passes
`--bot-reviewers "$(jq -c '.bot_reviewers' <<<"$POLICY_JSON")"` (the policy it
already resolves in Phase 1), and merge-guard's one-ask retry instruction is
rewritten to name the same flag with its own resolved policy's allowlist. The
Delivery section maps each caller edit to its PR.

Identity matching follows each script's existing convention:
`poll-copilot-review.sh` compares case-insensitively and Component 1 mirrors it;
`check-merge-eligibility.sh`'s existing review path compares exactly, and the
reaction path below does the same. The allowlist in `project-config.toml` holds
the identities verbatim, so both conventions match it.

### Component 2 — clean-pass fact

`check-merge-eligibility.sh` extends `bot_clean_review_at_head` to a disjunction.
It is true when **either**:

- **(a)** the existing review path holds — the latest non-dismissed review at
  `HEAD_OID` from an allowlisted identity is `APPROVED` or `COMMENTED`; **or**
- **(b)** the reaction path holds — all of:
    1. a reaction with `content == "+1"` exists on the pull-request body —
       endpoint `repos/{owner}/{repo}/issues/{n}/reactions`, fetched with
       `--paginate` — whose `user.login` is in the `bot_reviewers` allowlist
       (exact match) and whose `user.type` is `"Bot"`; **and**
    2. no reaction with `content == "eyes"` from **any** allowlisted identity is
       present in that same fetch (a review is in flight; wait); **and**
    3. that `+1`'s `created_at`, parsed to epoch seconds, is strictly greater
       than `last_head_change`, where
       `last_head_change = max(` the head commit's `commit.committer.date` from
       `repos/{owner}/{repo}/commits/{HEAD_OID}`, `,` the `created_at` of the
       latest `head_ref_force_pushed` event from
       `repos/{owner}/{repo}/issues/{n}/timeline`, fetched with `--paginate`
       and aggregated across pages `)` — the timeline term is omitted when no
       such event exists, a pagination failure follows the API-failure rule
       below, and a missing or unparseable committer date yields false; **and**
    4. the pull request's head OID, re-read after the reactions fetch, still
       equals the `HEAD_OID` under evaluation (the head moved mid-check
       otherwise; yield false).

All timestamp comparisons are numeric over epoch seconds
(`fromdateiso8601`-style parsing); the sources involved are GitHub-API
timestamps, which the API serves normalized to UTC `Z`, and any parse failure
yields false. An API call that fails outright follows the script's existing
`gh_api` idiom and exits 3 (infrastructure error); a call that succeeds with an
unexpected shape degrades the fact to false. An empty `bot_reviewers` allowlist
yields false. Since GitHub permits one reaction per user per content type,
multiple `+1`s can only come from distinct identities; any allowlisted one
satisfies (b)(1), while an `eyes` from any allowlisted identity blocks via
(b)(2).

A companion fact `bot_clean_signal_source` is emitted with value `review`,
`reaction` or `none` — `review` takes precedence when both paths hold. When
merge-guard merges on `reaction`, its announcement line includes the reaction's
id and `created_at` alongside the head SHA, since reactions leave no timeline
history to audit after the fact.

### Component 2b — clean-pass comment exemption

The untriaged-feedback blocker gains a narrow exclusion: an issue comment whose
author is an allowlisted bot identity **and** whose body begins with the
clean-pass marker `Codex Review: Didn't find any major issues` is not untriaged
feedback. Everything else from bot authors still blocks. The marker prefix is
pinned as observed on 2026-07-18; if the vendor rewords it, the comment resumes
blocking — a false negative, which hands off to a human and is the acceptable
direction.

### Component 3 — handshake accounting and clean-pass completion

The `eyes` reaction is exposed to the re-review poll path so the one-ask cap can
distinguish *the ask never reached a reviewer* from *the ask reached a reviewer
that is still working*. Conflating those is what currently burns the cap and
forces a hand-off.

The handshake alone is not enough: the existing poll helper completes only on a
submitted review object, so a clean Codex pass — which submits none — would time
out and consume the cap despite succeeding. The re-review completion contract
therefore recognises **any** of the following as completion, checked against the
same allowlist:

- a new review object from an allowlisted identity (the findings case, as
  today);
- a `+1` reaction on the PR body from an allowlisted identity whose
  `created_at` post-dates the ask (the clean case);
- an issue comment from an allowlisted identity carrying the clean-pass marker
  and post-dating the ask.

The poll helper's output gains a `completion_kind` field — `review`,
`clean_reaction`, or `timeout` — so callers (merge-guard's retry, Phase 6) can
distinguish a clean completion from silence. Only `timeout` counts as a silent
ask against the cap.

## Accepted residual

Two pushes inside Codex's ~70-second review window could, in principle, let a
`+1` earned by the earlier head post-date the later head's `last_head_change`
and satisfy (b)(3) — if Codex neither keeps `eyes` up for the second review nor
tears the reaction down promptly. The probes exercised serialized pushes only,
so this is untested rather than excluded. It is bounded by three facts: (b)(2)
blocks while `eyes` is present, (b)(4) rejects a head that moves mid-check, and
eligibility runs after a fix-loop round completes — minutes after the last push,
not seconds. Accepted. If it is ever observed, the remedy is a quiet-period
conjunct: reject a `+1` younger than the observed maximum review latency unless
the head has been stable at least that long.

An ordinary push can also advance the PR to a commit **created substantially
earlier** — an agent pushing previously-prepared local work — with no
force-push event. A `+1` earned by the prior head then post-dates the new
head's committer date and satisfies (b)(3), even though it predates the push.
Two things bound this: it additionally requires Codex to be unavailable after
the push (a push is a trigger, so within the normal lifecycle the stale `+1`
is torn down within seconds), and on the merge-guard retry path it is closed
outright — the retry accepts a `+1` only when its `created_at` post-dates the
retry's **own `@codex review` ask comment**, both server-generated timestamps.
The residual exposure is therefore the cold evaluation path times a Codex
outage times a stale-prepared-commit push. Accepted; if observed, the remedy
is a server-observed head timestamp (e.g. the head SHA's earliest check-suite
`created_at`) replacing the committer-date term.

Base-branch drift is likewise accepted, at parity with the existing review path:
neither a review object nor a reaction is invalidated when the base advances and
the effective diff changes without a head push.

## Testing

`request-rereview_test.sh` extends the existing fake-`gh`-on-`PATH` shim. New
cases: each known identity dispatches its own mechanism, asserted by recording
the argv the fake `gh` receives; an unknown identity warns and is skipped
without aborting its siblings; exit 0 when at least one ask succeeds, exit 1
when none do, exit 2 on usage errors as today; omitting `--bot-reviewers` still
performs the Copilot dance; `--bot-reviewers` rejects a non-array, an empty
array, and non-string members.

The poll-helper tests gain a clean-Codex completion case: a fixture where no
review object ever arrives but a `+1` (or the marker comment) post-dating the
ask does, asserting `completion_kind == "clean_reaction"` and that the silent
counter is NOT incremented — plus the inverse, where nothing arrives and
`completion_kind == "timeout"` increments it.

`check-merge-eligibility_test.sh` covers the fact as a truth table over fixture
payloads, asserting both `bot_clean_review_at_head` and
`bot_clean_signal_source`:

- review path alone; reaction path alone; both (source must read `review`);
  neither;
- a `+1` predating the head commit's committer date;
- a `+1` predating a later `head_ref_force_pushed` timeline event;
- a `head_ref_force_pushed` event on a later timeline page (pagination must
  still surface it);
- a `+1` from an identity outside the allowlist; a `+1` whose `user.type` is
  not `"Bot"`;
- an `eyes` present from a different allowlisted identity than the `+1`'s;
- an `eyes` arriving on the second page of the reactions fetch;
- head OID moved between the reactions fetch and the re-read;
- missing committer date; unparseable reaction timestamp; empty allowlist.

Exemption cases for Component 2b: bot author with the marker prefix is exempt;
bot author with any other body still blocks; a non-bot author with the marker
prefix still blocks.

## Delivery

Two pull requests, because the components sit in different skills and Component 1
is independently valuable — it is the part that is currently broken outright.

1. Components 1 and 3 and their tests, in `wait-for-pr-comments` — the dispatch
   table, the completion contract, and that skill's own caller edit (Phase 6
   step 1 passes `--bot-reviewers`); merge-guard's retry calls these helpers
   directly.
2. Components 2 and 2b and their tests, in `merge-guard` — including the
   merge-guard caller edit (the retry instruction passes `--bot-reviewers` and
   branches on `completion_kind`).

Both touch `src/**` and therefore floor to the HEAVY completion gate regardless
of diff size.

## Continuations

- `agents-config-abn9.8.51` — prgroom: `state.reviewers` is never populated
  (filed; blocks the item below)
- `agents-config-abn9.8.52` — prgroom: support Codex as a review bot (filed)

prgroom reimplements its own merge gate and never reads reactions, so it needs
this predicate independently. It must implement the predicate exactly as pinned
in Component 2 — every element above is stated to be implementable without
interpretation — and should reuse the truth-table fixtures as its own test
corpus, so the two implementations cannot drift apart silently.

## Review feedback

Round 1 — `ralf-review`, 2026-07-18, verdict **FAIL** (recorded; this revision
addresses findings but does not upgrade the verdict). Dispositions:

| Finding | Disposition |
| --- | --- |
| B1 two-push race | Accepted residual; bounded by (b)(2)/(b)(4) and gate timing; remedy named. |
| B2 committer-date forgery | Rejected — outside the cooperative-loop threat model (see Scope); force-push case covered server-side. |
| B3 timestamp-format mismatch | Disproven — the commits API normalizes committer dates to UTC `Z` (verified on commit `6a6dcc3` both ways). Epoch comparison adopted anyway as hygiene. |
| C1 wrong known-bound example | Adopted — cherry-pick example removed (it resets the committer date); force-push-to-ancestor closed via `head_ref_force_pushed` timeline event. |
| C2 reaction unlinked to review | Partially adopted — `user.type == "Bot"` required; trigger-evidence conjunct rejected as disproportionate to the threat model. |
| C3 eyes author / pagination | Adopted — `eyes` from any allowlisted identity blocks; `--paginate` mandated. |
| C4 SHA-comment as primary | Rejected — the comment does not exist on auto-trigger clean passes, so comment-primary forces a redundant explicit ask on every already-clean PR; marker retained only for the Component 2b exemption. |
| M1 clean-pass comment self-blocks | Adopted — Component 2b. |
| M2 review_wait blind to Codex | Deferred — the fact-level `eyes` check covers the unsafe direction; `review_wait` accuracy tracked as implementation-time work. |
| M3 steerability framed as virtue | Adopted — reframed as a recorded limitation. |
| M4 lifecycle treated as invariant | Adopted in part — stated as bot behaviour, recency guard named load-bearing; staleness ceiling rejected as redundant with (b)(3). |
| M5 contract underspecification | Adopted in part — every predicate element pinned in Component 2; shared fixtures via the truth table; a versioned conformance corpus deferred. |
| M6 no audit trail on reaction merges | Adopted in lightweight form — merge announcement records reaction id and `created_at`. |
| m1–m6 | m1 pinned per-script conventions; m2 empty-allowlist-false pinned; m3 exit-2 preserved; m4 error-shape rule pinned; m5 vendor claim named; m6 base-drift parity stated. |
