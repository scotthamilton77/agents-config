# workcli real-bd integration harness — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local `make itest-workcli` suite that drives the production `work` CLI against a real, isolated bd install in a temp dir — catching bd-JSON drift the hermetic unit fakes cannot.

**Architecture:** Make the production `SubprocessBdRunner` injectable (`bd_binary`/`cwd`/`env`), then build a `tests/integration/` suite whose fixtures `bd init` a throwaway `.beads` under `tmp_path`, bind bd to it with `BEADS_DIR`, and drive `workcli.cli.main(argv, runner=…)`. A `FaultInjectingBdRunner` decorator counts `.run()` calls and injects faults mid-sequence to exercise the deliver↔reconcile recovery contract against real bd state. The suite is kept out of the hermetic `make ci-workcli` gate.

**Tech Stack:** Python ≥3.11 (stdlib only), pytest, uv, real `bd` 1.0.3 (embedded Dolt), GNU make.

**Spec:** `docs/specs/2026-07-14-workcli-realbd-integration-harness-design.md`
**Bead:** agents-config-wgclw.9.7

**Worktree:** all paths are relative to the repo root `/Users/scott/src/projects/agents-config/.claude/worktrees/wgclw-9.7-realbd-itest`. **First action for any worker:** run `git rev-parse --show-toplevel` and confirm it ends in `.claude/worktrees/wgclw-9.7-realbd-itest`; if not, stop — you are in the wrong tree.

**Gate note:** the package gate is `make ci-workcli`, run **from the worktree root** (it `cd`s into `packages/workcli` itself). The new `tests/integration/` suite MUST NOT run in that gate. Faster inner loop for unit work: `make test-workcli`. The integration suite runs only via `make itest-workcli` (added in Task 11).

---

## File Structure

**Modify:**
- `packages/workcli/src/workcli/adapters/bd/runner.py` — add injectable `bd_binary`/`cwd`/`env` to `SubprocessBdRunner` (Task 1).
- `packages/workcli/tests/unit/test_subprocess_runner.py` — cover the injected params hermetically (Task 1).
- `packages/workcli/pyproject.toml` — add `[tool.pytest.ini_options] testpaths = ["tests/unit"]` (Task 2).
- `Makefile` (repo root) — add `itest-workcli` target (Task 11).
- `packages/workcli/AGENTS.md` — document the itest target (Task 11).

**Create (all under `packages/workcli/tests/integration/`):**
- `__init__.py` — empty (package marker).
- `conftest.py` — isolation guard, `bd_available`, `bd_env`, `_run_bd` helper, `read_only_install`, `fresh_install`, `driver` (Tasks 2–3).
- `fault_runner.py` — `FaultInjectingBdRunner` decorator + `Fault` modes (Task 4).
- `test_fault_runner.py` — hermetic unit test of the decorator (Task 4).
- `test_isolation.py` — proves the guard + isolation (Task 2).
- `test_verbs_happy.py` — every-verb-once, value-level (Task 5).
- `test_nouns.py` — every create-noun (Task 6).
- `test_lifecycle.py` — create→claim→deliver→reconcile; plan; promote (Task 7).
- `test_error_paths.py` — E_NOT_FOUND, E_USAGE, evidence-gate, type-wall dual (Task 8).
- `test_crash_recovery.py` — mid-deliver fault → reconcile heals; malformed-json→invalid_json (Task 9).
- `test_sync.py` — remote-less ok=true + commit-with-content (Task 10).

---

## Task 1: Injectable `SubprocessBdRunner`

**Files:**
- Modify: `packages/workcli/src/workcli/adapters/bd/runner.py`
- Test: `packages/workcli/tests/unit/test_subprocess_runner.py`

Thread `bd_binary`/`cwd`/`env` straight into `subprocess.run` with **no conditional branches** (`subprocess.run` treats `cwd=None`/`env=None` as "inherit"), so zero new branches touch the 90% floor. This lands first because every fixture depends on it.

- [ ] **Step 1: Write the failing tests** (append to `test_subprocess_runner.py`)

```python
def test_run_uses_injected_bd_binary_cwd_and_env(tmp_path, monkeypatch):
    # A fake bd that proves all three injected params reached subprocess.run:
    # it echoes its own argv[0] name, its cwd, and a custom env var.
    fake_dir = tmp_path / "bin"
    fake_dir.mkdir()
    fake_bd = fake_dir / "mybd"
    fake_bd.write_text(
        "#!/bin/sh\n"
        'echo "cwd=$(pwd)"\n'
        'echo "marker=$WORKCLI_ITEST_MARKER"\n'
    )
    fake_bd.chmod(fake_bd.stat().st_mode | stat.S_IEXEC)
    workdir = tmp_path / "work"
    workdir.mkdir()
    # Ensure PATH does NOT contain a `bd`, proving bd_binary (absolute) is used.
    monkeypatch.setenv("PATH", "/nonexistent")

    runner = SubprocessBdRunner(
        bd_binary=str(fake_bd),
        cwd=str(workdir),
        env={"WORKCLI_ITEST_MARKER": "42", "PATH": "/nonexistent"},
    )
    result = runner.run(["show", "--json"])

    assert result.returncode == 0
    assert f"cwd={workdir}" in result.stdout
    assert "marker=42" in result.stdout


def test_run_defaults_are_unchanged(tmp_path, monkeypatch):
    # Default construction must remain byte-identical to today: binary "bd",
    # inherited cwd/env. Prove by putting a fake `bd` on PATH and NOT passing
    # any injected params.
    _write_fake_bd(tmp_path, 'echo "default-path-bd"\n')
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)

    result = SubprocessBdRunner().run(["list"])

    assert result.returncode == 0
    assert result.stdout == "default-path-bd\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/workcli && uv run pytest tests/unit/test_subprocess_runner.py -v`
Expected: the two new tests FAIL with `TypeError: SubprocessBdRunner() takes no arguments` (or `__init__` got an unexpected keyword argument).

- [ ] **Step 3: Add the injectable constructor** — replace the `SubprocessBdRunner` class body in `runner.py`

```python
class SubprocessBdRunner:
    """Drives the real bd binary. timeout=60s; TimeoutExpired is retryable (decision 8).

    Raising `subprocess.TimeoutExpired` on deadline is subprocess.run's own
    documented behavior -- this class does not catch it. `adapters/bd/retry.py`
    is the layer that treats it as a retryable signal.

    `bd_binary`/`cwd`/`env` are injectable so a caller (the integration harness)
    can point the port at an isolated temp install or a fault-injecting wrapper.
    They are threaded straight into `subprocess.run`, which treats `None` as
    "inherit" -- so the defaults reproduce the original hardcoded behavior
    exactly, and no conditional branch is added.
    """

    def __init__(
        self,
        *,
        bd_binary: str = "bd",
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._bd_binary = bd_binary
        self._cwd = cwd
        self._env = env

    def run(self, args: Sequence[str]) -> BdResult:
        completed = subprocess.run(
            [self._bd_binary, *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=self._cwd,
            env=dict(self._env) if self._env is not None else None,
        )
        return BdResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
```

Add the imports at the top of `runner.py` (after `from typing import Protocol`):

```python
from collections.abc import Mapping
from pathlib import Path
```

Note: `dict(self._env) if self._env is not None else None` is a single expression, not an `if`-statement branch — mypy/coverage see one expression. `Sequence` is already imported; add `Mapping` to the existing `collections.abc` import line rather than duplicating it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/workcli && uv run pytest tests/unit/test_subprocess_runner.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Run the full hermetic gate to prove the floor is intact**

Run (from worktree root): `make ci-workcli`
Expected: PASS — lint, format, mypy --strict, `pytest --cov` ≥90% branch, pip-audit, entry-verify all green. The new params added zero uncovered branches.

- [ ] **Step 6: Commit**

```bash
git add packages/workcli/src/workcli/adapters/bd/runner.py packages/workcli/tests/unit/test_subprocess_runner.py
git commit -m "feat(workcli): make SubprocessBdRunner injectable (bd_binary/cwd/env)

Threaded straight into subprocess.run with no new branches. Unblocks the
real-bd integration harness (wgclw.9.7). Default construction unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 2: Integration scaffold — isolation guard, `bd_available`, `testpaths`

**Files:**
- Create: `packages/workcli/tests/integration/__init__.py` (empty)
- Create: `packages/workcli/tests/integration/conftest.py`
- Create: `packages/workcli/tests/integration/test_isolation.py`
- Modify: `packages/workcli/pyproject.toml`

The safety foundation: prove bd is present, resolve it to an absolute path, and refuse to run if the temp install could resolve into any git repo (defense against bd's upward `.beads` walk).

- [ ] **Step 1: Add `testpaths` so integration never runs in the hermetic gate** — add to `pyproject.toml` (new section; there is no `[tool.pytest.ini_options]` today)

```toml
[tool.pytest.ini_options]
# The default collection (make test-workcli / cov-workcli invoke pytest with no
# path arg) is the hermetic unit suite only. The real-bd integration suite is
# invoked by explicit path in `make itest-workcli` (which overrides testpaths)
# and must never enter the coverage-gated run.
testpaths = ["tests/unit"]
```

- [ ] **Step 2: Write the failing isolation test** — `tests/integration/test_isolation.py`

```python
"""The isolation guard is load-bearing: it must refuse to run bd anywhere that
could resolve into a real .beads via bd's upward directory walk."""

from __future__ import annotations

import subprocess

import pytest

from tests.integration.conftest import assert_off_repo, resolve_bd


def test_resolve_bd_returns_absolute_path_or_skips():
    bd = resolve_bd()  # skips the module if bd is absent
    assert bd.startswith("/")


def test_guard_refuses_a_path_inside_a_git_repo(tmp_path):
    # A tmp dir that IS a git repo must be rejected (bd would commit into it /
    # walk up to its .beads).
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with pytest.raises(RuntimeError, match="inside a git repo"):
        assert_off_repo(tmp_path)


def test_guard_allows_a_bare_tmp_dir(tmp_path):
    # pytest tmp_path is off-repo (/private/var/folders/... on macOS); no ancestor
    # is a git repo, so the guard passes.
    assert_off_repo(tmp_path)  # must not raise
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd packages/workcli && uv run pytest tests/integration/test_isolation.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'assert_off_repo'` (conftest not written yet).

- [ ] **Step 4: Write the guard + bd resolver** — start `tests/integration/conftest.py`

```python
"""Fixtures + guards for the real-bd integration suite.

Every install is a throwaway .beads under pytest tmp_path, bound to bd via
BEADS_DIR so bd's upward .beads discovery can never reach the repo's real DB.
The suite skips wholesale when bd is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def resolve_bd() -> str:
    """Absolute path to the bd binary, or skip the whole module if absent."""
    bd = shutil.which("bd")
    if bd is None:
        pytest.skip("bd not on PATH; the real-bd integration suite requires it")
    return bd


def assert_off_repo(path: Path) -> None:
    """Refuse if `path` is inside any git repo (belt: bd walks UP for .beads,
    so a repo-nested install could reach a real .beads or commit bd's self-init
    into an enclosing checkout). tmp_path is off-repo, so this passes normally."""
    resolved = path.resolve()
    for ancestor in (resolved, *resolved.parents):
        if (ancestor / ".git").exists():
            raise RuntimeError(
                f"refusing to run bd under {resolved}: ancestor {ancestor} is inside a git repo; "
                "the integration harness must install into an off-repo temp dir"
            )
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd packages/workcli && uv run pytest tests/integration/test_isolation.py -v`
Expected: PASS (or the whole module SKIPS if bd is absent — acceptable green).

Also confirm the hermetic gate still ignores integration:
Run (from worktree root): `make cov-workcli`
Expected: collects `tests/unit` only; integration not collected; coverage still ≥90%.

- [ ] **Step 6: Commit**

```bash
git add packages/workcli/tests/integration/ packages/workcli/pyproject.toml
git commit -m "test(workcli): integration scaffold — isolation guard + bd resolver + testpaths

Guard refuses any git-repo-nested install (bd walks up for .beads); testpaths
pins the hermetic gate to tests/unit. wgclw.9.7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

Add an empty `packages/workcli/tests/integration/__init__.py` in this commit too (so `from tests.integration.conftest import …` resolves; `tests/` already has its own package markers — mirror them).

---

## Task 3: Install fixtures — `bd_env`, `_run_bd`, `fresh_install`, `read_only_install`, `driver`

**Files:**
- Modify: `packages/workcli/tests/integration/conftest.py`
- Create: `packages/workcli/tests/integration/test_fixtures_smoke.py` (a smoke test that also serves as the fixtures' red/green)

Fixtures wrap `bd init` with loud failure, bind `BEADS_DIR`, seed the read-only corpus via raw bd, and hand back a production `SubprocessBdRunner` plus a `driver` that runs `main()`.

- [ ] **Step 1: Write the failing smoke test** — `tests/integration/test_fixtures_smoke.py`

```python
"""Smoke-proves the fixtures stand up a real isolated bd and the driver round-trips."""

from __future__ import annotations


def test_fresh_install_is_empty_and_isolated(fresh_install, driver):
    env = driver(["list", "--json"])
    assert env["ok"] is True
    assert env["data"]["items"] == []


def test_read_only_corpus_is_seeded(read_only_driver):
    env = read_only_driver(["list", "--json"])
    assert env["ok"] is True
    titles = {item["title"] for item in env["data"]["items"]}
    assert {"seed-alpha", "seed-beta", "seed-child"} <= titles
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/workcli && uv run pytest tests/integration/test_fixtures_smoke.py -v`
Expected: FAIL — fixtures `fresh_install`, `driver`, `read_only_driver` not defined.

- [ ] **Step 3: Add the fixtures** — append to `tests/integration/conftest.py`

```python
import io
import json
import os
from collections.abc import Callable, Sequence

from workcli.adapters.bd.runner import SubprocessBdRunner
from workcli.cli import main

_SEED_PREFIX = "itest"


@pytest.fixture(scope="session")
def bd_binary() -> str:
    return resolve_bd()


def _bd_env(install: Path) -> dict[str, str]:
    """Inherit the ambient env, force non-interactive, and BIND bd to this temp
    .beads so its upward-walk discovery can never reach the repo's real DB."""
    return {
        **os.environ,
        "BD_NON_INTERACTIVE": "1",
        "BEADS_DIR": str(install / ".beads"),
    }


def _run_bd(bd_binary: str, install: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Raw bd call for fixture setup/seeding (NOT the code under test). Loud on
    failure: a non-zero init/seed fails the suite with a named diagnostic, never
    a bare traceback."""
    proc = subprocess.run(
        [bd_binary, *args],
        cwd=install,
        env=_bd_env(install),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"fixture bd {' '.join(args)} failed (rc={proc.returncode}):\n{proc.stderr}"
        )
    return proc


def _bd_init(bd_binary: str, install: Path) -> None:
    assert_off_repo(install)  # guard BEFORE any bd call
    _run_bd(bd_binary, install, "init", "--prefix", _SEED_PREFIX)


def _make_driver(bd_binary: str, install: Path) -> Callable[[Sequence[str]], dict]:
    """Return a callable that drives the PRODUCTION main() against this install
    and returns the parsed stdout envelope."""
    runner = SubprocessBdRunner(bd_binary=bd_binary, cwd=str(install), env=_bd_env(install))

    def drive(argv: Sequence[str]) -> dict:
        out, err = io.StringIO(), io.StringIO()
        main(list(argv), runner=runner, out=out, err=err)
        return json.loads(out.getvalue())

    return drive


@pytest.fixture
def fresh_install(bd_binary: str, tmp_path: Path) -> Path:
    """A pristine bd install per test (for mutation/lifecycle/crash sequences)."""
    _bd_init(bd_binary, tmp_path)
    return tmp_path


@pytest.fixture
def driver(bd_binary: str, fresh_install: Path) -> Callable[[Sequence[str]], dict]:
    return _make_driver(bd_binary, fresh_install)


@pytest.fixture(scope="session")
def read_only_install(bd_binary: str, tmp_path_factory: pytest.TempPathFactory):
    """One shared, seeded install for read/happy-path assertions. Seeded via RAW
    bd so read tests fail for read reasons, not write-path bugs. The yield-based
    teardown re-asserts the corpus is intact, so a stray write-verb on the shared
    install fails LOUDLY rather than silently poisoning later read tests."""
    install = tmp_path_factory.mktemp("read_only_beads")
    _bd_init(bd_binary, install)
    # bd create's label flag is `--labels` (comma-separated), per backend.py.
    _run_bd(bd_binary, install, "create", "--title", "seed-alpha", "--type", "task",
            "--priority", "2", "--labels", "seed")
    _run_bd(bd_binary, install, "create", "--title", "seed-beta", "--type", "task",
            "--priority", "1")
    # A parent + child to give parent-edge assertions a real edge.
    parent = _run_bd(bd_binary, install, "create", "--title", "seed-parent", "--type", "epic",
                     "--priority", "2", "--json").stdout
    parent_id = json.loads(parent)["id"]
    _run_bd(bd_binary, install, "create", "--title", "seed-child", "--type", "task",
            "--priority", "2", "--parent", parent_id)

    yield install

    # Corpus-intact invariant (teardown): a read test that mutated the shared
    # install fails here, loudly.
    titles = {i["title"] for i in json.loads(_run_bd(bd_binary, install, "list", "--json").stdout)}
    assert {"seed-alpha", "seed-beta", "seed-child"} <= titles, (
        "read_only corpus was mutated by a test — read fixtures must stay read-only"
    )


@pytest.fixture
def read_only_driver(
    bd_binary: str, read_only_install: Path
) -> Callable[[Sequence[str]], dict]:
    return _make_driver(bd_binary, read_only_install)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd packages/workcli && uv run pytest tests/integration/test_fixtures_smoke.py -v`
Expected: PASS (≈4–6s: two `bd init`s + seeding). SKIPS cleanly if bd absent.

- [ ] **Step 5: Commit**

```bash
git add packages/workcli/tests/integration/
git commit -m "test(workcli): install fixtures — isolated bd init, BEADS_DIR bind, seeded corpus, driver

fresh_install/read_only_install wrap bd init with loud failure; driver runs the
production main() against a real isolated bd. wgclw.9.7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 4: `FaultInjectingBdRunner`

**Files:**
- Create: `packages/workcli/tests/integration/fault_runner.py`
- Create: `packages/workcli/tests/integration/test_fault_runner.py`

A `BdRunner` decorator that counts `.run()` calls, passes non-faulted calls to the wrapped real runner, and on a matched call returns a synthetic fault result. Its own test is hermetic (fake inner runner — no bd), so it is fast and deterministic.

- [ ] **Step 1: Write the failing test** — `tests/integration/test_fault_runner.py`

```python
from __future__ import annotations

from workcli.adapters.bd.runner import BdResult
from tests.integration.fault_runner import Fault, FaultInjectingBdRunner


class _RecordingRunner:
    """A fake inner BdRunner: records calls, returns a benign ok result."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(list(args))
        return BdResult(returncode=0, stdout="[]", stderr="")


def test_delegates_until_predicate_then_injects_nonzero():
    inner = _RecordingRunner()
    runner = FaultInjectingBdRunner(
        inner, fail_when=lambda n, argv: n == 2, fault=Fault.NONZERO_EXIT
    )
    first = runner.run(["show", "a", "--json"])
    second = runner.run(["update", "a", "--status", "closed"])

    assert first.returncode == 0          # delegated to real inner
    assert inner.calls == [["show", "a", "--json"]]  # call 2 never reached inner
    assert second.returncode != 0         # injected fault
    assert "injected" in second.stderr


def test_malformed_json_fault_is_exit_zero_garbage_stdout():
    inner = _RecordingRunner()
    runner = FaultInjectingBdRunner(
        inner, fail_when=lambda n, argv: "--json" in argv, fault=Fault.MALFORMED_JSON
    )
    result = runner.run(["show", "a", "--json"])

    assert result.returncode == 0
    assert result.stdout == "{ this is not valid json"
    assert inner.calls == []  # faulted on the first matching call
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/workcli && uv run pytest tests/integration/test_fault_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.integration.fault_runner`.

- [ ] **Step 3: Write the decorator** — `tests/integration/fault_runner.py`

```python
"""FaultInjectingBdRunner: wrap the real runner, count .run() calls, and inject a
fault on a matched call so a fault can land MID-`work`-command (a single work
command fans out to many bd children). This is what lets the crash-recovery test
leave real partial bd state for `reconcile` to heal — a boolean env-var shim
cannot, because it faults the first child (a read) before any mutation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum

from workcli.adapters.bd.runner import BdResult, BdRunner


class Fault(Enum):
    NONZERO_EXIT = "nonzero_exit"
    MALFORMED_JSON = "malformed_json"


# fail_when receives (1-based call index, argv) and returns True to fault THIS call.
FailWhen = Callable[[int, Sequence[str]], bool]


class FaultInjectingBdRunner:
    def __init__(self, inner: BdRunner, *, fail_when: FailWhen, fault: Fault) -> None:
        self._inner = inner
        self._fail_when = fail_when
        self._fault = fault
        self._n = 0

    def run(self, args: Sequence[str]) -> BdResult:
        self._n += 1
        if self._fail_when(self._n, args):
            if self._fault is Fault.MALFORMED_JSON:
                # exit 0 + garbage stdout: the ONLY path that reaches parse.py's
                # invalid_json drift alarm (a --json read verb parses stdout).
                return BdResult(returncode=0, stdout="{ this is not valid json", stderr="")
            return BdResult(returncode=1, stdout="", stderr="injected fault (itest)")
        return self._inner.run(args)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd packages/workcli && uv run pytest tests/integration/test_fault_runner.py -v`
Expected: PASS (hermetic, <1s).

- [ ] **Step 5: Commit**

```bash
git add packages/workcli/tests/integration/fault_runner.py packages/workcli/tests/integration/test_fault_runner.py
git commit -m "test(workcli): FaultInjectingBdRunner — call-counting mid-sequence fault injection

Wraps the real runner; faults on a matched call (index/argv predicate) so a
fault lands mid-work-command, leaving real partial state for reconcile. wgclw.9.7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 5: Happy-path — every verb once, value-level assertions

**Files:**
- Create: `packages/workcli/tests/integration/test_verbs_happy.py`

Drift detection is only as strong as assertion specificity. Read/happy-path tests assert **exact seeded values** round-trip (not just `ok=True`), because optional fields (`labels`/`parent`/`notes`) default silently on a rename.

- [ ] **Step 1: Write the tests** — `test_verbs_happy.py`

```python
"""Every verb once against real bd, asserting VALUE-LEVEL, not just ok=True.

Read verbs use the shared read_only corpus; mutating verbs use a fresh install."""

from __future__ import annotations


# ---- read verbs (shared corpus) ----

# NOTE (envelope shape, verified against verbs/read.py): a SINGLE-id `show`
# returns the item object DIRECTLY as `data` (not wrapped in {"items":[...]});
# only a 2+-id `show`, and every `list`/`ready`/`search`, wraps as
# `{"items": [...]}`. `label list` returns a BARE string[] as `data`.
# `Item.priority` is a STRING ("P0".."P4"), `Item.type` (not "issue_type").

def test_show_returns_exact_seeded_fields(read_only_driver):
    listing = read_only_driver(["list"])
    alpha_id = next(i["id"] for i in listing["data"]["items"] if i["title"] == "seed-alpha")
    env = read_only_driver(["show", alpha_id])
    assert env["ok"] is True
    item = env["data"]                          # single-id show → item object directly
    assert item["id"] == alpha_id
    assert item["title"] == "seed-alpha"
    assert item["status"] == "open"
    assert item["priority"] == "P2"             # priority is a string, not int
    assert "seed" in item["labels"]             # value-level: label round-trips


def test_list_filter_by_label(read_only_driver):
    env = read_only_driver(["list", "--label", "seed"])
    assert env["ok"] is True
    assert {i["title"] for i in env["data"]["items"]} == {"seed-alpha"}


def test_show_child_reports_seeded_parent(read_only_driver):
    listing = read_only_driver(["list"])
    child_id = next(i["id"] for i in listing["data"]["items"] if i["title"] == "seed-child")
    item = read_only_driver(["show", child_id])["data"]   # single-id show → item directly
    assert item["parent"] is not None           # value-level: parent edge survives


def test_ready_lists_unblocked(read_only_driver):
    env = read_only_driver(["ready"])
    assert env["ok"] is True
    assert isinstance(env["data"]["items"], list)


def test_search_finds_seeded(read_only_driver):
    env = read_only_driver(["search", "seed-beta"])
    assert env["ok"] is True
    assert any(i["title"] == "seed-beta" for i in env["data"]["items"])


# ---- write/relation/transition verbs (fresh install) ----

def test_create_raw_update_note_close_reopen_roundtrip(driver):
    created = driver(["create", "--raw", "--title", "wv-one", "--type", "task", "--priority", "2"])
    assert created["ok"] is True
    item_id = created["data"]["id"]             # create → {"id": ...}

    driver(["update", item_id, "--set-title", "wv-one-renamed"])
    assert driver(["show", item_id])["data"]["title"] == "wv-one-renamed"   # value-level

    driver(["note", item_id, "a durable note"])
    assert "a durable note" in driver(["show", item_id])["data"]["notes"]

    assert driver(["close", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "closed"

    assert driver(["reopen", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "open"


def test_label_add_list_remove(driver):
    item_id = driver(["create", "--raw", "--title", "wv-lbl", "--type", "task",
                      "--priority", "2"])["data"]["id"]
    driver(["label", "add", item_id, "alpha", "beta"])
    labels = driver(["label", "list", item_id])["data"]   # label list → bare string[]
    assert {"alpha", "beta"} <= set(labels)
    driver(["label", "remove", item_id, "alpha"])
    assert "alpha" not in driver(["label", "list", item_id])["data"]


def test_dep_add_list_remove(driver):
    a = driver(["create", "--raw", "--title", "wv-dep-a", "--type", "task",
                "--priority", "2"])["data"]["id"]
    b = driver(["create", "--raw", "--title", "wv-dep-b", "--type", "task",
                "--priority", "2"])["data"]["id"]
    driver(["dep", "add", a, b, "--type", "blocks"])
    listing = driver(["dep", "list", a])
    assert listing["ok"] is True
    driver(["dep", "remove", a, b])


def test_claim_and_release(driver):
    item_id = driver(["create", "--raw", "--title", "wv-claim", "--type", "task",
                      "--priority", "2"])["data"]["id"]
    assert driver(["claim", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "in_progress"
    assert driver(["release", item_id])["ok"] is True
```

(Note: `promote`, `plan`, `deliver`, `reconcile`, `sync` are covered by their dedicated tasks — Tasks 7/9/10 — not duplicated here.)

- [ ] **Step 2: Run to verify (red→green in one pass — behavior already exists)**

Run: `cd packages/workcli && uv run pytest tests/integration/test_verbs_happy.py -v`
Expected: PASS. If any assertion fails, that is a **real drift signal** — investigate whether bd's shape changed vs the parser's expectation (do NOT weaken the assertion to pass; that defeats the suite). Fix the parser/adapter or file a drift bead.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_verbs_happy.py
git commit -m "test(workcli): itest every-verb-once against real bd, value-level assertions (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 6: Every create-noun

**Files:**
- Create: `packages/workcli/tests/integration/test_nouns.py`

Assert each noun template's resulting bd fields (type + shape label), against real bd.

- [ ] **Step 1: Write the tests** — `test_nouns.py`

```python
"""Each `work create <noun>` template stamps the right bd type + shape label."""

from __future__ import annotations

import pytest

# (noun, expected bd type, expected shape label) — verified against
# lifecycle/nouns.py NOUN_TEMPLATES (bd_type, shape_label). Exact contract.
NOUN_EXPECTATIONS = [
    ("spike", "task", "shape-spike"),
    ("chore", "chore", "shape-chore"),
    ("decision", "decision", "shape-decision"),
    ("feat", "feature", "shape-feat"),
    ("bugfix", "bug", "shape-bugfix"),
    ("spec", "feature", "shape-spec"),
    ("epic", "epic", "shape-epic"),
]


@pytest.mark.parametrize("noun,bd_type,shape_label", NOUN_EXPECTATIONS)
def test_create_noun_stamps_type_and_shape_label(driver, noun, bd_type, shape_label):
    created = driver(["create", noun, "--title", f"noun-{noun}", "--priority", "2"])
    assert created["ok"] is True, created
    item_id = created["data"]["id"]                 # create → {"id": ...}
    shown = driver(["show", item_id])["data"]       # single-id show → item directly
    assert shown["type"] == bd_type                 # Item field is `type`, not `issue_type`
    assert shape_label in shown["labels"]
```

The `NOUN_EXPECTATIONS` table is already aligned to `lifecycle/nouns.py` `NOUN_TEMPLATES` (verified). If a run fails, that is a real signal — reconcile against `nouns.py`, do not blindly edit the table to pass.

- [ ] **Step 2: Run**

Run: `cd packages/workcli && uv run pytest tests/integration/test_nouns.py -v`
Expected: PASS for all 7 nouns.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_nouns.py
git commit -m "test(workcli): itest every create-noun template against real bd (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 7: Lifecycle sequences

**Files:**
- Create: `packages/workcli/tests/integration/test_lifecycle.py`

Multi-step guarded transitions end-to-end on real bd state: `create→claim→deliver(evidence)→reconcile`; `plan add→plan --done`; `promote`.

- [ ] **Step 1: Write the tests** — `test_lifecycle.py`

```python
"""Guarded lifecycle transitions on real bd state (happy path — no faults)."""

from __future__ import annotations


def test_create_claim_deliver_trivial_then_reconcile_noop(driver):
    # `create feat` mints a shape-feat leaf (not a container); claimable once ready.
    item_id = driver(["create", "feat", "--title", "lc-leaf", "--priority", "2"])["data"]["id"]
    assert driver(["claim", item_id])["ok"] is True
    # A leaf delivery with trivial evidence closes it.
    delivered = driver(["deliver", item_id, "--trivial"])
    assert delivered["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "closed"   # single-id show
    # reconcile with nothing recoverable is a clean no-op.
    swept = driver(["reconcile"])
    assert swept["ok"] is True


def test_plan_add_then_done(driver):
    # An epic IS a container (nouns.py: is_container=True), so `plan --done` needs
    # no --force (transitions.py::plan guards `not is_container and not --force`).
    item_id = driver(["create", "epic", "--title", "lc-epic", "--priority", "2"])["data"]["id"]
    assert driver(["plan", item_id])["ok"] is True             # add to Planning queue
    assert driver(["plan", item_id, "--done"])["ok"] is True   # container → no --force needed


def test_promote_leaf_to_spec_container(driver):
    # promote requires a shape-feat leaf (transitions.py::promote); `create feat`
    # provides exactly that. Result: the leaf becomes a shape-spec container.
    leaf = driver(["create", "feat", "--title", "lc-promote", "--priority", "2"])["data"]["id"]
    promoted = driver(["promote", leaf])
    assert promoted["ok"] is True
    assert promoted["data"]["promoted"] == "spec"
    assert "shape-spec" in driver(["show", leaf])["data"]["labels"]   # single-id show
```

Preconditions are verified against source (noted inline): `create feat`→claimable leaf; epic is a container so `plan --done` needs no `--force`; `promote` accepts the `shape-feat` leaf `create feat` produces. If a run fails, it is a real drift/logic signal — fix the cause, never weaken the transition being asserted.

- [ ] **Step 2: Run**

Run: `cd packages/workcli && uv run pytest tests/integration/test_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_lifecycle.py
git commit -m "test(workcli): itest lifecycle sequences (deliver/plan/promote) on real bd (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 8: Error paths (incl. type-wall dual assertion)

**Files:**
- Create: `packages/workcli/tests/integration/test_error_paths.py`

Typed failure envelopes from real bd. The type-wall needs **two** assertions because the verb layer pre-checks it before bd is ever called.

- [ ] **Step 1: Write the tests** — `test_error_paths.py`

```python
"""Typed error envelopes against real bd, within reason."""

from __future__ import annotations

from workcli.adapters.bd.runner import SubprocessBdRunner
from tests.integration.conftest import _bd_env


def test_show_bogus_id_is_not_found(driver):
    env = driver(["show", "itest-nope-xyz"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_NOT_FOUND"   # reaches bd, no pre-check → real drift coverage


def test_bad_flag_is_usage_error(driver):
    env = driver(["show", "--bogus-flag"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_USAGE"


def test_deliver_without_evidence_is_refused(driver):
    item_id = driver(["create", "feat", "--title", "ep-noevidence", "--priority", "2"])["data"]["id"]
    driver(["claim", item_id])
    env = driver(["deliver", item_id])   # no --pr/--items/--trivial
    assert env["ok"] is False
    assert env["error"]["code"] == "E_EVIDENCE"


def test_type_wall_verb_envelope(driver):
    # (a) The verb-layer pre-check raises E_TYPE_WALL before bd is called.
    epic = driver(["create", "epic", "--title", "ep-epic", "--priority", "2"])["data"]["id"]
    task = driver(["create", "feat", "--title", "ep-task", "--priority", "2"])["data"]["id"]
    env = driver(["dep", "add", epic, task, "--type", "blocks"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_TYPE_WALL"


def test_type_wall_raw_bd_marker_drift(fresh_install, bd_binary):
    # (b) DRIFT COVERAGE: drive bd's own `dep add` directly (bypassing the verb
    # pre-check) and assert bd still emits the marker map_bd_failure keys on
    # ("can only block"). This is the assertion that actually fails if bd changes
    # its wall wording — the verb-envelope test above cannot see that.
    runner = SubprocessBdRunner(bd_binary=bd_binary, cwd=str(fresh_install),
                                env=_bd_env(fresh_install))
    epic = _create_raw(runner, "rw-epic", "epic")
    task = _create_raw(runner, "rw-task", "task")
    result = runner.run(["dep", "add", epic, task, "--type", "blocks"])
    assert result.returncode != 0
    assert "can only block" in result.stderr.lower()


def _create_raw(runner, title, bd_type):
    import json
    r = runner.run(["create", "--json", "--title", title, "--type", bd_type, "--priority", "2"])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["id"]
```

The marker `"can only block"` matches `parse.py`'s `_TYPE_WALL_STDERR_MARKER` (verified) and real bd 1.0.3's stderr. If the raw-marker test ever fails, bd changed its wall wording — update `_TYPE_WALL_STDERR_MARKER` in `parse.py` (and note the drift); do not weaken the test.

- [ ] **Step 2: Run**

Run: `cd packages/workcli && uv run pytest tests/integration/test_error_paths.py -v`
Expected: PASS. The raw-marker test is the drift tripwire — if it fails, bd changed its wall message; update the marker in `parse.py` (and note the drift), don't weaken the test.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_error_paths.py
git commit -m "test(workcli): itest typed error paths + type-wall dual (verb + raw-bd marker) (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 9: Crash-recovery + malformed-JSON drift alarm

**Files:**
- Create: `packages/workcli/tests/integration/test_crash_recovery.py`

The crown jewel: fault a `work deliver` **mid-mutation** so real partial bd state survives, then prove `work reconcile` heals it. Plus the malformed-JSON→`invalid_json` drift-alarm path.

- [ ] **Step 1: Write the tests** — `test_crash_recovery.py`

```python
"""Crash-recovery against real bd state: a fault mid-`deliver` leaves the
impl-placeholder handle + manifest note recorded (real partial state); a
subsequent `work reconcile` replays reconcile_placeholder and heals to final
state. Also: a malformed-JSON bd response on a --json read verb must surface
E_BACKEND_DRIFT with detail.reason == "invalid_json"."""

from __future__ import annotations

import io
import json
from collections.abc import Sequence

from workcli.adapters.bd.runner import SubprocessBdRunner
from workcli.cli import main
from tests.integration.conftest import _bd_env
from tests.integration.fault_runner import Fault, FaultInjectingBdRunner


def _drive(runner, argv: Sequence[str]) -> dict:
    out, err = io.StringIO(), io.StringIO()
    main(list(argv), runner=runner, out=out, err=err)
    return json.loads(out.getvalue())


def test_malformed_json_on_read_is_invalid_json_drift(fresh_install, bd_binary):
    real = SubprocessBdRunner(bd_binary=bd_binary, cwd=str(fresh_install),
                              env=_bd_env(fresh_install))
    created = _drive(real, ["create", "--raw", "--title", "cr-item", "--type", "task",
                            "--priority", "2"])
    item_id = created["data"]["id"]

    # Fault the `show --json` read with garbage stdout, exit 0.
    faulted = FaultInjectingBdRunner(
        real, fail_when=lambda n, argv: "show" in argv and "--json" in argv,
        fault=Fault.MALFORMED_JSON,
    )
    env = _drive(faulted, ["show", item_id])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_BACKEND_DRIFT"
    assert env["error"]["detail"]["reason"] == "invalid_json"


def test_interrupted_deliver_is_healed_by_reconcile(fresh_install, bd_binary):
    """Fault a design-child `deliver` at the set_type call (after the spec: and
    manifest: notes are appended, before impl-placeholder is removed), leaving
    real partial state; `reconcile` must then complete the placeholder."""
    real = SubprocessBdRunner(bd_binary=bd_binary, cwd=str(fresh_install),
                              env=_bd_env(fresh_install))

    # --- Arrange: promote a shape-feat leaf → a shape-spec container. That mints
    # a design child (shape-design) + an impl-placeholder sibling under it
    # (transitions.py::promote → finalize_spec_instantiation). Verified flow.
    leaf = _drive(real, ["create", "feat", "--title", "cr-spec", "--priority", "2"])["data"]["id"]
    _drive(real, ["promote", leaf])
    design_child, placeholder = _design_and_placeholder(real, leaf)

    # A `## Continuations` single-item manifest. GRAMMAR (manifest.py, verified):
    # `- <noun>: <title> — AC: <acceptance>` — note the em-dash separator " — AC: ".
    spec_file = fresh_install / "cont.md"
    spec_file.write_text(
        "# spec\n\n## Continuations\n\n- feat: cr-impl — AC: the impl unit is built\n"
    )

    # --- Act: fault the deliver at the FIRST `update ... --type` call. Verified
    # call order for a design-child deliver: get(design)#1, get(container)#2,
    # get(placeholder)#3, append spec:#4, append manifest:#5, get(placeholder)#6,
    # set_type#7. Faulting #7 leaves both notes recorded and impl-placeholder
    # present — genuine mid-deliver partial state.
    def fail_on_set_type(n: int, argv: Sequence[str]) -> bool:
        return argv[:1] == ["update"] and "--type" in argv

    faulted = FaultInjectingBdRunner(real, fail_when=fail_on_set_type, fault=Fault.NONZERO_EXIT)
    crashed = _drive(faulted, ["deliver", design_child, "--spec", str(spec_file)])
    assert crashed["ok"] is False   # the injected fault aborted deliver

    # Partial state is real: the placeholder still carries the impl-placeholder
    # handle (the recovery signal) and has NOT yet gained its shape label.
    mid = _drive(real, ["show", placeholder])["data"]
    assert "impl-placeholder" in mid["labels"]
    assert "shape-feat" not in mid["labels"]

    # --- Heal: reconcile replays reconcile_placeholder off the handle.
    swept = _drive(real, ["reconcile"])
    assert swept["ok"] is True

    healed = _drive(real, ["show", placeholder])["data"]
    assert "impl-placeholder" not in healed["labels"]   # handle removed strictly last
    assert "shape-feat" in healed["labels"]             # manifest item noun=feat
    assert "spec-ready" in healed["labels"]
    assert _drive(real, ["show", design_child])["data"]["status"] == "closed"


def _design_and_placeholder(runner, container_id: str) -> tuple[str, str]:
    """Return (design_child_id, placeholder_id): the container's two children."""
    children = _drive(runner, ["show", container_id])["data"]["children"]  # single-id show
    design_child = placeholder = None
    for child_id in children:
        labels = _drive(runner, ["show", child_id])["data"]["labels"]
        if "shape-design" in labels:
            design_child = child_id
        else:
            placeholder = child_id
    assert design_child and placeholder, f"expected design+placeholder under {container_id}"
    return design_child, placeholder
```

**This is the highest-risk task.** The code above is grounded in verified source facts (deliver call order #1–#7, the `- <noun>: <title> — AC: <text>` manifest grammar, the shape-feat/spec-ready/impl-placeholder label lifecycle). Before Step 2, the worker re-confirms two things by re-reading `lifecycle/deliver.py` + `reconcile.py`: (1) that `work reconcile` re-derives the manifest from the recorded in-band snapshot note (so no `--spec` is needed on the reconcile call); (2) that a design-child deliver's call order still matches #1–#7 (if `deliver.py` changed, move the fault predicate to whatever the first post-manifest-append mutation is). The final assertions are concrete — keep them; a failure is a real signal.

- [ ] **Step 2: Run**

Run: `cd packages/workcli && uv run pytest tests/integration/test_crash_recovery.py -v`
Expected: PASS — both the malformed-JSON drift and the deliver→reconcile heal. If the heal test is a no-op (reconcile finds nothing), the fault landed too early (before any mutation) — move the fault point later in the sequence, per the deliver call order.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_crash_recovery.py
git commit -m "test(workcli): itest crash-recovery — mid-deliver fault healed by reconcile; malformed-json drift (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 10: Sync (remote-less)

**Files:**
- Create: `packages/workcli/tests/integration/test_sync.py`

Verified real behavior: `bd dolt commit` (nothing pending) and `bd dolt push` (no remote) both exit 0 → `work sync` returns `ok=true`. Add a commit-with-content case so the commit path runs with a real pending change. The two guessed stderr markers stay knowingly un-drift-covered (documented in the spec).

- [ ] **Step 1: Write the tests** — `test_sync.py`

```python
"""Remote-less sync against real embedded-dolt: honest ok=true, incl. a real
pending change through the commit path."""

from __future__ import annotations


def test_sync_remote_less_is_ok(driver):
    env = driver(["sync"])
    assert env["ok"] is True
    assert env["data"]["mode"] == "push"


def test_sync_after_a_real_mutation_commits(driver):
    # A real pending change exercises `dolt commit` with content (not the
    # nothing-pending path).
    driver(["create", "--raw", "--title", "sync-content", "--type", "task", "--priority", "2"])
    env = driver(["sync"])
    assert env["ok"] is True
```

The `work sync` success `data` is `asdict(SyncResult)` → `{"synced": true, "mode": "push"}` (verified: `verbs/syncing.py` + `model.SyncResult`). Remote-less push exits 0, so `mode` is `"push"`.

- [ ] **Step 2: Run**

Run: `cd packages/workcli && uv run pytest tests/integration/test_sync.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add packages/workcli/tests/integration/test_sync.py
git commit -m "test(workcli): itest remote-less sync (ok=true + commit-with-content) (wgclw.9.7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Task 11: Wiring — `make itest-workcli` + docs

**Files:**
- Modify: `Makefile` (repo root)
- Modify: `packages/workcli/AGENTS.md`

- [ ] **Step 1: Add the target** — in the workcli block of the root `Makefile` (after `verify-entry-workcli`, before the vizsuite block), add:

```makefile
# itest-workcli is the real-bd integration suite: it stands up an isolated
# embedded-Dolt bd install per test and drives the production `work` CLI against
# it. It requires `bd` on PATH and is DELIBERATELY EXCLUDED from `ci-workcli` /
# `ci` (needs the bd toolchain; ~40s+ serial). Pre-push discipline, not a gate.
# `-p no:xdist` pins it serial so the session-scoped read_only_install pays its
# ~1.4s bd init ONCE (under -n auto it would re-init per worker).
itest-workcli:
	cd $(WORKCLI) && uv run pytest tests/integration -q -p no:xdist
```

Also add `itest-workcli` to the `.PHONY` list at the top of the Makefile (append it to the existing workcli entries on lines 6–7).

- [ ] **Step 2: Verify the target runs (and is NOT in the gate)**

Run (from worktree root): `make itest-workcli`
Expected: the full integration suite runs and PASSES (or SKIPS wholesale if bd is absent).

Run: `make ci-workcli`
Expected: PASS and collects `tests/unit` only — grep the output to confirm no `tests/integration` test ran under coverage.

- [ ] **Step 3: Document in `packages/workcli/AGENTS.md`** — add this subsection after the "The quality gate is mandatory" section:

```markdown
## Real-bd integration suite (`make itest-workcli`)

`make itest-workcli` drives the production `work` CLI against a **real, isolated**
bd install (embedded Dolt in a temp dir, bound via `BEADS_DIR` so it can never
reach the repo's `.beads`). It catches bd-JSON drift the hermetic unit fakes
cannot. **Requirements & rules:**

- Needs `bd` on PATH; skips wholesale otherwise.
- **NOT** part of `make ci-workcli` / `make ci` — it needs the bd toolchain and
  runs ~40s+ serial. It is **pre-push discipline, not a merge gate**.
- Runs serial (`-p no:xdist`) so the shared read-only install pays `bd init` once.
- Never weaken an integration assertion to make it pass: a failure is a real
  drift signal — fix the adapter/parser (and note the drift) instead.
```

- [ ] **Step 4: Final full verification**

Run (from worktree root):
```bash
make ci-workcli        # hermetic gate — must stay green, unit-only coverage ≥90%
make itest-workcli     # real-bd suite — must pass (or skip if no bd)
```
Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add Makefile packages/workcli/AGENTS.md
git commit -m "build(workcli): make itest-workcli target + AGENTS.md docs (wgclw.9.7)

Local real-bd integration suite, excluded from ci-workcli/ci. Pre-push discipline.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LNC8t8yfaotN7aSFeJxh7e"
```

---

## Definition of Done

- `make ci-workcli` green from the worktree root: lint, format, mypy --strict, `pytest --cov` ≥90% branch on `tests/unit`, pip-audit, entry-verify.
- `make itest-workcli` green (or cleanly skipped when bd absent), covering: every verb once (value-level), every create-noun, the three lifecycle sequences, the four error paths (incl. type-wall dual assertion), crash-recovery (mid-deliver fault healed by reconcile), malformed-JSON→`invalid_json`, and remote-less sync.
- `tests/integration` never runs under the coverage gate (confirmed via `make cov-workcli`).
- `SubprocessBdRunner` default construction is byte-identical to pre-change behavior (existing unit tests unchanged and green).
- Isolation is structural: `BEADS_DIR` bind + off-repo `tmp_path` + pre-flight git-repo guard; no test can touch the repo's real `.beads`.
- `packages/workcli/AGENTS.md` documents the target.

## Out of scope (do not build)

CI job for the integration suite; Dolt-server mode; perf benchmarking; cross-bd-version matrix; closing the two guessed `sync` stderr markers (documented as knowingly un-drift-covered).
