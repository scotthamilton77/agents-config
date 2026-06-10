# prgroom gh/git Protocol Adapter Layer — Implementation Plan (bead 8.5)

> **For agentic workers:** Implement task-by-task using `test-driven-development` (red-green-refactor per task). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the gh and git boundary-adapter layer — two `@runtime_checkable` Protocols with structurally-satisfying subprocess CLI adapters that map gh/git failures to the existing `ErrorCode` registry, plus recorded-response fakes and per-adapter fit-tests.

**Architecture:** A shared `CommandRunner` Protocol (mirrors the `Clock`/`Randomness`/`Deps` seam) is the single injection point — the system boundary is `subprocess.run`, wrapped by `SubprocessRunner` in production and a `RecordedRunner` fake in tests. `GhCli` and `GitCli` adapters route every external call through the injected runner and classify failures into existing `PrgroomError(tier, code)` pairs. 404 from gh surfaces as a typed `GhNotFoundError` (the out-of-scope verb owns the precondition decision per spec §3.7); non-404 4xx → `RUNTIME_GH_TERMINAL`.

**Tech Stack:** Python 3.11+, stdlib `subprocess`, typer (runtime), pytest + mypy --strict (dev). No new dependencies.

---

## Reconciliation pins (from spec §3.6/§3.7 + errors.py)

- gh 5xx OR rate-limit (403/429 with `Retry-After` / `X-RateLimit-Remaining: 0`) → `Tier.RUNTIME_TRANSIENT` + `ErrorCode.RUNTIME_GH_TRANSIENT`
- gh 4xx ≠ 404 ≠ rate → `Tier.RUNTIME_TERMINAL_USER` + `ErrorCode.RUNTIME_GH_TERMINAL`
- gh 404 → `GhNotFoundError` (typed signal; NOT a PrgroomError — caller's startup precondition owns `PRECONDITION_REPO_UNREACHABLE`)
- gh GraphQL: exit 0 but `errors[]` present in JSON → `Tier.RUNTIME_TRANSIENT` + `ErrorCode.RUNTIME_GRAPHQL_FAILED`
- git push rejected (`! [rejected]`, `non-fast-forward`, `protected branch`, hook decline) → `Tier.RUNTIME_TERMINAL_USER` + `ErrorCode.RUNTIME_PUSH_REJECTED`
- git network failure (`subprocess.TimeoutExpired`, `Could not resolve host`, `Connection timed out`, `Connection reset`) → `Tier.RUNTIME_TRANSIENT` + `ErrorCode.RUNTIME_GIT_TRANSIENT`
- Adapters structurally satisfy their Protocol (no inheritance); `mypy --strict` proves the fit.

## File structure

- Create `src/prgroom/proc.py` — `CommandResult`, `CommandRunner` Protocol, `SubprocessRunner`.
- Create `src/prgroom/gh/__init__.py` — re-export `GhClient`, `GhCli`, `GhNotFoundError`.
- Create `src/prgroom/gh/client.py` — Protocol + adapter + `_classify_gh_failure`.
- Create `src/prgroom/git/__init__.py` — re-export `GitClient`, `GitCli`.
- Create `src/prgroom/git/client.py` — Protocol + adapter + `_classify_git_failure`.
- Create `tests/fakes.py` — `RecordedRunner` (matches argv → recorded `CommandResult`).
- Create `tests/unit/test_proc.py` — `SubprocessRunner` boundary test (monkeypatch `subprocess.run`).
- Create `tests/unit/test_gh_fit.py` — gh adapter surface + every classification arm vs `RecordedRunner`.
- Create `tests/unit/test_git_fit.py` — git adapter surface + every classification arm vs `RecordedRunner`.
- Create `tests/fixtures/gh/*`, `tests/fixtures/git/*` — recorded stdout/stderr fixtures.

---

### Task 1: Shared CommandRunner seam (`proc.py`)

**Files:**
- Create: `src/prgroom/proc.py`
- Create: `tests/fakes.py`
- Test: `tests/unit/test_proc.py`

- [ ] Step 1: Write `tests/fakes.py` with `RecordedRunner` — a `CommandRunner` fake that pops a queued `CommandResult` per call (FIFO) and records the argv it saw; raises if the queue empties. Also support a `TimeoutRunner` that raises `subprocess.TimeoutExpired`.
- [ ] Step 2: Write failing `tests/unit/test_proc.py`: `SubprocessRunner().run([...])` returns a `CommandResult` whose fields come from a monkeypatched `subprocess.run` (boundary mock). Assert `text=True`, `capture_output=True`, `check=False`, and that `input`/`timeout` are forwarded. Run → FAIL (module missing).
- [ ] Step 3: Implement `proc.py`: `@dataclass(frozen=True, slots=True) CommandResult(returncode, stdout, stderr)`; `@runtime_checkable CommandRunner(Protocol)` with `run(argv, *, input=None, timeout=None) -> CommandResult`; `SubprocessRunner` wrapping `subprocess.run(list(argv), capture_output=True, text=True, check=False, input=input, timeout=timeout)`.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(prgroom): CommandRunner subprocess seam (8.5)`.

### Task 2: gh adapter + classification (`gh/client.py`)

**Files:**
- Create: `src/prgroom/gh/client.py`, `src/prgroom/gh/__init__.py`
- Test: `tests/unit/test_gh_fit.py`
- Fixtures: `tests/fixtures/gh/`

- [ ] Step 1: Write failing `test_gh_fit.py` covering the full public surface against `RecordedRunner`:
  - `head_ref_oid(ref)` parses `{"headRefOid": "abc"}` stdout.
  - `rest("GET", path)` returns parsed JSON on success.
  - `graphql(query, variables)` returns `data` on success; raises `PrgroomError(RUNTIME_GRAPHQL_FAILED, RUNTIME_TRANSIENT)` when stdout JSON has `errors[]`.
  - classification arms: 503 stderr `gh: ... (HTTP 503)` → `RUNTIME_GH_TRANSIENT`; 429 with rate-limit → `RUNTIME_GH_TRANSIENT`; 422 → `RUNTIME_GH_TERMINAL`; 404 → `GhNotFoundError`.
  - structural fit: `isinstance(GhCli(RecordedRunner()), GhClient)`.
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement `gh/client.py`: `GhNotFoundError(Exception)`; `@runtime_checkable GhClient(Protocol)` with `head_ref_oid`, `rest`, `graphql`; `GhCli(runner)` adapter; `_classify_gh_failure(result)` parsing `(HTTP NNN)` from stderr, rate-limit via stderr/`Retry-After`, raising the mapped error. GraphQL success-with-errors detected by inspecting parsed JSON.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(prgroom): gh subprocess adapter + failure classification (8.5)`.

### Task 3: git adapter + classification (`git/client.py`)

**Files:**
- Create: `src/prgroom/git/client.py`, `src/prgroom/git/__init__.py`
- Test: `tests/unit/test_git_fit.py`
- Fixtures: `tests/fixtures/git/`

- [ ] Step 1: Write failing `test_git_fit.py`:
  - `head_sha()` returns stripped stdout SHA.
  - `rev_list(range_)` splits stdout lines into a list (empty stdout → `[]`).
  - `push(remote, branch)` returns None on success.
  - `stash()` returns None on success.
  - classification: push `! [rejected] ... (non-fast-forward)` → `RUNTIME_PUSH_REJECTED`; `protected branch` → `RUNTIME_PUSH_REJECTED`; `Could not resolve host` → `RUNTIME_GIT_TRANSIENT`; `TimeoutRunner` → `RUNTIME_GIT_TRANSIENT`.
  - structural fit: `isinstance(GitCli(RecordedRunner()), GitClient)`.
- [ ] Step 2: Run → FAIL.
- [ ] Step 3: Implement `git/client.py`: `@runtime_checkable GitClient(Protocol)`; `GitCli(runner)`; `_classify_git_failure(result_or_timeout)` mapping rejection vs transient.
- [ ] Step 4: Run → PASS.
- [ ] Step 5: Commit `feat(prgroom): git subprocess adapter + push/transient classification (8.5)`.

### Task 4: Integration tier — real git on a fixture repo

**Files:**
- Test: `tests/integration/test_git_real.py`

- [ ] Step 1: Write a test using a `tmp_path` git repo (real `SubprocessRunner`): init, commit twice, assert `head_sha()` is 40 hex chars and `rev_list("HEAD~1..HEAD")` has length 1. Skip if `git` not on PATH.
- [ ] Step 2: Run → may FAIL until paths align; Step 3 fix; Step 4 PASS.
- [ ] Step 5: Commit `test(prgroom): real-git integration for the git adapter (8.5)`.

### Task 5: Coverage close-out + completion gate

- [ ] `make -C <worktree> ci-prgroom` green (90% branch).
- [ ] quality-reviewer → address → simplify → address → verify-checklist.
