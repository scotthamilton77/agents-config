# workcli real-bd integration harness — design

**Bead:** agents-config-wgclw.9.7 (child of the work-facade CLI v1 epic, wgclw.9)
**Status:** design — proposal
**Depends on:** none blocking (bd ≥ 1.0.3 on PATH at run time)

## Problem

`packages/workcli` quarantines the issue tracker (bd) behind a stable JSON
envelope. Its entire value is that the facade absorbs bd's quirks so callers
never couple to bd. But **every** current test under `tests/unit/` drives the
CLI with a `ScriptedBdRunner` fake or a `FakeBackend` — nothing ever shells out
to the real `bd` binary. The bd adapter (`adapters/bd/parse.py`,
`adapters/bd/runner.py`) is validated only against golden `--json` snapshots
captured **once, by hand**, and frozen into fixtures. A future bd release that
drifts its JSON output shape — a renamed field, a changed error string, a new
null where a value was expected — would sail past the whole suite and only
surface as a production break.

The facade's core contract with reality is untested against reality.

## Goal

A real-bd integration suite that stands up an **isolated** bd install in a temp
directory and drives the **production** `work` entry point against it, covering
every verb, every create-noun, representative lifecycle sequences, typed error
paths, and — via a fault-injecting bd wrapper — the crash-recovery contract.
When bd's real behavior drifts from what the fake asserts, this suite fails.

## Decisions (resolved during brainstorm)

1. **Venue — separate local target, not CI.** A distinct `make itest-workcli`,
   run manually / pre-push. `make ci-workcli` stays hermetic (no bd, no Dolt,
   zero deps). Accepted trade-off: the real-bd contract is pre-push developer
   discipline, not a merge gate. No bd+Dolt install burden in GitHub Actions.
2. **Depth — lifecycle sequences + typed error paths + injected faults.**
   Beyond each-verb-once and each-noun-once happy paths: multi-step guarded
   transitions, the typed failure envelopes, and a bd wrapper shim that injects
   crashes/garbage to exercise recovery.
3. **Runner — injectable production port (not a test-only clone).** Extend the
   real `SubprocessBdRunner` so the harness exercises the actual production
   subprocess call, not a parallel copy. See §2.

## Feasibility (verified against bd 1.0.3, not assumed)

- **Isolation is cwd-based.** `bd -C <dir>` refuses to *init* a non-existent
  project; the working mechanism is running bd with `cwd=<tmpdir>` — `bd init`
  creates a self-contained `.beads/` there and later calls auto-discover it.
- **Dolt is embedded.** The temp `.beads/` carries an `embeddeddolt` engine —
  no external `dolt` binary or sql-server needed. Toolchain requirement is
  just `bd` on PATH.
- **Cost:** a `bd init` ≈ 1.4s (Dolt bring-up); a mutation ≈ 0.7s. This is the
  number that drives fixture scope (§3).
- **The production port is not reusable as-is.** `SubprocessBdRunner` hardcodes
  `["bd", *args]` with no cwd/env — it always hits whatever `.beads` the
  process stands in. Isolation *requires* cwd injection.

## Architecture

A new `packages/workcli/tests/integration/` suite drives the production
`workcli.cli.main()` against a real, isolated bd install. The sole production
change is making the bd subprocess port injectable. Hermetic unit tests and the
`make ci-workcli` gate are untouched.

```
make itest-workcli  ──▶ pytest tests/integration   (NOT in ci-workcli / ci)
                              │
        ┌─────────────────────┼──────────────────────┐
   fixtures (conftest)   crash shim (bd wrapper)   test modules
        │                     │                         │
   bd init in tmpdir    exec real bd  OR          drive workcli.cli.main(
   → SubprocessBdRunner  inject fault               argv, runner=SubprocessBdRunner(
     (cwd=tmpdir,        (exit≠0 / garbage           cwd=install, bd_binary=<real|shim>))
      bd_binary,          stdout)                   → assert JSON envelope
      env=NON_INTERACTIVE)
```

## 2. The one `src/` change — injectable port

`SubprocessBdRunner` today has no `__init__` and hardcodes `["bd", *args]`. Add:

```python
def __init__(
    self,
    *,
    bd_binary: str = "bd",
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
```

and thread `bd_binary`/`cwd`/`env` into `subprocess.run`. **Default construction
is byte-for-byte identical to today** (`"bd"`, inherit cwd/env), so
`_build_backend` and every existing caller are unaffected. The new branches get
hermetic **unit** tests (an echo/stub binary — no real bd), preserving the 90%
branch floor. This is the honest fix for an un-configurable port the future GH
adapter would trip over anyway.

## 3. Fixture architecture

- **`bd_available`** — autouse skip guard; if `bd` is not on PATH the suite
  *skips* (never hard-fails), so a contributor without bd still gets green.
- **`read_only_install`** (session-scoped) — one `bd init` + seed a known corpus
  (a few issues, a dep edge, labels) via **raw `bd`** (not `work create`, so
  read-verb tests fail for read reasons, not write bugs). Serves all read /
  happy-path assertions. Pays Dolt's ~1.4s **once**.
- **`fresh_install`** (function-scoped) — a pristine `bd init` per test, only
  for mutation / lifecycle / crash sequences that need clean state.

Both hand back a production `SubprocessBdRunner(cwd=<tmp>, env={**os.environ,
"BD_NON_INTERACTIVE": "1"})` and drive `main(argv, runner=…, out=…, err=…)`,
asserting on the stdout envelope.

## 4. Coverage matrix

- **Every verb once** (happy-path): show, list, ready, search · create --raw,
  update, note, close, reopen · claim, release, plan, promote, deliver,
  reconcile · dep {add,remove,list}, label {add,remove,list} · sync.
- **Every create-noun** (7): spike, chore, decision, feat, bugfix, spec, epic —
  assert each template's resulting bd fields.
- **Lifecycle sequences:** `create→claim→deliver(evidence)→reconcile`;
  `plan add→plan --done`; `promote shape-feat→shape-spec container`.
- **Error paths (within reason):** `E_NOT_FOUND` (bogus id), `E_USAGE` (bad
  flags), the dep **type-wall** (epic-blocks-non-epic hard error),
  **evidence-gate refusal** on `deliver`.

## 5. Crash-injection shim

A committed `tests/integration/shims/bd_shim.sh` reads `WORKCLI_ITEST_FAULT` and
either `exec`s real bd or injects a fault — **non-zero exit**, **malformed JSON
on stdout** (asserts the `BACKEND_DRIFT` drift-alarm fires against real adjacent
output), or fault-at-step-N inside a real lifecycle sequence, after which
**`reconcile` must recover** real bd state. That last one exercises the
deliver↔reconcile recovery contract (the wgclw.9.5 work) end-to-end — impossible
to fake honestly.

**Boundary:** true 60s-timeout retry stays a fast **unit** test (injected
short-timeout runner); the shim covers exit-code and garbage-output faults, not
a real 60s hang.

## 6. Isolation & safety

- Every install lives under pytest `tmp_path` — never the repo tree.
- The runner always gets an explicit `cwd`; a fixture guard **refuses to run**
  if the resolved install path is inside the repo root — structurally
  impossible to touch the repo's real `.beads`.
- Embedded Dolt (no sql-server) means no lingering process to reap; `tmp_path`
  auto-cleans.

## 7. Wiring & docs

- `make itest-workcli` → `cd $(WORKCLI) && uv run pytest tests/integration -q`.
  **Not** in `ci-workcli` or `ci`.
- `pyproject.toml`: default `testpaths = ["tests/unit"]` so `make test-workcli`
  / `cov-workcli` stay hermetic and the coverage floor keeps measuring unit
  tests only. The integration suite is invoked by explicit path.
- `packages/workcli/AGENTS.md`: document the target, its `bd`-on-PATH
  requirement, and that it is **pre-push discipline, not a merge gate**.

## Resolved open items

- **`sync` on a remote-less temp install** — `dolt push` has no remote, so the
  test asserts the *honest* envelope bd actually returns (commit-only success or
  typed failure), whatever it is — still real contract coverage. No remote is
  forced.
- **Seed via raw `bd`, not `work`** — keeps read-fixture correctness independent
  of the write path under test.

## Out of scope (YAGNI)

No CI job, no Dolt-server mode, no perf benchmarking, no cross-bd-version
matrix.

## Continuations

- Optional follow-up (file only if desired after the suite proves stable):
  a CI job that installs bd and runs `make itest-workcli` as a merge gate —
  deferred per decision 1. Not created now.
