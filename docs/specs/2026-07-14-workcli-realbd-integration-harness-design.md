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
make itest-workcli ─▶ pytest tests/integration -p no:xdist  (NOT in ci-workcli/ci)
                              │
        ┌─────────────────────┼───────────────────────────┐
   fixtures (conftest)   FaultInjectingBdRunner        test modules
        │                (wraps real runner,               │
   bd init in tmpdir      counts .run(); calls 1..N-1  drive workcli.cli.main(
   → SubprocessBdRunner    → real bd, call N → fault)   argv, runner=<real|fault>)
     (bd_binary=<abs bd>,        │                      → assert JSON envelope
      cwd=tmpdir,           real partial state            (value-level)
      env=NON_INTERACTIVE     left for reconcile
        + BEADS_DIR=tmp)      to heal
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
`_build_backend` and every existing caller are unaffected. This is the honest
fix for an un-configurable port the future GH adapter would trip over anyway.

**Coverage discipline — thread through, don't branch.** Implement as
`subprocess.run([bd_binary, *args], cwd=cwd, env=env, …)` with **no conditional
guards** on the new params (`subprocess.run` accepts `cwd=None`/`env=None` as
"inherit"), so the change adds **zero new branches**. The integration suite is
excluded from the coverage run (§7), so it cannot help the 90% branch floor;
any `if env is not None:` style guard would add a branch whose injected-True
side then needs a dedicated hermetic **unit** test in `tests/unit/`
(`test_subprocess_runner.py` today constructs only the default). Threading the
params straight through keeps the floor green without new unit tests; if a guard
is genuinely unavoidable, the unit test lands with it.

## 3. Fixture architecture

- **`bd_available`** — autouse guard resolving `bd` to an **absolute path** once
  (`shutil.which("bd")`); if bd is not on PATH the suite *skips* (never
  hard-fails), so a contributor without bd still gets green. The resolved path
  and `bd --version` are recorded to a test artifact so a drift failure is
  attributable to a known binary (two bd binaries on PATH is a real, observed
  condition). The absolute path — not the bare name `"bd"` — is what every
  fixture passes as `bd_binary`, so "the bd we validate against" is
  unambiguous.
- **`read_only_install`** (session-scoped) — one `bd init` + seed a known corpus
  (a few issues, a dep edge, labels) via **raw `bd`** (not `work create`, so
  read-verb tests fail for read reasons, not write bugs). Serves all read /
  happy-path assertions. Pays Dolt's ~1.4s **once** (serial — see §7). A
  session-finalizer re-asserts the seeded corpus invariants (count, labels,
  dep-edge) so any accidental write-verb bleed from a read test **fails loudly**
  rather than silently poisoning later reads.
- **`fresh_install`** (function-scoped) — a pristine `bd init` per test, only
  for mutation / lifecycle / crash sequences that need clean state.
- **init-failure is a loud failure, not a raw traceback.** Both installs wrap
  `bd init`; a non-zero init (e.g. `git user.useConfigOnly=true`, a hostile
  enclosing pre-commit hook) fails the suite with a clear diagnostic naming the
  init stderr — not an opaque fixture error. (Env is otherwise sufficient:
  verified that `bd init` auto-derives a git identity under a minimal env, so no
  `BEADS_ACTOR`/gitconfig is needed.)

Both hand back a production `SubprocessBdRunner(bd_binary=<abs bd>, cwd=<tmp>,
env={**os.environ, "BD_NON_INTERACTIVE": "1", "BEADS_DIR": "<tmp>/.beads"})` and
drive `main(argv, runner=…, out=…, err=…)`, asserting on the stdout envelope.
`BEADS_DIR` is the load-bearing isolation lever — see §6.

## 4. Coverage matrix

- **Every verb once** (happy-path): show, list, ready, search · create --raw,
  update, note, close, reopen · claim, release, plan, promote, deliver,
  reconcile · dep {add,remove,list}, label {add,remove,list} · sync.
- **Every create-noun** (7): spike, chore, decision, feat, bugfix, spec, epic —
  assert each template's resulting bd fields.
- **Lifecycle sequences:** `create→claim→deliver(evidence)→reconcile`;
  `plan add→plan --done`; `promote shape-feat→shape-spec container`.
- **Error paths (within reason):** `E_NOT_FOUND` (bogus id — reaches bd with no
  pre-check, genuinely drift-covered), `E_USAGE` (bad flags),
  **evidence-gate refusal** on `deliver`, and the dep **type-wall** — with the
  caveat below.

**Assertions are value-level, not `ok=True`.** Drift detection is only as sound
as assertion specificity. `parse_item` hard-requires just `id/title/issue_type/
status/priority`; every *optional* field (`labels`, `parent`, `notes`,
`description`, `dependencies`, timestamps) is defaulted from `raw.get(...)`, so a
bd rename `labels`→`tags` parses silently to `[]` and an `ok=True`-only test
never notices — defeating goal 3. Therefore: read/happy-path tests assert the
**exact seeded values** round-trip (the seeded labels, parent, notes, dep-edge
come back with the seeded content), and at least one seeded issue is asserted as
a full normalized `Item`. The noun tests already assert each template's bd
fields; this extends that discipline to the read verbs.

**Type-wall — two distinct assertions, because the verb pre-checks it.**
`work dep add <epic> <task>` raises `E_TYPE_WALL` from the **verb-layer
pre-check** (`verbs/relations.py` reads both items and compares epic-ness
*before* calling bd), so a verb-level test is behaviorally identical to the
existing hermetic unit test and is **drift-blind** to bd's own wall. To get real
coverage: (a) keep the verb-level `E_TYPE_WALL` envelope assertion, **and**
(b) drive bd's `dep add` directly through a raw `SubprocessBdRunner` (bypassing
the pre-check) and assert bd's real stderr still contains the
`map_bd_failure` marker (`"can only block"`). (b) is what actually pins the
marker against bd drift; (a) alone does not.

## 5. Fault injection — a Python call-counting runner, not a shell shim

The naive design (a `bd_shim.sh` reading a boolean `WORKCLI_ITEST_FAULT`) is
**wrong for the marquee test** and is dropped. A single `work` command fans out
to *many* bd subprocesses — `deliver` reads before it mutates; `dep_list` makes
2 calls; `sync` makes `commit` then `push`; `label_mutate` one call per label. A
boolean env var faults the **first** bd child (a read), so `deliver` aborts
*before any mutation* and `reconcile` has nothing to heal — the recovery test
degenerates to a no-op. The interesting partial state (`[work] manifest:` note
appended but `impl-placeholder` label not yet removed) lives *between* bd child
call *k* and *k+1* of one `work deliver`, and only per-call targeting reaches it.

**Mechanism: `FaultInjectingBdRunner`** — a `BdRunner` decorator in the test tree
that wraps the real `SubprocessBdRunner`, counts `.run()` invocations, delegates
calls `1..N-1` to real bd (leaving **genuine partial bd state**), and on call `N`
injects the fault. This needs no OS crash: a mid-sequence bd *failure* already
aborts `deliver` (`map_bd_failure` → `WorkError`) with real state half-applied,
after which `work reconcile` **in the same test** heals it against real bd. It is
also portable (no shell, no PATH/`exec` hazard) and rides the same injectable
port §2 introduces.

Fault modes the decorator emits on call `N`:
- **non-zero exit** — abort a lifecycle sequence mid-mutation; assert `reconcile`
  recovers the real partial state (the deliver↔reconcile contract, the wgclw.9.5
  work, exercised end-to-end — impossible to fake honestly).
- **malformed JSON on stdout with exit 0**, targeted at a **`--json` read verb**
  (`work show <seeded-id>`) — this is the only path that reaches the `parse.py`
  drift alarm. Assert the specific `detail.reason == "invalid_json"` from
  `_load_json_array`, not a generic `BACKEND_DRIFT`. (Rationale: mutation verbs
  don't pass `--json` and never parse stdout — garbage with exit 0 there is
  silently ignored; garbage with non-zero exit hits `map_bd_failure`'s rc-branch
  instead, a *different* alarm.)

**Boundary:** true 60s-timeout retry stays a fast **unit** test (injected
short-timeout runner); the decorator never `sleep`s (a real sleep would block on
`runner.py`'s hard-coded 60s deadline). It covers exit-code and garbage-output
faults, not a real hang.

## 6. Isolation & safety

The naive claim "cwd isolation structurally cannot touch the repo DB" is
**overstated**: bd discovers `.beads` by walking *up* the directory tree
(verified — from a dir nested under the worktree, `bd list` returned the repo's
real issue). cwd-only isolation then rests on three contingent conditions
(tmp lands off-repo, `bd init` creates a nearer `.beads` before any mutation, the
guard fires otherwise), not structure — and a partway-failed `bd init` leaves no
nearer `.beads`, so a follow-on seed would walk up. The design makes isolation
**actually structural**:

- **`BEADS_DIR=<install>/.beads` in the fixture env** binds bd to the temp DB and
  **disables walk-up entirely** (verified: with cwd at the repo root,
  `BEADS_DIR=<tmp>/.beads bd list` returned the tmp DB, never the repo's). This
  is the primary guarantee; cwd isolation becomes belt, not the whole belt.
- **Every install lives under pytest `tmp_path`** (default basetemp is off-repo,
  `/private/var/folders/…`), never the repo tree.
- **A pre-flight guard runs before *any* bd call** and refuses if the install
  path resolves inside a git repo. "Repo" here means the **main repo common-dir**
  (`git rev-parse --git-common-dir`), not the worktree toplevel — the real
  `.beads` sits two levels *above* this worktree, so a guard keyed on
  `--show-toplevel` would resolve to the worktree root and miss a basetemp placed
  under the main repo but above the worktree. Defense-in-depth: refuse if
  `tmp_path` is nested in *any* git repo, so bd can never commit its self-init
  into an enclosing checkout.
- **Embedded Dolt spawns no sql-server** (verified: no `dolt sql-server` appears
  across repeated inits; only short-lived file locks released on process exit),
  so there is no lingering process to reap; `tmp_path` auto-cleans. Note `bd
  init` also writes a local git repo + `.claude/`/`CLAUDE.md`/hooks into the temp
  dir — all inert under `tmp_path`, listed here only so they don't surprise.

## 7. Wiring & docs

- `make itest-workcli` → `cd $(WORKCLI) && uv run pytest tests/integration -q
  -p no:xdist`. **Not** in `ci-workcli` or `ci`. The explicit `-p no:xdist`
  pins the suite **serial**: pytest-xdist is a declared dev dep, and under
  `-n auto` the session-scoped `read_only_install` re-inits **once per worker**
  (each worker gets its own `popen-gwN` basetemp, so no DB collision — just the
  ~1.4s init cost multiplied), silently defeating the "pay Dolt once" claim.
  Serial keeps that claim true.
- `pyproject.toml`: default `testpaths = ["tests/unit"]` so `make test-workcli`
  / `cov-workcli` (both invoked with no path arg) collect `tests/unit` only —
  coverage stays unit-scoped and the hermetic gate stays hermetic; the
  integration suite's explicit path arg overrides `testpaths`. This is the
  correct isolation mechanism (simpler than markers) — load-bearing caveat: the
  new `SubprocessBdRunner` params are therefore covered only by unit tests, met
  by the zero-new-branch discipline in §2.
- `packages/workcli/AGENTS.md`: document the target, its `bd`-on-PATH
  requirement, the ~40s+ serial wall-clock (≈30 function-scoped inits × 1.4s
  before mutations — a pre-push target, not a fast inner loop), and that it is
  **pre-push discipline, not a merge gate**.

## Resolved open items

- **`sync` on a remote-less temp install** — verified: `bd dolt commit` (nothing
  pending) → "Nothing to commit." on **stdout**, exit 0; `bd dolt push` (no
  remote) → "No remote is configured — skipping.", exit 0. So `work sync` returns
  `ok=true` and the test asserts that honest success. **But** this path never
  exercises the two `map_bd_failure` markers `_NOTHING_TO_COMMIT_STDERR_MARKER`
  and `_SYNC_BEHIND_STDERR_MARKER` — which are explicitly *guessed* in
  `backend.py` (an "orchestrator ruling, not a golden capture"), precisely the
  strings a real-bd suite should validate. Worse, real bd prints "Nothing to
  commit." on *stdout* while the marker checks *stderr* lowercase — a latent
  dead-code mismatch. Coverage decision: add a `sync` test that **seeds a real
  pending change then commits** (exercises the commit-with-content path), and
  explicitly document the two stderr markers as **knowingly un-drift-covered**
  by this suite (reachable only with a configured remote / dirty-merge state,
  out of scope per YAGNI). The suite usefully *pins* the stdout-vs-stderr fact.
- **Seed via raw `bd`, not `work`** — keeps read-fixture correctness independent
  of the write path under test.

## Out of scope (YAGNI)

No CI job, no Dolt-server mode, no perf benchmarking, no cross-bd-version
matrix.

## Continuations

- Optional follow-up (file only if desired after the suite proves stable):
  a CI job that installs bd and runs `make itest-workcli` as a merge gate —
  deferred per decision 1. Not created now.

## Review feedback

Round 1 — two independent adversarial reviewers (ralf-review, cap 2/2),
each validating claims against real bd 1.0.3 in throwaway installs. Verdict:
`PASS_WITH_RESERVATIONS`. All findings folded into the body above:

- **CRITICAL (both) — crash-fault targeting.** A boolean env-var shim faults the
  first bd child (a read), so `deliver` aborts before mutating and `reconcile`
  heals nothing. → §5 rewritten to a call-counting `FaultInjectingBdRunner`; the
  shell shim is dropped.
- **MAJOR (both) — dep type-wall is drift-blind.** The verb-layer pre-check
  raises `E_TYPE_WALL` before bd is called. → §4 adds a raw-runner assertion on
  bd's real marker alongside the verb-level envelope test.
- **MAJOR — isolation overstated.** bd walks up the tree (verified). → §6 binds
  `BEADS_DIR`, strengthens the guard to the main-repo common-dir + any-git-repo.
- **MAJOR — drift needs value-level assertions.** Optional-field renames parse
  silently. → §4 mandates seeded-value round-trip assertions.
- **MAJOR — sync bypasses the guessed markers.** → resolved-open-items documents
  them as knowingly un-drift-covered and adds a commit-with-content test.
- **Minor — malformed-JSON path** (target a `--json` read verb, exit 0, assert
  `invalid_json`), **xdist per-worker cost** (`-p no:xdist`), **absolute bd path**
  (`shutil.which`), **init-failure diagnostic**, **thread-through-don't-branch**
  coverage guidance. → folded into §§2/3/5/7.

Reviewers confirmed sound (no change needed): injectable-port back-compat,
embedded-Dolt leaves no process, `testpaths` cov-isolation, env sufficiency
(git identity auto-derives), remote-less sync returns `ok=true`,
`E_NOT_FOUND` genuinely drift-covered.
