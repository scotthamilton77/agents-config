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

This package is in the installer's `CLI_PACKAGES` registry, so it deploys onto
PATH via `uv tool install`. A change to `pyproject.toml` or `src/**` shifts the
source digest and forces a reinstall on the next installer run.

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

- **`Disposition` and `Risk` stay orthogonal.** Lifecycle and data-loss are
  different questions with different overrides. `--force` overrides `Risk`
  only; nothing overrides `Disposition.PROTECTED`.
- **A probe that did not answer is `None`, and `None` never authorises a
  deletion.** Every count read from git is optional; `None` means "unknown",
  not zero, clean, or absent. Defaulting an unanswered question to the
  convenient value turns each transient git failure into data loss, so
  unknowns produce the conservative verdict plus a reason naming the probe
  that went quiet. If you add a read, add its `None` path with it.
- **Do not spend a check that git is already making for you.** `worktree
  remove` without `--force`, and `push --force-with-lease`, are the last
  guards against state that changed after the survey. Pass `--force` only
  where a verified salvage already holds the content.
- **Never add a merge check that relies on ancestry alone.** `git branch
  --merged` is wrong in both directions under squash merges. New evidence goes
  in as a tier in `_resolve_merge` with its own `MergeEvidence` member, so the
  report can say *why* a deletion was called safe.
- **Salvage must be verified before the deletion it authorises.** If
  `git bundle verify` fails, the target is left alone.
- **Verify every deletion by re-asking git.** Exit codes are claims.
- **Anomalies carry `CommandResult.transcript()`.** An agent reading the output
  must be able to remediate without re-running anything. Never summarise a
  failure into prose that drops the argv.
- **Never drop a target silently.** Anything the automatic sweep omits goes in
  `Plan.skipped` with a reason.

## Tests

- Behavioural. Each test pins a coded decision, never the stdlib.
- `ScriptedCommands` answers by argv prefix, so tests read as "when git is
  asked X, say Y" rather than as a call-order transcript. **An unmatched call
  raises** — a benign default would let a test pass while production asks git
  something the test never anticipated. Do not add a fallback.
- The builders in `tests/unit/conftest.py` default to the boring case; a test
  should state only the fact it is about.
- **`tests/integration/` runs the CLI over real repositories, and is inside the
  gate.** Scripted answers pin the code to beliefs about git's output; these
  build throwaway repos and check the claims that are about git itself — a real
  squash merge, a real dirty worktree, a salvage that unpacks. They stay
  hermetic: tmp directories, `gh` forced off, no network. Anything genuinely
  needing `gh` would belong outside the gate, and nothing does yet.
