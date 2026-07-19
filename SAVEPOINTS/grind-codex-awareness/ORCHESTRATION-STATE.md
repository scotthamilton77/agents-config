# ORCHESTRATION-STATE — grind "codex awareness fixes"

Self-contained handoff. A post-compaction ROOT resumes from this file alone.

## 1. Mission

Close 7 beads that make the merge/review gate lie or waste cycles. Outcome when done:
real CI status finally reaches the eligibility floor; the ratchet no longer leaves
silent partial-blocked states; the start-handshake stops false-negativing on Codex;
routine Codex infra hiccups stop costing a full triage cycle each.

**Out of scope:** anything not in the two lane queues below. No prgroom cutover work.
No installer runs.

## 2. Pause state

**HALTED by Scott, 2026-07-19.** All three teammates ordered to a clean stop: commit or
report anything uncommitted, write a handoff file, then stop. No teammate is running.

Per-teammate handoffs sit alongside this file:

| File | Author |
|---|---|
| `HANDOFF-lane-eligibility.md` | `lane-eligibility` |
| `HANDOFF-lane-polling.md` | `lane-polling` |
| `HANDOFF-bookkeeper.md` | `bookkeeper` |

This file stays the entry point. Read it first, then the lane handoff for whichever
lane you are resuming. `dashboard.html` is marked FINAL — it is a snapshot of the
halt, not a live view; nothing is updating it.

**Resuming is a fresh spawn, not a wake.** The teammates are stopped. A resuming ROOT
re-partitions from the queues below, re-spawns lieutenants, and briefs each one from
its handoff file. Do not assume a named agent from the roster is still addressable.

Before the halt, Scott gave an explicit GO on the partition and roster.

### `abn9.44.7` — reviewed clean, MAJOR fixed, ready to push

`fix/44-7-eyes-reaction-window` @ `5b974ad`, not pushed, no PR, worktree clean.
**First action on resume: push and open the PR.** No known open findings.

The directed reviewer's verdict landed at ROOT *after* lane-polling had written its handoff
and stopped — worker completions notify ROOT, not the dispatching lieutenant. It cleared the
double-poll question, confirmed the old text genuinely did gate step 4 (so this is a real fix,
not a phantom), confirmed no merge-guard cross-lane surface, and explicitly blessed the
ask-to-`+1` evidence labeling. One MAJOR stands: the "not a new magnitude of wait" sentence
(~line 590) spins a real ~16x worst-case regression on the Codex-miss path (~80s → ~1280s).

ROOT authorized a one-sentence fix and the lane applied it as `5b974ad` before stopping —
ROOT verified the diff independently: one hunk, one paragraph, exactly the authorized change,
and the replacement wording names the regression plainly ("a real regression in detection
latency on this specific path... trades that latency for correctness") instead of minimizing
it. `HANDOFF-lane-polling.md` briefly recorded the verdict as "unknown / never returned";
both the lane and ROOT have since corrected it.

### Two bookkeeping defects found at halt — unresolved, need a human call

1. **Defect-count disagreement.** ROOT carried "11 defects filed this run"; the
   bookkeeper's finalized `state.json` says 8. Neither number was reconciled against
   `bd` before the halt, and a `bd list` sweep of beads created 2026-07-19 shows the
   true figure depends entirely on where you draw the line between "discovered during
   the grind" and "filed today by an adjacent session." **Do not quote either number
   as fact.** Recount from `bd` against an explicit definition before it appears in
   any retro.
2. **`abn9.44.5` and `abn9.44.6` are duplicates.** Identical titles ("review_summary
   ratchet clears staleness fact but not the superseded review's own unresolved
   threads"), filed one minute apart (15:51 and 15:52), both `open`. `44.6` is the one
   in the lane-eligibility queue. `44.5` was left open deliberately at the halt rather
   than closed — deduping is a tracker mutation that deserves its own scope check, not
   a drive-by during a stand-down.

### Decided-but-unwritten at halt: `abn9.44.4` attempt 5

Duplicated here deliberately — this decision cost four rejected attempts and must not
depend on a handoff file being written correctly.

Attempts 1–4 all tried to validate the *shape* of an attacker-controlled comment body
(`2589dbe` first-line match, `882d2b6` `contains($marker)`, `2749572` positional
line1+line2, `00fd5c4` closing sentinel). Every one was defeated, the last by mid-body
injection above the sentinel. The approach itself is the bug: `request-rereview.sh`
posts as `$auth_login`, the same identity the human controls, so there is no privilege
separation and no body-shape check can be a real boundary. An unkeyed digest would be
public in this open-source repo and computable by anyone — rejected as theater.

**Attempt 5, specified and unwritten:** AND the marker-fence clause with
`.created_at == .updated_at` on the comment object. Already in the ISSUE_COMMENTS fetch
(line 636) — zero extra API calls, zero producer changes, no new marker, no drift
surface. GitHub tracks that pair server-side; an edited comment cannot report them
equal. Closes every exploit proven this round, all of which were framed as editing an
already-posted tool comment. The bare exact-whole-body clause stays untouched: editing
replaces the body rather than appending, so a retraction down to a bare `@codex review`
is an intentional withdrawal, not a hole.

**Known residual, accepted, not blocking:** a fresh never-edited hand-authored comment
matching the fence still forges an exemption. Different threat class — deliberate
self-sabotage by the PR's own author, versus the accidental feedback loss every proven
exploit actually demonstrated. Permanent fix is a dedicated bot/App identity for
`request-rereview.sh` keying on GitHub-enforced author login instead of body shape,
mirroring `approve_pr.py`.

Filed as **`agents-config-abn9.44.18`** (P2, open) — parent `agents-config-abn9.44`,
`discovered-from` edge to `agents-config-abn9.44.4`, triage block attached. ROOT filed
it directly: the lane was ordered to file it during wind-down, reported a clean stop
without doing so, and was already stopped by the time the gap was noticed. The full
"no privilege separation / an unkeyed digest in an open-source repo is public"
argument is captured in the bead description so it never has to be re-derived.

## 3. Roster

Repo main root: `/Users/scott/src/projects/agents-config` (branch `main`).
Grind dir: `/Users/scott/src/projects/agents-config/.claude/grind-codex-awareness/`

| Teammate | Model | Owns |
|---|---|---|
| ROOT (this session) | Opus, medium | management, merges, watchers |
| `lane-eligibility` | Sonnet, high | `src/user/.agents/skills/merge-guard/*` |
| `lane-polling` | Sonnet, high | `src/user/.agents/skills/wait-for-pr-comments/*` |
| `bookkeeper` | Haiku, low | `state.json` + `dashboard.html` in the grind dir |

Workers are UNNAMED, dispatched by lieutenants, sized per task (mechanical -> haiku low,
implementation -> sonnet medium).

### lane-eligibility queue (in order, one small PR each)
1. `abn9.44.3` P1 — CI-green blocker reads only the legacy classic branch-protection
   endpoint; 404s on ruleset repos and is misread as "no required checks" => vacuously
   green. Union in `rules/branches/{base}`. **Most important bead in the grind.**
2. `abn9.44.4` P1 — `is_trigger_comment` exact-matches `"@codex review"`, so the tool's
   own multi-line disposition-table re-ask trips its own `untriaged_feedback` blocker.
   Match first line post-trim.
3. `abn9.44.6` P2 — ratchet clears the staleness fact but the superseded review's inline
   threads stay open; PR reads ratchet-clean AND blocked, with no signal. Document
   ratchet scope OR auto-trigger the thread check.
4. `abn9.44.8` P3 — Codex's transient "Something went wrong" comment should auto-SKIP.

### lane-polling queue (in order, one small PR each)
1. `abn9.44.2.9` P1 — `request-rereview.sh` exits 0 on >=1 success instead of per-identity,
   masking a failed dispatch as a later silent timeout. Also two `poll-copilot-review.sh`
   gaps: completion matches only `state==COMMENTED` (never APPROVED); `clean_reaction`
   fires on the marker comment without the real +1.
2. `m5tkg` P2 — `>=` (start-detection) vs strict `>` (staleness bound) across the two poll
   helpers; same-second tie yields a false timeout. Fails closed. Needs a deliberate
   cross-file semantics reconciliation, not an inequality flip.
3. `abn9.44.7` P2 — the fixed 80s window catches Codex's eyes-reaction unreliably
   (1 hit / 3 miss / 2 n-a across 6 live events). Widen/tune, or confirm+document that
   callers treat a miss as inconclusive rather than negative.

## 4. Ledger

**MERGED (6):**

| PR | Bead | Merge commit | Authorized by |
|---|---|---|---|
| [#353](https://github.com/scotthamilton77/agents-config/pull/353) | abn9.44.3 | `8f8ff298bc0f49d6fbe1faaf706861a8970c7e14` | bot-quiescence, Codex `+1` reaction; App review 4731110214 |
| [#354](https://github.com/scotthamilton77/agents-config/pull/354) | abn9.44.2.9 | `91a2d64c23fed71e439ade08ba0fef406309f71c` | bot-quiescence, submitted clean review; App review 4731111478 |
| [#356](https://github.com/scotthamilton77/agents-config/pull/356) | abn9.44.9 | `aa7462d7cb7594f870a30d96319532cdb6d16e6a` | bot-quiescence, submitted clean review; App review 4731157587 |
| [#359](https://github.com/scotthamilton77/agents-config/pull/359) | abn9.44.11 | `cbe3e6c2df910cb67a91b81a4bf4033a59829427` | bot-quiescence |
| [#360](https://github.com/scotthamilton77/agents-config/pull/360) | abn9.44.14 | `1d6379c6eb767a2a483c95b6f55e46ebb2b67f6d` | bot-quiescence, Codex `+1` reaction id 415793812 @ 17:56:18Z; App review 4731222668 |
| [#363](https://github.com/scotthamilton77/agents-config/pull/363) | m5tkg *(endorsed descope)* | `860be4092f3bb40f4883bf69bca579a8fd4db571` | bot-quiescence, Codex `+1` reaction id 415819398 @ 18:41:19Z; App review 4731281105 |

**#363 — two things a successor should not have to rediscover.** Its base moved from `cbe3e6c2`
to `640f463c` between PR-open and merge; the floor recomputed against the current base and
still returned eligible. That is why ROOT re-runs the FULL floor immediately pre-merge rather
than trusting a lane's earlier `EXIT=0` — both runs were correct, they simply measured
different bases.

And **three CLEAN rings on that PR were false.** One carried a marker citing `01349fc` while
head was `9dda2b4`; one had no qualifying reaction at all (only `eyes`); only the third was
real. The lane caught all three by checking the marker's `Reviewed commit:` line against the
actual head every time. **That check lives in neither the watcher nor the floor's routing
hint** — a `class=CLEAN` ring means only "something happened that looked positive".

✅ **`abn9.44.3` is validated end-to-end on live data.** During #356's floor check, the lane ran
`check-merge-eligibility.sh` from its **worktree** copy (fixed source) and got
`ci_state="green"` on the same PR where the **installed** copy still returns `"none"`. Same
commit, two scripts, two answers — the new one correct. The ruleset-union fix genuinely reads
Ruleset-sourced required checks.

Every merge in this run cleared the floor **immediately beforehand** (exit 0, blockers `[]`),
was head-pinned via `--match-head-commit`, and had **CI verified by hand** — because the floor
itself still reports `ci_state: "none"` (see the CI caveat below). Do not skip the manual CI
check on the strength of a green floor; the floor's green is currently one fact short.

**#360 detail, since it exercised the reaction path:** authorized by
`bot_clean_signal_source="reaction"` — reaction id `415793812` at `2026-07-19T17:56:18Z`,
fresh relative to the ask at 17:53:44. A reaction leaves no timeline history to audit later,
which is why the id and timestamp are recorded here rather than just "clean". The lane
correctly distinguished that real `+1` from two decoys: a clean-pass **marker comment** at the
same head (which alone would NOT have satisfied the floor), and its own reply's REST
**"review" wrapper** (id 4731214645, user `scotthamilton77`) — an artifact of threaded replies
that reads as a review object to anything merely counting reviews.

**Scott granted the `approve_pr.py` permission in-session** after the auto-mode classifier
initially denied it. That grant is what unblocked both merges — record it here so it is
never later mistaken for a lane merging on its own initiative.

| [#359](https://github.com/scotthamilton77/agents-config/pull/359) | abn9.44.11 | `cbe3e6c2df910cb67a91b81a4bf4033a59829427` | bot-quiescence, submitted clean review; App review 4731167097 |

`origin/main` is at **`cbe3e6c2`**. Local `main` is deliberately left at `1054517`
(1 ahead / behind) — it carries Scott's unpushed commit. **ROOT owns main; do not reconcile
it.** Lanes branch off `origin/main`.

**Beads closed (4):** abn9.44.3, abn9.44.2.9, abn9.44.9, abn9.44.11.
Two closed with **ENDORSED DESCOPES**: `abn9.44.2.9` → `abn9.44.9` + `abn9.44.11`;
`abn9.44.11` → `abn9.44.12` (criterion 4).

### In flight — READ THIS BEFORE ACTING

**lane-eligibility → `abn9.44.4`** (trigger-comment first-line match), worktree
`.claude/worktrees/elig-44-4`, branch `fix/44-4-trigger-comment-match`, based at `aa7462d`
(**2 behind `origin/main`** — fine, gate against the merge-base, decide on rebase before PR).

**STATUS: THIRD ATTEMPT (`2749572`), directed review IN FLIGHT. Not cleared. No PR.**
Suites green: `check-merge-eligibility_test.sh` 237/237, `request-rereview_test.sh` 79/79.

**Three attempts is the gate working, not thrash — each rejection was a real security defect
caught before merge.** Read this history before touching the predicate; two "obvious" fixes
are already buried here.

| # | Commit | Approach | Verdict |
|---|---|---|---|
| 1 | `2589dbe` | first-line match | **REJECTED, MAJOR** — `"@codex review\n<human feedback>"` became exempt, silently dropping real feedback from the merge floor |
| 2 | `882d2b6` | machine marker via substring `contains` | **REJECTED** — GitHub quote-reply copies the RAW body including HTML comments, so a human quote-replying the bot and appending feedback carried the marker and earned the exemption. Same defect class, more likely route. The author guard does **not** save this: it admits `$pr_author`, and the human *is* the PR author |
| 3 | `2749572` | **positional anchoring** — line 1 trimmed `== "@codex review"` AND line 2 trimmed `== $marker` | current. A quoted line reads `> <!-- ... -->`; trimming strips whitespace, not `>`, so quoting breaks both clauses structurally — no quote-detection special case needed |

Attempt 3 also added a **cross-file consistency test** asserting the marker literal in
`check-merge-eligibility.sh` equals `CODEX_REREVIEW_MARKER` in `request-rereview.sh` — turning
a `MUST match` code comment into an enforced constraint. The failure mode it guards is silent
and total: if those literals drift, the exemption never fires and the tool trips its own
blocker, restoring the original bug.

**Producer/consumer split:** the fix spans `merge-guard/check-merge-eligibility.sh` (consumer)
and `wait-for-pr-comments/request-rereview.sh` (producer, +20 lines). The producer keeps
`@codex review` as line 1 and puts the marker on line 2, leaving the BARE case byte-identical —
so the bare path still matches via the exact-whole-body clause and never depends on the marker.
Two independent narrow conditions, not one carrying everything.

⚠️ **OWNERSHIP: `request-rereview.sh` + `request-rereview_test.sh` belong to lane-eligibility
until 44.4 merges** (declared to lane-polling, whose subsystem they normally are). Verified no
conflict at declaration time: `poll-m5tkg` was clean and had not touched them.

**The still-open question for the in-flight review:** lines 1–2 are pinned, but lines 3+ are
unconstrained. Does appended human feedback below a *genuine* tool-generated re-ask ride along
exempt? If so, the original MAJOR survives in narrower form.

*Historical detail of the rejected attempts follows.*

**The MAJOR:** the first-line match is too wide. Any body whose first line trims to the
trigger phrase is exempt *regardless of what follows*, so `"@codex review\n<anything>"` earns
the exemption. The realistic case is mundane and silent: a human types `@codex review`, adds
"also fix the null deref in foo.go" on the next line, and **that feedback is dropped from
`untriaged_feedback`**. Pre-fix it blocked. In a gate whose whole job is fail-closed, that is
real feedback vanishing from the merge floor. The lane's own comment block anticipated the
hazard but rebutted only the *same-line* variant; the reasoning does not extend to the
newline variant, and there was no test for it.

Also found: CRLF bodies are exempt (`gsub \s` eats the `\r`) — benign alone, but it compounds
the MAJOR since trailing content survives that path identically. Correctly fail-closed:
leading blank line, BOM, unicode look-alike, same-line extra text.

**Tests (11) and (12) are VACUOUS** — proven by mutation, not by reading. Reverting the
predicate to the pre-fix whole-body version fails ONLY test (10); (11) and (12) pass both
before *and* after, so they validate nothing about this change. They are not worthless — a
mutation to a `contains` match does fire them, so they guard against over-*widening* — but
they should be relabelled regression guards rather than implied validators.

**Clean, verified:** the author guard is intact (left conjunct of `and`; no body shape can
bypass it). Test independence checked programmatically across ALL 230 assertions — `744640e`
was the correct and complete fix, no second hijack exists. 230 ok / 0 FAIL / exit 0.

**Fix direction given to the lane (ROOT recommendation, lane may counter with reasoning):**
do not tighten the prose match — the reviewer's suggestion of matching the producer's known
tails couples this script to `request-rereview.sh`'s exact wording across three branches and
silently re-breaks the moment anyone edits it. Instead make the contract explicit: have
`request-rereview.sh` emit a machine marker (an HTML-comment sentinel, invisible in rendered
markdown) and have `is_trigger_comment` require it. Tool-generated re-ask carries the marker →
exempt regardless of body shape; a human typing the phrase has no marker → blocks; already
posted comments lack it → blocked, fail-closed, forward-only. Both files are in this lane's
subsystem. The lane must verify the marker survives GitHub's comment rendering rather than
assume it. **This restructures control flow, so it buys a fresh review round.**

Gated against merge-base `aa7462d` — **not** `origin/main`, which would spuriously include
the inverse of merged PR #359.

Commits: `aa7462d` (base) → `2589dbe` (the fix + tests 10-12) → **`744640e`** (restores the
hijacked assertion). Tree verified stable across 3 consecutive reads, 230/230 pass.

- The **worktree flap** is resolved — work committed, no loss, content was correct
  throughout. No definitive root cause; no `checkout`/`restore`/`stash` on the lane's side
  and its reviewer had no write tools. Treated as transient.
- The **BLOCKING test-hijack** is fixed in `744640e`: the auth-login-failure assertion now
  sits immediately after its own `run_script` (line 730), exactly one copy, and test (12)
  still asserts its own `rc`. **ROOT reconciled the arithmetic independently:** base 226
  assert statements → HEAD 229 = **+3**, matching tests (10)(11)(12). The lane's original
  "4 new tests" claim had counted a pre-existing sanity check as new.

**REBASE QUESTION: SETTLED — no rebase.** The lane's reasoning, accepted: zero file overlap
with #359; `gh pr create` computes the PR diff server-side against the current `origin/main`
tip regardless of local staleness; merge-guard re-runs the full floor and pins the head SHA at
merge time, so staleness is caught by construction. Plus the leg ROOT would have missed —
**do not move a tree a reviewer is currently examining.** Do not reopen this.

**NEXT for this lane:** implement the marker fix, commit *before* gating (`gate_triage` counts
only committed changes — `wgclw.33`), gate against merge-base `aa7462d`, then a fresh directed
review, then PR.

**lane-polling → `agents-config-abn9.44.14`** — ✅ **MERGED AND CLOSED.** PR #360, squash commit
`1d6379c6`, merged 2026-07-19T17:59:45Z. Bead closed; close-walk verified not to have
over-propagated (parent `abn9.44` still `in_progress`, `abn9.44.15` still `open`).
**lane-polling → `m5tkg`** — worktree `poll-m5tkg`, branch
`fix/m5tkg-timestamp-inequality-reconcile`, commit `70017fe`, based at `1d6379c` (== `origin/main`
tip). **Reviewed CLEAN (no BLOCKING/MAJOR). Two ROOT-required changes pending, then PR.**

**DESCOPE — ENDORSED. Record it as adjudicated, never as "done as specified".** The bead's
implied DoD was *reconcile the `>=` vs `>` operators*. The lane investigated and concluded the
premise was wrong: the two bounds compare the same captured timestamp but answer **different
questions with opposite failure asymmetries** — start-detection asks "has anything happened
since the ask" (missing a same-second start costs liveness → `>=`), staleness asks "is this a
response to THIS ask" (false-accepting a leftover costs soundness → strict `>`). Unifying them
would pick a failure mode for a question nobody asked. **No functional code changed**; both
operators are byte-identical to the merge-base. Reconciled in documentation instead.

Its reviewer earned the clean verdict rather than asserting it: it confirmed "never an unsafe
merge" *against the code* (the collision yields `completion_kind=timeout`, and the pre-existing
header contract says only `timeout` spends the silent-ask budget), confirmed the `>=`
justification **pre-existed** this change (so this is genuine reconciliation, not post-hoc cover
for an accident), and proved the new assertions additive by testing them against the merge-base.
Suites: `poll-copilot-rereview-start_test.sh` 51/51, `poll-copilot-review_test.sh` 77/77.

**Two changes required before PR** (no fresh review round needed, provided no operator or
assertion semantics move):
1. **Strip the bead ID `m5tkg` from source comments and test assertions** — repo rule, no
   tracker IDs in code or living docs. Assert on the sibling FILENAME instead: stable, survives
   rewording, still fails if the cross-reference is stripped wholesale.
2. **Collapse duplicated rationale.** The same ~120-word block appears near-verbatim in FIVE
   places (SKILL.md, both script headers, both test-comment blocks). SKILL.md Phase 6 becomes
   canonical; the rest get short pointers. Five prose copies cannot be kept in sync, and the
   drifted one gets read as authoritative by whoever opens that file first.

Queue after: `abn9.44.7`. Keep `m5tkg` (an off-by-one in an EXISTING comparison) distinct from
`abn9.44.15` (a MISSING final head re-read); if a fix starts touching the exit paths, that is
drift into `44.15`'s territory and it stops.

Historical detail of that delivery follows — PR **#360**
(`fix/44-14-initial-poll-freshness`, worktree `poll-44-14`, commit **`dbe20f1`**, based on
`origin/main` `cbe3e6c2`). 76/76 assertions pass, exit 0; 3 sibling test files unaffected.
Queue after this: `m5tkg` → `abn9.44.7`.

⚠️ **#360 has TWO gates outstanding and is NOT merge-eligible:**
1. **Bot review loop** (lane-owned). Codex reviewed `dbe20f1` and raised one P2 (thread
   comment `3611043315`): a TOCTOU window between the head fetch/filter and the poll's exit.
   **Dispositioned SKIP-with-tracking → bead `abn9.44.15`.** The lane traced it, confirmed it
   real, and found the same gap pre-exists on the `clean_reaction` and `clean_marker` paths —
   Codex flagged one instance, the lane found the pattern. Safe to defer because
   `check-merge-eligibility.sh`'s own `commit_id`-at-merge-time filter is the backstop
   (ROOT verified independently); damage is bounded to retry-budget accounting.
2. **Delta review on `dbe20f1`** (ROOT-owned) — **CLEAR. Nothing at or above MAJOR. This gate
   is SATISFIED.** #360 now waits only on the bot loop.
   Verified, each proved rather than argued: fail-closed preserved on **both** callers
   (`fetch_head_sha()` is a byte-for-byte lift of the original guards; `head_committer_epoch()`
   kept its own independent failure handling and did **not** inherit the review path's
   rejection semantics — that was the coupling risk and it did not materialize); dropping
   `|| current_head=""` is safe post-refactor (three exit paths, all rc 0; `gh_api` returns at
   most 1, absorbed by `|| return 0`, so `set -euo pipefail` cannot trip); no caching
   introduced, still one fresh call per poll iteration; test independence clean file-wide; and
   **the new tests genuinely discriminate — proved by mutation**, unlike `44.4`'s (11)/(12).
   Two NITs only (oversized header restating the inline comment; a test stub whose JSON
   default relies on quote-stripping). Textual trims need no re-review.
   ⚠️ **Premise correction — ROOT was wrong about the shape.** `dbe20f1` is a **single squashed
   commit** containing both the filter and the extraction; `git grep 'fetch_head_sha' dbe20f1^`
   returns nothing, so there was never a pre-refactor commit and the reviewed content existed
   only as an uncommitted working tree. The lane did **not** commit out of order. The concern
   was still valid (shipping artifact ≠ reviewed artifact) and the re-review was still correct
   — it just had to be framed semantically rather than as a diff. ROOT inferred a two-commit
   history from a prose report without checking `git log`. See L15-AMENDMENT.

**Watcher `watch-pr-360.sh` has RUNG and is DOWN.** It fired `class=FINDINGS` at t=120s and
exits after one ring. Re-arm it after the lane pushes fixes — nobody has coverage on #360
until that happens.

⚠️ **CI verification is still manual.** The `abn9.44.3` fix is merged to `src/`, but the
*installed* `check-merge-eligibility.sh` the guard actually executes is still the old copy
until Scott runs `scripts/install.sh` (ROOT must never run it). Until then `ci_state` will
keep reading `"none"` — verify CI directly with
`gh api repos/<owner>/<repo>/commits/<head>/check-runs` before every merge.

Watcher scripts live in `watchers/` beside this file (`watch-pr-353.sh` … `watch-pr-360.sh`),
rendered from the grind skill's template. Re-arm by running one directly with
`run_in_background` — never inside a wrapper with `&`. To render a new one, copy an existing
watcher and substitute the `PR="<n>"` line (line 78) — the rest of the config block
(`REPO`, `BOT_REVIEWERS`) is identical across all of them.

⚠️ **STATE LOCATION IS WRONG (user-directed, do not fix mid-run).** Grind state belongs at
`{project}/.grind/{worktree_slug}/`, not here. This run's path is wrong twice over: `.claude/`
is Claude Code's own config home and grind state is a *run artifact*, not tool config (and
parking it there makes portable discipline Claude-specific); and the directory is slugged by
**topic** ("codex-awareness") rather than by **worktree**, so a successor cannot mechanically
derive it. Moving now would break the bookkeeper's live `state.json`/`dashboard.html` paths
and the armed watchers, for no benefit — **do the move at shutdown**. The root cause is that
`orchestrated-grind` never specifies a state path, which is why this run invented one; file
that against the skill, not against this run. (Lesson L17.)

### Discovered work filed this run (P0, unowned, NOT in any lane queue)

- **`agents-config-wgclw.31`** — quality-gate workflow ignores its `repo_root` arg; finder
  agents inherit the caller's cwd and review the wrong worktree, returning a false clean.
  Caught live: a gate returned `exit=acceptance/clean-at-floor` on a change it never saw,
  which contained a BLOCKING defect. Notes carry a **validated** fix: the harness does not
  chdir, but interpolating a mandatory `git -C <repo_root>` directive into every finder
  prompt works, and an empty-diff tripwire (`GATE-HARNESS-ERROR`, never an empty findings
  list) makes any residual miss loud instead of silent.
- **`agents-config-wgclw.32`** — quality-gate refuter panel fabricated "this code does not
  exist" evidence and discarded a TRUE finding. `report_outcome()` is defined at line 262 of
  `request-rereview.sh` and called at six sites; both refuters claimed it existed nowhere.
  The destroyed finding was minor, but the mechanism is severity-blind, and
  unanimity-to-confirm lets a single fabricating refuter bury anything.

Both are anchored under `agents-config-wgclw` (M0) with `discovered-from` edges to the beads
that surfaced them; `.32` is `related-to` `.31`. They are DISTINCT defects with distinct
fixes. **Do not assign either to a lane.**

### Also filed this run (review-loop subsystem, under `agents-config-abn9.44`)

- **`agents-config-abn9.44.9`** (P1) — merge-guard SKILL.md's retry caller still handles only
  `RR_EXIT==0/1` and passes the full reviewer list to the poller, so a partial dispatch
  doesn't poll the bot that *was* asked and its retry can silently no-op. **In-scope
  deferral**, not discovery: abn9.44.2.9's DoD required both caller sites updated, and
  ROOT's lane partition made this half unreachable from lane-polling. Assigned to
  **lane-eligibility's queue**, position 2. When abn9.44.2.9 closes, its close note MUST
  record the endorsed descope naming this bead.
- **`agents-config-abn9.44.10`** (P1) — wait-for-pr-comments Phase 9 and
  check-merge-eligibility.sh disagree on when a SKIP thread is "settled", so a lane can pass
  its own review skill clean and still be blocked at the floor by the same thread. Cost a
  full diagnostic round on #354. Also covers the `thread_id`-vs-`reply_to_comment_id` trap
  (`filter-actionable-threads.sh` matches only on the GraphQL node id; a REST-built
  inventory has it null by construction and nothing validates it) and the misleading
  "unposted-SKIP" blocker wording, which describes a lost reply when the real condition is
  replied-but-unresolved.

- **`agents-config-abn9.44.11`** (P1) — the undelivered half of `abn9.44.2.9`'s DoD, which hid
  in that bead's NOTES field. **Delivered**, PR #359, in review.
- **`agents-config-abn9.44.12`** (P2) — merge-guard SKILL.md doc follow-up. HARD-BLOCKED by
  both `44.9` and `44.11`; deliberately sequenced so its text describes shipped reality.
  Assigned lane-eligibility. Verified absent from the ready queue.
- 🔴 **`agents-config-abn9.44.13`** (P1, label `deadline-2026-08-01`) — **LIVE DEFECT IN
  MERGED CODE, the most significant find of this run.** `request-rereview.sh` reports only the
  FIRST-matched alias per mechanism, so a successful Copilot dispatch emits
  `identity="Copilot"`; callers pass that narrowed set to `poll-copilot-review.sh
  --bot-reviewers`, which does EXACT login matching. Real Copilot reviews carry
  `copilot-pull-request-reviewer[bot]` — verified empirically on PRs 271/252/250/213, with
  plain `Copilot` on ZERO review objects across 8 PRs. A successful review therefore reads as
  a timeout, burning retry budget and blocking autonomous merge.
  **Shipped in PR #354's Phase 6 (line ~558) tonight.** Dormant only because Copilot is
  budget-dead until **2026-08-01**; Codex has one alias so it cannot be affected. It goes hot
  on that date with no further change.
  Found by Codex, not by any internal pass. Note the trap: the narrowing that FIXES the
  partial-dispatch bug is what INTRODUCED this — do not "fix" it by reverting to the full
  policy list, that regresses `44.2.9`/`44.9`. Recommended fix is producer-side (emit all
  aliases per dispatched mechanism); caller-side expansion was rejected as it duplicates
  mechanism-classification into every consumer.
  ⚠️ An automated verification pass concluded "NO DEFECT" here — it described pre-#354
  behavior and missed that the call site had changed. Do not re-derive this from that pass.

**Standing rule for every lane, learned here:** Phase 9 clean means "my triage is done," NOT
"this PR can merge." Run `check-merge-eligibility.sh` and report its exit code as the
evidence — never assert "reviewed-clean" off the review skill alone.

- **`agents-config-abn9.44.14`** (P2) — `poll-copilot-review.sh`'s INITIAL poll (no
  `--since-timestamp`) applies no freshness filter at all: any historical review, even
  against a stale commit, ends the poll as `completion_kind="review"`. **Pre-existing**, not
  introduced by `44.11` — but `44.11` widened the state filter to `APPROVED`, extending the
  gap onto a stronger signal. No unsafe merge results (the floor applies its own `commit_id`
  filter); the damage is the silent-ask counter failing to advance, leaking an ask past the
  cap. Assigned lane-polling, sequenced BEFORE `m5tkg` so freshness semantics settle before
  the `>=` vs `>` bound reconciliation. Distinct from `m5tkg` — absence of a comparison vs an
  off-by-one in an existing one. **Do not conflate them.** **DELIVERED — PR #360, awaiting
  two gates.**

- **`agents-config-abn9.44.15`** (P2, filed this run) — `poll-copilot-review.sh`'s completion
  paths lack a **final head re-read** before exiting (TOCTOU). Between the head fetch/filter
  and the exit there is at least one more network round-trip, so a push landing in that window
  makes the emitted completion stale against a head that has moved. Raised by Codex on PR #360
  against the review path only; **the lane traced it and found the same gap pre-exists on the
  `clean_reaction` and `clean_marker` paths** — this bead covers all three.
  **`44.14` did NOT introduce this race — it introduced the first freshness check precise
  enough to be raced.** Before it, that path had no freshness check at all, so "is the check
  racy?" was not a coherent question. Do not file or describe this as a regression.
  Fix direction: adopt `check-merge-eligibility.sh`'s existing HEAD_REREAD discipline rather
  than inventing a second pattern. No unsafe merge results (same merge-time `commit_id`
  backstop, ROOT-verified); damage is retry-budget accounting. Parented under `abn9.44`,
  provenance `discovered-from abn9.44.14` — **both edges verified present.**

- **`agents-config-wgclw.33`** (P1) — `gate_triage.py` counts only COMMITTED changes, so
  uncommitted `src/**` work reports `files=0` and routes **HEAVY → SERIAL** silently. Clean
  repro on a stable tree: identical content, uncommitted = `files 0`/SERIAL, committed =
  `files 2, loc 62`/HEAVY. The router and the HEAVY workflow disagree about what "the change"
  is — the workflow's finders examine committed UNION working-tree, the router does not.
  Third gate-measurement defect of the run, sibling to `.31` and `.32`.
  *Only found because ROOT refused to file the first (unstable) measurement and re-measured.*
  Also confirmed NOT a defect, so nobody re-files it: `gate_triage` handles a behind-base
  branch correctly — always diff against the **merge-base**, never a moved base.

**Standing rule for ROOT:** audit EVERY HEAVY gate run via an ephemeral subagent before
relaying a verdict. Confirm finders obtained a non-empty diff at the intended `repo_root` and
cited real code; independently re-check any finding the refuters eliminated. Of five gate runs
so far: one hollow (wrong worktree), two with fabricated refutations, one genuinely clean, one
unauditable.

**The gate is no longer trusted for a clean verdict — superseding rule.** Gate run
`wf_a0e6f00b-ac5` (bead 44.4) returned "clean-at-floor" with 3 of 4 finders empty. The diff
was independently confirmed real (2 files, +52/-9, tree clean at `744640e`), so empty findings
were not explained by an absent change — but the run could not be adjudicated either way,
because `journal.jsonl` logs only `{started}`/`{result}` envelopes: no cwd, no tool calls, no
command output. "Measured and clean" and "never measured" have identical journal
representations. The GATE-HARNESS-ERROR injection added after the first hollow run did NOT
fire and gave no signal in either direction.

Be careful stating this: the audit subagent reported "FALSE CLEAN," reading *no evidence they
reached the diff* as *evidence they did not*. Those are different claims — a finder that
genuinely reviewed 61 clean lines also returns `[]`. ROOT relayed only the weaker true claim.
Same discipline as the `wgclw.33` episode: do not let an auditor's overreach become the
finding.

**Therefore, for the rest of this grind:** a HEAVY verdict of "clean" with empty finder results
is NOT accepted as evidence. Replace it with a directed reviewer — explicit worktree-absolute
`repo_root`, a mandatory first-action `git -C <root> diff <merge-base> --stat` it must quote,
an instruction to STOP on an unexpected diff, and the anti-fabrication rule (no absence claim
without quoted `git grep` output). That play produced real findings on 44.14 and 44.4; the gate
produced none on either. `wgclw.31` has been escalated with this second occurrence and two
added acceptance criteria (finders must log cwd + the diff stat they measured; synthesis must
refuse to emit acceptance from traceless empty results).

All beads synced to the Dolt remote (`bd dolt commit` + `bd dolt push`, push confirmed).

### Standing consequence for this grind

This gate's "clean" is not trustworthy on its own. ROOT's practice, which should continue:
after every HEAVY run, dispatch an ad-hoc ephemeral subagent to audit the journal —
confirm finders obtained a non-empty diff at the intended `repo_root` and cited real code,
and independently re-check any finding the refuters eliminated. Two of three gate runs so
far were defective, and in both cases the returned payload looked identical to a real pass.
`agents_empty_result` in the usage block is a hint, not a verdict — it read "3 of 4 empty" on
both a hollow run and a genuine one.

## 5. Human's docket

**EMPTY.** The one item that was here — PR #353 blocked at the approver step — was resolved:
Scott granted the `approve_pr.py` permission and both PRs merged. Historical detail retained
below because the failure mode will recur in any auto-mode grind, and because L2 in
`LESSONS.md` proposes fixing it at the skill's setup sequence.

### RESOLVED — PR #353 was eligible and authorized, blocked on a harness permission

- merge-guard floor: **exit 0, `blockers: []`**, re-cleared immediately before the merge
  attempt with head (`534f8ffb185d`) and base (`d935bf36f451`) unchanged.
- Policy `rule-based` / `bot-quiescence`; the rule **holds** —
  `bot_clean_review_at_head=true`, `bot_clean_signal_source=reaction`, Codex `+1`
  reaction id **415744809** at **2026-07-19T16:32:35Z**. (A reaction leaves no timeline
  history, so those identifiers are the audit trail.)
- **CI: verified independently.** The guard reported `ci_state="none"` — which is the
  exact defect this PR fixes; the *installed* `check-merge-eligibility.sh` is the unfixed
  copy and is blind to Ruleset-enforced checks. ROOT did not accept that vacuous pass and
  checked directly: `ci | completed | success` at the head. Genuinely green.
- `reviewDecision` is `REVIEW_REQUIRED`. The approver App is configured and
  `MERGE_GUARD_APPROVER_KEY_PATH` is set with the key present at
  `~/.config/merge-guard/approver.pem`.
- **Blocker:** the Claude Code auto-mode classifier denied execution of `approve_pr.py`.
  A harness permission denial, not a policy or eligibility failure. ROOT did not attempt
  to route around it — laundering a blocked approval through another tool is exactly the
  thing that must never work.

Options: (1) grant the Bash permission for `approve_pr.py`; (2) approve/merge #353 in the
UI; (3) hand off and keep the lanes moving.

**A successor ROOT must NOT retry `approve_pr.py` hoping for a different answer.** If the
permission is still denied, the item stays on this docket. (Standing grant already on file: Scott has authorized autonomous merge of eligible
PRs on this repo via merge-guard + the App approver — do NOT add a per-PR merge checkpoint
on top of the rule-based policy.)

## 6. Operating protocols in force

- **Partition rule.** `check-merge-eligibility.sh` is the god file (4 beads touch it) —
  lane-eligibility owns it exclusively. `wait-for-pr-comments/SKILL.md` is referenced by
  beads in BOTH lanes; **lane-polling owns it outright**, lane-eligibility escalates to
  ROOT for any edit there. One author per file.
- **Message crossing (§2).** A lieutenant report that seems to ignore a standing order is
  almost certainly stale. Check timestamps and verify with `gh`/`git`/`bd` before nudging.
- **Idles (§1).** A bare idle means PARKED. Never reply to one, never log one, never let
  one trigger anything. Silence materially longer than the work should take IS a trigger —
  verify with `gh`/`git`/agent status, not by messaging the lane.
- **Nesting trap (§3) — this grind's biggest deadlock risk.** `wait-for-pr-comments`
  dispatches a per-comment fixer subagent per FIX item, and those completions wake ROOT,
  not the lieutenant that spawned them. Lanes were briefed that they will park, and that
  **ROOT relays each worker/fixer completion back to the owning lane and re-engages it.**
  A lane left un-relayed sits idle forever holding finished work.
- **Review protocol.** Active path is the `wait-for-pr-comments` skill. Do NOT use
  `monitor-pr` (prgroom CLI not deployed here). Codex is the reviewer, triggered by an
  "@codex review" PR comment. Copilot is budget-dead until 2026-08-01. Meta/bookkeeping
  SKIP items get an inventory disposition but their IDs go to
  `post-replies.sh --skip-comment-ids` — never post "no action required" replies.
- **Stalemate ladder.** Rounds of REAL defects = reviewer working, keep going. Only
  re-raises on UNCHANGED code are a stalemate; spend exactly one do-not-relitigate round
  (hand over settled dispositions + evidence) before escalating. A re-flag of an
  already-made fix => check `git show <sha>:<path>` at the commit the reviewer claims it
  reviewed; that is malfunction, a different escalation path.
- **Merge authority (§4).** ROOT merges, lanes never do. Per PR: lane reports
  reviewed-clean -> ROOT invokes `merge-guard` (its eligibility run IS the verification;
  do not hand-roll a `gh` sweep) -> ROOT runs the head-pinned command it hands back.
  Sort blockers by who can clear them: `escalations_pending` and
  `requested_changes_active` are human-clearing; `unresolved_threads`,
  `untriaged_feedback`, `ci_not_green` go back to the lane.
- **Watchers (§6).** ROOT arms every watcher from
  `/Users/scott/.claude/skills/orchestrated-grind/scripts/watch-pr.sh.tmpl`, launched
  DIRECTLY via `run_in_background` (never wrapped with `&` — the wrapper orphans it).
  60s interval, 30min timeout. Must count reactions, including nested ones. Classes:
  FINDINGS > CLEAN > IN-FLIGHT > ACTIVITY, most severe wins, never most recent. A class is
  a routing hint, never authorization. Two or three inconclusive re-arms = suspect the
  watcher, spot-check the PR directly.
- **Completion gate.** Everything here is under `src/**`, which floors the gate at HEAVY:
  `gate-triage` helper -> `Workflow({name:"quality-gate", args:<triage JSON>})` (args
  REQUIRED, it sizes the fleet) -> `verify-checklist` (non-substitutable). Lieutenants own
  gate steps needing a separate agent; workers self-gate inline only and spawn nothing.
- **Post-merge leg** (lieutenant's job): leave the worktree first, remove it,
  `git branch -D` (squash reads as unmerged), `bd --append-notes` with PR number + merge SHA,
  `bd close`, check parent epic but DO NOT auto-close, then `bd dolt commit && bd dolt push`.
- ⚠️ **NO LANE TOUCHES LOCAL `main` — amended mid-run, and the amendment is load-bearing.**
  The skill's stock post-merge leg tells *each lieutenant* to fast-forward main, which in a
  multi-lane grind is a shared mutable resource with no owner. Both lanes did it within a
  minute of each other with **different strategies** (rebase vs `merge --no-ff`) and it only
  came out clean by ordering luck. That step is now **ROOT's**, performed once from the main
  tree. Lanes create worktrees off **`origin/main`** explicitly
  (`git worktree add <path> -b <branch> origin/main`), never off local `main`.
- **Report what git shows, not what the command intended.** A lane reported creating a merge
  commit that did not exist. After any history operation, read `git log --oneline -3` and
  `git status -sb` and report the observation. Same discipline as reporting the merge floor's
  exit code instead of asserting "reviewed-clean."
- **Scott has an unpushed commit on local `main`** (`1054517`, `docs(worktrees)…`). It is his
  to push. Do not push local `main`; doing so publishes his work without his say-so.
- **Dashboard.** Opened exactly once by the bookkeeper. Never re-open. If it looks stale,
  check `state.json`'s timestamp. Browser-automation tools are prohibited for opening it.

## 7. Repo quirks and traps

- Edit source under `src/**` ONLY. `~/.claude/...` is deploy output, overwritten on install.
- **NEVER** run `scripts/install.sh` / `install.py` — user-only.
- The installed skill copies are STALE relative to `src/**` until an install runs. Lanes
  editing `wait-for-pr-comments` scripts must run the INSTALLED copy for actual review work
  while editing the `src/**` source.
- Never run `graphify update` from a worktree; never stage `graphify-out` in a feature PR.
- Skill Python/bash in this repo holds to `ruff check` clean but NOT `ruff format` —
  compact hand-formatting is house convention. Probe a sibling before reformatting.
- Other live sessions exist in `.claude/worktrees/` (viz-*, trunk-*, prgroom-*, docs, feat,
  fix, grind-30-1, cx6.7.3-*). Do not touch worktrees this grind did not create.
- The git stash stack is shared across worktrees — never bare `git stash`/`pop`.
- ROOT's own cwd is the `live-codex-verification` worktree; the lanes work from
  `.claude/worktrees/elig-*` and `.claude/worktrees/poll-*` off `main`.
