# workcli Track Layer Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the track-partition spec's §4 workcli surface — config discovery, the `create` track gate, the `Item.track` envelope field, `work track set (±cascade)`, `work lint`, `work graph --json` with a shipped schema, and three new `ErrorCode` members — satisfying acceptance criteria 1–12 and 16–17 of `docs/specs/2026-07-15-workcli-track-partition-design.md`.

**Architecture:** All changes are additive to the transport/lifecycle contracts: the `Backend` protocol does NOT change. A new lazily-loaded config module (`workcli/config.py`) follows the package's `main()`-injects-everything pattern (the loader attaches to `args` exactly like `read_file`). Track derivation is a pure, config-free function over labels (`workcli/tracks.py`), applied in the verb layer — the bd adapter stays config-free. New verbs (`track`, `lint`, `graph`) register in the existing `VERBS` dict. Protocol bumps MINOR: `1.0` → `1.1`.

**Tech Stack:** Python ≥3.11 stdlib only at runtime (`tomllib` for TOML); `jsonschema` added as a **dev** dependency for schema-validation tests. Gate: `make ci-workcli` (ruff check, ruff format --check, mypy --strict, pytest --cov ≥90 branch, pip-audit, entry verify).

**Bead:** `agents-config-ey4rl`. Spec: `docs/specs/2026-07-15-workcli-track-partition-design.md` (call it "the track spec" below).

---

## Delivery slices (three PRs)

| Slice | Tasks | Ships | Criteria |
|-------|-------|-------|----------|
| **A — foundation** | 1–6 | config module + `E_NOT_CONFIGURED`/`E_UNKNOWN_TRACK`/`E_TRACK_REQUIRED` enum members, `derive_track`, `Item.track` on all read verbs, `--config` flag + lazy loader wiring, `list --track`, protocol 1.1, contract-spec amendment, repo `[tracks]` config | 8, 16, 17 |
| **B — the gate** | 7–10 | `create --track` + enforcement modes + parent inheritance + envelope warnings, `work track set ±cascade` | 1–7, 9 (create leg) |
| **C — reporting** | 11–13 | `work lint` (5 invariants), `work graph --json` + shipped schema | 9 (lint leg), 10, 11, 12 |

Each slice ends with the full gate + its own PR (worktree → PR → review loop → merge per the completion-gate chain). Do not start slice B until slice A is merged.

**Behavioral ground rules pinned from the track spec (read before any task):**

- Track **derivation is config-free** (pure label parsing); only *validation/enforcement* needs config. Hence `Item.track` appears on read envelopes unconditionally — that additive field is what the MINOR bump legitimizes. "No existing verb changes" (§4) refers to *behavior/gating*, not the additive field.
- Config loading is **lazy**: only a new §4 surface (`--track`, `--config`-dependent behavior, `track`/`lint`/`graph` verbs, the create gate) may trigger a load. A pre-existing verb invocation must never call the loader.
- `E_NOT_CONFIGURED` covers *both* "no config found" and "config malformed/invalid", with a message naming the specific problem. The `detail.reason` field distinguishes `"not-found"` from `"invalid"` — the create gate uses this to stay fail-safe (skip silently when not-found, skip with a warning when invalid).
- Closed beads and milestone-type beads are exempt from every track invariant and gate.

---

## File structure

```
packages/workcli/
  src/workcli/
    __init__.py                 # MODIFY: PROTOCOL_VERSION "1.0" -> "1.1"  (Task 3)
    config.py                   # CREATE: TrackLayerConfig + load_config    (Task 1)
    tracks.py                   # CREATE: derive_track, require_known_track,
                                #         TRACK_PREFIX, track-label helpers (Task 2)
    envelope.py                 # MODIFY: 3 new ErrorCode members           (Task 1)
    cli.py                      # MODIFY: --config flag, config_loader seam,
                                #         list --track, create --track,
                                #         track/lint/graph subparsers       (Tasks 4,5,7,9,11,12)
    verbs/read.py               # MODIFY: track in _serialize_item; --track filter (Tasks 3,5)
    verbs/tracks.py             # CREATE: `work track set` handler          (Tasks 9,10)
    verbs/report.py             # CREATE: `work lint` + `work graph` handlers (Tasks 11,12)
    verbs/__init__.py           # MODIFY: register track/lint/graph in VERBS (Tasks 9,11,12)
    lifecycle/create.py         # MODIFY: _resolve_track gate + warnings    (Task 8)
    schemas/work-graph.schema.json  # CREATE: shipped graph data contract   (Task 12)
  tests/
    conftest.py                 # MODIFY: config_loader seam in run_cli helpers (Task 4)
    unit/test_config_loading.py # CREATE  (Task 1)
    unit/test_track_derivation.py # CREATE (Task 2)
    unit/test_item_track_field.py # CREATE (Task 3)
    unit/test_config_seam.py    # CREATE  (Task 4)
    unit/test_list_track_filter.py # CREATE (Task 5)
    unit/test_create_track_gate.py # CREATE (Task 8)
    unit/test_track_set.py      # CREATE  (Tasks 9,10)
    unit/test_lint.py           # CREATE  (Task 11)
    unit/test_graph.py          # CREATE  (Task 12)
  pyproject.toml                # MODIFY: jsonschema dev dep (Task 12)
project-config.toml             # MODIFY: [tracks] + [operating-model] + [extraction] (Task 6)
docs/specs/2026-07-04-work-facade-cli-contract.md  # MODIFY: amendment (Task 6)
```

Responsibilities: `config.py` owns discovery/parse/validation (parse once at the boundary, trust the frozen dataclass inward). `tracks.py` owns the pure label↔track mapping shared by every consumer. `verbs/report.py` owns the two repo-wide reporting verbs. The bd adapter is untouched in every task.

---

## Task 1: Config module + the three ErrorCode members

**Files:**
- Create: `packages/workcli/src/workcli/config.py`
- Modify: `packages/workcli/src/workcli/envelope.py` (ErrorCode)
- Test: `packages/workcli/tests/unit/test_config_loading.py`

The enum members ship here because this is the first behavior that raises one — enum-literal tests are tautologies, so the members are pinned only through behavior tests. All commands below run from `packages/workcli/` unless noted.

- [ ] **Step 1: Write the first failing test — discovery via upward search (criterion 16)**

```python
"""Behavioral tests for workcli.config.load_config (track spec §3, criterion 16/17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from workcli.config import load_config
from workcli.envelope import ErrorCode, WorkError

VALID_TRACKS = """
[tracks]
names = ["alpha", "beta", "gamma"]
organizing-only = ["gamma"]
enforcement = "advisory"

[operating-model]
milestone-wip-cap = 2
wip-exempt-milestones = ["proj-m1"]
"""


def _repo(tmp_path: Path, config_text: str | None = VALID_TRACKS) -> Path:
    """A fake git repo root: .git marker + optional project-config.toml."""
    (tmp_path / ".git").mkdir()
    if config_text is not None:
        (tmp_path / "project-config.toml").write_text(config_text, encoding="utf-8")
    return tmp_path


def test_finds_config_upward_from_repo_subdirectory(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    subdir = root / "packages" / "workcli"
    subdir.mkdir(parents=True)

    config = load_config(subdir)

    assert config.names == ("alpha", "beta", "gamma")
    assert config.organizing_only == ("gamma",)
    assert config.enforcement == "advisory"
    assert config.milestone_wip_cap == 2
    assert config.wip_exempt_milestones == ("proj-m1",)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_config_loading.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workcli.config'`

- [ ] **Step 3: Add the enum members and the minimal config module**

In `envelope.py`, extend `ErrorCode` (after `TIMEOUT`):

```python
    TRACK_REQUIRED = "E_TRACK_REQUIRED"
    UNKNOWN_TRACK = "E_UNKNOWN_TRACK"
    NOT_CONFIGURED = "E_NOT_CONFIGURED"
```

Create `src/workcli/config.py`:

```python
"""Track-layer config: discovery, parsing, validation (track spec §3).

Loaded lazily -- only when a track-layer surface (a §4 flag, verb, or gate)
needs it -- so pre-existing verbs never trigger a load. Every failure is the
single typed `E_NOT_CONFIGURED`, its message naming the specific parse or
validation problem; `detail.reason` distinguishes "not-found" from "invalid"
so the create gate can stay fail-safe (spec §3: a broken config fails only
the track layer, never an existing verb). Parse and validate once here;
everything inward trusts the frozen dataclass.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from workcli.envelope import ErrorCode, WorkError

CONFIG_FILENAME = "project-config.toml"

Reason = Literal["not-found", "invalid"]


@dataclass(frozen=True)
class TrackLayerConfig:
    names: tuple[str, ...]
    organizing_only: tuple[str, ...]
    enforcement: str  # "advisory" | "required"; omitted key parses to "advisory"
    milestone_wip_cap: int | None  # None: [operating-model] absent/key omitted -> lint skips WIP check
    wip_exempt_milestones: tuple[str, ...]


def _not_configured(problem: str, reason: Reason) -> WorkError:
    return WorkError(
        ErrorCode.NOT_CONFIGURED,
        f"track layer not configured: {problem}",
        detail={"reason": reason},
    )


def _find_config(start_dir: Path) -> Path | None:
    """Upward search from `start_dir` to the enclosing git root (spec §3).

    The directory containing `.git` (a dir, or a file in linked worktrees) is
    the last one searched; with no git root on the walk -- the working
    directory lies outside any repo -- the search finds nothing.
    """
    current = start_dir.resolve()
    for candidate_dir in (current, *current.parents):
        candidate = candidate_dir / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if (candidate_dir / ".git").exists():
            return None
    return None


def load_config(start_dir: Path, explicit_path: str | None = None) -> TrackLayerConfig:
    """Resolve, parse, and validate `[tracks]`/`[operating-model]`.

    `explicit_path` (the `--config` flag) overrides the search in every case.
    """
    if explicit_path is not None:
        config_path = Path(explicit_path)
        if not config_path.is_file():
            raise _not_configured(f"--config path not found: {explicit_path}", "not-found")
    else:
        found = _find_config(start_dir)
        if found is None:
            raise _not_configured(
                f"no {CONFIG_FILENAME} between {start_dir} and the enclosing git root",
                "not-found",
            )
        config_path = found
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as read_error:
        raise _not_configured(f"cannot read {config_path}: {read_error}", "invalid") from read_error
    except tomllib.TOMLDecodeError as parse_error:
        raise _not_configured(
            f"malformed TOML in {config_path}: {parse_error}", "invalid"
        ) from parse_error
    return _validate(raw, config_path)


def _string_tuple(value: object, where: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise _not_configured(f"{where} must be a list of strings in {path}", "invalid")
    return tuple(value)


def _validate(raw: dict[str, object], path: Path) -> TrackLayerConfig:
    tracks = raw.get("tracks")
    if not isinstance(tracks, dict):
        raise _not_configured(f"no [tracks] table in {path}", "not-found")
    names = _string_tuple(tracks.get("names", []), "[tracks].names", path)
    if not names:
        raise _not_configured(f"[tracks].names is empty or missing in {path}", "invalid")
    organizing_only = _string_tuple(
        tracks.get("organizing-only", []), "[tracks].organizing-only", path
    )
    unknown_organizing = [name for name in organizing_only if name not in names]
    if unknown_organizing:
        raise _not_configured(
            f"[tracks].organizing-only entries not in names: {unknown_organizing} in {path}",
            "invalid",
        )
    enforcement = tracks.get("enforcement", "advisory")
    if enforcement not in ("advisory", "required"):
        raise _not_configured(
            f"[tracks].enforcement must be 'advisory' or 'required', got {enforcement!r} in {path}",
            "invalid",
        )

    operating = raw.get("operating-model")
    operating_table = operating if isinstance(operating, dict) else {}
    cap = operating_table.get("milestone-wip-cap")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)):
        raise _not_configured(
            f"[operating-model].milestone-wip-cap must be an integer in {path}", "invalid"
        )
    exempt = _string_tuple(
        operating_table.get("wip-exempt-milestones", []),
        "[operating-model].wip-exempt-milestones",
        path,
    )
    return TrackLayerConfig(
        names=names,
        organizing_only=organizing_only,
        enforcement=str(enforcement),
        milestone_wip_cap=cap,
        wip_exempt_milestones=exempt,
    )
```

Design note (decide-in-scope, recorded): an absent `[operating-model]` table or omitted `milestone-wip-cap` yields `milestone_wip_cap = None` and `work lint` *skips* the WIP check rather than inventing a default — §6 says "nothing hardcoded", and the omitted-key⇒fail-safe pattern matches `enforcement`'s. A missing `[tracks]` table maps to reason `"not-found"` (the repo hasn't opted in — same fail-safe class as no file); every other defect is `"invalid"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config_loading.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Remaining behaviors, one red-green cycle each** (add to `test_config_loading.py`; run the file's tests after each cycle — implementation above already satisfies most; any that pass immediately confirm the boundary, any that fail reveal a real gap to fix in `config.py`)

```python
def test_search_stops_at_git_root(tmp_path: Path) -> None:
    # Config ABOVE the git root must not be found: the root bounds the search.
    (tmp_path / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "not-found"


def test_outside_any_git_repo_is_not_configured(tmp_path: Path) -> None:
    # No .git anywhere on the walk -> treated as "no config found" (spec §3),
    # even when a project-config.toml exists in a parent dir.
    (tmp_path / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")
    workdir = tmp_path / "nested"
    workdir.mkdir()

    with pytest.raises(WorkError) as exc_info:
        load_config(workdir)
    assert exc_info.value.detail["reason"] == "not-found"
```

Note: `test_outside_any_git_repo_is_not_configured` walks past `tmp_path` up to the real filesystem root — on a machine whose `/` or home dir contained a stray `project-config.toml` + `.git` this could misfire, but pytest tmp dirs live under a private prefix with neither; if CI ever grows such a marker, revisit with a `monkeypatch`-chrooted walk.

```python
def test_explicit_config_flag_overrides_search(tmp_path: Path) -> None:
    root = _repo(tmp_path)  # valid config at root...
    elsewhere = tmp_path / "elsewhere.toml"
    elsewhere.write_text(
        VALID_TRACKS.replace('"alpha", "beta", "gamma"', '"delta"').replace(
            '["gamma"]', "[]"
        ),
        encoding="utf-8",
    )

    config = load_config(root, explicit_path=str(elsewhere))
    assert config.names == ("delta",)


def test_explicit_config_flag_missing_path_is_not_configured(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(WorkError) as exc_info:
        load_config(root, explicit_path=str(tmp_path / "nope.toml"))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED


def test_malformed_toml_is_invalid_and_names_the_problem(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text="[tracks\nnames = not toml")
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert exc_info.value.detail["reason"] == "invalid"
    assert "malformed TOML" in exc_info.value.message


def test_missing_tracks_table_reads_as_not_found(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[project]\nname = "x"\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "not-found"


def test_non_list_names_is_invalid(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = "alpha"\n')
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"
    assert "[tracks].names" in exc_info.value.message


def test_enforcement_omitted_defaults_to_advisory(tmp_path: Path) -> None:
    # Criterion 4's config-layer leg: omitted key parses as advisory.
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    assert load_config(root).enforcement == "advisory"


def test_bogus_enforcement_value_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path, config_text='[tracks]\nnames = ["alpha"]\nenforcement = "yolo"\n'
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"


def test_organizing_only_outside_names_is_invalid(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        config_text='[tracks]\nnames = ["alpha"]\norganizing-only = ["beta"]\n',
    )
    with pytest.raises(WorkError) as exc_info:
        load_config(root)
    assert exc_info.value.detail["reason"] == "invalid"


def test_operating_model_absent_yields_no_wip_cap(tmp_path: Path) -> None:
    root = _repo(tmp_path, config_text='[tracks]\nnames = ["alpha"]\n')
    config = load_config(root)
    assert config.milestone_wip_cap is None
    assert config.wip_exempt_milestones == ()


def test_git_file_marker_counts_as_root(tmp_path: Path) -> None:
    # Linked worktrees have a .git FILE, not a dir -- the search must still
    # treat that directory as the root boundary.
    root = tmp_path / "wt"
    root.mkdir()
    (root / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    (root / "project-config.toml").write_text(VALID_TRACKS, encoding="utf-8")

    assert load_config(root).names == ("alpha", "beta", "gamma")
```

- [ ] **Step 6: Run the whole file, then lint/type the new module**

Run: `uv run pytest tests/unit/test_config_loading.py -v`
Expected: PASS (13 tests)

Run: `uv run ruff check src/workcli/config.py src/workcli/envelope.py && uv run ruff format src tests && uv run mypy --strict src`
Expected: clean (format may rewrap — rerun tests if it does)

- [ ] **Step 7: Commit**

```bash
git add src/workcli/config.py src/workcli/envelope.py tests/unit/test_config_loading.py
git commit -m "feat(workcli): track-layer config discovery + E_NOT_CONFIGURED/E_UNKNOWN_TRACK/E_TRACK_REQUIRED"
```

---

## Task 2: Pure track derivation (`tracks.py`)

**Files:**
- Create: `packages/workcli/src/workcli/tracks.py`
- Test: `packages/workcli/tests/unit/test_track_derivation.py`

- [ ] **Step 1: Write the failing tests** (four behaviors, one module — small enough for a single red phase since all four pin the same pure function's contract, spec §4 "exactly one" rule)

```python
"""derive_track: the single label->track rule every consumer shares (track spec §4)."""

from __future__ import annotations

from workcli.tracks import derive_track


def test_single_track_label_derives_its_name() -> None:
    assert derive_track(["shape-task", "track:installer", "planned"]) == "installer"


def test_no_track_label_derives_none() -> None:
    assert derive_track(["shape-task", "planned"]) is None


def test_multiple_track_labels_derive_none() -> None:
    # Reachable via raw label writes; spec §4 pins null, lint invariant 1 flags it.
    assert derive_track(["track:installer", "track:prgroom"]) is None


def test_non_track_prefix_lookalikes_ignored() -> None:
    assert derive_track(["tracking:x", "track", "backtrack:y"]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_track_derivation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workcli.tracks'`

- [ ] **Step 3: Implement `src/workcli/tracks.py`**

```python
"""Track derivation and vocabulary validation (track spec §4).

Derivation is config-free by design -- a pure function over labels -- so the
`Item.track` envelope field appears on every read verb regardless of config
state. Only *validation* (`require_known_track`) needs the vocabulary.
"""

from __future__ import annotations

from collections.abc import Sequence

from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError

TRACK_PREFIX = "track:"


def derive_track(labels: Sequence[str]) -> str | None:
    """Exactly one `track:*` label -> its name; zero or 2+ -> None (spec §4)."""
    names = [label[len(TRACK_PREFIX) :] for label in labels if label.startswith(TRACK_PREFIX)]
    if len(names) == 1:
        return names[0]
    return None


def track_label(name: str) -> str:
    return f"{TRACK_PREFIX}{name}"


def require_known_track(name: str, config: TrackLayerConfig) -> None:
    """Unknown names fail with E_UNKNOWN_TRACK naming the vocabulary -- never a new label."""
    if name not in config.names:
        raise WorkError(
            ErrorCode.UNKNOWN_TRACK,
            f"unknown track {name!r}; configured tracks: {', '.join(config.names)}",
            detail={"track": name, "names": list(config.names)},
        )
```

(`require_known_track` earns its tests in Task 5 where the first consumer arrives — no orphan-method tests here.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_track_derivation.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/workcli/tracks.py tests/unit/test_track_derivation.py
git commit -m "feat(workcli): pure track derivation (exactly-one track:* rule)"
```

---

## Task 3: `Item.track` on every read verb + protocol 1.1

**Files:**
- Modify: `packages/workcli/src/workcli/verbs/read.py` (`_serialize_item`)
- Modify: `packages/workcli/src/workcli/__init__.py` (`PROTOCOL_VERSION`)
- Test: `packages/workcli/tests/unit/test_item_track_field.py`

- [ ] **Step 1: Write the failing test — envelope-level, through the CLI, per read verb**

The four read verbs share one serialization seam (`_serialize_item`), so one verb proves the seam and a parametrized sweep proves every verb routes through it. `ScriptedBdRunner` fixtures follow the house pattern in `tests/unit/test_show_normalization.py` — read that file first and reuse its bd-JSON fixture shape exactly (the `ScriptedStep` argv/stdout format).

```python
"""Item.track envelope field on all read verbs (track spec §4, criterion 8)."""

from __future__ import annotations

import json

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult


def _bd_item(item_id: str, labels: list[str]) -> dict[str, object]:
    """Minimal bd show/list JSON record accepted by adapters/bd/parse.py.

    Mirror the fixture fields used in test_show_normalization.py; extend only
    if parse_items rejects the record (its drift alarm names what's missing).
    """
    return {
        "id": item_id,
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": labels,
    }


def _show_step(item_id: str, labels: list[str]) -> ScriptedStep:
    return ScriptedStep(
        ("show",),
        BdResult(returncode=0, stdout=json.dumps([_bd_item(item_id, labels)]), stderr=""),
    )


def test_show_carries_derived_track() -> None:
    exit_code, envelope, _ = run_cli(
        ["show", "w-1"], [_show_step("w-1", ["track:installer", "planned"])]
    )
    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["track"] == "installer"


def test_show_zero_or_multi_track_labels_carry_null() -> None:
    exit_code, envelope, _ = run_cli(
        ["show", "w-1"], [_show_step("w-1", ["track:a", "track:b"])]
    )
    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["track"] is None


@pytest.mark.parametrize(
    ("argv", "prefix"),
    [
        (["list"], ("list",)),
        (["ready"], ("ready",)),
        (["search", "T"], ("search",)),
    ],
)
def test_every_list_shaped_read_verb_carries_track(
    argv: list[str], prefix: tuple[str, ...]
) -> None:
    step = ScriptedStep(
        prefix,
        BdResult(
            returncode=0,
            stdout=json.dumps([_bd_item("w-1", ["track:prgroom"])]),
            stderr="",
        ),
    )
    exit_code, envelope, _ = run_cli(argv, [step])
    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["track"] == "prgroom"
```

`ScriptedStep` matches on an argv *prefix* tuple (`tests/fakes.py`), so scripting the verb head alone is enough — the adapter's tail flags (`--json`, `--limit 0`) don't need enumerating. `_bd_item`'s field names must match what `adapters/bd/parse.py` accepts (`issue_type`, integer `priority`, `labels`) — mirror `test_show_normalization.py`'s fixtures exactly.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_item_track_field.py -v`
Expected: FAIL — `KeyError: 'track'` (envelope lacks the field)

- [ ] **Step 3: Implement — one seam change**

In `verbs/read.py`, import and extend:

```python
from workcli.tracks import derive_track
```

```python
def _serialize_item(item: Item) -> dict[str, JsonValue]:
    # `dataclasses.asdict` recurses into the nested `DepEdge` list too, so
    # `deps` comes out already lean (`{id, type, status}`) with no extra work.
    serialized = cast("dict[str, JsonValue]", dataclasses.asdict(item))
    # Derived in the verb layer, config-free, so every read envelope carries
    # it regardless of config state (track spec §4; the 1.1 additive field).
    serialized["track"] = derive_track(item.labels)
    return serialized
```

In `src/workcli/__init__.py`:

```python
PROTOCOL_VERSION = "1.1"
```

- [ ] **Step 4: Pin the new wire value and run the full unit suite**

The existing protocol tests (`test_protocol_handshake.py`, `test_envelope.py`, `test_envelope_invariants.py`) already assert against the imported `PROTOCOL_VERSION` constant — they follow the bump automatically. The literal `"1.0"` strings in `test_render_human.py` are arbitrary *input sample data* for the renderer, not version pins — leave that file untouched. What's missing is a wire-value pin: today nothing would catch an accidental constant edit. ADD one literal assertion to `test_protocol_handshake.py`:

```python
def test_protocol_wire_value_is_pinned() -> None:
    # The serialization boundary pins the literal wire value; every other
    # test references PROTOCOL_VERSION. Bumping the protocol means updating
    # this one assertion deliberately.
    assert PROTOCOL_VERSION == "1.1"
```

Run: `uv run pytest -n auto`
Expected: PASS, full suite (fix any envelope-shape assertions in existing tests that enumerate item keys — e.g. exact-dict comparisons in show/list tests now expect `"track": None`).

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat(workcli): Item.track envelope field on all read verbs; protocol 1.1"
```

---

## Task 4: `--config` flag + lazy config-loader seam in `main()`

**Files:**
- Modify: `packages/workcli/src/workcli/cli.py`
- Modify: `packages/workcli/tests/conftest.py`
- Test: `packages/workcli/tests/unit/test_config_seam.py`

- [ ] **Step 1: Write the failing tests — laziness is the contract**

```python
"""The config-loader seam: injected, lazy, --config passthrough (track spec §3)."""

from __future__ import annotations

import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig


def _exploding_loader(_explicit_path: str | None) -> TrackLayerConfig:
    # Underscore-prefixed unused param: house convention for test doubles
    # (ruff ARG001 is enabled package-wide).
    raise AssertionError("config loader invoked by a pre-existing verb (must be lazy)")


def test_pre_existing_verbs_never_touch_the_config_loader() -> None:
    # Criterion 17's laziness leg: `show` with no track flags must complete
    # without the loader ever running -- even with --config on the command line.
    step = ScriptedStep(
        ("show",),
        BdResult(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": "w-1",
                        "title": "T",
                        "issue_type": "task",
                        "status": "open",
                        "priority": 2,
                        "labels": [],
                    }
                ]
            ),
            stderr="",
        ),
    )
    exit_code, envelope, _ = run_cli(
        ["--config", "/tmp/anything.toml", "show", "w-1"],
        [step],
        config_loader=_exploding_loader,
    )
    assert exit_code == 0
    assert envelope["ok"] is True


```

(The `--config`-passthrough companion test — a recording loader observing the explicit path — arrives in Task 5, because the first surface that actually loads config is `list --track`. Task 4 ships only the laziness contract.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_config_seam.py -v`
Expected: FAIL — `run_cli` has no `config_loader` parameter / `--config` unrecognized (E_USAGE envelope)

- [ ] **Step 3: Implement the seam**

In `cli.py`:

1. Imports:

```python
from workcli.config import TrackLayerConfig, load_config
```

2. In `_build_parser()`, after the `--format` argument:

```python
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="explicit project-config.toml path; overrides the upward search",
    )
```

3. Default loader helper (next to `_default_read_file`):

```python
def _default_config_loader(explicit_path: str | None) -> TrackLayerConfig:
    """The real track-layer config resolution: upward search from cwd (track spec §3)."""
    return load_config(Path.cwd(), explicit_path)
```

4. `main()` signature gains the injectable (after `read_file`):

```python
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None,
```

5. Attachment, directly after the `args.read_file` line (same precedent, same rationale — the fixed `(Backend, Namespace)` handler signature never widens):

```python
    # Same args-attachment precedent as read_file: resolved once, loaded
    # LAZILY -- only a track-layer surface calls args.load_config(), so
    # pre-existing verbs never trigger config resolution (track spec §3).
    resolved_config_loader = config_loader if config_loader is not None else _default_config_loader
    args.load_config = lambda: resolved_config_loader(args.config)
```

In `tests/conftest.py`: add the parameter to BOTH `run_cli` and `run_cli_with_runner`, mirroring `read_file`'s pattern:

```python
def _no_config_loads(_explicit_path: str | None) -> TrackLayerConfig:
    raise AssertionError(
        "config loader unexpectedly invoked; inject config_loader= explicitly"
    )
```

— import `TrackLayerConfig` from `workcli.config`; each helper's signature gains `config_loader: Callable[[str | None], TrackLayerConfig] | None = None`, and each `main(...)` call passes `config_loader=config_loader if config_loader is not None else _no_config_loads`. The fail-loud default mirrors `_NO_READS`: a test that forgets to script config fails clearly (as an `E_INTERNAL` envelope with the AssertionError traceback on stderr) instead of silently reading the developer's real repo config.

- [ ] **Step 4: Run — first test green, suite green**

Run: `uv run pytest tests/unit/test_config_seam.py::test_pre_existing_verbs_never_touch_the_config_loader -v`
Expected: PASS

Run: `uv run pytest -n auto`
Expected: all existing tests PASS (they hit the fail-loud default only if something eagerly loads config — which would be the exact regression this seam forbids).

- [ ] **Step 5: Commit**

```bash
git add src/workcli/cli.py tests/conftest.py tests/unit/test_config_seam.py
git commit -m "feat(workcli): --config flag + lazy injected config-loader seam"
```

---

## Task 5: `work list --track <name>`

**Files:**
- Modify: `packages/workcli/src/workcli/cli.py` (list subparser)
- Modify: `packages/workcli/src/workcli/verbs/read.py` (`list_`)
- Test: `packages/workcli/tests/unit/test_list_track_filter.py` (+ Task 4's second test goes green)

- [ ] **Step 1: Write the failing tests — handler-level with FakeBackend**

```python
"""list --track filters on DERIVED Item.track, not raw label presence (criterion 8)."""

from __future__ import annotations

from argparse import Namespace

import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.read import list_

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
)


def _list_args(track: str | None, load_config: object) -> Namespace:
    return Namespace(
        status=None,
        label=None,
        parent=None,
        type=None,
        limit=None,
        track=track,
        load_config=load_config,
    )


def _backend() -> FakeBackend:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    backend.add("w-2", labels=["track:beta"])
    backend.add("w-3", labels=[])                          # untracked -> null
    backend.add("w-4", labels=["track:alpha", "track:beta"])  # multi -> null
    return backend


def test_filters_on_derived_track_value() -> None:
    data = list_(_backend(), _list_args("alpha", lambda: CONFIG))
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    ids = [item["id"] for item in items if isinstance(item, dict)]
    # w-4 carries a track:alpha LABEL but derives to null -> must not match.
    assert ids == ["w-1"]


def test_unknown_track_name_fails_naming_vocabulary() -> None:
    with pytest.raises(WorkError) as exc_info:
        list_(_backend(), _list_args("gamma", lambda: CONFIG))
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert "alpha" in exc_info.value.message  # names the configured vocabulary


def test_no_track_flag_never_loads_config() -> None:
    def explode() -> TrackLayerConfig:
        raise AssertionError("plain list must not load config")

    data = list_(_backend(), _list_args(None, explode))
    assert isinstance(data, dict)
    items = data["items"]
    assert isinstance(items, list)
    assert len(items) == 4


def test_unconfigured_repo_fails_track_flag_with_e_not_configured() -> None:
    def not_configured() -> TrackLayerConfig:
        raise WorkError(ErrorCode.NOT_CONFIGURED, "track layer not configured: nope")

    with pytest.raises(WorkError) as exc_info:
        list_(_backend(), _list_args("alpha", not_configured))
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
```

Plus one CLI-level test in the same file — the `--config` passthrough deferred from Task 4 (extend the file's imports with these):

```python
import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult


def test_config_flag_reaches_the_loader_verbatim() -> None:
    # main()'s seam threads --config through to the loader untouched;
    # list --track is the first surface that triggers a load.
    seen: list[str | None] = []

    def recording_loader(explicit_path: str | None) -> TrackLayerConfig:
        seen.append(explicit_path)
        return CONFIG

    step = ScriptedStep(
        ("list",),
        BdResult(returncode=0, stdout=json.dumps([]), stderr=""),
    )
    exit_code, _, _ = run_cli(
        ["--config", "/etc/custom.toml", "list", "--track", "alpha"],
        [step],
        config_loader=recording_loader,
    )
    assert exit_code == 0
    assert seen == ["/etc/custom.toml"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_list_track_filter.py -v`
Expected: FAIL — `AttributeError`/`TypeError` on the missing `--track` handling (`list_` ignores `args.track`) and, once wired, assertion failures until the filter exists

- [ ] **Step 3: Implement**

`cli.py`, in `_add_read_subparsers`, on the list parser:

```python
    list_parser.add_argument("--track", metavar="NAME")
```

`verbs/read.py` — EXTEND the existing Task 3 import line (a second import of the same module trips ruff F811):

```python
from workcli.tracks import derive_track, require_known_track
```

```python
def list_(backend: Backend, args: Namespace) -> JsonValue:
    """`work list [--status --label --parent --type --limit --track]`.

    `--track` filters on the DERIVED `Item.track` (never raw label presence),
    so filter and envelope field always agree: zero-or-multi-label beads
    derive to null and match nothing (track spec §4). Validated against the
    vocabulary for parity with `create --track` -- a typo returns
    E_UNKNOWN_TRACK, not a silently-empty result.
    """
    filters = QueryFilters(
        status=args.status,
        label=args.label,
        parent=args.parent,
        type=args.type,
        limit=args.limit,
    )
    items = backend.query(filters)
    if args.track is not None:
        require_known_track(args.track, args.load_config())
        items = [item for item in items if derive_track(item.labels) == args.track]
    return _serialize_items(items)
```

(Vocabulary validation on `list --track` is a decide-in-scope call: the track spec mandates it only for `create`/`track set`, but a silently-empty result on a typo'd name is the exact failure class `E_UNKNOWN_TRACK` exists for, and the config is already loaded. Recorded here so the contract amendment in Task 6 documents it.)

- [ ] **Step 4: Run this file, then the full suite**

Run: `uv run pytest tests/unit/test_list_track_filter.py -v`
Expected: PASS (all, including the CLI-level passthrough test)

Run: `uv run pytest -n auto`
Expected: PASS. If any pre-existing test constructs a `list` Namespace by hand, add `track=None` to it (find them with `grep -rn "Namespace(" tests/unit/ | grep -v test_list_track`).

- [ ] **Step 5: Commit**

```bash
git add src/workcli/cli.py src/workcli/verbs/read.py tests/unit/test_list_track_filter.py
git commit -m "feat(workcli): work list --track filters on derived Item.track"
```

---

## Task 6: Slice A close-out — repo config, contract amendment, gate, PR

**Files:**
- Modify: `project-config.toml` (repo root)
- Modify: `docs/specs/2026-07-04-work-facade-cli-contract.md`
- No new tests (docs + config only)

- [ ] **Step 1: Add the track-layer sections to the repo's `project-config.toml`** (verbatim from the track spec §3, enforcement stays `advisory` — the flip is bead `agents-config-63nm3`; `groom-state-bead` stays `""` until the backfill bead `agents-config-jpn0s` mints it). Append after the `[completion-gate]` section:

```toml
# ---------------------------------------------------------------------------
# [tracks] / [operating-model] / [extraction] — work-tracker track partition
# Read by: workcli (work create gate, work list --track, work track set,
#          work lint, work graph) and, when they ship, work triggers/groom.
# Contract: docs/specs/2026-07-15-workcli-track-partition-design.md §3
# ---------------------------------------------------------------------------
[tracks]
names = ["installer", "prgroom", "workcli", "pdlc-orchestrator",
         "holding-place", "vizsuite", "skills-discipline",
         "portability", "ops-meta"]
organizing-only = ["skills-discipline", "portability", "ops-meta"]
enforcement = "advisory"   # flip to "required" is agents-config-63nm3, gated on backfill

[operating-model]
milestone-wip-cap = 2
wip-exempt-milestones = ["agents-config-uxns2"]  # PORT — bead id, never display name
backlog-groom-nag-days = 7
groom-state-bead = ""   # minted by the backfill migration (spec §7)

[extraction.pressure]
max-track-backlog = 100
external-consumer-tracks = []
independent-release-tracks = []

[extraction.eligibility]
max-cross-track-edges = 3
```

- [ ] **Step 2: Amend the work-facade contract spec** (`docs/specs/2026-07-04-work-facade-cli-contract.md`) — the MINOR-bump amendment the track spec mandates. Surgical edits, current-state wording (no "changed in" narration):

1. In §4 (envelope): update the protocol examples' `"protocol": "1.0"` to `"1.1"`.
2. In the §4 `data`-shapes paragraph, add: `Item` payloads on every read verb carry a derived, nullable `track` field — the name of the item's single `track:*` label, `null` on zero or multiple (contract pinned by the 2026-07-15 track-partition design, §4). Add that `create` responses MAY carry an optional `warnings: [string]` array (advisory-mode track gate).
3. In the error-code enumeration, add `E_TRACK_REQUIRED`, `E_UNKNOWN_TRACK`, `E_NOT_CONFIGURED` with one-line meanings, marked as raised only by track-layer surfaces.
4. In the verb inventory, add one line: `track set`, `lint`, `graph --json`, and the `--track`/`--config` flags are specified in the 2026-07-15 track-partition design §4 (this spec owns only their envelope/error-code vocabulary).

Locate each section with `grep -n "1.0\|E_TIMEOUT\|error-code\|## " docs/specs/2026-07-04-work-facade-cli-contract.md` from the repo root and keep the edits to those anchors.

- [ ] **Step 3: Run the package gate from the worktree root**

Run (repo/worktree root): `make ci-workcli`
Expected: all green — lint, format, mypy --strict, pytest cov ≥90, pip-audit, entry verify (`work --protocol-version` now prints protocol 1.1 inside the envelope).

- [ ] **Step 4: Commit and deliver slice A as its own PR**

```bash
git add project-config.toml docs/specs/2026-07-04-work-facade-cli-contract.md
git commit -m "feat(workcli): repo [tracks] config (advisory) + contract-spec 1.1 amendment"
```

Then run the delivery chain (completion gate → `finishing-a-development-branch` → PR → PR-review monitoring → merge per merge-guard). PR title: `feat(workcli): track layer slice A — config discovery, Item.track, list --track (protocol 1.1)`.

---

## Task 7: `create --track` flag plumbing (slice B begins)

**Files:**
- Modify: `packages/workcli/src/workcli/cli.py` (create subparser)
- Modify: `packages/workcli/src/workcli/verbs/__init__.py` (`_raw_incompatible_flags`)
- Test: extend `packages/workcli/tests/unit/test_create_raw.py` pattern in `packages/workcli/tests/unit/test_create_track_gate.py` (file created here, grows in Task 8)

- [ ] **Step 1: Write the failing test — `--raw` refuses `--track`**

```python
"""create track gate (track spec §4; criteria 1-5, 9, 17)."""

from __future__ import annotations

import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult


def test_create_raw_refuses_track_flag() -> None:
    # --raw is the documented track bypass; a silently-ignored --track would
    # look tracked while creating an untracked bead. E_USAGE, creates nothing.
    exit_code, envelope, _ = run_cli(
        ["create", "--raw", "--title", "T", "--track", "alpha"], []
    )
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_USAGE"
    assert "--track" in str(error["message"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_create_track_gate.py -v`
Expected: FAIL — E_USAGE mentions "unrecognized arguments: --track" via argparse rather than the offenders list; after wiring the flag (step 3.1 alone) it would create successfully — either way the assertion on the offenders message fails until step 3.2.

- [ ] **Step 3: Implement**

1. `cli.py`, in `_add_write_subparsers`, after the create parser's `--acceptance`:

```python
    create_parser.add_argument("--track", metavar="NAME")
```

2. `verbs/__init__.py`, in `_raw_incompatible_flags`, after the `--acceptance` check:

```python
    if args.track is not None:
        offenders.append("--track")
```

Also update the function's docstring list of flags to include `--track` (it enumerates the lifecycle-only inputs).

- [ ] **Step 4: Run to verify pass, then the full suite**

Run: `uv run pytest tests/unit/test_create_track_gate.py -v && uv run pytest -n auto`
Expected: PASS (hand-built create Namespaces in existing lifecycle tests need `track=None` — find with `grep -rln "noun=" tests/unit/`)

- [ ] **Step 5: Commit**

```bash
git add src/workcli/cli.py src/workcli/verbs/__init__.py tests/unit/test_create_track_gate.py
git commit -m "feat(workcli): create --track flag; --raw refuses it as lifecycle-only"
```

---

## Task 8: The create gate — derive, else enforce

**Files:**
- Modify: `packages/workcli/src/workcli/lifecycle/create.py`
- Test: `packages/workcli/tests/unit/test_create_track_gate.py` (extend)

Resolution order (track spec §4): explicit `--track` (validated) → tracked parent's derived track → enforcement (`advisory`: create untracked + envelope warning; `required`: `E_TRACK_REQUIRED`, create nothing). Config not-found → behave exactly as today (criterion 17); config invalid → same, plus a warning (spec §3 fail-safe). Spec-noun containers stamp the resolved track on their two template children too (they'd otherwise be born as instant lint violations); `promote`/`reconcile` minting stays unchanged — untracked children they mint are lint's to catch, the backfill bead sweeps them.

These are handler-level FakeBackend tests (house pattern for lifecycle: `tests/unit/test_create_noun.py` — copy its Namespace-building helper shape). One red-green cycle per behavior, in this order:

- [ ] **Cycle 1 (criterion 1): tracked parent inherits, no flag** — test first:

```python
from argparse import Namespace

import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.create import create_noun


def _config(enforcement: str) -> TrackLayerConfig:
    return TrackLayerConfig(
        names=("alpha", "beta"),
        organizing_only=(),
        enforcement=enforcement,
        milestone_wip_cap=None,
        wip_exempt_milestones=(),
    )


def _create_args(
    *,
    noun: str = "chore",
    parent: str | None = None,
    track: str | None = None,
    load_config: object,
) -> Namespace:
    return Namespace(
        noun=noun,
        raw=False,
        title="New work",
        description=None,
        type=None,
        priority=None,
        parent=parent,
        label=[],
        orphan=parent is None,
        spec=None,
        trivial=False,
        acceptance=None,
        track=track,
        load_config=load_config,
    )


@pytest.mark.parametrize("enforcement", ["advisory", "required"])
def test_tracked_parent_inherits_track_without_flag(enforcement: str) -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(parent="epic-1", load_config=lambda: _config(enforcement)),
    )
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert "track:alpha" in backend.labels(new_id)
    assert "warnings" not in data
```

Run: `uv run pytest tests/unit/test_create_track_gate.py -v` → FAIL (no `track:alpha` label). Then implement the gate in `lifecycle/create.py`:

```python
from workcli.tracks import derive_track, require_known_track, track_label
```

```python
def _resolve_track(backend: Backend, args: Namespace, parent: str | None) -> tuple[str | None, list[str]]:
    """Track resolution for `work create <noun>`: derive, else enforce (track spec §4).

    Explicit --track wins; else a tracked parent's derived track is inherited
    (a track-less parent falls through); else enforcement decides. A repo with
    no resolvable config behaves exactly as before the track layer existed
    (criterion 17); an INVALID config skips the gate with a warning instead of
    breaking `create` (spec §3: a broken config fails only the track layer).
    """
    try:
        config = args.load_config()
    except WorkError as not_configured:
        if not_configured.code is not ErrorCode.NOT_CONFIGURED or args.track is not None:
            raise
        if not_configured.detail.get("reason") == "invalid":
            return None, [f"track gate skipped: {not_configured.message}"]
        return None, []
    if args.track is not None:
        require_known_track(args.track, config)
        return args.track, []
    if parent is not None:
        parent_track = derive_track(backend.get(parent).labels)
        if parent_track is not None:
            return parent_track, []
    if config.enforcement == "required":
        raise WorkError(
            ErrorCode.TRACK_REQUIRED,
            "track is required: pass --track NAME or create under a tracked parent "
            f"(configured tracks: {', '.join(config.names)})",
        )
    return None, ["created untracked: no --track and no tracked parent (advisory mode)"]


def _with_warnings(data: dict[str, JsonValue], warnings: list[str]) -> JsonValue:
    if warnings:
        data["warnings"] = list(warnings)
    return data
```

Wire into `create_noun` (after `parent = ...`), threading the track into both branches:

```python
    parent = None if args.orphan else args.parent
    track, warnings = _resolve_track(backend, args, parent)

    if noun is Noun.SPEC:
        return _with_warnings(
            _create_spec_container(backend, args, template, parent, track), warnings
        )

    labels = [template.shape_label]
    if template.expects_evidence and (args.spec is not None or args.trivial):
        labels.append(SPEC_READY_LABEL)
    if track is not None:
        labels.append(track_label(track))
```

…and close with `return _with_warnings({"id": new_id}, warnings)`. Tighten `_create_spec_container`'s return annotation from `JsonValue` to `dict[str, JsonValue]` (it already returns a dict literal) so the `_with_warnings` composition passes mypy --strict without a cast.

`_create_spec_container` gains the `track: str | None` parameter; its container `labels` tuple becomes:

```python
            labels=(template.shape_label, CREATING_SPEC_LABEL)
            + ((track_label(track),) if track is not None else ()),
```

and it passes `track` through to `finalize_spec_instantiation(backend, container_id, args.title, track)`. Both `finalize_spec_instantiation` and `instantiate_spec_shape` gain a trailing `track: str | None = None` parameter (default `None` keeps `promote`/`reconcile` call sites source-compatible and unchanged in behavior); inside `instantiate_spec_shape`, both `CreateFields.labels` tuples append `(track_label(track),)` when `track is not None`:

```python
                labels=(DESIGN_CHILD_LABEL,)
                + ((track_label(track),) if track is not None else ()),
```

(and the same for `IMPL_PLACEHOLDER_LABEL`). Run the cycle-1 test → PASS.

- [ ] **Cycle 2 (criterion 2): required + underivable refuses, creates nothing**

```python
def test_required_mode_underivable_fails_and_creates_nothing() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(load_config=lambda: _config("required")))
    assert exc_info.value.code is ErrorCode.TRACK_REQUIRED
    assert backend.ids() == []
```

Run → should PASS already (the gate runs before any `backend.create`); if it fails, the gate is ordered after creation — fix the ordering, that is the entire point of this test.

- [ ] **Cycle 3 (criteria 3+4): advisory (explicit AND omitted-key) succeeds untracked with a warning**

```python
@pytest.mark.parametrize("enforcement", ["advisory"])
def test_advisory_underivable_succeeds_untracked_with_warning(enforcement: str) -> None:
    # Criterion 4's create leg rides on config parsing: an omitted enforcement
    # key already parses to "advisory" (test_config_loading), so this single
    # behavior covers both spellings.
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=lambda: _config(enforcement)))
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert all(not label.startswith("track:") for label in backend.labels(new_id))
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("untracked" in str(warning) for warning in warnings)
```

Run → PASS expected from cycle-1's implementation; a failure means the warning plumbing is broken.

- [ ] **Cycle 4 (criterion 5): unknown --track fails naming the vocabulary**

```python
def test_unknown_track_flag_fails_with_vocabulary() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(
            backend,
            _create_args(track="gamma", load_config=lambda: _config("advisory")),
        )
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert "alpha" in exc_info.value.message
    assert backend.ids() == []
```

- [ ] **Cycle 5: explicit --track wins over parent inheritance, and stamps**

```python
def test_explicit_track_flag_wins_over_parent() -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(parent="epic-1", track="beta", load_config=lambda: _config("required")),
    )
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert "track:beta" in backend.labels(new_id)
```

- [ ] **Cycle 6 (criterion 17): no config resolvable → behaves exactly as today**

```python
def _not_found_loader() -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def _invalid_loader() -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: malformed TOML in project-config.toml",
        detail={"reason": "invalid"},
    )


def test_unconfigured_repo_creates_exactly_as_before() -> None:
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=_not_found_loader))
    assert isinstance(data, dict)
    assert "warnings" not in data
    new_id = data["id"]
    assert isinstance(new_id, str)
    assert all(not label.startswith("track:") for label in backend.labels(new_id))


def test_unconfigured_repo_fails_explicit_track_flag() -> None:
    backend = FakeBackend()
    with pytest.raises(WorkError) as exc_info:
        create_noun(
            backend, _create_args(track="alpha", load_config=_not_found_loader)
        )
    assert exc_info.value.code is ErrorCode.NOT_CONFIGURED
    assert backend.ids() == []


def test_invalid_config_skips_gate_with_warning_never_breaks_create() -> None:
    backend = FakeBackend()
    data = create_noun(backend, _create_args(load_config=_invalid_loader))
    assert isinstance(data, dict)
    new_id = data["id"]
    assert isinstance(new_id, str)
    warnings = data["warnings"]
    assert isinstance(warnings, list)
    assert any("track gate skipped" in str(warning) for warning in warnings)
```

- [ ] **Cycle 7 (criterion 9, create leg): milestones via --raw bypass the gate entirely** — CLI-level, since `--raw` routing lives in `verbs/__init__.py`:

```python
def test_raw_milestone_create_bypasses_gate_even_in_required_mode() -> None:
    # Milestones are track-exempt (track spec §3) and enter via --raw; the
    # gate must not touch this path regardless of enforcement. The exploding
    # loader proves --raw never even loads config.
    def explode(_explicit_path: str | None) -> TrackLayerConfig:
        raise AssertionError("--raw create must not load config")

    step = ScriptedStep(
        ("create",),
        BdResult(returncode=0, stdout=json.dumps({"id": "w-9"}), stderr=""),
    )
    exit_code, envelope, _ = run_cli(
        ["create", "--raw", "--title", "M9", "--type", "milestone"],
        [step],
        config_loader=explode,
    )
    assert exit_code == 0
    assert envelope["ok"] is True
```

Verify the scripted `stdout` shape against what `BdBackend.create` parses (read `adapters/bd/backend.py::create` and `tests/unit/test_create_raw.py` fixtures; mirror their `BdResult` stdout exactly — the prefix `("create",)` needs no tail flags).

- [ ] **Cycle 8: spec-noun container stamps its track on the template children**

```python
def test_spec_container_children_inherit_resolved_track() -> None:
    backend = FakeBackend()
    backend.add("epic-1", type="epic", labels=["track:alpha"])
    data = create_noun(
        backend,
        _create_args(noun="spec", parent="epic-1", load_config=lambda: _config("advisory")),
    )
    assert isinstance(data, dict)
    for key in ("id", "design_child", "placeholder"):
        bead_id = data[key]
        assert isinstance(bead_id, str)
        assert "track:alpha" in backend.labels(bead_id)
```

- [ ] **Final step: full suite, then commit**

Run: `uv run pytest -n auto`
Expected: the existing `test_create_noun.py` tests FAIL first — they are CLI-level (`run_cli`/`run_cli_with_runner`) and every parented/orphan create now reaches the gate, where conftest's fail-loud `_no_config_loads` raises a plain `AssertionError` (not a `WorkError`), surfacing as `E_INTERNAL`. Fix: add a module-level CLI-shape loader to `test_create_noun.py` —

```python
def _not_found_config_loader(_explicit_path: str | None) -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )
```

— and pass `config_loader=_not_found_config_loader` to each affected `run_cli`/`run_cli_with_runner` call. Do NOT inject a *valid* config there: the gate would then issue an unscripted `bd show <parent>` between `search` and `create` and break the call log. The not-found path is byte-identical to today's behavior (criterion 17), so no scripted step changes. `test_seam_lifecycle.py` needs nothing — its creates hit `backend.create` directly, below the gate. Re-run `uv run pytest -n auto` → PASS.

```bash
git add src/workcli/lifecycle/create.py tests/unit/test_create_track_gate.py tests/unit
git commit -m "feat(workcli): create track gate — derive, else enforce (advisory/required)"
```

---

## Task 9: `work track set <id> <name>`

**Files:**
- Modify: `packages/workcli/src/workcli/cli.py` (track subparser)
- Create: `packages/workcli/src/workcli/verbs/tracks.py`
- Modify: `packages/workcli/src/workcli/verbs/__init__.py` (VERBS registry)
- Test: `packages/workcli/tests/unit/test_track_set.py`

- [ ] **Step 1: Write the failing tests (criterion 6)**

```python
"""work track set: validated label swap; cascade in Task 10 (criteria 6-7)."""

from __future__ import annotations

from argparse import Namespace

import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.verbs.tracks import track

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
)


def _track_args(item_id: str, name: str, *, cascade: bool = False) -> Namespace:
    return Namespace(
        action="set",
        id=item_id,
        name=name,
        cascade=cascade,
        load_config=lambda: CONFIG,
    )


def _track_labels(backend: FakeBackend, item_id: str) -> list[str]:
    return [label for label in backend.labels(item_id) if label.startswith("track:")]


def test_set_swaps_to_exactly_one_track_label() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["planned", "track:alpha"])
    data = track(backend, _track_args("w-1", "beta"))
    assert _track_labels(backend, "w-1") == ["track:beta"]
    assert "planned" in backend.labels(backend.ids()[0])
    assert isinstance(data, dict)
    assert data["previous"] == "alpha"


def test_set_on_untracked_bead_is_a_pure_add() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["planned"])
    data = track(backend, _track_args("w-1", "alpha"))
    assert _track_labels(backend, "w-1") == ["track:alpha"]
    assert isinstance(data, dict)
    assert data["previous"] is None


def test_set_heals_a_multi_label_bead_to_exactly_one() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha", "track:beta"])
    track(backend, _track_args("w-1", "alpha"))
    assert _track_labels(backend, "w-1") == ["track:alpha"]


def test_unknown_name_fails_and_mutates_nothing() -> None:
    backend = FakeBackend()
    backend.add("w-1", labels=["track:alpha"])
    with pytest.raises(WorkError) as exc_info:
        track(backend, _track_args("w-1", "gamma"))
    assert exc_info.value.code is ErrorCode.UNKNOWN_TRACK
    assert _track_labels(backend, "w-1") == ["track:alpha"]


def test_missing_bead_is_not_found() -> None:
    with pytest.raises(WorkError) as exc_info:
        track(FakeBackend(), _track_args("ghost", "alpha"))
    assert exc_info.value.code is ErrorCode.NOT_FOUND
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_track_set.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workcli.verbs.tracks'`

- [ ] **Step 3: Implement**

Create `src/workcli/verbs/tracks.py`:

```python
"""`work track set ID NAME [--cascade]` -- validated track reassignment.

Its own verb family: `update` stays scalar-replace-only per the contract's
layering (labels are not `UpdateFields`). The two underlying label operations
are NOT transactional -- an interruption can leave the bead track-less, which
lint invariant 1 surfaces (track spec §4: lint-recoverable, not atomic). Raw
`work label add track:<anything>` stays possible and unvalidated by design:
lint is the net, `track set` is the gate.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.tracks import TRACK_PREFIX, derive_track, require_known_track, track_label


def _swap_track_label(
    backend: Backend, current_labels: list[str], item_id: str, new_name: str
) -> None:
    """Remove stale `track:*` labels, then add the target (spec §4 ordering:
    a crash between the two leaves the bead track-less -- lint's case --
    never double-tracked)."""
    target = track_label(new_name)
    stale = [
        label
        for label in current_labels
        if label.startswith(TRACK_PREFIX) and label != target
    ]
    if stale:
        backend.label_mutate("remove", item_id, stale)
    if target not in current_labels:
        backend.label_mutate("add", item_id, [target])


def track(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work track ACTION`; v1 ships `set` only (argparse pins choices)."""
    config = args.load_config()
    require_known_track(args.name, config)
    root = backend.get(args.id)
    previous = derive_track(root.labels)
    _swap_track_label(backend, root.labels, args.id, args.name)
    relabeled = 0
    skipped: list[str] = []
    return {
        "id": args.id,
        "track": args.name,
        "previous": previous,
        "relabeled": relabeled,
        # list() wrap: a NAMED list[str] local is not assignable to a
        # JsonValue slot under mypy --strict (invariance); the constructor
        # call re-infers from context. Same idiom as the bd adapter.
        "skipped": list(skipped),
    }
```

`cli.py` — new subparser group function, called from `_build_parser()` after `_add_relations_subparsers(subparsers)`:

```python
def _add_track_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    track_parser = subparsers.add_parser(
        "track", help="track assignment: track set ID NAME [--cascade]"
    )
    track_parser.add_argument("action", choices=["set"])
    track_parser.add_argument("id", metavar="ID")
    track_parser.add_argument("name", metavar="NAME")
    track_parser.add_argument("--cascade", action="store_true")
```

`verbs/__init__.py` — import and register:

```python
from workcli.verbs.tracks import track
```

```python
    "track": track,
```

(inside `VERBS`, after `"sync": sync` — no `REQUIRED_CAPABILITY` entry: label ops are unconditional in v1.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/unit/test_track_set.py -v && uv run pytest -n auto`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/workcli/verbs/tracks.py src/workcli/verbs/__init__.py src/workcli/cli.py tests/unit/test_track_set.py
git commit -m "feat(workcli): work track set — validated single-command track swap"
```

---

## Task 10: `track set --cascade`

**Files:**
- Modify: `packages/workcli/src/workcli/verbs/tracks.py`
- Test: `packages/workcli/tests/unit/test_track_set.py` (extend)

- [ ] **Step 1: Write the failing tests (criterion 7)**

```python
def _tree_backend() -> FakeBackend:
    """root(alpha) -> child-same(alpha), child-other(beta), child-untracked;
    child-other -> grandchild-same(alpha) [cross-track subtrees still traversed]."""
    backend = FakeBackend()
    backend.add("root", labels=["track:alpha"])
    backend.add("child-same", parent="root", labels=["track:alpha"])
    backend.add("child-other", parent="root", labels=["track:beta"])
    backend.add("child-untracked", parent="root", labels=[])
    backend.add("grandchild-same", parent="child-other", labels=["track:alpha"])
    return backend


def test_cascade_relabels_matching_and_untracked_skips_other_tracks() -> None:
    backend = _tree_backend()
    data = track(backend, _track_args("root", "beta", cascade=True))
    assert _track_labels(backend, "child-same") == ["track:beta"]
    assert _track_labels(backend, "child-untracked") == ["track:beta"]
    assert _track_labels(backend, "grandchild-same") == ["track:beta"]
    assert _track_labels(backend, "child-other") == ["track:beta"]  # already the target
    assert isinstance(data, dict)
    assert data["relabeled"] == 3
    assert data["skipped"] == []


def test_cascade_skips_and_reports_descendants_on_a_third_track() -> None:
    backend = FakeBackend()
    backend.add("root", labels=["track:alpha"])
    backend.add("child-loyal", parent="root", labels=["track:beta"])
    data = track(
        backend,
        Namespace(
            action="set",
            id="root",
            name="alpha",
            cascade=True,
            load_config=lambda: CONFIG,
        ),
    )
    # Deliberately-cross-track child is never clobbered, only reported.
    assert _track_labels(backend, "child-loyal") == ["track:beta"]
    assert isinstance(data, dict)
    assert data["relabeled"] == 0
    assert data["skipped"] == ["child-loyal"]


def test_without_cascade_descendants_are_untouched() -> None:
    backend = _tree_backend()
    track(backend, _track_args("root", "beta"))
    assert _track_labels(backend, "child-same") == ["track:alpha"]
    assert _track_labels(backend, "child-untracked") == []
```

Wait — `test_cascade_relabels_matching_and_untracked_skips_other_tracks` asserts `child-other` ends at `track:beta` with `skipped == []`: the target IS beta, and a descendant already on the *target* track needs no relabel and is not "deliberately on another track" relative to the outcome. Pin the intended semantics explicitly instead: a descendant's fate depends on its track vs the root's PRE-change track (`alpha`): equal-or-untracked → relabel; anything else → skip. `child-other` (beta ≠ alpha) is therefore SKIPPED — and since it already carries the target label the visible state is identical, but the report must count it in `skipped`. Correct the two assertions to:

```python
    assert data["relabeled"] == 3
    assert data["skipped"] == ["child-other"]
```

(This mirrors the spec's rule with no target-track special case — one rule, no carve-outs.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_track_set.py -v`
Expected: FAIL — cascade tests (relabeled stays 0, labels untouched)

- [ ] **Step 3: Implement — extend `verbs/tracks.py`**

```python
def _cascade(backend: Backend, root_id: str, previous: str | None, new_name: str) -> tuple[int, list[str]]:
    """Relabel descendants on the root's PRE-change track (plus untracked ones);
    skip-and-report everything else -- cross-track parenting is legal and a
    descendant deliberately on another track is never clobbered (spec §4).
    Whole-subtree traversal: a skipped child's own descendants are still
    evaluated by the same one rule."""
    relabeled = 0
    skipped: list[str] = []
    queue: list[str] = list(backend.get(root_id).children)
    while queue:
        child_id = queue.pop(0)
        child = backend.get(child_id)
        queue.extend(child.children)
        child_track = derive_track(child.labels)
        if child_track == previous or child_track is None:
            _swap_track_label(backend, child.labels, child_id, new_name)
            relabeled += 1
        else:
            skipped.append(child_id)
    return relabeled, skipped
```

In `track()`, replace the two placeholder locals:

```python
    relabeled = 0
    skipped: list[str] = []
    if args.cascade:
        relabeled, skipped = _cascade(backend, args.id, previous, args.name)
```

Recorded decisions: (a) traversal covers closed descendants too — the spec exempts closed beads from *invariants*, not from an explicit human-invoked relabel, and skipping them would strand any later-reopened bead on a dead track; (b) an untracked descendant relabels even when `previous` is `None` (the pure-add root case) — both fall out of the one rule above. Note `child_track == previous` also matches the multi-label→`None` derivation, so double-tracked descendants get healed as "untracked" — invariant-1 beads exit the report clean.

- [ ] **Step 4: Run to verify pass, full suite**

Run: `uv run pytest tests/unit/test_track_set.py -v && uv run pytest -n auto`
Expected: PASS

- [ ] **Step 5: Commit, close slice B**

```bash
git add src/workcli/verbs/tracks.py tests/unit/test_track_set.py
git commit -m "feat(workcli): track set --cascade — pre-change-track rule, skip-and-report"
```

Run (worktree root): `make ci-workcli` → green, then deliver slice B as its own PR: `feat(workcli): track layer slice B — create gate + work track set ±cascade`.

---

## Task 11: `work lint` (slice C begins)

**Files:**
- Create: `packages/workcli/src/workcli/verbs/report.py`
- Modify: `packages/workcli/src/workcli/cli.py`, `packages/workcli/src/workcli/verbs/__init__.py`
- Test: `packages/workcli/tests/unit/test_lint.py`

The track spec's "opt-in `--format human` view to stderr" needs zero new code: the existing global `--format human` mechanism (`render_human` in `cli.py`'s finish helpers) already renders any envelope `data` to stderr — lint's report dict rides it as-is.

The sweep is one unbounded `backend.query(QueryFilters())` with a defensive `status != "closed"` filter (bd `list` already omits closed; `FakeBackend.query` does not — the filter makes the verb correct against both, and against any future backend that returns closed items). Milestone-ancestry walks the parent chain through the sweep map, falling back to `backend.get` for parents outside it (closed containers), memoized, cycle-guarded.

- [ ] **Step 1: Write the failing test — the criterion-10 fixture, all five invariant classes at once** (one fixture, five assertions — the envelope is one report, so this is one behavior: "lint reports each class")

```python
"""work lint: five advisory invariants over one sweep (criteria 9-11)."""

from __future__ import annotations

from argparse import Namespace

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.verbs.report import lint

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=1,
    wip_exempt_milestones=("m-exempt",),
)


def _lint_args(config: TrackLayerConfig = CONFIG) -> Namespace:
    return Namespace(load_config=lambda: config)


def _fixture() -> FakeBackend:
    """One backend exercising every invariant class (criterion 10)."""
    backend = FakeBackend()
    # Milestones: two in_progress non-exempt (cap 1 -> breach) + one exempt.
    backend.add("m-1", type="milestone", status="in_progress")
    backend.add("m-2", type="milestone", status="in_progress")
    backend.add("m-exempt", type="milestone", status="in_progress")
    # Invariant 1: missing track / multi track (both under a milestone).
    backend.add("no-track", parent="m-1", labels=[])
    backend.add("two-tracks", parent="m-1", labels=["track:alpha", "track:beta"])
    # Invariant 2: milestone-orphan; and an explicitly exempted orphan.
    backend.add("orphan", labels=["track:alpha"])
    backend.add(
        "orphan-exempt", labels=["track:alpha", "lint-exempt:no-milestone"]
    )
    # Ancestry through a CLOSED intermediate container must still find m-1.
    backend.add("closed-epic", type="epic", status="closed", parent="m-1")
    backend.add("deep-child", parent="closed-epic", labels=["track:alpha"])
    # Invariant 4: one track holding two leases.
    backend.add(
        "lease-1", parent="m-1", status="in_progress", labels=["track:alpha"]
    )
    backend.add(
        "lease-2", parent="m-1", status="in_progress", labels=["track:alpha"]
    )
    # Invariant 5: parent-child mismatch below milestone level.
    backend.add("epic-beta", type="epic", parent="m-1", labels=["track:beta"])
    backend.add(
        "mismatch-child", parent="epic-beta", labels=["track:alpha"]
    )
    # Closed beads are exempt from everything.
    backend.add("closed-untracked", status="closed", labels=[])
    return backend


def test_lint_reports_every_invariant_class() -> None:
    report = lint(_fixture(), _lint_args())
    assert isinstance(report, dict)

    violations = report["track_violations"]
    assert isinstance(violations, list)
    flagged = {entry["id"] for entry in violations if isinstance(entry, dict)}
    assert flagged == {"no-track", "two-tracks"}  # closed + milestones exempt

    orphans = report["milestone_orphans"]
    assert isinstance(orphans, list)
    assert orphans == ["orphan"]  # exempt label honored; deep-child anchored
                                  # through its CLOSED epic to m-1

    wip = report["wip"]
    assert isinstance(wip, dict)
    assert wip["breached"] is True
    active = wip["active"]
    assert isinstance(active, list)
    assert sorted(str(m) for m in active) == ["m-1", "m-2"]  # criterion 11: exempt excluded

    leases = report["leases"]
    assert isinstance(leases, dict)
    assert leases["crowded_tracks"] == ["alpha"]
    all_leases = leases["leases"]
    assert isinstance(all_leases, list)
    assert len(all_leases) == 2  # every non-milestone lease listed for triage

    mismatches = report["track_mismatches"]
    assert isinstance(mismatches, list)
    assert mismatches == [
        {
            "child": "mismatch-child",
            "child_track": "alpha",
            "parent": "epic-beta",
            "parent_track": "beta",
        }
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_lint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workcli.verbs.report'`

- [ ] **Step 3: Implement `src/workcli/verbs/report.py` (lint half)**

```python
"""`work lint` + `work graph --json` -- the repo-wide reporting verbs.

Both are defined as aggregations over tracks (track spec §4's
split-portability rule): one sweep, pure reducers, no single-DB semantics in
the contract. Advisory in v1: lint always exits 0 (spec §9 defers CI-gating);
violations live in the envelope, not the exit code.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import Item, QueryFilters
from workcli.tracks import TRACK_PREFIX, derive_track

NO_MILESTONE_EXEMPT_LABEL = "lint-exempt:no-milestone"


def _sweep(backend: Backend) -> list[Item]:
    """All non-closed items. bd list already omits closed; the filter makes
    the verb correct against any backend that returns them anyway."""
    return [item for item in backend.query(QueryFilters()) if item.status != "closed"]


def _track_violations(non_milestone: list[Item]) -> list[JsonValue]:
    """Invariant 1: exactly one track:* label per non-closed, non-milestone bead."""
    violations: list[JsonValue] = []
    for item in non_milestone:
        track_labels = [label for label in item.labels if label.startswith(TRACK_PREFIX)]
        if len(track_labels) != 1:
            # list() wrap: named list[str] locals are not assignable to a
            # JsonValue slot under mypy --strict (invariance).
            violations.append({"id": item.id, "track_labels": list(track_labels)})
    return violations


def _has_milestone_ancestor(
    backend: Backend, item: Item, known: dict[str, Item], fetched: dict[str, Item]
) -> bool:
    seen: set[str] = set()
    parent_id = item.parent
    while parent_id is not None and parent_id not in seen:
        seen.add(parent_id)
        ancestor = known.get(parent_id) or fetched.get(parent_id)
        if ancestor is None:
            ancestor = backend.get(parent_id)  # closed container outside the sweep
            fetched[parent_id] = ancestor
        if ancestor.type == "milestone":
            return True
        parent_id = ancestor.parent
    return False


def _milestone_orphans(
    backend: Backend, swept: list[Item], by_id: dict[str, Item]
) -> list[JsonValue]:
    """Invariant 2: milestone ancestor, or an explicit exempt label."""
    fetched: dict[str, Item] = {}
    return [
        item.id
        for item in swept
        if item.type != "milestone"
        and NO_MILESTONE_EXEMPT_LABEL not in item.labels
        and not _has_milestone_ancestor(backend, item, by_id, fetched)
    ]


def _milestone_wip(swept: list[Item], config: TrackLayerConfig) -> JsonValue:
    """Invariant 3: in_progress milestones vs the WIP cap, exempt list excluded.
    An unset cap ([operating-model] absent) skips the check: breached=False,
    cap=null -- §6 hardcodes nothing."""
    active = [
        item.id
        for item in swept
        if item.type == "milestone"
        and item.status == "in_progress"
        and item.id not in config.wip_exempt_milestones
    ]
    if config.milestone_wip_cap is None:
        return {"cap": None, "active": list(active), "breached": False}
    return {
        "cap": config.milestone_wip_cap,
        "active": list(active),
        "breached": len(active) > config.milestone_wip_cap,
    }


def _lease_report(non_milestone: list[Item]) -> JsonValue:
    """Invariant 4: every non-milestone lease listed; tracks holding >1 flagged."""
    leases = [item for item in non_milestone if item.status == "in_progress"]
    counts: dict[str, int] = {}
    for item in leases:
        track_name = derive_track(item.labels)
        if track_name is not None:
            counts[track_name] = counts.get(track_name, 0) + 1
    return {
        "leases": [
            {"id": item.id, "track": derive_track(item.labels)} for item in leases
        ],
        "crowded_tracks": list(sorted(name for name, count in counts.items() if count > 1)),
    }


def _track_mismatches(non_milestone: list[Item], by_id: dict[str, Item]) -> list[JsonValue]:
    """Invariant 5: soft warning on parent-child track mismatch below milestone level."""
    mismatches: list[JsonValue] = []
    for item in non_milestone:
        if item.parent is None or item.parent not in by_id:
            continue
        parent = by_id[item.parent]
        if parent.type == "milestone":
            continue
        child_track = derive_track(item.labels)
        parent_track = derive_track(parent.labels)
        if child_track is not None and parent_track is not None and child_track != parent_track:
            mismatches.append(
                {
                    "child": item.id,
                    "child_track": child_track,
                    "parent": item.parent,
                    "parent_track": parent_track,
                }
            )
    return mismatches


def lint(backend: Backend, args: Namespace) -> JsonValue:
    """`work lint` -- five advisory invariants, one sweep (track spec §4)."""
    config = args.load_config()
    swept = _sweep(backend)
    by_id = {item.id: item for item in swept}
    non_milestone = [item for item in swept if item.type != "milestone"]
    return {
        "track_violations": _track_violations(non_milestone),
        "milestone_orphans": _milestone_orphans(backend, swept, by_id),
        "wip": _milestone_wip(swept, config),
        "leases": _lease_report(non_milestone),
        "track_mismatches": _track_mismatches(non_milestone, by_id),
    }
```

`cli.py` — add to a new `_add_report_subparsers` (called from `_build_parser()` after the track group):

```python
def _add_report_subparsers(subparsers: _SubParsersAction[_EnvelopeArgumentParser]) -> None:
    subparsers.add_parser(
        "lint", help="track/milestone hygiene report (advisory; always exits 0)"
    )
    graph_parser = subparsers.add_parser(
        "graph", help="bulk node/edge export for visualization consumers"
    )
    graph_parser.add_argument("--json", action="store_true", dest="json_output")
```

`verbs/__init__.py`:

```python
from workcli.verbs.report import graph, lint
```

```python
    "lint": lint,
    "graph": graph,
```

(Add a placeholder-free `graph` in the same edit — Task 12 writes it; to keep this task green-able standalone, define `graph` in `report.py` now with just the `--json` guard and `raise WorkError(ErrorCode.USAGE, "work graph requires --json (the only v1 output)")` when absent, returning `{"nodes": [], "edges": []}` otherwise — Task 12's red test immediately replaces that stub's empty return with real behavior. The stub ships inside slice C only, never crosses a PR boundary.)

- [ ] **Step 4: Add the two config-gate tests + advisory-exit test (CLI-level), run everything**

```python
import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode, WorkError


def _not_configured_loader(_explicit_path: str | None) -> TrackLayerConfig:
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def test_lint_without_config_is_e_not_configured() -> None:
    exit_code, envelope, _ = run_cli(["lint"], [], config_loader=_not_configured_loader)
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_NOT_CONFIGURED"


def test_lint_with_violations_still_exits_zero() -> None:
    # Criterion 10's advisory leg: violations live in the envelope, exit stays 0.
    def loader(_explicit_path: str | None) -> TrackLayerConfig:
        return CONFIG

    step = ScriptedStep(
        ("list",),
        BdResult(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": "w-1",
                        "title": "T",
                        "issue_type": "task",
                        "status": "open",
                        "priority": 2,
                        "labels": [],
                    }
                ]
            ),
            stderr="",
        ),
    )
    exit_code, envelope, _ = run_cli(["lint"], [step], config_loader=loader)
    assert exit_code == 0
    assert envelope["ok"] is True
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["track_violations"] == [{"id": "w-1", "track_labels": []}]
```

Run: `uv run pytest tests/unit/test_lint.py -v && uv run pytest -n auto`
Expected: PASS (note: the bd `list` scripted argv must match `BdBackend.query` exactly, and lint's orphan check will re-`get` nothing here because `w-1` has no parent)

- [ ] **Step 5: Commit**

```bash
git add src/workcli/verbs/report.py src/workcli/verbs/__init__.py src/workcli/cli.py tests/unit/test_lint.py
git commit -m "feat(workcli): work lint — five advisory track/milestone invariants"
```

---

## Task 12: `work graph --json` + shipped schema

**Files:**
- Modify: `packages/workcli/src/workcli/verbs/report.py` (graph half)
- Create: `packages/workcli/src/workcli/schemas/work-graph.schema.json`
- Modify: `packages/workcli/pyproject.toml` (jsonschema dev dep)
- Test: `packages/workcli/tests/unit/test_graph.py`

- [ ] **Step 1: Add `jsonschema` to the dev dependency group and lock**

In `pyproject.toml` `[dependency-groups]` dev list, append `"jsonschema"`. Then:

Run: `uv lock && uv sync`
Expected: lockfile updates. (Runtime `dependencies = []` is untouched — the pip-audit surface stays nil; remember `make ci` audits every package's lock, so this `uv.lock` change rides in this PR.)

- [ ] **Step 2: Write the failing tests (criterion 12)**

```python
"""work graph --json: bulk node/edge export validating against the shipped schema."""

from __future__ import annotations

import json
from argparse import Namespace
from importlib import resources

import jsonschema
import pytest

from tests.fake_backend import FakeBackend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.model import DepEdge
from workcli.verbs.report import graph

CONFIG = TrackLayerConfig(
    names=("alpha", "beta"),
    organizing_only=(),
    enforcement="advisory",
    milestone_wip_cap=None,
    wip_exempt_milestones=(),
)


def _graph_args(*, json_output: bool = True) -> Namespace:
    return Namespace(json_output=json_output, load_config=lambda: CONFIG)


def _backend() -> FakeBackend:
    backend = FakeBackend()
    backend.add("m-1", type="milestone", status="in_progress")
    # Non-closed bead whose ancestry runs through a CLOSED epic.
    backend.add("closed-epic", type="epic", status="closed", parent="m-1")
    backend.add(
        "leaf",
        parent="closed-epic",
        labels=["track:alpha"],
        deps=[DepEdge(id="blocker", type="blocks", status="open")],
    )
    backend.add("blocker", labels=["track:beta"])
    return backend


def _schema() -> dict[str, object]:
    schema_text = (
        resources.files("workcli") / "schemas" / "work-graph.schema.json"
    ).read_text(encoding="utf-8")
    loaded = json.loads(schema_text)
    assert isinstance(loaded, dict)
    return loaded


def test_graph_output_validates_against_shipped_schema() -> None:
    data = graph(_backend(), _graph_args())
    jsonschema.validate(data, _schema())  # criterion 12's contract leg


def test_graph_carries_every_nonclosed_bead_with_track_and_typed_edges() -> None:
    data = graph(_backend(), _graph_args())
    assert isinstance(data, dict)
    nodes = data["nodes"]
    edges = data["edges"]
    assert isinstance(nodes, list)
    assert isinstance(edges, list)

    by_id = {node["id"]: node for node in nodes if isinstance(node, dict)}
    # Every non-closed bead present...
    assert {"m-1", "leaf", "blocker"} <= set(by_id)
    # ...plus the closed container needed for leaf's ancestry.
    assert "closed-epic" in by_id
    assert by_id["closed-epic"]["status"] == "closed"
    assert by_id["leaf"]["track"] == "alpha"
    assert by_id["m-1"]["track"] is None

    assert {"from": "leaf", "to": "blocker", "type": "blocks"} in edges
    assert {"from": "leaf", "to": "closed-epic", "type": "parent-child"} in edges
    assert {"from": "closed-epic", "to": "m-1", "type": "parent-child"} in edges


def test_graph_without_json_flag_is_usage_error() -> None:
    with pytest.raises(WorkError) as exc_info:
        graph(_backend(), _graph_args(json_output=False))
    assert exc_info.value.code is ErrorCode.USAGE
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/unit/test_graph.py -v`
Expected: FAIL — schema file missing (`FileNotFoundError`) and the stub returns empty nodes/edges

- [ ] **Step 4: Implement**

Create `src/workcli/schemas/work-graph.schema.json` (the shipped data contract — vizsuite V2's read path):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "workcli/work-graph.schema.json",
  "title": "work graph --json `data` payload",
  "description": "Bulk export: every non-closed bead plus closed containers needed for ancestry; dependency edges typed as bd emits them, parent-child edges synthesized child->parent. Edge endpoints MAY reference closed beads absent from nodes (severed-blocker case).",
  "type": "object",
  "required": ["nodes", "edges"],
  "additionalProperties": false,
  "properties": {
    "nodes": { "type": "array", "items": { "$ref": "#/$defs/node" } },
    "edges": { "type": "array", "items": { "$ref": "#/$defs/edge" } }
  },
  "$defs": {
    "node": {
      "type": "object",
      "required": ["id", "title", "type", "status", "priority", "labels", "track", "parent"],
      "additionalProperties": false,
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
        "type": { "type": "string" },
        "status": { "type": "string" },
        "priority": { "type": "string" },
        "labels": { "type": "array", "items": { "type": "string" } },
        "track": { "type": ["string", "null"] },
        "parent": { "type": ["string", "null"] }
      }
    },
    "edge": {
      "type": "object",
      "required": ["from", "to", "type"],
      "additionalProperties": false,
      "properties": {
        "from": { "type": "string" },
        "to": { "type": "string" },
        "type": { "type": "string" }
      }
    }
  }
}
```

Replace the Task 11 stub in `report.py`:

```python
def _node(item: Item) -> JsonValue:
    return {
        "id": item.id,
        "title": item.title,
        "type": item.type,
        "status": item.status,
        "priority": item.priority,
        "labels": list(item.labels),
        "track": derive_track(item.labels),
        "parent": item.parent,
    }


def _closed_ancestors(
    backend: Backend, items: list[Item], by_id: dict[str, Item]
) -> list[Item]:
    """Closed containers needed for ancestry: walk every parent chain, fetch
    what the sweep didn't carry, memoized, cycle-guarded."""
    fetched: dict[str, Item] = {}
    for item in items:
        seen: set[str] = set()
        parent_id = item.parent
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            if parent_id in by_id:
                parent_id = by_id[parent_id].parent
                continue
            if parent_id not in fetched:
                fetched[parent_id] = backend.get(parent_id)
            parent_id = fetched[parent_id].parent
    return list(fetched.values())


def graph(backend: Backend, args: Namespace) -> JsonValue:
    """`work graph --json` -- the vizsuite V2 / landscape data contract
    (track spec §4; schema shipped at workcli/schemas/work-graph.schema.json)."""
    if not args.json_output:
        raise WorkError(ErrorCode.USAGE, "work graph requires --json (the only v1 output)")
    args.load_config()  # new-verb gate (criterion 17); the payload itself is config-free
    lean = _sweep(backend)
    items = backend.batch_get([item.id for item in lean])  # full detail: deps + children
    by_id = {item.id: item for item in items}
    ancestors = _closed_ancestors(backend, items, by_id)

    edges: list[JsonValue] = []
    for item in items:
        edges.extend(
            {"from": item.id, "to": edge.id, "type": edge.type} for edge in item.deps
        )
    for node_item in (*items, *ancestors):
        if node_item.parent is not None:
            edges.append(
                {"from": node_item.id, "to": node_item.parent, "type": "parent-child"}
            )

    return {"nodes": [_node(item) for item in (*items, *ancestors)], "edges": edges}
```

(`batch_get` is one `bd show id... --json` call for the whole sweep — full deps without N+1 subprocess round-trips. Dep edges are emitted from non-closed beads only; a dep pointing at a closed bead stays in the edge list with its endpoint absent from nodes, as the schema documents.)

- [ ] **Step 5: Run to verify pass; confirm the schema ships in the wheel**

Run: `uv run pytest tests/unit/test_graph.py -v && uv run pytest -n auto`
Expected: PASS

Run: `uv build && unzip -l dist/workcli-0.1.0-py3-none-any.whl | grep schema`
Expected: `workcli/schemas/work-graph.schema.json` listed (hatchling packages the whole `src/workcli` dir). Delete `dist/` afterward: `rm -rf dist`.

- [ ] **Step 6: Commit**

```bash
git add src/workcli/verbs/report.py src/workcli/schemas/work-graph.schema.json pyproject.toml uv.lock tests/unit/test_graph.py
git commit -m "feat(workcli): work graph --json + shipped schema (vizsuite V2 data contract)"
```

---

## Task 13: Slice C close-out — gate, PR, bead bookkeeping

- [ ] **Step 1: Full gate from the worktree root**

Run: `make ci-workcli`
Expected: green across lint/format/mypy/coverage(≥90 branch)/pip-audit/entry-verify. Coverage risk spots: `config.py`'s OSError read branch and `report.py`'s cycle guards — if under threshold, cover the OSError branch with a `chmod 0` tmp file test (skip on Windows-style platforms is unnecessary; CI is POSIX) rather than a pragma.

- [ ] **Step 2: Deliver slice C as its own PR**

PR title: `feat(workcli): track layer slice C — work lint + work graph --json with shipped schema`.

- [ ] **Step 3: After the slice-C merge, close the bead**

```bash
bd close agents-config-ey4rl
bd show agents-config-wgclw.9.10   # confirm epic state; downstream beads djcr5/jpn0s now unblocked
bd dolt push
```

---

## Acceptance-criteria traceability

| Criterion | Where proven |
|---|---|
| 1 parent inheritance, both modes | Task 8 cycle 1 (parametrized) |
| 2 required refuses, creates nothing | Task 8 cycle 2 |
| 3 advisory untracked + warning (+ lint flags it) | Task 8 cycle 3 (warning) + Task 11 invariant 1 (flag) |
| 4 omitted enforcement key ⇒ advisory | Task 1 (`test_enforcement_omitted_defaults_to_advisory`) + Task 8 cycle 3 note |
| 5 unknown --track names vocabulary | Task 8 cycle 4 |
| 6 track set exactly-one, pure add, unknown fails | Task 9 |
| 7 cascade relabel/skip/report; no-cascade untouched | Task 10 |
| 8 track on every read verb; list --track derived-match | Task 3 (parametrized verbs) + Task 5 |
| 9 milestones exempt at create + never lint-flagged | Task 8 cycle 7 + Task 11 fixture (milestones absent from `track_violations`) |
| 10 lint fixture, all five classes, exit 0 | Task 11 |
| 11 exempt milestone not counted | Task 11 (`m-exempt` absent from `wip.active`) |
| 12 graph completeness + schema validation | Task 12 |
| 16 upward search + --config override | Task 1 + Task 4 |
| 17 E_NOT_CONFIGURED on new surfaces; pre-existing verbs untouched | Tasks 1, 4 (laziness), 5, 8 cycle 6, 11 |

Criteria 13–15 belong to the `work triggers`/`work groom` continuation (bead `agents-config-djcr5`), not this plan.
