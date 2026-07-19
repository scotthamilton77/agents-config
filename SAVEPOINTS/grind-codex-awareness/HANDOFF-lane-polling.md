# HANDOFF — lane-polling

Halted by Scott, 2026-07-19. Facts only; unsure items are marked as such.

## Queue status

Owned files: `src/user/.agents/skills/wait-for-pr-comments/*` (NOT `request-rereview.sh` or
`request-rereview_test.sh` — those belong to lane-eligibility until `abn9.44.4` merges).

| Bead | Status | PR | Notes |
|---|---|---|---|
| `abn9.44.2.9` | CLOSED | #354 merged | Endorsed descope → `abn9.44.9` (merge-guard caller half) + `abn9.44.11` (poll-copilot-review.sh completion-detection half) |
| `abn9.44.11` | CLOSED | #359 merged | Endorsed descope → `abn9.44.12` (criterion 4, repointing merge-guard/SKILL.md's stale residual text — that file is lane-eligibility's) |
| `abn9.44.14` | CLOSED | #360 merged | Full DoD delivered |
| `m5tkg` | CLOSED | #363 merged | Descope: closed with documentation reconciliation, not the operator-inequality "fix" the title implied — investigated, divergence found intentional |
| `abn9.44.7` | **OPEN, claimed, in flight** | none | See full section below |

Beads discovered by this lane during the run (not mine to pick up, filed by ROOT):
`abn9.44.9`, `abn9.44.10`, `abn9.44.12`, `abn9.44.13` (identity-matching, mentioned by ROOT,
never touched by me), `abn9.44.15` (poll-copilot-review.sh TOCTOU head-reread gap, filed from
my escalation on PR #360's Codex review — three completion paths lack a final head-reread
immediately before their exit; deferred, not fixed).

## `abn9.44.7` — full detail (the only in-flight work)

**What it's about:** `poll-copilot-rereview-start.sh`'s 80s window (step 3 of
`wait-for-pr-comments/SKILL.md` Phase 6) unreliably catches Codex's `eyes` reaction start
signal. Bead's own live data: 1 hit (~7s), 3 misses, 2 n/a across 6 real events.

**What I found on investigation:** the OLD Phase 6 step 4 text ("If step 3 detected a
re-review start (either signal), launch poll-copilot-review.sh...") read literally means a
step-3 MISS skips step 4 (the patient completion poller, timeout up to the policy's
`bot_inactivity_timeout_seconds`, 1200s default) entirely and falls straight through to
incrementing the "silent ask" retry-budget counter — treating an unreliable miss as
authoritative confirmed silence. Neither of the bead's two acceptance-criteria branches were
satisfied: window tuning can't fix the "n/a" cases (eyes never emitted at all, distinct from
whether the review later completes), and callers did NOT already treat a miss as
non-authoritative.

**Fix implemented (commit `c63c72f`, refined in `97c2673` — both on branch
`fix/44-7-eyes-reaction-window`, NOT pushed):** step 4 now launches in exactly one of three
mutually exclusive cases (an if/else on step 3's single outcome, explicitly worded to prevent
double-poll on a hit):
1. Step 3 detected a start signal (either kind) → launch immediately.
2. Step 3 reported `no_rereview_started` AND the dispatched policy includes an eyes-capable
   identity (Codex) → launch anyway. Step 3's eyes check becomes an early-exit optimization
   for Codex, not a precondition.
3. Step 3 reported `no_rereview_started` AND the policy is Copilot-only → do NOT launch step
   4 (unchanged from before — Copilot's event-based signal has no documented reliability gap).

The downstream "no new review → increment silent counter" paragraph was updated to reflect
that silence can now originate from either source (2) above, or step 4 itself timing out
after being launched anyway.

**Docs-only.** Neither `poll-copilot-rereview-start.sh` nor `poll-copilot-review.sh` was
touched — this is entirely `wait-for-pr-comments/SKILL.md` Phase 6 prose. Confirmed
`merge-guard/SKILL.md` does NOT call `poll-copilot-rereview-start.sh` at all — no cross-lane
surface. `skill_a_frontmatter_test.sh` + 4 sibling script test suites all green (0 failures,
5x exit 0 each) — expected, no scripts changed, this is just confirming nothing else broke.

**Bead notes:** I recorded the full adjudication in `bd` (append-notes on `agents-config-abn9.44.7`)
BEFORE the halt message arrived — acceptance criterion 1 (widen/tune the window) deliberately
NOT satisfied, with the bimodal-data reason; criterion 2 satisfied via the caller-logic fix,
worst-case cost named. This is done, not pending.

**The measurement caveat, verbatim, because it is the single most likely fact to get
corrupted by a later reader:** my 154s (#360) and 156s (#363) figures are **ask-to-`+1` total
completion time, NOT eyes-specific reaction latency.** Do not write or repeat "measured eyes
latency ≈155s" — that would be false. I could not recover precise eyes-reaction timestamps
retrospectively at all.

**Negative result worth keeping:** GitHub reactions leave no audit trail once torn down.
Confirmed by querying the reactions API on PRs #354, #359, #360, #363 after their eyes
reactions had already been withdrawn — only currently-present reactions return; nothing
historical. Anyone attempting to re-derive eyes-reaction latency data from the GitHub API
after the fact will hit the same wall. Live capture during an active poll is the only way to
get this data; it cannot be reconstructed later.

**ROOT's two unanswered review questions** (I addressed both in the prose itself, in commit
`97c2673`, before dispatching a directed reviewer. The verdict DID return, to ROOT, after
this lane stopped — see the reviewer section below for its rulings on both):
1. Does a step-3 hit for a Codex-inclusive policy now double-poll (launch step 4 twice, or
   risk a second `--since-timestamp` window spending the silent counter on an already-completed
   ask)? I added an explicit framing sentence ("launch exactly once, per whichever ONE of
   these mutually exclusive cases... an if/else, never two independent triggers") specifically
   to close this. Reviewer confirmed: no double-poll risk.
2. What does the always-launch path cost on a genuinely silent Codex? Named inline: worst-case
   time-to-silent-detection rises from ~80s to up to ~1280s (step 3's 80s + step 4's 1200s
   default). Framed as consistent with the pre-existing "detected" branch's own worst case
   (which already permitted the full 1200s on every hit), not a new magnitude — **and the
   reviewer rejected that framing as spin. See the OPEN MAJOR below; the numbers stand, the
   "not a new magnitude" sentence does not.**

**Directed reviewer status: VERDICT RETURNED.** *(Corrected by ROOT after the lane stopped.
The lane's own copy of this section said "unknown / never returned" — accurate from where it
sat, since the verdict landed at ROOT after the lane had written its handoff and stopped.
Worker completions notify ROOT, not the dispatching lieutenant. Trust this section, not any
recollection that the review never came back.)*

The reviewer read the working-tree file, so its verdict applies to `97c2673` content, not
`c63c72f`.

- **Q1 (double-poll on a step-3 hit): NO RISK.** Mutual exclusivity is structural, not merely
  asserted — step 3 yields exactly two outcomes and all three bullets key off that binary,
  split further by `DISPATCHED_OK_REVIEWERS`. A literal reader treating it as if/elif/elif
  cannot reach two branches in one invocation. The added framing sentence is
  belt-and-suspenders, not cover for a real ambiguity.
- **Q3 (did the OLD text genuinely gate step 4): CONFIRMED — real defect.** Verified at
  `git show 860be409...:.../SKILL.md`: old step 4 read "If step 3 detected a re-review start
  (either signal), launch..." with no else-branch, so a literal reader skips step 4 entirely
  on any miss, including a Codex miss, even though step 3 already had eyes detection in that
  same commit. The old prose's own claim that step 3's eyes detection "is what fixes that"
  was itself an overclaim. This change is a real fix, not a fix for a phantom.
- **Cross-lane check: CONFIRMED CLEAN.** `merge-guard/SKILL.md` calls `poll-copilot-review.sh`
  directly (lines 191, 226, 284, 307, 313) and never calls `poll-copilot-rereview-start.sh`.
- **Evidence labeling: VERIFIED GOOD.** The 150s+ figure is correctly scoped as total time to
  a completed clean pass, not eyes-reaction latency. Flagged by the reviewer as explicitly
  correct, not merely un-objectionable.

**MAJOR — FIXED. `97c2673`'s spin sentence is gone as of `5b974ad`.**

Q2's cost framing drew a MAJOR against `97c2673`. The arithmetic was right, but the "not a
new magnitude of wait" sentence (~line 590 at the time) spun a real ~16x worst-case regression
on this specific path (Codex-inclusive miss: ~80s → up to ~1280s) by pointing at a 1200s bound
that exists elsewhere in the system.

Fixed in commit `5b974ad` (the message crossed with the lane's stop, then the lane picked it
back up on resume and applied it): the sentence now reads "this trades detection latency for
correctness on this path" instead of implying no regression exists — ROOT's authorized wording,
applied verbatim. `skill_a_frontmatter_test.sh` re-run clean after the edit; `grep -rn
"abn9.44\."` confirmed no tracker-ID reintroduction. This was the ONLY change made — nothing
else in the file was touched. No PR was opened; this is still uncommitted-to-origin, worktree
work only.

## Branch/worktree state

- Worktree: `/Users/scott/src/projects/agents-config/.claude/worktrees/poll-44-7`
- Branch: `fix/44-7-eyes-reaction-window`
- HEAD: `5b974ad` (was `97c2673` at the reviewer's read; `5b974ad` is the one-sentence MAJOR fix on top)
- **Not pushed to origin.** No PR opened.
- `git status --porcelain` at this stop: **empty** (clean, nothing uncommitted).
- Based on `origin/main` at claim time (tip was `860be4092f3bb40f4883bf69bca579a8fd4db571`,
  the m5tkg merge). A fresh lieutenant should `git fetch origin main` and check whether
  `origin/main` has moved before rebasing/gating — I did not check this before the halt.

## Standing rules a fresh lieutenant needs (learned the hard way this session)

- **Never touch local `main`.** Branch worktrees off `origin/main` explicitly
  (`git fetch origin main` then `-b <branch> origin/main`), never local `main` — it may carry
  Scott's own unpushed commits. ROOT owns local main exclusively.
- **No tracker IDs (bead IDs) in source code or living docs.** I embedded
  `agents-config-abn9.44.7` in the SKILL.md prose once during this bead's own drafting and
  caught it myself before committing — confirmed clean via `grep -rn "abn9.44\." SKILL.md`
  before the final commit. Same mistake happened once earlier on `m5tkg` (caught after
  ROOT's review flagged it, required a follow-up commit). Always grep before committing.
- **PR-public reply text on your own PRs is yours to write** — ROOT sends changes, doesn't
  edit your posted comments directly (a mid-air-collision incident happened once on PR #360;
  resolved, rule stated explicitly by ROOT afterward).
- **Stale clean-pass markers are a real, recurring false-positive.** On three separate
  occasions this session, a watcher "CLEAN" ring turned out to be a marker comment whose
  `Reviewed commit:` line cited an EARLIER head than the PR's actual current head (my push
  had moved the head after Codex's review landed). Always check the marker's cited commit
  against the actual current head, and check for a genuine `+1` reaction (not just the
  marker) before trusting a clean signal. Also watch for your own PR-reply endpoint's REST
  side effect: it creates a "review" object under your own login that can be mistaken for a
  bot review by naive counting.
- **`gate_triage` must run against a committed tree, and against the merge-base, not
  `origin/main` directly** if your branch could be behind — `git merge-base origin/main HEAD`
  first. Commit before gating; a dirty tree silently downgrades HEAVY to SERIAL.
- **No Workflow/HEAVY harness available to this lane this session** — every gate this lane
  ran was a self-dispatched `quality-reviewer` subagent (SERIAL-tier fallback per the
  completion-gate rule), never an actual HEAVY workflow run.
