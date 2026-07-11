# GateStrength Enum + Disposition.gate Validation Implementation Plan

> **For agentic workers:** Implement this plan task-by-task using the `test-driven-development` skill (red-green-refactor per task). For subagent dispatch, invoke one fresh subagent per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `recommended_gate` load-bearing: type `Disposition.gate` as a `GateStrength` enum and flip a `FIXED` item with an absent/invalid gate to `FAILED` via the fix audit (spec: `docs/specs/2026-06-20-prgroom-fix-verify-subsystem.md` §6.1; bead `agents-config-abn9.8.23.1`).

**Architecture:** `GateStrength(StrEnum)` joins the serialization-contract enums in `prsession/enums.py` with a lenient `parse()` classmethod. `Disposition.gate` retypes `str → GateStrength | None` (omit-when-None JSON, additive — schema_version stays 1). The fix audit gains one per-item rule in `_audit_fixed` (gate check runs AFTER the sha checks so richer sha violations keep winning). `FixItemResult.recommended_gate` stays a raw `str` at the contract boundary — lenient parse, audit owns validation (the `MemoryEntry.classification` precedent).

**Tech Stack:** Python 3.12, dataclasses, StrEnum, pytest. Package gate: `make ci-prgroom` (lint, format, typecheck, coverage, audit).

**Out of scope:** the `verify` VerbStep, tier selection, `VerifyVerdict`, config (all `abn9.8.23.2`); `resolve_escalated --as fixed` keeps building gate-less dispositions (None-handling at tier selection is 8.23.2's concern).

---

### Task 1: `GateStrength` enum + lenient `parse()`

**Files:**
- Modify: `packages/prgroom/src/prgroom/prsession/enums.py`
- Test: `packages/prgroom/tests/unit/test_gate_strength.py` (create)

- [ ] **Step 1: Write the failing test**

```python
"""GateStrength enum + lenient parse (fix-verify spec §6.1)."""

from __future__ import annotations

import pytest

from prgroom.prsession.enums import GateStrength


def test_values_are_the_serialization_contract() -> None:
    assert GateStrength.FULL.value == "full"
    assert GateStrength.LITE.value == "lite"


@pytest.mark.parametrize(("raw", "want"), [("full", GateStrength.FULL), ("lite", GateStrength.LITE)])
def test_parse_accepts_valid_values(raw: str, want: GateStrength) -> None:
    assert GateStrength.parse(raw) is want


@pytest.mark.parametrize("raw", ["", "banana", "FULL", " full"])
def test_parse_returns_none_for_invalid(raw: str) -> None:
    assert GateStrength.parse(raw) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_gate_strength.py -v`
Expected: FAIL with `ImportError: cannot import name 'GateStrength'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/prgroom/src/prgroom/prsession/enums.py`:

```python
class GateStrength(StrEnum):
    """The verify tier a fix recommends for its item (fix-verify spec §6.1)."""

    FULL = "full"
    LITE = "lite"

    @classmethod
    def parse(cls, raw: object) -> GateStrength | None:
        """None for anything that is not a canonical gate value (lenient boundary parse).

        ``raw`` is typed ``object`` because the value flows from a contract
        boundary (``FixItemResult.recommended_gate``) that may carry whatever a
        provider emitted for that JSON field — a canonical string, but also
        ``null`` (Python ``None``), a number, a bool, a list, or a dict. The
        non-str guard makes that leniency explicit: any non-str value returns
        ``None`` rather than raising.
        """
        if not isinstance(raw, str):
            return None
        try:
            return cls(raw)
        except ValueError:
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_gate_strength.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/prsession/enums.py packages/prgroom/tests/unit/test_gate_strength.py
git commit -m "feat(prgroom): add GateStrength enum with lenient parse"
```

### Task 2: Retype `Disposition.gate` as `GateStrength | None`

**Files:**
- Modify: `packages/prgroom/src/prgroom/prsession/state.py:87,102-103,117`
- Test: `packages/prgroom/tests/unit/test_state_serde.py:95,183` + new tests

- [ ] **Step 1: Write the failing tests**

In `test_state_serde.py`, update the two existing `Disposition` constructions: `gate="full"` → `gate=GateStrength.FULL` (line 95) and `gate="lite"` → `gate=GateStrength.LITE` (line 183); add `GateStrength` to the `prgroom.prsession.enums` import. Then append:

```python
def test_disposition_gate_roundtrips_as_enum() -> None:
    d = Disposition(
        kind=DispositionKind.FIXED,
        decided_at=_T,
        decided_by="agent",
        gate=GateStrength.FULL,
    )
    encoded = d.to_dict()
    assert encoded["gate"] == "full"
    decoded = Disposition.from_dict(encoded)
    assert decoded.gate is GateStrength.FULL


def test_disposition_gate_none_is_omitted_and_loads_none() -> None:
    d = Disposition(kind=DispositionKind.SKIPPED, decided_at=_T, decided_by="agent")
    encoded = d.to_dict()
    assert "gate" not in encoded
    assert Disposition.from_dict(encoded).gate is None


def test_disposition_legacy_empty_gate_loads_none() -> None:
    # Pre-enum writers omitted falsy gates, but a hand-edited "" must not raise.
    raw = {"kind": "skipped", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": ""}
    assert Disposition.from_dict(raw).gate is None


def test_disposition_invalid_gate_raises() -> None:
    # Same strictness as kind: an unknown non-empty enum value is a corrupt state file.
    raw = {"kind": "fixed", "decided_at": _T.isoformat(), "decided_by": "agent", "gate": "banana"}
    with pytest.raises(ValueError, match="banana"):
        Disposition.from_dict(raw)
```

(Reuse the module's existing `_T` timestamp constant and `pytest` import; add either if absent.)

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_state_serde.py -v`
Expected: the four new tests FAIL (`encoded["gate"]` is a bare enum repr / no ValueError); pre-existing tests still pass.

- [ ] **Step 3: Implement in `state.py`**

Import: add `GateStrength` to the `prgroom.prsession.enums` import block. Field (line 87):

```python
    gate: GateStrength | None = None
```

`to_dict` (lines 102-103):

```python
        if self.gate is not None:
            d["gate"] = self.gate.value
```

`from_dict` (line 117) — absent-form guard keeps legacy `""` loading as None while any other value (including falsy `0`/`False`) parses or raises like `kind` does:

```python
            # Absent-form guard: missing/legacy "" load as None; anything else must
            # parse or raise like `kind` does (corrupt state file, not silent data
            # loss). Only None and "" are absent — falsy 0/False still parse-or-raise.
            gate=GateStrength(raw_gate)
            if (raw_gate := d.get("gate")) is not None and raw_gate != ""
            else None,
```

- [ ] **Step 4: Run to verify all serde tests pass**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_state_serde.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/prsession/state.py packages/prgroom/tests/unit/test_state_serde.py
git commit -m "feat(prgroom): type Disposition.gate as GateStrength | None"
```

### Task 3: Fix-audit rule — FIXED requires a valid gate

**Files:**
- Modify: `packages/prgroom/src/prgroom/agent/fix_audit.py` (`_audit_fixed` + module docstring §5 list)
- Test: `packages/prgroom/tests/unit/test_agent_fix_audit.py`

- [ ] **Step 1: Write the failing tests**

In `test_agent_fix_audit.py`, update the one clean-FIXED fixture (line 62) to carry a gate:

```python
    out = FixOutput(
        items=[_row("C_1", DispositionKind.FIXED, commit_shas=["new1"], recommended_gate="full")]
    )
```

Append after `test_fixed_claiming_pre_baseline_sha_is_audit_failed`:

```python
def test_fixed_with_empty_gate_is_audit_failed() -> None:
    # §6.1: recommended_gate is load-bearing — a FIXED item must carry a valid tier.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["new1"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED
    assert "recommended_gate" in v["C_1"].detail


def test_fixed_with_invalid_gate_is_audit_failed() -> None:
    req = _req("C_1")
    out = FixOutput(
        items=[
            _row("C_1", DispositionKind.FIXED, commit_shas=["new1"], recommended_gate="banana")
        ]
    )
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_AUDIT_FAILED


def test_fixed_gate_check_runs_after_sha_checks() -> None:
    # An unreachable sha must keep its richer UNREACHABLE_SHA code even when the
    # gate is also missing — first offending rule wins, shas first.
    req = _req("C_1")
    out = FixOutput(items=[_row("C_1", DispositionKind.FIXED, commit_shas=["ghost"])])
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster={"new1"})
    assert v["C_1"].code is ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA


def test_non_fixed_dispositions_need_no_gate() -> None:
    req = _req("C_1")
    out = FixOutput(
        items=[_row("C_1", DispositionKind.ALREADY_ADDRESSED, commit_shas=["base"])]
    )
    v = audit_fix_items(req, out, ancestors_of_pre={"base"}, new_in_cluster=set())
    assert "C_1" not in v
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_agent_fix_audit.py -v`
Expected: `test_fixed_with_empty_gate_is_audit_failed` and `test_fixed_with_invalid_gate_is_audit_failed` FAIL (no violation produced); the rest PASS.

- [ ] **Step 3: Implement the audit rule**

In `fix_audit.py`: add `GateStrength` to the `prgroom.prsession.enums` import. In `_audit_fixed`, after the sha loop (before the final `return None`):

```python
    if GateStrength.parse(row.recommended_gate) is None:
        return _fail(
            row,
            f"item {row.gh_id!r} 'fixed' has missing/invalid recommended_gate "
            f"{row.recommended_gate!r} (must be one of {[g.value for g in GateStrength]})",
        )
```

Module docstring, extend the `fixed` bullet in the §5 list:

```
* ``fixed`` → ≥1 claimed sha, every claimed sha is a NEW commit
  (``∈ new_in_cluster``), and ``recommended_gate`` parses as a
  :class:`~prgroom.prsession.enums.GateStrength` — an absent/invalid gate is a
  ``CONTRACT_FIX_AUDIT_FAILED`` (§6.1 makes the gate load-bearing). ...
```

- [ ] **Step 4: Run to verify all audit tests pass**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_agent_fix_audit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/agent/fix_audit.py packages/prgroom/tests/unit/test_agent_fix_audit.py
git commit -m "feat(prgroom): fix audit fails FIXED items with missing/invalid recommended_gate"
```

### Task 4: `run_fix` builds enum-typed gates end-to-end

**Files:**
- Modify: `packages/prgroom/src/prgroom/agent/fix.py:336-345` (`_clean_disposition`)
- Test: `packages/prgroom/tests/unit/test_agent_fix.py`

- [ ] **Step 1: Write the failing tests**

In `test_agent_fix.py`: add `GateStrength` to the `prgroom.prsession.enums` import; strengthen line 163 to the enum identity:

```python
    assert c1.gate is GateStrength.FULL
```

Append (reusing the module's existing fake-git/dispatcher helpers — follow the pattern of the surrounding `run_fix` tests for constructing `req`/dispatcher/git fakes):

```python
def test_fixed_row_with_missing_gate_flips_to_failed_end_to_end() -> None:
    # The audit rule rides through run_fix: a FIXED row without a gate lands FAILED
    # with the gate cause in the rationale, and the built disposition carries no gate.
    req = _fix_input("C_1")
    out = FixOutput(
        items=[
            FixItemResult(
                gh_id="C_1",
                disposition=DispositionKind.FIXED,
                commit_shas=["n1"],
            )
        ]
    )
    git = _GitStub(pre="pre", post="post", new=["n1"])
    result = run_fix(
        req, _StubDispatcher(out), git, now=_T, decided_by="agent", known_thread_ids=set()
    )
    d = result.dispositions["C_1"]
    assert d.kind is DispositionKind.FAILED
    assert "recommended_gate" in d.rationale
    assert d.gate is None
```

(`_fix_input` / `_GitStub` / `_StubDispatcher` stand for the file's actual helper names — reuse whatever the existing `run_fix` tests in that file use; do not invent parallel fakes.)

- [ ] **Step 2: Run to verify the new test fails**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_agent_fix.py -v`
Expected: the new test FAILS (item lands FIXED, not FAILED) — it needs Task 3's audit rule plus this task's typing to fully pass; with Task 3 landed the flip already works, so the failure to look for here is `c1.gate is GateStrength.FULL` (a raw `"full"` str fails the `is` check).

- [ ] **Step 3: Implement the conversion**

In `fix.py`: add `GateStrength` to the imports from `prgroom.prsession.state`'s sibling (`from prgroom.prsession.enums import GateStrength`). In `_clean_disposition`:

```python
        gate=GateStrength.parse(row.recommended_gate),
```

(For a clean FIXED row the audit guarantees a valid value; for other kinds an absent/garbage gate parses to None instead of raising — `_clean_disposition` stays total.)

- [ ] **Step 4: Run to verify all fix tests pass**

Run: `cd packages/prgroom && uv run pytest tests/unit/test_agent_fix.py tests/unit/test_contracts_fit.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/prgroom/src/prgroom/agent/fix.py packages/prgroom/tests/unit/test_agent_fix.py
git commit -m "feat(prgroom): build Disposition.gate as GateStrength in run_fix"
```

### Task 5: Whole-package gate

- [ ] **Step 1: Run the package CI gate**

Run: `make ci-prgroom` (repo root)
Expected: lint, format-check, typecheck, coverage, audit, entry-verify all green. Typecheck is the real audit here — it sweeps every other `Disposition(...)` construction site (`resolve_escalated.py`, `agent/errors.py`, integration tests) for str/enum mismatches the unit runs missed.

- [ ] **Step 2: Fix any stragglers typecheck finds, re-run, commit**

```bash
git add -A packages/prgroom
git commit -m "test(prgroom): sweep remaining gate call sites to GateStrength"
```

(Skip the commit if Step 1 was already green with nothing to sweep.)
