# gitclean redesign — sweep what merged, report the rest

**Status:** implemented — shipped as `packages/gitclean/`, on PATH, driven by the `/clean-up-git` command
**Parent:** `agents-config-9k9.53`
**Supersedes:** the fix slices `agents-config-9k9.53.2` – `.53.5`, all closed wont-fix.
**Evidence:** `SAVEPOINTS/gitclean-9k9-53/review-round-3/FINDINGS-REVISED.md`, in the
`scotthamilton77/agents-config-ARCHIVE` repository — 13
confirmed findings, each reproduced against `a8c6401` with the exact command.

## 1. Why this is a redesign and not another fix round

Three remediation rounds each passed their gate and each shipped new defects of the same
shape. The previous reassessment diagnosed prose-stated invariants enforced point-wise,
and removed `--clean-all` on the principle *delete by proof, not by exclusion*. The
re-triage measured what that bought on the surviving findings: **nothing**. All 13 still
reproduce, and six became reachable *more* cheaply, because `--clean-all` implied
`--force` and the paths that replaced it do not. Seven now fire on a bare `gitclean
--cleanup` with no flags at all.

That principle was right and stopped one level short. This spec finishes the move.

### The root cause, in one line of code

`execute.py:257` deletes with `git branch -D`. Measured directly:

| case | `git branch -d` (git's own interlock) |
|---|---|
| unmerged branch, 3 commits, remote copy gone (finding 2) | **refuses** — "not fully merged" |
| genuinely merged branch | deletes |
| **squash-merged branch** | **refuses** — git cannot see squash merges |
| clean detached worktree holding an orphan commit (finding 5) | *n/a — `git worktree remove` allows it* |

Git already refuses finding 2's deletion. The package discards that refusal on every
delete and reimplements it in Python, where findings 1, 2 and 4 live.

It has to. Row 3 is the reason the tool exists: `git branch -d` refuses squash-merged
branches, so a `-d`-only cleanup never cleans anything in a squash-merge workflow. Real
merge evidence is required, and acting on it requires `-D`. **The moment you pass `-D`
you own every deletion decision in the repository.**

"Prove this deletion is safe" is then a *total* function over every repository state that
exists — detached HEADs, prunable records, unmounted volumes, server-only commits,
refs named `-m`. Each review round found another uncovered state, because the model must
be complete to be safe. "Only delete what I can prove is merged" is a *partial* function:
an unproven target simply appears in the report. Failure costs a leftover branch instead
of someone's work.

### What the evidence says to keep

**Zero of the 13 findings are in the merge-evidence tiers.** They sit in the risk model
(5), salvage and verification (3), survey assumptions (4), and plan reporting (1). The
expensive, genuinely hard part — resolving merges through PR state, ancestry, patch-id
and squash-equivalence — is the part that works. It stays.

## 2. Decisions

- **D1 — Two outcomes, not two verdicts.** A target is either *provably merged* (the tool
  may delete it unattended) or *reported with measured facts* (only the user may
  authorise deleting it). The `Disposition` × `Risk` model, the `Risk` enum, and the
  refusal ladder built on them are removed.
- **D2 — Proof means merge evidence and nothing else.** The tiers stay exactly as they
  are. A closed-unmerged PR is **not** proof; `MergeEvidence.PR_CLOSED_UNMERGED` stops
  authorising deletion and becomes a reported fact. This alone retires findings 2 and 4.
- **D3 — The report states measurements, never inferences.** No verdict word is derived
  from a proxy. "Abandoned" is not computed; the report carries the commit date, branch,
  upstream state, PR state and file counts, and the human draws the conclusion.
- **D4 — Never assert an answer a probe did not give.** Where a probe cannot run, the
  report says so in that item's own row. An unknown never renders as a fact and never
  enters the sweep. This is the existing `unanswered_probes` rule, applied without the
  short-circuits that currently bypass it.
- **D5 — Authorised deletion is not re-adjudicated.** When the user names a target, the
  tool deletes it and reports the outcome. It does not re-derive safety, refuse, or
  demand `--force`. The reflog is the undo for local branches; git's own refusals still
  apply where they are not explicitly overridden.
- **D6 — Server refs are never swept unattended.** Remote deletion is irreversible for
  everyone fetching and has no reflog. It requires an explicit named target every time.
- **D7 — Salvage is retained only where no reflog exists.** That is remote-ref deletion,
  and D6 already makes it explicit and rare. Local-branch bundling is removed; `git
  branch -D` leaves the commit in the reflog for the configured expiry.
- **D8 — The tool never deletes the directory it is running from.** Resolve the invoking
  worktree at survey time and exclude it from every plan.

## 3. What is removed, and what each removal takes with it

| Removed | Findings retired |
|---|---|
| The `Risk` enum and `_branch_risk` / `classify_worktree` risk assignment (D1) | 2, 4, 5 |
| Closed-unmerged PR as a deletion authority (D2) | 2, 4 |
| Derived lifecycle verdicts — `abandoned`, `active`, idle windows (D3) | 13 |
| `--base` as a caller-supplied merge target (D1, D2) | 1 |
| Unattended remote deletion, and the `Skipped` bookkeeping it needed (D6) | 12 |
| Local-branch salvage bundles (D7) | 9, 15 |
| Post-delete re-verification of what git already reported (D5) | 11 |

Findings **3**, **6**, **10** and **14** survive the redesign as ordinary bugs and are
fixed on their merits — each is small, and each is an instance of D3 or D4:

- **3** — `resolve_default_branch` returns origin's published HEAD unverified, so a
  dangling `origin/HEAD` names a trunk that does not exist, no branch is protected, and
  the warning that would say so is suppressed because the guess is recorded as knowledge.
- **6** — the invoking worktree is never protected; the run deletes its own cwd and every
  later git call in the same process fails.
- **10** — `prunable` is read as "directory is gone" and dirt is asserted `(0,0,0)`; git
  reports prunable when the path is merely unreachable, so a moved-aside tree holding
  uncommitted work is reported empty.
- **14** — `--untracked-files=normal` collapses a directory to one status line, so 40,000
  files under `node_modules/` are disclosed as one.

## 4. Acceptance criteria

- **GCR-A1** The sweep deletes a target only when `MergeEvidence` is one of
  `PR_MERGED`, `ANCESTOR`, `PATCH_EQUAL`, `SQUASH_EQUAL`. Every other target — including
  `PR_CLOSED_UNMERGED` and every unresolved probe — appears in the report and is never
  deleted without being named.
- **GCR-A2** No `Risk` type, no derived lifecycle verdict, and no idle window remains in
  the codebase. Report rows carry measurements only: commit date, branch or detached
  HEAD, upstream state, PR number and state, and file counts.
- **GCR-A3** A squash-merged branch is still swept. An integration test performs a real
  squash merge and asserts the sweep removes the branch, pinning the one capability that
  justifies bypassing git's own refusal.
- **GCR-A4** Every probe that fails renders as a stated unknown on the affected item's
  row. No unknown is rendered as a fact, and no item with an unknown enters the sweep.
  A dangling `origin/HEAD` resolves to no default branch and says so.
- **GCR-A5** Untracked and ignored file counts are true file counts. A worktree holding
  an ignored directory of 500 files reports 500, not 1.
- **GCR-A6** A worktree git reports `prunable` is never asserted clean. Its dirt is
  reported unknown and it is excluded from the sweep.
- **GCR-A7** The worktree the process is running in is excluded from every plan, and a
  run that names it is refused with its path.
- **GCR-A8** Remote refs are deleted only when named explicitly. No bare sweep, under any
  flag combination, issues `push --delete`.
- **GCR-A9** A named deletion is executed and its outcome reported without
  re-adjudication. A deletion git performed successfully is never reported as a failure.
- **GCR-A10** Where salvage is retained (remote refs), the bundle is proven by the
  restore route the tool prints: a test restores from the bundle and asserts the content
  is present. A bundle that cannot restore is never recorded as verified.
- **GCR-A11** Every repo-derived name reaching git is argv-terminated through one
  constructor. A branch named `-m` survives a full sweep-and-delete cycle.
- **GCR-A12** A reachability assertion covers every mutating test: snapshot reachable
  commits before the mutation, assert nothing reachable became unreachable unless it sits
  in a salvage proven by restore.
- **GCR-A13** Each of the 13 findings in the revised list is closed by a named test, or
  dispositioned in writing with the reason it cannot occur in this design.

## 5. Slices

Ordered. Each is independently gateable.

### Slice A — the reachability oracle (GCR-A12)

Lands first so the rework is written against the invariant rather than measured after.
Carries **GCR-A12**. This is the one part of the retired `.53.2` worth keeping verbatim:
229 example-based tests at 98% branch coverage missed roughly a quarter of the defects in
new code, because each test encodes a topology its author already imagined. The oracle
asserts the property instead.

### Slice B — collapse the verdict model (GCR-A1, GCR-A2, GCR-A3)

Delete the `Risk` enum, `_branch_risk`, the lifecycle derivation and the refusal ladder.
Keep the merge-evidence tiers untouched and pin them with **GCR-A3**. This is the slice
that removes the most code and retires the most findings; expect `classify.py` and much
of `plan.py` to go.

### Slice C — make the report true (GCR-A4, GCR-A5, GCR-A6)

The three surviving report-accuracy bugs plus the unknown-rendering rule. Under this
design the report *is* the product for everything the sweep will not touch, so it carries
**GCR-A4**, **GCR-A5** and **GCR-A6** together.

### Slice D — the executor (GCR-A7, GCR-A8, GCR-A9, GCR-A10, GCR-A11)

Authorised deletion without re-adjudication, remote refs named-only, restore-proven
salvage where it is retained, and one argv constructor. Covers **GCR-A7** through
**GCR-A11**.

### Slice E — disposition every finding (GCR-A13)

Walk the revised findings list and close each entry against **GCR-A13** with a test or a
written reason. Gates re-admission (`agents-config-9k9.53.6`), which stays closed until
this slice passes.

## 6. Out of scope

- **Re-admission to PATH and the skill.** Owned by `agents-config-9k9.53.6`; that item's
  own preconditions now point here.
- **Scan scope.** Current repo only, unchanged.
- **The merge-evidence tiers.** Not touched. Carrying no findings, they are the earned
  complexity this design is built to preserve.
- **Interactive authorisation UI.** The contract is report-then-name-targets. A prompt
  loop is a later question, not a blocker.

## Continuations

Minted at merge, not before. The order is the slice order in §5 — each depends on the
one above it.

- chore: reachability oracle in the gitclean test harness — snapshot reachable commits
  before every mutating test and assert nothing reachable became unreachable unless it
  sits in a salvage proven by restore, plus the same assertion over a property-based
  harness generating random topologies — AC: **GCR-A12**.
- feat: collapse the two-verdict model to merge-proof-or-report — remove the `Risk` enum,
  `_branch_risk`, worktree risk assignment, derived lifecycle verdicts and the refusal
  ladder; retire closed-unmerged PR as a deletion authority; leave the merge-evidence
  tiers untouched — AC: **GCR-A1**, **GCR-A2**, **GCR-A3**.
- bugfix: make the report true — verified default-branch resolution, true untracked and
  ignored file counts, and a `prunable` worktree reported unknown rather than clean;
  every failed probe renders as a stated unknown on its own row — AC: **GCR-A4**,
  **GCR-A5**, **GCR-A6**.
- feat: executor without re-adjudication — exclude the invoking worktree from every plan,
  require an explicit name for any remote deletion, prove retained salvage by restoring
  it, and terminate every repo-derived argument through one constructor — AC: **GCR-A7**,
  **GCR-A8**, **GCR-A9**, **GCR-A10**, **GCR-A11**.
- chore: disposition every finding in the revised list with a named test or a written
  reason it cannot occur in this design; gates re-admission — AC: **GCR-A13**.

## Evidence

How each criterion above is discharged. States: `open`;
`test: <file>::<test_fn>`; `probe: <file>::<name>`;
`observed: #<PR> <YYYY-MM-DD> <name>`. A criterion whose own text says it is
verified in a browser cannot be discharged by `test:` — a test that never
opens one proves something else.

- GCR-A1 | open
- GCR-A2 | open
- GCR-A3 | open
- GCR-A4 | open
- GCR-A5 | open
- GCR-A6 | open
- GCR-A7 | open
- GCR-A8 | open
- GCR-A9 | open
- GCR-A10 | open
- GCR-A11 | open
- GCR-A12 | open
- GCR-A13 | open
