# AGENTS.md — `packages/gitclean/`

Package-scoped guidance for the `gitclean` CLI. The repo-root `AGENTS.md` still
applies; this file adds what is specific to this package. Like the other
packages here, **this is real code with a real quality gate** — unlike the
config content under `src/`.

## The quality gate is mandatory

Before pushing any change under `packages/gitclean/`, run the canonical gate
from the repo root:

```bash
make ci-gitclean
```

It runs, in order: `ruff check`, `ruff format --check`, `mypy --strict src`,
`pytest --cov` (90% branch floor), `pip-audit`, and `gitclean --help`. Do not
hand-pick a subset — the linter and the formatter are orthogonal. Faster inner
loop: `make test-gitclean`.

This package **is** in the installer's `CLI_PACKAGES` registry and installs onto
PATH as `gitclean`. Being inside `make ci` is not what earns that — `vizsuite`
is gated and stays off — so a change here reaches a deployed tool, driven by the
`/clean-up-git` command interactively and named to agents by the
`post-merge-cleanup` skill.

## Architecture

A pipeline of pure stages around one I/O seam:

```
ports.py  →  survey.py  →  classify.py  →  plan.py  →  execute.py  →  cli.py
 (the only     (reads)      (judges)      (resolves)   (acts)        (envelope)
  subprocess)
```

- **`ports.py` is the only module that shells out.** Everything above it takes
  `CommandResult` values and returns data, which is what makes the rules
  testable without a fixture repo.
- **`survey.py` and `classify.py` are strictly separated.** The survey records
  facts; classification applies opinion. A new judgement rule belongs in
  `classify.py` and must not need a new git call.
- **`plan.py` is pure and returns `Plan | Refusal`.** Refusals are values, not
  exceptions.

## Rules that are load-bearing, not stylistic

- **The tool proves "this is merged", never "deleting this is safe."** The
  second is a total function over every repository state that exists, and three
  review rounds each found another state it did not cover. The first is
  partial: an unproven target appears in the report and a human names it. Any
  change that widens what a bare sweep takes must widen it through merge
  evidence, not around it.
- **No verdict is derived from a proxy.** Age measures commits, not intent. A
  clean working tree measures files, not consent. If you find yourself adding a
  field that names a lifecycle state — abandoned, active, stale — the answer is
  to report the measurement and let the reader conclude.
- **The six sweep conditions are six boolean checks in one function.** They
  live in `withheld_reason`, they return the prose that goes in the report, and
  they stay that shape. A strategy class or rule registry expressing them would
  be this package's failure mode returning: every defect it has shipped came
  from cleverness, none from the checks being written out plainly.
- **A probe that did not answer is `None`, and `None` never authorises a
  deletion.** Every count read from git is optional; `None` means "unknown",
  not zero, clean, or absent. Defaulting an unanswered question to the
  convenient value turns each transient git failure into data loss, so unknowns
  render as a stated unknown on that target's own row. If you add a read, add
  its `None` path with it.
- **A relation the report states is a field, never a sentence.** A worktree, the
  branch it holds and that branch's copy on the server are one thing with two or
  three parts, and a reader deciding about one has to see the others. Those
  relations travel as `Target.pairing`, keyed by relation, each entry carrying a
  `name`, the `id` of the row for it, and `known`. The prose in `reasons` says
  the same thing for a person and is not the channel — recovering a pairing from
  `checked out at /a/b` means splitting on a delimiter the path is allowed to
  contain, the mis-keyed lookup returns nothing, and nothing then reads as an
  absence somebody measured. Add a relation and it goes here too; do not leave a
  consumer to parse it back out.
- **Do not spend a check that git is already making for you.** `worktree
  remove` without `--force`, and `push --force-with-lease`, are the last guards
  against state that changed after the survey. There is no `--force` in this
  CLI and adding one means re-implementing, in Python, what git has just read
  off the disk.
- **A named target is an authorisation, not a proposal.** Do not re-derive
  safety underneath the caller, and do not add a flag for them to pass. git's
  own refusals still stand, and they carry better information than a
  re-derivation would.
- **A job already done is a success.** When the state the caller asked for
  already holds, that is neither a refusal nor an anomaly: a name matching
  nothing lands in `Plan.absent`, and a server ref the remote no longer has
  becomes a `Deletion` with `already_absent`. Both exit 0. The cost of getting
  this wrong is not cosmetic — a caller told a finished job failed retries,
  hand-rolls raw git, or escalates, and every one of those is worse than the
  no-op it should have been handed. Two rules keep it honest: `deleted` stays
  false, because only a true there is evidence the tool acted; and the state is
  measured before anything is spent on reaching it, which is why the server is
  asked about a ref *before* its history is bundled rather than after the push
  is rejected.
- **Absence is a measurement, and "I did not find it" is not one.** This is the
  same discipline as `None` never authorising a deletion, applied to the other
  end: before reporting that a named thing is already gone, check that the look
  was capable of finding it. Three ways it is not, and all three arrive looking
  identical to a name that matches nothing — the listing that would have held it
  failed, which is what `branches_known` and `worktrees_known` are for; the name
  is a ref deliberately kept out of the target list, which is why
  `Survey.not_offered` records those rather than dropping them; or the remote is
  not advertising a ref it still holds. The first two refuse, and the first is
  asked *per selector kind*: a `worktree:` name is answered by the worktree
  listing alone, so a failed ref read must not block it, and a bare name needs
  both because it could have been either. The
  third cannot be distinguished by any question `ls-remote` can ask, so the row
  states what was measured — the remote does not advertise it — instead of the
  conclusion, and the cost lands as a deletion not made rather than as a lie.
  Adding an exclusion to `read_branches` without adding its `NotOffered` record
  reintroduces this defect silently.
- **With one exception, and know why it is there.** git's refusals cover
  uncommitted content; they say nothing about a commit made inside a worktree
  on no branch. That tree is clean, git removes it happily, and the record it
  deletes is what held the commit — the per-worktree reflog dies with it, so
  there is no undo. Before removing a worktree the executor asks git whether
  any ref contains that commit and declines when none does. **It asks about
  the commit the tree holds now, re-read as the deletion happens, not the one
  the survey recorded.** Every other guard on that path is git's own and is
  taken at that moment; this one is ours, so it is taken then too. A commit
  made in the tree after the survey ran is held by the record about to be
  deleted and by nothing else, while the commit it replaced sits on a branch
  and answers "contained" — so asking about the surveyed commit is not a
  weaker check, it is the wrong one, and it clears in the exact case it exists
  to refuse. This is the one
  place a named target is refused on reachability grounds, and it is not a
  precedent for re-deriving anything else: it exists because "the reflog is
  the undo" — the argument that retired salvage everywhere else — is simply
  false here. Do not generalise it, and do not remove it without replacing
  the guarantee.
- **Never add a merge check that relies on ancestry alone.** `git branch
  --merged` is wrong in both directions under squash merges. New evidence goes
  in as a tier in `_resolve_merge` with its own `MergeEvidence` member, so the
  report can say *why* a deletion was called merged.
- **Salvage exists only where there is no reflog** — a ref on the server — and
  the deletion it authorises is earned by a restore, not by an inspection. The
  bundle is cloned into an empty scratch directory and the commit about to be
  deleted has to be reachable from a ref in what comes out. `git bundle verify`
  is not that check and never was: it asks whether the archive applies to the
  repository that already holds every object, so it passes on a bundle that
  clones back empty and, in a shallow clone, on one `git clone` refuses. A
  salvage that does not restore is an anomaly carrying the transcript, is
  recorded as no salvage, and leaves the target alone. Unbundling is not a
  substitute — it reports success on exactly the bundle that will not clone.
- **Verify every deletion by re-asking git.** Exit codes are claims.
- **Anomalies carry `CommandResult.transcript()`.** An agent reading the output
  must be able to remediate without re-running anything. Never summarise a
  failure into prose that drops the argv.
- **Never drop a target silently.** A target the sweep selected and then
  dropped goes in `Plan.skipped`; one that never entered the sweep carries its
  own `Target.withheld`.

## Tests

- Behavioural. Each test pins a coded decision, never the stdlib.
- `ScriptedCommands` answers by argv prefix, so tests read as "when git is
  asked X, say Y" rather than as a call-order transcript. **An unmatched call
  raises** — a benign default would let a test pass while production asks git
  something the test never anticipated. Do not add a fallback.
- The builders in `tests/unit/conftest.py` default to the boring case; a test
  should state only the fact it is about. They also build every ref at the same
  commit, which is what lets a worktree pick up its branch's evidence for free
  — and what makes a fixture containing the trunk mark that shared commit as
  the trunk's. A test about anything else gives its refs distinct `head`s.
- **`tests/integration/` runs the CLI over real repositories, and is inside the
  gate.** Scripted answers pin the code to beliefs about git's output; these
  build throwaway repos and check the claims that are about git itself — a real
  squash merge, a real dirty worktree, a real refusal. They stay hermetic: tmp
  directories, `gh` forced off, no network. Anything genuinely needing `gh`
  would belong outside the gate, and nothing does yet.
- **A mutating test belongs inside `reachability_guard`.** It snapshots the
  commits reachable from a ref or a worktree HEAD before the run and demands
  each one still is afterwards, so a run that strands a commit nobody thought
  to write a test about fails a test that never mentions it. Exempt a commit
  only by naming it or by restoring the salvage that holds it; loosening the
  guard to make a suite green is how the last three rounds shipped. A test that
  deletes from the server guards the **bare** repository rather than the
  working clone: `push --delete` is what the run performs, and the server is
  what loses the ref.
- **The guard only covers the topologies the matrix names.** It is a property
  check, but it runs on the shapes in `test_a_sweep_strands_only_the_commits_it_proved_redundant`,
  and every one of those but a single named branch drives a *bare* sweep. A
  deletion reached by naming a target is barely represented, so a defect on the
  named path can pass the whole suite. Adding a row is cheap; assuming one
  exists is how a shape goes unmeasured.
