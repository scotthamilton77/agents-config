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

This package is **not** in the installer's `CLI_PACKAGES` registry and nothing
installs it onto PATH — being inside `make ci` does not deploy a package. Run it
from a checkout. Do not add it to that registry without an explicit decision to
ship it.

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
- **Do not spend a check that git is already making for you.** `worktree
  remove` without `--force`, and `push --force-with-lease`, are the last guards
  against state that changed after the survey. There is no `--force` in this
  CLI and adding one means re-implementing, in Python, what git has just read
  off the disk.
- **A named target is an authorisation, not a proposal.** Do not re-derive
  safety underneath the caller, and do not add a flag for them to pass. git's
  own refusals still stand, and they carry better information than a
  re-derivation would.
- **Never add a merge check that relies on ancestry alone.** `git branch
  --merged` is wrong in both directions under squash merges. New evidence goes
  in as a tier in `_resolve_merge` with its own `MergeEvidence` member, so the
  report can say *why* a deletion was called merged.
- **Salvage exists only where there is no reflog** — a ref on the server — and
  must be verified before the deletion it authorises. If `git bundle verify`
  fails, the target is left alone.
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
  guard to make a suite green is how the last three rounds shipped. Two
  server-ref tests still run outside it — `test_the_salvage_ref_does_not_outlive_the_run`
  and `test_an_unrelated_sibling_ref_is_not_read_as_the_deletion_having_failed`.
  That is a gap to close, not a precedent to copy.
- **The guard only covers the topologies the matrix names.** It is a property
  check, but it runs on the shapes in `test_a_sweep_strands_only_the_commits_it_proved_redundant`,
  and every one of those but a single named branch drives a *bare* sweep. A
  deletion reached by naming a target is barely represented, so a defect on the
  named path can pass the whole suite. Adding a row is cheap; assuming one
  exists is how a shape goes unmeasured.
