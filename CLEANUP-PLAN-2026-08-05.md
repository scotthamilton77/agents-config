# Cleanup sweep — plan

Companion to `ARCHIVE-TRIAGE-2026-08-05.md`, which holds the per-file verdicts.
This file holds the sequencing, the decisions taken, and the tracker
reconciliation. Both files live on `chore/archive-relocation` and are deleted in
the last commit of the sweep — they are scaffolding, not deliverables.

**The backlog already knows about most of this.** Five open items cover chunks of
the sweep — `9k9.13`, `9k9.132`, `9k9.133`, `9k9.40`, `9k9.50`. The plan attaches
to those rather than minting parallel work. Two of the five had themselves gone
stale in the backlog and were rescoped on 2026-08-05; see "Tracker reconciliation".

## Decisions taken

- **`oss-snapshots/`** — counter-proposal accepted. Delete the tree; convert the
  six provenance rows from local paths to `owner/repo @ SHA` plus the in-repo path.
  No new repository. Detail in Decision 4.
- **`docs/guide/reference.md`** — full rewrite parked behind the milestone. This
  sweep replaces its contents with a short placeholder naming the work that must
  finish before it can be written truthfully. Detail in Phase 3.
- **`9k9.50`** — rescoped from `packages/*/AGENTS.md` to the whole repository, **and
  raised P3 → P1**. It is the only item in this plan that prevents recurrence rather
  than paying down what already rotted; it was ranked below every item it would have
  prevented. Detail in Phase 6. *Not yet applied to the tracker — one command,
  pending go.*
- **New repositories** — the extracted trees are staged as sibling projects under
  `~/src/projects/` and pushed to **private** repos under the `scotthamilton77`
  account via `gh`. Authorized 2026-08-05. Detail in "New repositories".
- **Delivery** — stacked PRs on `chore/archive-relocation`, with a tag on `main`
  before the first merge. Detail in "Branch, PRs and tagging".

---

## Decision 1 — the `SAVEPOINTS/…handoff.md` reference in `AGENTS.md:15`

**Cut the pointer, but lift three sentences into `AGENTS.md` first.**

I read the file. 114 lines, and about 80% of it is time-stamped evidence about a
harness that no longer exists: two config trees loading at once (fixed by S3), 55%
of specs carrying no acceptance language (now enforced by `spec_lint.py`), the
1,283-line `wait-for-pr-comments`, `writing-plans`' code-in-markdown mandate, the
stubbed pdlc gates. All dead. Nothing there is worth a pointer.

But three claims are the *reasoning* under the charter, and the charter states its
decisions without them. `AGENTS.md:15` currently offers that file as the thing to
read "when a decision seems underjustified" — which is a real need, badly served
by a 114-line archived document. Lift these and the need is met in four sentences:

1. **Why acceptance criteria are load-bearing (under D1/D3/D8).** An LLM reviewer
   is a findings generator: given any surface it emits findings proportional to
   that surface, indefinitely. Convergence requires a contract to check against;
   taste is inexhaustible. Acceptance criteria are not primarily defect
   prevention — they are the termination condition review otherwise lacks.

2. **Why every artifact carries a removal condition (under D16).** The system had
   an add operator and no delete operator. Every failure historically minted a
   permanent global rule; nothing carried a budget, a scope bound, or a
   cutover-with-teardown obligation. Duplicate deploys, contradictory rules, and
   two live workflow generations were all one disease, not four.

3. **Why reviewer prompts must not carry the house rulebook (under D5/D7).**
   In-house reviewers load the full house context and review the change against
   the plan — both in-house artifacts, sharing the author's blind spots.
   Fresh-context reviewers review the artifact against the world. Doc/code
   inconsistency is invisible to plan-conformance review when the plan is the
   inconsistent document.

Optional fourth, if you want the D4 rationale in one line: the signature is the
decision and the implementation is the consequence; a plan that embeds bodies
promotes consequences into decisions and freezes them early.

Then delete orientation source #3 and renumber. Sources 1 (charter) and 2
(`work show agents-config-9k9`) stay as they are.

**Same defect, different answer: `packages/grind/AGENTS.md:19`.** It cites
`SAVEPOINTS/2026-07-24-v1-executor-loop-fit-report.md` as the evidence for that
package's core design constraint — a 354-line verification report, not a
diagnosis. That one needs its own read: either inline the constraint it
establishes, or drop the citation. Do not batch it with this decision.

---

## Decision 2 — visualization-suite extraction

**I agree. Four conditions, one of which is a genuine coupling you should know about
before committing.**

The package is cleaner than I expected. `packages/vizsuite/pyproject.toml` declares
exactly three dependencies (`pathspec`, `pydriller`, `networkx`) and imports nothing
from a sibling package — every mention of `workcli` in its source is prose
describing a structural mirror, not an import.

**The coupling: it drives the `work` binary as a subprocess.**
`packages/vizsuite/src/vizsuite/tracker/port.py:57` runs `["work", *argv]` and line 28
pins `_EXPECTED_PROTOCOL_MAJOR = "1"` against the facade's envelope contract. Today
that contract and its consumer are gated by the same `make ci`. Extract the package
and that becomes an unverified cross-repo dependency: `work` can bump its protocol
major and nothing fails until someone runs `viz`.

Conditions:

1. **The new repo has CI green before this one deletes anything.** Not after.
   `ci-vizsuite` is a real gate today and there must be no window where the code
   is gated by nothing.
2. **The protocol coupling gets an explicit test in the new repo** — a contract
   test that shells `work --protocol-version` and asserts major 1, so a facade bump
   breaks something visible. Alternatively split the tracker adapter out and leave
   it here; I'd take the contract test, it's cheaper.
3. **`docs/specs/2026-07-12-visualization-suite-design.md` goes with it.** It is
   currently KEEP in the triage report only because the package is live here. If
   the package leaves, so does its spec, and so does the whole
   `docs/plans/visualization-suite/` corpus — which resolves that subtree without
   needing my earlier relocate-to-`docs/prototypes/` proposal.
4. **State V2's fate explicitly in the extraction.** The V2 work-map prototypes are
   specified and unbuilt. Extraction is implicitly a decision about whether V2 ever
   gets built; say which, so it isn't rediscovered as a mystery in three months.

Bonus: extracting the package and its corpus together empties `docs/plans/`
completely, so that directory can go rather than lingering with one survivor.

---

## Decision 3 — `packages/pdlc/` + `packages/holding-place/`

**Agreed, no objection. Move both together** — pdlc has a path dependency on
holding-place and splitting them breaks its lockfile.

Where the pointer goes so S9 doesn't lose it. The S9 epic is `agents-config-9k9.1`
("Executor loop: re-aim event-sourced grind runtime (D14)"), open, with 24 children.
Record it in **both** places, because they serve different readers:

- A note on `agents-config-9k9.1` — what was archived, where it went, and the
  specific reasoning worth reading: lease lifecycle, CAS-predicate concurrency
  control, crash-recovery roll-forward, pre-strike triage. That reasoning came out
  of an adversarial review round with 20+ applied showstoppers, which is why it is
  worth a pointer at all.
- A line in `docs/specs/2026-07-25-executor-seam-s9-tier1.md`, which is the live
  spec an S9 implementer actually opens.

Note the shape of what you are pointing *at*: `../agents-config-ARCHIVE/` is not a
git repo of its own right now. If it stays a loose directory, a pointer into it is a
pointer at something with no history and no remote. Worth deciding whether the
archive gets `git init` — see the open question at the end.

---

## Decision 4 — `oss-snapshots/` — DECIDED: delete and pin

**Accepted 2026-08-05: no new repository. The tree is deleted and the provenance
rows carry the SHA, which is what the contract was resting on all along.**

`src/user/.agents/skills/AGENTS.md:60-65` pins each snapshot to `owner/repo @ SHA`:
`obra/superpowers @ f2cbfbe`, `anthropics/skills @ f458cee`, `mattpocock/skills @
e74f0061`. If the SHA is the contract, then 1.6M of vendored copy earns its keep only
as insurance against upstream disappearing or force-pushing — because
`git clone` at a pinned SHA reproduces it on demand.

The insurance is not worth a repository nobody clones, so the tree goes and the
rows carry the SHA. That removes 244 tracked files and 1.6M.

Three edits: 

- `src/user/.agents/skills/AGENTS.md` — six provenance rows plus the prose at `:36`,
  `:48` and `:83` that tells a reader to `diff` two local trees.
- **Careful at `:50`** — that line declares `Source: oss-snapshots` a *literal string
  a resync sweep greps for*. Changing the value's shape is fine; renaming the key is
  explicitly forbidden by the same line.
- `docs/specs/2026-07-24-spec-contract-s5.md:20,21,38` — a **live** spec with open
  work (`9k9.22`, `9k9.82`) that sources `grilling` and `to-spec` from
  `oss-snapshots/pocock/`. This is inside the spec-lint window, so verify the gate
  after editing.

**One sequencing constraint.** S5 is unfinished and reads `oss-snapshots/pocock/`
for `grilling` and `to-spec`. Two options, and this needs a call before the phase
runs: either finish the S5 sourcing first and delete the tree afterwards, or delete
now and have the S5 work clone `mattpocock/skills @ e74f0061` when it needs it.
Deleting now is fine — the SHA is pinned and the clone is cheap — but it must be a
decision, not a surprise discovered mid-slice.

**Also flip `writing-skills` off `accept-periodic-resync`.** It is the only skill
whose drift policy ever re-reads a snapshot, and after this change there is no local
tree to re-read. Leaving the policy in place documents a resync that cannot happen.

---

## The plan

Six phases. Phases 1–3 are the cleanup sweep you asked for; 4 is the sweep proper;
5 is the extractions, which are independent and can run alongside; 6 is what stops
this recurring.

All six land as stacked PRs on `chore/archive-relocation` — see "Branch, PRs and
tagging" below for the stack shape and the tag. Prose-only changes state what was
checked; anything touching `packages/**` or a `src/` suite runs `make ci` standalone
from the worktree root, exit status read directly — never piped into a
`grep && commit` chain.

**Phase 0 is already done.** `chore/archive-relocation` carries commit `dda95a1c`,
which removes the 412 tracked files of `archive/`, `SAVEPOINTS/` and
`issues.backup.jsonl` — the relocation you performed by hand, now a reviewable
commit. `main` was restored to `origin/main` and is clean. Verified before
committing: all 383 `archive/` files and all 28 tracked `SAVEPOINTS/` files are
present in `../agents-config-ARCHIVE/`, which additionally holds 29 files git never
tracked.

### Phase 1 — Dangling references (do this first, it's cheap and it's live)

Six edits. No dependencies on anything else in this plan. Everything here is already
broken *today* because of the moves you've already made.

| File | Edit |
|---|---|
| `AGENTS.md:15` | Lift the three sentences from Decision 1, delete orientation source #3, renumber |
| `AGENTS.md` (archive bullet + Repository Structure entry) | Both describe an `archive/` tree that is gone |
| `packages/grind/AGENTS.md:19` | Needs its own read — see the note in Decision 1 |
| `project-config.toml:8` | Cites `archive/docs/specs/bead-pipeline-architecture.md` |
| `src/user/.agents/README.md:17`, `src/user/.claude/rules/AGENTS.md`, `src/user/.agents/rules/AGENTS.md` | All three cite `archive/src/user/...` |

Attach to: **`9k9.40`**, rescoped — its `make ci` half is already fixed in the tree;
what survives is the "pruned on retirement" claim at `AGENTS.md:100`, which belongs
in this phase. See "Tracker reconciliation". The rest of the table is new work.

### Phase 2 — The two primers

Highest harm per word in the repo: both teach an author to produce something the
deploy gate silently drops or the content gate rejects.

- `docs/primers/RULES_PRIMER.md` — **`9k9.132` is already open and correctly scoped.**
  Invert the `:21` frontmatter claim, add `admission:` to the `:23-37` worked example,
  replace the `src/plugins/beads/` collision example, restate cross-tool embedding as
  shipped rather than intended.
- `docs/primers/SKILLS_PRIMER.md` — **new item, no coverage in the backlog.** Replace
  the 500-line body budget at `:106` and `:211` with the enforced 2,000-token cap and
  its consequence; add `admission:` to required frontmatter at `:34-43`; fix the dead
  `src/plugins/beads/` fix-advice at `:219` and the file-locations block at `:236`.

`COMMANDS_PRIMER.md` is already correct and is the model both should follow —
`9k9.132`'s own description says this is "the identical defect PR #438 fixed in
COMMANDS_PRIMER, in the sibling primer that sweep did not reach."

`AGENTS_PRIMER.md` is stale but describes a class with zero instances, so nobody is
currently misled. Lowest priority; fold into Phase 3 or defer.

### Phase 3 — README and the guide

- `README.md` — **`9k9.133` is open and scoped to the skills tables.** Its description
  is now partly stale itself: it says the deleted skills "sit under
  `archive/src/user/.agents/skills/`", which is no longer true — `archive/` has left
  the building. Widen it, or note the change. Beyond the tables, README also needs
  the `src/` file tree (`:63-90`), the `packages/` list (four entries, six exist,
  three on PATH missing), and the templates block at `:170`.
- `docs/guide/` — **`9k9.13` is open**, and most of what it describes is already
  fixed; what survives of it is exactly this phase's README and `configuration.md`
  work. See "Tracker reconciliation".
  - `index.md` — banner stating the guide describes the pre-rework harness, pointing
    at the charter.
  - `configuration.md` — remove step 1 (it instructs the reader to personalize two
    files that do not exist), and mark the completion-gate and merge-policy sections
    unimplemented.
  - `getting-started.md`, `sdlc-workflow.md` — correct the false prerequisites and
    the dead pipeline names; both have surviving spines worth keeping
    (`getting-started.md:64-67` is the one correct verification step in the guide).
  - **`reference.md` — DECIDED: replace with a placeholder.** The full rewrite parks
    behind the milestone. This sweep reduces the file to a short stub: one sentence
    saying the reference described the pre-rework harness and is being rewritten,
    a pointer to the charter, and the specific work whose completion unblocks it
    (S5 spec contract, S6 review contracts, S8 prgroom carve, S9 executor loop).
    No tables. A stub that says "not yet" beats six tables that are 90% false, and
    it does not get paid for twice.

### Phase 4 — The archive and delete sweep

Per `ARCHIVE-TRIAGE-2026-08-05.md`: 80 files under `docs/` plus 8 items outside it
to archive, 41 files plus three regenerable caches to delete.

Order within the phase, because some moves have blockers:

1. **Lift-before-move.** `docs/architecture/prgroom/data-view.md` §5 (escalation-event
   JSON) and §4.5 (`status` output) are D13-**retained** contracts inside an
   archived file — move them into `design.md` first. Same for the one true paragraph
   in `prgroom/c4-deployment.md`.
2. **Blocker edits** — the ten citations listed in the triage report's blocker table,
   most importantly `project-config.toml:7,77` (rewrite the comments to point at D9,
   don't aim them into the archive), `packages/workcli/AGENTS.md` ×3, and
   `packages/vizsuite/src/vizsuite/__init__.py:9` (which Phase 5 may resolve instead).
3. **Then move and delete.**
4. **Rewrite `docs/architecture/prgroom/index.md`** — it is a reading order through
   ten files that will no longer be there.

Gate note: `spec-lint` only reads `docs/specs/YYYY-MM-DD-*.md` dated on or after
2026-07-24 (`GATE_START_DATE`). All 39 specs on the archive list are older, so the
sweep cannot break `make ci`. Verified in `packages/installer/src/installer/core/spec_lint.py`.

### Phase 5 — Extractions (independent; can run alongside 2–4)

Three separate pieces of work, in decreasing order of confidence:

1. **`packages/pdlc/` + `packages/holding-place/`** → archive, plus the two pointers
   from Decision 3. No conditions, no risk — nothing imports them, neither is in
   `make ci`, neither is on PATH.
2. **`oss-snapshots/`** → deleted, provenance rows repinned to `owner/repo @ SHA`,
   `writing-skills` flipped off `accept-periodic-resync` (Decision 4). Settle the S5
   sourcing question named there before this runs.
3. **visualization-suite** → new repo, subject to Decision 2's four conditions. This
   is the largest and the only one with a live gate to reconstitute; do it last.

### Phase 6 — The thing that stops this happening again

Everything above is a one-time fix for drift that took about six weeks to accumulate.
Without a mechanical check it comes back.

**`9k9.50` is open and is the right idea aimed at the wrong target.** It proposes a
symbol-existence lint over `packages/*/AGENTS.md` — extract backticked code-shaped
citations, verify each resolves by AST walk. Good. But every defect in this sweep was
in a *different* class: prose naming a **deployed asset** — a skill, rule, command, or
agent — that does not exist in `src/`. README, all five guide files, and both primers
failed exactly that check, and `9k9.50` as scoped would catch none of them.

**DECIDED: `9k9.50` is rescoped to the whole repository**, not just
`packages/*/AGENTS.md`. Two check classes, one lint:

1. **Symbol existence** (its original scope) — backticked code-shaped citations
   resolve to a real file, and a named symbol is defined by AST walk rather than grep.
2. **Asset existence** (new) — prose naming a skill, rule, command or agent asserts
   something that exists under `src/`. The authoritative name list is already
   mechanically available: it is what `content-lint` walks when it stages the tree.

Scope is every tracked `.md` outside `docs/specs/` — README, guide, primers,
architecture, package orientation files, `AGENTS.md`. Dated specs are excluded on
purpose: a spec is a point-in-time proposal and is *supposed* to name things that do
not exist yet, which is the same reason `spec-lint` carries a date cutoff.

Remediation advice matters as much as the check. **Where the authoritative list is
mechanically available, the fix is to cite the source, not to correct the copy.**
That is what actually resolved `9k9.40`'s first half — someone replaced an
enumeration of `ci` targets with "read the `Makefile`" — and it is what `9k9.133`
independently recommends for the README skills tables. An enumeration that can go
stale will go stale; a pointer cannot.

This is the highest-leverage item in the plan and the only one that reduces future
interventions rather than paying down past ones. It is also the only phase that must
not be dropped if the sweep runs long.

---

## Tracker reconciliation

Audited 2026-08-05 against the working tree. Two of the five items had themselves
gone stale while sitting in the backlog — the same add-without-delete disease one
level up, in the tracker.

| Item | Verdict | Action |
|---|---|---|
| `9k9.132` RULES_PRIMER | **Clean, take as written** | None. Every claim re-verified: `:21` says frontmatter is optional, `rules` is in `GATED_NAMESPACES`, and `src/user/.claude/rules/delegation.md` carries the complete `admission:` record the primer says is unnecessary |
| `9k9.133` README skills tables | **Valid, one stale pointer** | Description says the retired skills "sit under `archive/src/user/.agents/skills/`" — that tree left the repo in `dda95a1c`. Repoint to `../agents-config-ARCHIVE/` |
| `9k9.40` root AGENTS.md gate claims | **Half fixed, half live** | Rescope to the surviving half |
| `9k9.13` persona/session-primer sweep | **Mostly overtaken** | Rescope to what survives, and cut the blocked `remove_when` |
| `9k9.50` symbol-existence lint | **Right idea, wrong target, wrong rank** | Widen to repo-wide, two check classes (Phase 6). **Raise P3 → P1** — pending, not yet applied |

**`9k9.40` in detail.** The defect it describes is gone: root `AGENTS.md` no longer
enumerates `ci` targets — line 107 now says "Read the `Makefile` for which packages
are currently in `ci`", and line 34 says the same. Proof the pointer beats the
enumeration: *the work item's own quoted `ci` line is now stale*, missing
`ci-gitclean`, `ci-executor`, `content-lint` and `content-tests`. What survives is
the notes half, still accurate — `AGENTS.md:100` claims the PATH CLIs are
"receipt-tracked, **pruned on retirement**" while `clis.py:47` is
`RETIRED_CLIS: tuple[str, ...] = ()`. Prune is real code with a permanently empty
input, so an agent retiring a package believes cleanup is automatic when it needs a
manual tuple edit. One sentence. Drops P1 → P2, since the high-blast-radius half is
already fixed.

**`9k9.13` in detail.** `grep -rln "PERSONA|SESSION-PRIMER" src/` returns zero;
`SESSION-PRIMER-README.md` is gone; and the root `AGENTS.md` template list it flagged
is now correct (`AGENTS.md.template`, `CLAUDE.md.template`, `settings.json.template`
all exist). Its first note duplicated `9k9.40`'s `ci` claim, also fixed. What survives
sits entirely outside `src/`: `README.md:77-78` and `:174-175` (persona templates in
the file tree and templates block) and `docs/guide/configuration.md:16-22` (the
persona step). Both are Phase 3. Separately, its `remove_when` is gated on "the
DYNAMIC-INCLUDE engine reassessment (D17) has settled" — a dependency on unfinished
S4 work that would hold the item open long after the prose is right. Split that off.

---

## New repositories

Authorized 2026-08-05: stage extracted trees as sibling projects under
`~/src/projects/`, create the remotes with `gh` under the **`scotthamilton77`**
account, **private**. Two repos — `oss-snapshots` is *not* one of them, it is deleted
and repinned per Decision 4.

**First, a correction to how "archive" has been framed in this plan.** Deleting a
tracked file from `agents-config` does not lose it — its history stays in that repo's
git objects. The archive repository is for *browsability*, not preservation. The only
material genuinely at risk is what git never tracked, and that is a short, specific
list: the 29 untracked files under `SAVEPOINTS/`, `.grind/ORCHESTRATION-STATE.md`,
and `.viz/kimi-k3-ui-assessment-2026-07-18.md`. Those exist in one place on disk. Get
them committed first and the rest is convenience.

### Repo A — `agents-config-ARCHIVE` (already staged at `~/src/projects/agents-config-ARCHIVE`)

**The `.gitignore` trap is real and worse than expected.** Verified 2026-08-05:
`~/src/projects/agents-config-ARCHIVE/SAVEPOINTS/.gitignore` contains exactly:

```
.gitignore
*
```

That ignores every file in the directory *and itself*. It is why only 28 of 57
`SAVEPOINTS/` files were ever tracked in `agents-config` — the other 29 were created
after the ignore landed and git never saw them. **`git init` + add in that directory
without deleting this file first captures almost nothing, silently.** Delete it before
the first commit.

Lines from `agents-config/.gitignore` that must **not** be carried into the archive
repo, because each suppresses something being deliberately archived:

| Line | Suppresses |
|---|---|
| `.grind` | `.grind/ORCHESTRATION-STATE.md` — on the archive list |
| `.viz/` | `.viz/kimi-k3-ui-assessment-2026-07-18.md` — on the archive list |
| `scripts/backlog-landscape/output/` | regenerated output; harmless to drop, but decide rather than inherit |

An archive `.gitignore`, if written at all, should carry only genuine noise:
`.DS_Store`, `__pycache__/`, `.venv/`, and the tooling caches. **Do not copy the
source repo's file.**

Procedure:

1. Survey first — `find . -name .gitignore` across the whole tree, and check whether
   `.git/` already exists. *(Unverified at time of writing: the Bash classifier was
   unavailable. Treat the two facts above as verified and this survey as still owed.)*
2. Delete `SAVEPOINTS/.gitignore` and any other suppressing ignore file found.
3. `git init`, then stage **by explicit top-level path** — `git add archive SAVEPOINTS
   issues.backup.jsonl …` — never `git add -A` or `git add .`, per the shared hard
   lines. Read `git status --porcelain` first and name what is being committed.
4. **Verify the ignore work mechanically** before pushing:
   `git ls-files | wc -l` against `find . -type f -not -path './.git/*' | wc -l`.
   A mismatch means an ignore rule is still eating something. This is the check that
   catches a silent `*`.
5. `gh repo create scotthamilton77/agents-config-ARCHIVE --private --source=. --push`.
6. Move `packages/pdlc/` and `packages/holding-place/` in as part of Phase 5, together
   (path dependency), and land the S9 pointers from Decision 3.

### Repo B — visualization-suite

Staged at `~/src/projects/vizsuite` (name follows the package; the CLI it installs is
`viz`). Contents: `packages/vizsuite/` at the repo root, plus the design spec
`docs/specs/2026-07-12-visualization-suite-design.md` and the whole
`docs/plans/visualization-suite/` corpus, which is its evidence base.

**Preserve history — do not `git init` from a copy.** This is a live, CI-gated package
with real history and four rounds of review behind parts of it. Use `git filter-repo
--path packages/vizsuite --path docs/plans/visualization-suite` against a clone of
`agents-config`, then restructure. A fresh init would throw away exactly the record
that makes the extraction safe to review.

Decision 2's four conditions all attach here, and condition 1 is the ordering rule:
**CI green in the new repo before `agents-config` deletes anything.** Also carry over
the `work` protocol contract test (condition 2), since
`vizsuite/tracker/port.py:57` shells out to the `work` binary and line 28 pins
`_EXPECTED_PROTOCOL_MAJOR = "1"` — a coupling that today is held by a shared `make ci`
and after extraction is held by nothing.

`gh repo create scotthamilton77/vizsuite --private --source=. --push` once the tree
and its gate are in place.

---

## Branch, PRs and tagging

**Branch:** `chore/archive-relocation`, worktree at
`.claude/worktrees/archive-relocation`. Phase 0 is committed there as `dda95a1c`.

**Stacked, not one PR.** The phases have genuinely different review needs and one
combined diff would be unreviewable — Phase 4 alone moves 80 files and deletes 41.
Stack order, each PR based on the one before:

```
main
 └─ 1  chore/archive-relocation      relocation (dda95a1c) + dangling refs
     └─ 2  primers                   RULES_PRIMER + SKILLS_PRIMER
         └─ 3  README + guide        incl. reference.md placeholder
             └─ 4  archive/delete sweep
                 └─ 5  extractions   pdlc+holding-place, oss-snapshots, viz
                     └─ 6  prevention lint
```

PRs 1–3 are small and independently useful; if the stack stalls, they still land.
PR 4 is the bulk move and should be reviewed as a move, not as content. PR 5 splits
further if the viz extraction needs its own review cycle. The repo ships a `gh-stack`
skill for exactly this shape.

**The tag.** Before the first merge, tag `main` at the last commit containing the
archive and out-of-date material:

```
git tag -a pre-harness-cleanup-2026-08 <sha-of-main-head> -m "..."
```

Two things to get right:

- **Tag `main`'s head immediately before the first merge, not now.** `main` moves —
  it advanced from `b8b7433f` to `64e5f2d6` during this session's analysis alone. A
  tag placed now could sit behind unrelated commits that also predate the sweep.
- **The tag must be annotated, not lightweight**, so it carries a message explaining
  what it marks. The message should say plainly: this is the last commit where
  `archive/`, `SAVEPOINTS/`, `oss-snapshots/`, `packages/pdlc/`,
  `packages/holding-place/`, and the pre-rework `docs/` tree are present in the
  repository, and name `../agents-config-ARCHIVE/` as where the first three went.

Push the tag (`git push origin <tag>`) so it survives a fresh clone — a local-only
tag marking a deliberate boundary is a promise that evaporates.

---

## Open questions

1. **~~Does `../agents-config-ARCHIVE/` become a git repo?~~ RESOLVED** — yes,
   private, under `scotthamilton77`. See "New repositories". The residual risk is
   narrower than first stated: only the 29 never-tracked `SAVEPOINTS/` files and the
   two untracked `.grind`/`.viz` documents exist in a single place on disk. Everything
   git ever tracked remains recoverable from `agents-config` history regardless.
   **Sequencing consequence: create this repo and verify its file count before any
   phase deletes anything.**
2. **S5 versus the `oss-snapshots/` deletion** — finish the S5 sourcing first, or
   delete now and have S5 clone at the pinned SHA? See Decision 4.
3. **Repo B's name.** `vizsuite` follows the package; the CLI is `viz`. Say if you
   want something more descriptive — renaming a private repo later is cheap, but the
   `gh` command in this plan hardcodes it.
3. **Admission records on deletion work.** The delivery contract says new work enters
   as a child of `9k9` with an admission record stating what it prevents or provides.
   That maps fine here — "prevents agents authoring rules that silently do not
   deploy" is a real `prevents` — but the records on this batch will read oddly, since
   what is being admitted is a deletion.
