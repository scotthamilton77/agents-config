# HANDOFF — lane-eligibility

Self-contained. Written at HALT (Scott stopped the run). Assume the reading
lieutenant has none of this session's transcript.

## 1. Queue status

Original queue (in order): `abn9.44.3`, `abn9.44.4`, `abn9.44.6`, `abn9.44.8`.
`abn9.44.9` was inserted ahead of `abn9.44.4` mid-run by ROOT (see below).

| Bead | Status | Notes |
|---|---|---|
| `agents-config-abn9.44.3` | **CLOSED, MERGED** | PR #353, merge commit `8f8ff298bc0f49d6fbe1faaf706861a8970c7e14`. Ruleset-sourced CI-green union fix. Validated end-to-end on live data (worktree copy correctly read `ci_state="green"` where the stale installed copy still says `"none"`). |
| `agents-config-abn9.44.9` | **CLOSED, MERGED** | PR #356, merge commit `aa7462d7cb7594f870a30d96319532cdb6d16e6a`. merge-guard SKILL.md retry caller: consume request-rereview.sh NDJSON, handle `RR_EXIT==3` partial dispatch. Inserted into the queue by ROOT ahead of 44.4 (see ORCHESTRATION-STATE.md for why). Closed CLEAN, no descope — its own DoD was fully delivered. |
| `agents-config-abn9.44.4` | **IN FLIGHT, NOT MERGED, PR NOT YET OPENED** | See section 2 below — this is the valuable part. |
| `agents-config-abn9.44.6` | **UNTOUCHED** | Never started. |
| `agents-config-abn9.44.8` | **UNTOUCHED** | Never started. |

## 2. `abn9.44.4` — full history, four attempts, why each was rejected

**Bug**: `check-merge-eligibility.sh`'s `is_trigger_comment` predicate exempts
`request-rereview.sh`'s "@codex review" re-review-ask comment from the
`untriaged_feedback` blocker. The original predicate required the comment
body, whole and trimmed, to equal exactly `"@codex review"`. But
`request-rereview.sh` renders a multi-line body (disposition table, focus
line) whenever `--disposition-table-file`/`--since-sha` are supplied — so
the tool's own re-ask comment failed its own exemption and blocked its own
merge.

**Worktree**: `/Users/scott/src/projects/agents-config/.claude/worktrees/elig-44-4`
**Branch**: `fix/44-4-trigger-comment-match`
**Current HEAD**: `00fd5c4c0dc9b8f379aaabb8db86ebeac2b7badf`
**Pushed**: NO. `git status --porcelain` is empty (nothing uncommitted) but
the branch has never been pushed to `origin` — no remote branch, no PR.
Confirmed via `gh pr list --head fix/44-4-trigger-comment-match --state all`
(empty) immediately before writing this file.
**Base**: branched from `origin/main` at `aa7462d` (post-#356). `origin/main`
has since moved further (at least to `cbe3e6c2` / PR #359, possibly beyond —
check current `origin/main` before resuming). Do not assume `aa7462d` is
still current.

### Attempt 1 — commit `2589dbe` (superseded)

Matched on the body's FIRST LINE only (trimmed) being exactly `"@codex
review"`, instead of the whole body.

**Rejected — MAJOR from a directed reviewer.** Too wide: ANY body whose
first line trims to `"@codex review"` was exempt regardless of what
followed. Realistic case: a human types `"@codex review"` then appends real
feedback on the next line (e.g. "also please fix the null deref in
foo.go"). Pre-fix that blocked (correctly). Post-fix it silently vanished
from `untriaged_feedback`. Proven via `"@codex review\nrm -rf /"` reading as
exempt.

A companion commit `744640e` on the same branch fixed an UNRELATED
self-inflicted bug: new tests (10)-(12) had been inserted between an
existing test's `run_script` call and its second assertion, so that
assertion silently checked the wrong test's `$rc`. Caught by ROOT via
arithmetic (claimed 4 new tests, count only went up by 3 — the mismatch
itself was the bug report). Not part of the design rejection; a process
lesson about test insertion adjacency.

### Attempt 2 — commit `882d2b6` (superseded)

Replaced first-line matching with two conditions: (a) whole body exactly
`"@codex review"` (human bare case, unchanged/narrow), OR (b) body
`contains()` a machine marker — an HTML-comment sentinel
(`<!-- agents-config:codex-rereview-ask -->`) that `request-rereview.sh` now
emits on the disposition-table branch and the truncation-fallback branch
(the bare case is deliberately untouched — it already matches via the exact
clause, so it never needed the marker, which also meant NOT touching
`request-rereview_test.sh`, whose two exact-string assertions on the bare
case would otherwise have broken).

Design note preserved because it is genuinely good and should survive into
whatever attempt 5 becomes: keeping `"@codex review"` as the literal first
line always, with the marker as a separate line, decomposes the exemption
into two INDEPENDENT narrow conditions rather than one condition doing
everything. Keep this shape.

**Rejected — MAJOR, found by ROOT before a reviewer even ran.** GitHub's
"Quote reply" feature copies a comment's raw markdown SOURCE, HTML comments
included, prefixing every line with `"> "`. A human quote-replying the
tool's marker-bearing re-ask and appending feedback below still has the
marker present in the body (just prefixed) — `contains()` wrongly exempted
it. Verified via web search (not assumed): GitHub's quote-reply operates on
markdown source, not rendered text (evidenced by a documented artifact
where quoted markdown lists turn into code blocks).

### Attempt 3 — commit `2749572` (superseded)

Replaced `contains()` with positional exact-line matching: `lines[0]`
(trimmed) must be exactly `"@codex review"` AND `lines[1]` (trimmed) must be
exactly the marker. Quoting breaks this structurally — a quoted line reads
`"> <!-- ... -->"`, never equal to the bare marker.

Also added: a cross-file consistency test extracting the marker literal
from both `check-merge-eligibility.sh` and `request-rereview.sh` via grep
and asserting equality (turns the "MUST match" code comment into an
enforced check). ROOT explicitly asked for this; keep it, and extend it to
any new markers attempt 5 introduces.

**Rejected — MAJOR.** Lines 2..n are completely unconstrained. A body with
the opening marker correctly on line 2 and arbitrary appended content below
(e.g. mid-body, or after everything) still matched. Concretely: the tool
posts under `$auth_login`, and the author guard admits both `$pr_author`
and `$auth_login` — a human with either identity (which, in this repo's
actual deployment, is the SAME person as the one running the automation)
could edit the tool's own posted comment, or hand-author a fresh one, to
append real feedback that rides through unexamined.

### Attempt 4 — commit `00fd5c4` (superseded, most recent)

Added a CLOSING marker (`<!-- agents-config:codex-rereview-ask-end -->`) as
the mandatory LAST line of the body, in addition to the two opening-fence
lines. `request-rereview.sh` now emits it unconditionally at the end of
`_render_codex_comment_body()` (covers both the disposition-table branch
and the since-sha-only branch, since both fall through the same tail) and
in `build_codex_comment_body()`'s truncation-fallback branch. Bare case
still untouched.

Also fixed a genuine bug in my OWN test fixture during this round, not the
implementation: a heredoc piped straight into `jq -Rs` carries a trailing
newline the real producer's `$(...)`-captured output never has (command
substitution strips it), so `split("\n")` produced a spurious trailing
empty element and the closing-marker check failed for the wrong reason.
Verified the real producer's actual byte output with a fake-`gh` capture
harness + `od -c` before concluding this was a fixture bug, not an
implementation bug. Fixed by capturing the fixture body via `$(...)` too.
**Lesson for future body-shape fixtures in this file: always capture through
the same command-substitution path the producer uses — do not pipe a
heredoc straight into `jq -Rs`.**

Also flagged, NOT yet folded in (see section 4): a NIT in
`request-rereview.sh`'s truncation-fallback branch — it uses bare `echo` for
the closing marker outside any `$(...)`-stripped path, so it's only correct
today because the CALLER (`request_codex`) does
`body="$(build_codex_comment_body)"`. Should use `printf '%s'` directly like
elsewhere, per ROOT.

**Rejected — MAJOR, proven by a reviewer running the actual predicate (not
just reasoning about it).** The closing sentinel moved the unconstrained
region, it did not remove it. Lines `2..n-1` (between the two fences) are
still completely free. Proof body (framed as a human editing the tool's own
posted comment):

```
@codex review
<!-- agents-config:codex-rereview-ask -->

Prior-round findings:

Also please fix the auth bypass in login.c before merging.
<!-- agents-config:codex-rereview-ask-end -->
```

Both fences present and in the right position; the injected line sits
between them; predicate returns exempt; should block. Also demonstrated:
closing marker present twice with feedback between the two occurrences, and
markers embedded inside a code fence. Author guard confirmed NO help — the
probe ran as `alice` = `$pr_author`, exactly the threat model in question
(it DOES correctly reject a third-party `mallory`, so the guard itself is
fine — the marker predicate is the gap).

### RULING (decided after HALT, still unwritten as code)

ROOT ruled **immutability-only, no digest** — matching the position I
argued below. Explicit confirmation quoted: "RULING: immutability-only. No
digest. Your analysis is right... An unkeyed digest checked into an
open-source repo is a speed bump wearing a cryptography costume. Do not add
it." The halt still stands regardless — **attempt 5 was NOT coded.** No
commit beyond `00fd5c4`. See "Design discussion" below for the full
reasoning; it does not need to be re-derived.

**Exact consumer change for attempt 5** (not yet written):
`is_trigger_comment`'s marker-fenced clause (the `(b)` branch — lines[0],
lines[1], last-line checks already in `00fd5c4`) gets ANDed with one more
condition on the SAME matched comment object: `.created_at == .updated_at`.
The bare exact-whole-body clause (`(a)`) is untouched — do not add the
immutability check there. Reasoning: editing a GitHub comment REPLACES its
body, it does not append to it, so a human editing their own feedback down
to exactly `"@codex review"` has not hidden anything — the post-edit body
genuinely IS just the trigger phrase, nothing more, and that is
functionally a legitimate retraction of their own prior content, not a new
way to hide feedback. The immutability requirement is only needed on the
marker-fenced clause, because THAT is the clause with room for hidden
appended/injected content between two fixed anchors.

**The residual is filed**: `agents-config-abn9.44.18` (P2, open, parent
`agents-config-abn9.44`, `discovered-from` edge to `agents-config-abn9.44.4`,
full triage block already attached — ROOT filed it, since I reported a
clean stop before actually filing it and ROOT caught the gap). I also
independently filed a duplicate, `agents-config-abn9.44.17`, moments later
by mistake (we filed at nearly the same time); I closed mine as a duplicate
of `.18` once I noticed. `.18` is the canonical one — do not re-file this
residual again.

### Design discussion at HALT — background for the ruling above

The reviewer that found attempt 4's defect offered three candidate
directions:

1. **Producer-known fixed offset for the closing marker.** ROOT's own read:
   brittle the moment a branch changes line count. Weakest option.
2. **Producer emits a content digest inside the opening marker; consumer
   recomputes over lines `2..n-1`.**
3. **Drop body-shape matching for THIS axis; key on comment immutability.**
   GitHub exposes `created_at` vs `updated_at` on issue comments (already
   present in the `ISSUE_COMMENTS` fetch at
   `check-merge-eligibility.sh:636` — `repos/{o}/{r}/issues/{n}/comments`,
   no extra API call needed). An edited comment (`updated_at !=
   created_at`) would never qualify for the marker-fenced exemption.

ROOT's own stated read, which I (lane-eligibility) was in the middle of
responding to when Scott halted the run: "(3) alone is also incomplete — it
defends the *edit* path but a human can hand-author a fresh, never-edited
comment carrying both markers and injected middle text, and that comment
passes immutability trivially. (2) is the only one that binds interior
content to something the producer alone can compute, and it composes with
(3)."

**My (lane-eligibility's) design position, sent to ROOT but NOT yet
ruled on before the halt** (see the message logged in this session — not
reproduced verbatim here since this file must stand alone, but summarized):

I argued for **(3) alone**, not (2)+(3), on the grounds that:

- No purely content-shape check — including a digest — is a real
  cryptographic security boundary here, because `request-rereview.sh` posts
  as `$auth_login`, the SAME GitHub identity the human at the keyboard
  controls in this repo's actual deployment (a local agent session running
  under Scott's own `gh` auth, not a separate bot/App identity with its own
  credential). An UNKEYED digest (no secret unavailable to the account
  holder exists in this design) only raises the bar from "type text" to
  "run one more shell command" — it does not close the gap against a
  determined actor, only against an accidental/naive one.
- Every CONCRETELY PROVEN exploit across all four attempts, including
  attempt 4's, was framed as **editing an already-posted comment**. (3)
  alone closes every demonstrated exploit outright, with GitHub's own
  server-side timestamps (genuinely unforgeable) and ZERO producer changes
  — no new marker, no new drift-risk surface.
- The residual (3) leaves — a PR author willing to read this open-source
  predicate and hand-author a fresh, never-edited comment matching the
  fence shape exactly — requires DELIBERATE, source-code-level sabotage of
  one's own merge gate by the PR's own author. That is a different,
  arguably out-of-scope threat class from the accidental/natural-behavior
  bugs this whole round of fixes has been about (a human typing a genuine
  follow-up, a natural quote-reply, editing a comment to add more). I
  argued the REAL permanent fix for that residual is giving
  `request-rereview.sh` its own dedicated bot/App identity (the same class
  of mechanism `merge-guard`'s own `approve_pr.py` already uses via
  `MERGE_GUARD_APPROVER_KEY_PATH`) so the exemption can key on an
  unforgeable GitHub-enforced author login instead of body-shape matching
  at all — eliminating this entire arms race. I recommended that as a
  SEPARATE bead (new infrastructure/provisioning, outside a same-round code
  patch), not something to attempt now.

**This has since been ruled on — see the "RULING" section above.**
Immutability-only, no digest, matching my position below. **Attempt 5 has
still not been started — no code, no tests, no commit beyond `00fd5c4`,**
because the halt order and the ruling crossed in flight and the halt takes
precedence. The next lieutenant can start coding attempt 5 directly from
the "Exact consumer change" spelled out in the RULING section — no need to
re-litigate the design question.

If resuming: the immutability check (`.created_at == .updated_at` on the
matched issue comment) is cheap to verify is even wired correctly — the
`ISSUE_COMMENTS` array already carries both fields from the standard
GitHub REST payload; I did not add any test or implementation code for it,
only confirmed via `grep` that the fetch already has the data available.

## 3. `request-rereview.sh` ownership loan

**I (lane-eligibility) hold write access to
`src/user/.agents/skills/wait-for-pr-comments/request-rereview.sh` (and by
extension its co-located test `request-rereview_test.sh`, though I have NOT
touched the test file) UNTIL `abn9.44.4` merges.** This is an explicit,
formal loan ROOT granted and announced to lane-polling — normally that whole
`wait-for-pr-comments/` directory is off-limits to this lane. Do not let a
fresh lieutenant assume it's still off-limits, and do not let lane-polling
resume editing it while `44.4` is open. Confirmed clean before the halt:
lane-polling's own `poll-m5tkg` worktree was based at `1d6379c` and had not
touched this file — no collision as of the halt.

**Outstanding NIT not yet folded in** (flagged by ROOT on attempt 4's
review, still open at `00fd5c4`): `request-rereview.sh` lines ~233-238 (the
`build_codex_comment_body` truncation-fallback branch) uses bare `echo` for
its lines, including the closing marker, OUTSIDE the `$(...)`-stripped
capture path — it is only correct today because the caller
(`request_codex`) wraps the whole call in `body="$(build_codex_comment_body)"`,
which strips the trailing newline as a side effect of ITS OWN capture, not
because that branch was written defensively. ROOT wants `printf '%s'` used
there instead, matching how the OTHER four marker-emitting call sites are
written, so the "closing marker is unconditionally the last line" claim in
the comment above it is actually true by construction rather than true by
caller accident. This is small and mechanical — fold it into whatever
attempt 5 becomes, do not ship attempt 5 without it.

## 4. Everything else I know that is not written anywhere else

- **Local `main` is NOT to be touched by any lane** — a standing rule ROOT
  established mid-run after two lanes independently tried to reconcile it
  with different git strategies (rebase vs merge) within about a minute of
  each other. ROOT owns local `main` exclusively now. New worktrees branch
  off `origin/main` directly (`git worktree add <path> -b <branch>
  origin/main`), never off local `main`.
- **The worktree flapping phenomenon**: earlier in this session (around
  attempt 1/`744640e`), `git status --short` on this exact worktree gave
  three different answers across three reads about two minutes apart
  (clean → 2 files modified → clean). Root cause was never determined.
  Content was never lost — verified via `git show HEAD:<path>` matching the
  live file, and via 3 consecutive stable reads before committing. Treated
  as transient/environmental, not a bug in any script. If it recurs: do NOT
  assume data loss, re-read 2-3 times with a short pause before concluding
  anything, and commit as soon as the tree reads stable twice in a row.
- **The HEAVY gate's reliability is actively in question this session.**
  ROOT filed `agents-config-wgclw.31` (finder agents inherit the CALLING
  session's cwd instead of the target `repo_root`, causing false-clean
  results on the wrong worktree) and `agents-config-wgclw.32` (the gate's
  refuter panel fabricated "this code does not exist" and destroyed a true
  finding — confirmed twice this session, a 2-for-2 false-refutation rate).
  ROOT now personally audits every HEAVY gate run rather than trusting a
  "clean" verdict at face value. If a fresh lieutenant gets a suspiciously
  clean gate result on a non-trivial change, do not treat it as authoritative
  without asking ROOT to confirm the audit.
- **CI verification is still manual for anything merge-adjacent.** The
  `abn9.44.3` ruleset-CI-union fix IS merged to `src/`, but the *installed*
  copy of `check-merge-eligibility.sh` that the guard actually executes at
  runtime is still the OLD, pre-fix copy until Scott personally runs
  `scripts/install.sh` (no agent may run it). Until then, `ci_state` will
  keep reading `"none"` from the installed copy even though the source fix
  is correct — verify real CI status directly via
  `gh api repos/<owner>/<repo>/commits/<head>/check-runs` before trusting
  any merge-eligibility read that depends on it.
- **I did not open a PR for `abn9.44.4`.** All four attempts happened
  entirely within the local worktree, reviewed by ROOT's dispatched
  reviewers reading the worktree directly (not via a GitHub PR diff). No
  `@codex review` was ever triggered for this bead. When attempt 5 is
  designed, coded, and reviewed clean, the PR-open step is still fully
  ahead — do not assume any part of the normal PR/review/merge chain has
  happened for this bead yet.
- Full ledger of merged PRs, other lanes' state, and further background
  context lives in `ORCHESTRATION-STATE.md` and `LESSONS.md` in this same
  directory — I did not duplicate that here except where it directly bears
  on this lane's own work.
