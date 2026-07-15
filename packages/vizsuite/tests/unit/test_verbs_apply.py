"""`viz apply <recommendation-id> [--dry-run]` — gated, idempotent one-click
mutation execution (spec §5.7/§10 test items 14/17).

`viz apply` refuses any recommendation without a recorded Tier-3 ACCEPTED
verdict for that exact fact id (typed `E_APPLY_NOT_ACCEPTED` refusal — a
reject/dismiss verdict, no verdict at all, or a verdict recorded against a
*different* fact id all refuse identically). A recommendation id absent from
`recommendations.json` is the existing `E_NOT_FOUND` refusal. The
recommendation's `payload["mutation"]` carries a typed mutation plan (`kind`:
`mint_bead` | `add_edge` | `relabel` | `resequence`) parsed with the same
strictness as `verdict.py`'s `_parse_ledger_payload` — an unrecognized kind,
a missing required field, an extra unknown field, or a wrong field type all
refuse as `E_SIDECAR_MALFORMED`.

`add_edge` writing a `blocks` edge runs `cycle_guard.find_cycle` over the full
accepted logical dependency graph (beads `blocks` edges plus every
already-promoted `dependency`-kind fact in `edges.json`) before any tracker
write, refusing as `E_APPLY_CYCLE_REFUSAL` with no mutation on a would-be
cycle. `resequence` is refused as `E_APPLY_RESEQUENCE_NOT_SUPPORTED` before
the tracker runner is ever touched (spec: `ruling-needed`, never `one-click`).

Idempotency differs by mutation class: `add_edge`/`relabel` re-issue their
tracker call on every replay and converge because the backend upserts are
idempotent (`work dep add`/`work label add`); `mint_bead` is NOT idempotent at
the backend (`work create` would mint a second bead), so it is keyed on a
`payload["application"]` ledger entry recording the minted bead id — replay
finds the ledger and is a pure no-op, never touching the tracker again. That
ledger is persisted the instant `mint_bead` returns an id and BEFORE the
audit-note append (unlike edge promotion's tracker-writes-then-ledger-last
ordering) precisely because the mint call itself cannot be safely repeated;
see `test_mint_...` below for the crash-window behavior this ordering buys.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedTrackerRunner, tracker_error, tracker_ok, tracker_show_ok
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import FactRecord, MatchingDescriptor, Verdict, VerdictRecord
from vizsuite.sidecar.store import SidecarStore

_NOW = "2026-07-15T09:30:00+00:00"


def _recommendation(
    fact_id: str,
    *,
    mutation: dict[str, Any] | None,
    payload_extra: dict[str, Any] | None = None,
    basis_hash: str = "basis-1",
) -> FactRecord:
    payload: dict[str, Any] = {}
    if mutation is not None:
        payload["mutation"] = mutation
    if payload_extra:
        payload.update(payload_extra)
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind="guardrail"),
        basis_hash=basis_hash,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=("spec:5.7",)
        ),
        payload=payload,
    )


def _edge_fact(
    fact_id: str,
    *,
    kind: str = "dependency",
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = (("x",), ("y",)),
    payload: dict[str, Any] | None = None,
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(
            plan_pair=("plan-a", "plan-b"), kind=kind, endpoint_bead_ids=endpoint_bead_ids
        ),
        basis_hash="basis-1",
        provenance=Provenance(
            kind=ProvenanceKind.ACCEPTED, freshness=Freshness.FRESH, citations=("spec:5.3",)
        ),
        payload=dict(payload) if payload is not None else {},
    )


def _accept(store: SidecarStore, fact_id: str, *, basis_hash: str = "basis-1") -> None:
    store.upsert_verdict(
        VerdictRecord(
            verdict_id=fact_id, fact_id=fact_id, verdict=Verdict.ACCEPT, basis_hash=basis_hash
        )
    )


def _apply_module() -> Any:
    # String-target setattr would resolve `vizsuite.verbs.apply` to the
    # *function* re-exported by `verbs/__init__` -- patch the submodule object
    # directly (the established gotcha, see test_verbs_verdict.py).
    return importlib.import_module("vizsuite.verbs.apply")


def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_apply_module(), "datetime", _make_fixed_datetime())


def _note_text(recommendation_id: str, basis_hash: str) -> str:
    return (
        f"agent-recommendation-applied: {_NOW} "
        f"(recommendation {recommendation_id}, basis {basis_hash})"
    )


def _make_fixed_datetime() -> Any:
    from datetime import UTC, datetime

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # noqa: ARG003 - mirrors datetime.now's signature
            return datetime(2026, 7, 15, 9, 30, tzinfo=UTC)

    return _FixedDatetime


# ── gating: no verdict / wrong verdict / verdict for a different fact ──────


def test_apply_refuses_a_recommendation_with_no_recorded_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation={"kind": "resequence"}),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_NOT_ACCEPTED"
    assert tracker.calls == []


@pytest.mark.parametrize("verdict_value", [Verdict.REJECT, Verdict.DISMISS])
def test_apply_refuses_a_recommendation_with_a_reject_or_dismiss_verdict(
    verdict_value: Verdict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation={"kind": "resequence"}),))
    store.upsert_verdict(
        VerdictRecord(
            verdict_id="rec-1", fact_id="rec-1", verdict=verdict_value, basis_hash="basis-1"
        )
    )
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_NOT_ACCEPTED"
    assert tracker.calls == []


def test_apply_refuses_when_the_only_accepted_verdict_is_for_a_different_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation("rec-1", mutation={"kind": "resequence"}),
            _recommendation("rec-2", mutation={"kind": "resequence"}),
        )
    )
    _accept(store, "rec-2")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_NOT_ACCEPTED"
    assert tracker.calls == []


def test_apply_on_an_unknown_recommendation_id_is_a_typed_not_found_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "ghost"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_NOT_FOUND"
    assert tracker.calls == []


# ── resequence: refused before touching the runner ──────────────────────────


def test_resequence_is_refused_before_touching_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (_recommendation("rec-1", mutation={"kind": "resequence", "reason": "dep unscheduled"}),)
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_RESEQUENCE_NOT_SUPPORTED"
    assert tracker.calls == []


def test_resequence_dry_run_is_also_refused_before_touching_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (_recommendation("rec-1", mutation={"kind": "resequence", "reason": "dep unscheduled"}),)
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_RESEQUENCE_NOT_SUPPORTED"
    assert tracker.calls == []


# ── mint_bead: fresh mint, idempotent replay, partial-failure ordering ─────


def test_mint_bead_mints_a_fresh_bead_and_records_the_ledger_and_audit_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "mint_bead",
                    "noun": "task",
                    "title": "Extract shared slice",
                    "parent": "epic-1",
                    "orphan": False,
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        responses={
            ("create", "task", "--title", "Extract shared slice", "--parent", "epic-1"): (
                tracker_ok({"id": "bead-new"})
            ),
            ("note", "bead-new", note): tracker_ok(None),
        }
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    mutation = envelope["data"]["mutation"]
    assert mutation == {"kind": "mint_bead", "bead_id": "bead-new", "already_applied": False}
    assert ("note", "bead-new", note) in tracker.calls
    (updated,) = store.read_recommendations()
    assert updated.payload["application"] == {"bead_id": "bead-new"}


def test_mint_bead_replay_is_idempotent_no_second_mint_no_second_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    create_argv = ("create", "task", "--title", "T", "--orphan")
    tracker = ScriptedTrackerRunner(
        responses={
            create_argv: tracker_ok({"id": "bead-new"}),
            ("note", "bead-new", note): tracker_ok(None),
        }
    )

    first_exit, first_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)
    second_exit, second_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert first_exit == 0
    assert second_exit == 0
    assert first_envelope["data"]["mutation"]["already_applied"] is False
    assert second_envelope["data"]["mutation"]["already_applied"] is True
    assert tracker.calls.count(create_argv) == 1
    assert tracker.calls.count(("note", "bead-new", note)) == 1


def test_mint_bead_partial_failure_persists_the_ledger_before_the_note_and_never_remints_on_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The crash-window decision this slice makes: `work create` is NOT
    idempotent at the backend (unlike `dep add`/`label add`), so re-issuing it
    on replay would mint a SECOND bead. The ledger is therefore persisted the
    instant `mint_bead` returns an id -- before the audit-note append -- so a
    failure on the note (the only fallible step left after a successful mint)
    never leaves the ledger unwritten. Replay then finds the ledger and treats
    the mint as already done (never re-attempting the mint OR the note, mirror
    -ing verdict.py's `_AlreadyPromoted` no-op contract) -- the accepted
    residual cost is that a note lost to this exact failure window never gets
    a second attempt, in exchange for an ironclad no-duplicate-mint guarantee.
    """
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    create_argv = ("create", "task", "--title", "T", "--orphan")
    tracker = ScriptedTrackerRunner(
        responses={
            create_argv: tracker_ok({"id": "bead-new"}),
            ("note", "bead-new", note): tracker_error("E_NOT_FOUND", "no such bead: bead-new"),
        }
    )

    first_exit, first_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert first_exit == 1
    assert first_envelope["error"]["code"] == "E_TRACKER_BACKEND_ERROR"
    # The ledger DID persist despite the overall failure: mint succeeded and
    # is recorded before the (fallible) note append was even attempted.
    (after_first,) = store.read_recommendations()
    assert after_first.payload["application"] == {"bead_id": "bead-new"}

    second_exit, second_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert second_exit == 0
    assert second_envelope["data"]["mutation"] == {
        "kind": "mint_bead",
        "bead_id": "bead-new",
        "already_applied": True,
    }
    # Exactly ONE create call across both attempts -- mint is never retried.
    assert tracker.calls.count(create_argv) == 1


def test_mint_bead_create_call_failure_leaves_the_ledger_unwritten_and_is_safe_to_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Contrast case: when `mint_bead`'s OWN tracker call fails cleanly (the
    backend answers `ok:false`, so we know FOR CERTAIN no bead was created),
    nothing is written to the ledger at all, and a retry is unconditionally
    safe to attempt the mint again."""
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(store, "rec-1")
    create_argv = ("create", "task", "--title", "T", "--orphan")
    tracker = ScriptedTrackerRunner(
        responses={create_argv: tracker_error("E_USAGE", "title is required")}
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_TRACKER_BACKEND_ERROR"
    (unchanged,) = store.read_recommendations()
    assert "application" not in unchanged.payload


def test_mint_bead_optional_fields_are_passed_through_to_the_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "mint_bead",
                    "noun": "task",
                    "title": "T",
                    "parent": "epic-1",
                    "description": "desc",
                    "priority": "p1",
                    "acceptance": "AC",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    create_argv = (
        "create",
        "task",
        "--title",
        "T",
        "--parent",
        "epic-1",
        "--description",
        "desc",
        "--priority",
        "p1",
        "--acceptance",
        "AC",
    )
    tracker = ScriptedTrackerRunner(
        responses={
            create_argv: tracker_ok({"id": "bead-new"}),
            ("note", "bead-new", note): tracker_ok(None),
        }
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["mutation"]["bead_id"] == "bead-new"


# ── mint_bead: dry-run ──────────────────────────────────────────────────────


def test_dry_run_previews_a_fresh_mint_with_zero_tracker_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    rec = _recommendation(
        "rec-1", mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True}
    )
    store.write_recommendations((rec,))
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0
    data = envelope["data"]
    assert data["dry_run"] is True
    preview = data["mutation"]
    assert preview["kind"] == "mint_bead"
    assert preview["already_applied"] is False
    assert preview["tracker_writes"]
    assert tracker.calls == []
    assert store.read_recommendations() == (rec,)


def test_dry_run_previews_an_already_minted_recommendation_as_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
                payload_extra={"application": {"bead_id": "bead-existing"}},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0
    preview = envelope["data"]["mutation"]
    assert preview == {
        "kind": "mint_bead",
        "bead_id": "bead-existing",
        "already_applied": True,
        "tracker_writes": [],
    }
    assert tracker.calls == []


def test_dry_run_never_enters_a_sidecar_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    setup_store = SidecarStore(tmp_path)
    setup_store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(setup_store, "rec-1")
    monkeypatch.chdir(tmp_path)
    tracker = ScriptedTrackerRunner()

    def _explode(_self: SidecarStore) -> None:
        raise AssertionError("dry-run must never acquire the sidecar transaction lock")

    monkeypatch.setattr(SidecarStore, "transaction", _explode)

    exit_code, _envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0


# ── add_edge: fresh write, cycle guard, idempotent convergence ─────────────


def test_add_edge_writes_a_blocks_edge_and_appends_audit_notes_to_both_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "bead-a",
                    "to_bead": "bead-b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        show_results={"bead-b": tracker_show_ok("bead-b", deps=[])},
        responses={
            ("dep", "add", "bead-a", "bead-b", "--type", "blocks"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
            ("note", "bead-b", note): tracker_ok(None),
        },
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["mutation"] == {
        "kind": "add_edge",
        "from_bead": "bead-a",
        "to_bead": "bead-b",
        "edge_kind": "blocks",
    }
    note_calls = {call[1]: call[2] for call in tracker.calls if call[0] == "note"}
    assert note_calls == {"bead-a": note, "bead-b": note}


def test_add_edge_related_to_writes_directly_without_a_cycle_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "bead-a",
                    "to_bead": "bead-b",
                    "edge_kind": "related-to",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    # No show_results scripted at all -- a cycle-check read would raise.
    tracker = ScriptedTrackerRunner(
        responses={
            ("dep", "add", "bead-a", "bead-b", "--type", "related-to"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
            ("note", "bead-b", note): tracker_ok(None),
        }
    )

    exit_code, _envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert not any(call[0] == "show" for call in tracker.calls)


def test_add_edge_replay_reissues_the_tracker_call_and_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "bead-a",
                    "to_bead": "bead-b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        show_results={"bead-b": tracker_show_ok("bead-b", deps=[])},
        responses={
            ("dep", "add", "bead-a", "bead-b", "--type", "blocks"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
            ("note", "bead-b", note): tracker_ok(None),
        },
    )

    first_exit, _first_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)
    second_exit, second_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert first_exit == 0
    assert second_exit == 0
    assert tracker.calls.count(("dep", "add", "bead-a", "bead-b", "--type", "blocks")) == 2
    assert second_envelope["data"]["mutation"]["edge_kind"] == "blocks"


def test_add_edge_refuses_a_blocks_write_that_would_close_a_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner(
        show_results={"b": tracker_show_ok("b", deps=[("a", "blocks", "open")])}
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_CYCLE_REFUSAL"
    assert envelope["error"]["detail"]["cycle"] == ["a", "b", "a"]
    assert not any(call[0] == "dep" for call in tracker.calls)
    assert not any(call[0] == "note" for call in tracker.calls)


def test_add_edge_cycle_check_gathers_other_promoted_dependency_edges_and_skips_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    already_promoted = _edge_fact(
        "edge-2",
        endpoint_bead_ids=(("x",), ("y",)),
        payload={"promotion": {"from_bead": "x", "to_bead": "y", "tracker_edge_kind": "blocks"}},
    )
    unpromoted = _edge_fact("edge-3", endpoint_bead_ids=(("m",), ("n",)))
    unrelated_conflict = _edge_fact("edge-4", kind="conflict", endpoint_bead_ids=(("p",), ("q",)))
    store.write_edges((already_promoted, unpromoted, unrelated_conflict))
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        show_results={"b": tracker_show_ok("b", deps=[])},
        responses={
            ("dep", "add", "a", "b", "--type", "blocks"): tracker_ok(None),
            ("note", "a", note): tracker_ok(None),
            ("note", "b", note): tracker_ok(None),
        },
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["mutation"]["edge_kind"] == "blocks"


def test_add_edge_cycle_check_refuses_as_malformed_when_another_promoted_ledger_is_not_a_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_edge_fact("edge-corrupt", payload={"promotion": "not-a-dict"}),))
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


def test_add_edge_cycle_check_refuses_as_malformed_when_another_promoted_ledger_has_bad_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges(
        (
            _edge_fact(
                "edge-corrupt",
                payload={
                    "promotion": {"from_bead": 1, "to_bead": "y", "tracker_edge_kind": "blocks"}
                },
            ),
        )
    )
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


def test_add_edge_raises_on_an_unrecognized_cycle_check_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_apply_module(), "find_cycle", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


# ── add_edge: dry-run ────────────────────────────────────────────────────


def test_dry_run_previews_add_edge_running_the_cycle_check_read_with_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "bead-a",
                    "to_bead": "bead-b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner(show_results={"bead-b": tracker_show_ok("bead-b", deps=[])})

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0
    preview = envelope["data"]["mutation"]
    assert preview["tracker_writes"]
    assert any(call[0] == "show" for call in tracker.calls)
    assert not any(call[0] == "dep" for call in tracker.calls)
    assert not any(call[0] == "note" for call in tracker.calls)


def test_dry_run_previews_add_edge_related_to_without_a_cycle_check_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "bead-a",
                    "to_bead": "bead-b",
                    "edge_kind": "related-to",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    # No show_results scripted at all -- a cycle-check read would raise.
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0
    preview = envelope["data"]["mutation"]
    assert preview["edge_kind"] == "related-to"
    assert preview["tracker_writes"]
    assert tracker.calls == []


def test_dry_run_add_edge_refuses_on_a_would_be_cycle_identically_to_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner(
        show_results={"b": tracker_show_ok("b", deps=[("a", "blocks", "open")])}
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_APPLY_CYCLE_REFUSAL"


def test_dry_run_add_edge_raises_on_an_unrecognized_cycle_check_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "blocks",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_apply_module(), "find_cycle", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


# ── relabel: fresh, idempotent convergence, dry-run ─────────────────────────


def test_relabel_adds_a_label_and_appends_an_audit_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "relabel",
                    "bead_id": "bead-a",
                    "labels": ["guardrail"],
                    "remove": False,
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        responses={
            ("label", "add", "bead-a", "guardrail"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
        }
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["mutation"] == {
        "kind": "relabel",
        "bead_id": "bead-a",
        "labels": ["guardrail"],
        "remove": False,
    }
    assert ("note", "bead-a", note) in tracker.calls


def test_relabel_remove_calls_the_remove_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "relabel",
                    "bead_id": "bead-a",
                    "labels": ["stale"],
                    "remove": True,
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        responses={
            ("label", "remove", "bead-a", "stale"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
        }
    )

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["mutation"]["remove"] is True


def test_relabel_replay_reissues_the_tracker_call_and_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "relabel",
                    "bead_id": "bead-a",
                    "labels": ["guardrail"],
                    "remove": False,
                },
            ),
        )
    )
    _accept(store, "rec-1")
    note = _note_text("rec-1", "basis-1")
    tracker = ScriptedTrackerRunner(
        responses={
            ("label", "add", "bead-a", "guardrail"): tracker_ok(None),
            ("note", "bead-a", note): tracker_ok(None),
        }
    )

    first_exit, _first_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)
    second_exit, _second_envelope, _ = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert first_exit == 0
    assert second_exit == 0
    assert tracker.calls.count(("label", "add", "bead-a", "guardrail")) == 2


def test_dry_run_previews_relabel_with_zero_tracker_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "relabel",
                    "bead_id": "bead-a",
                    "labels": ["guardrail"],
                    "remove": False,
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 0
    preview = envelope["data"]["mutation"]
    assert preview["tracker_writes"]
    assert tracker.calls == []


# ── unrecognized mutation-plan type (exhaustiveness else-raise) ────────────


def test_apply_raises_on_an_unrecognized_mutation_plan_type_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_apply_module(), "_read_mutation", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


def test_apply_raises_on_an_unrecognized_mutation_plan_type_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_apply_module(), "_read_mutation", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["apply", "rec-1", "--dry-run"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


# ── malformed mutation payload shapes ────────────────────────────────────────


def test_apply_refuses_a_recommendation_whose_payload_has_no_mutation_key_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation=None),))
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_a_mutation_payload_that_is_not_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (_recommendation("rec-1", mutation=None, payload_extra={"mutation": "not-an-object"}),)
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_an_unrecognized_mutation_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation={"kind": "levitate"}),))
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "mint_bead", "title": "T"},
        {"kind": "add_edge", "to_bead": "b", "edge_kind": "blocks"},
        {"kind": "relabel", "labels": ["x"]},
    ],
    ids=["mint_bead-missing-noun", "add_edge-missing-from_bead", "relabel-missing-bead_id"],
)
def test_apply_refuses_a_mutation_payload_missing_a_required_field(
    mutation: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation=mutation),))
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True, "bogus": 1},
        {
            "kind": "add_edge",
            "from_bead": "a",
            "to_bead": "b",
            "edge_kind": "blocks",
            "bogus": 1,
        },
        {"kind": "relabel", "bead_id": "a", "labels": ["x"], "bogus": 1},
        {"kind": "resequence", "reason": "x", "bogus": 1},
    ],
    ids=["mint_bead-extra", "add_edge-extra", "relabel-extra", "resequence-extra"],
)
def test_apply_refuses_a_mutation_payload_with_an_unknown_extra_field(
    mutation: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_recommendation("rec-1", mutation=mutation),))
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


def test_apply_refuses_mint_bead_with_a_non_bool_orphan_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": "yes"},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_mint_bead_with_a_non_string_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "parent": 42},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_add_edge_with_an_invalid_edge_kind_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={
                    "kind": "add_edge",
                    "from_bead": "a",
                    "to_bead": "b",
                    "edge_kind": "sideways",
                },
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_relabel_with_an_empty_labels_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (_recommendation("rec-1", mutation={"kind": "relabel", "bead_id": "a", "labels": []}),)
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_relabel_with_a_non_string_labels_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1", mutation={"kind": "relabel", "bead_id": "a", "labels": ["ok", 5]}
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_relabel_with_a_non_bool_remove_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "relabel", "bead_id": "a", "labels": ["x"], "remove": "yes"},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_apply_refuses_resequence_with_a_non_string_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (_recommendation("rec-1", mutation={"kind": "resequence", "reason": 42}),)
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


# ── malformed mint-application ledger ────────────────────────────────────────


def test_apply_refuses_a_mint_application_ledger_that_is_not_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
                payload_extra={"application": "not-an-object"},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


def test_apply_refuses_a_mint_application_ledger_whose_bead_id_is_not_a_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations(
        (
            _recommendation(
                "rec-1",
                mutation={"kind": "mint_bead", "noun": "task", "title": "T", "orphan": True},
                payload_extra={"application": {"bead_id": 42}},
            ),
        )
    )
    _accept(store, "rec-1")
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["apply", "rec-1"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"
    assert tracker.calls == []


# ── CLI usage ────────────────────────────────────────────────────────────────


def test_apply_rejects_missing_positional_argument_as_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    exit_code, envelope, _stderr = run_cli(["apply"], tracker_runner=ScriptedTrackerRunner())

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_USAGE"
