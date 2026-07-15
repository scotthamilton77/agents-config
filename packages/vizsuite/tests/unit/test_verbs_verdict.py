"""`viz verdict <fact-id> <accept|reject|dismiss>` — Tier-3 verdict recording
plus accept-time edge promotion (spec §5.3/§5.7, test items 5/14/17).

Verdicts are recorded exclusively through `SidecarStore.upsert_verdict`; the
verdict write and the resolution of the fact's pending flag happen atomically
in one `store.transaction()`. Accepting an edge-class fact (one found in
`edges.json`) edge-promotes it into beads via `TrackerPort`: a `dependency`
fact tries a real `blocks` edge first, falling back to `related-to` on a
type-wall backend error; `conflict`/`overlap`/`synergy` facts always write
`related-to` directly, sidecar-authoritative on kind. The chosen bead pair is
recorded on the fact's own `payload["promotion"]` ledger entry; idempotency
checks that ledger, never re-derivation, so re-accepting an already-promoted
fact never touches the tracker again. `cycle_guard.find_cycle` runs before
every `blocks` attempt over the full accepted logical dependency graph (beads
`blocks` edges plus every other already-promoted `dependency`-kind sidecar
edge, including type-wall `related-to` fallbacks); a refusal is a typed error
with no tracker write. `--dry-run` computes the exact same decision (the
cycle-check read is allowed) but performs zero sidecar or tracker mutation.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedTrackerRunner, tracker_error, tracker_ok, tracker_show_ok
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import (
    FactRecord,
    FlagKind,
    FlagRecord,
    MatchingDescriptor,
    Verdict,
)
from vizsuite.sidecar.store import SidecarStore

_NOW = "2026-07-15T09:30:00+00:00"


def _fact(
    fact_id: str,
    *,
    kind: str = "dependency",
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = (("bead-a",), ("bead-b",)),
    payload: dict[str, Any] | None = None,
    basis_hash: str = "basis-1",
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(
            plan_pair=("plan-a", "plan-b"), kind=kind, endpoint_bead_ids=endpoint_bead_ids
        ),
        basis_hash=basis_hash,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=("spec:5.3",)
        ),
        payload=dict(payload) if payload is not None else {},
    )


def _verdict_module() -> Any:
    # String-target setattr would resolve `vizsuite.verbs.verdict` to the
    # *function* re-exported by `verbs/__init__` (the established gotcha, see
    # test_verbs_sweep.py) -- patch the submodule object directly.
    return importlib.import_module("vizsuite.verbs.verdict")


def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_verdict_module(), "datetime", _make_fixed_datetime())


def _note_text(fact_id: str, basis_hash: str) -> str:
    return f"agent-inferred-then-accepted: {_NOW} (fact {fact_id}, basis {basis_hash})"


def _promotion_tracker(
    *,
    from_bead: str = "bead-a",
    to_bead: str = "bead-b",
    edge_kind: str = "blocks",
    fact_id: str = "edge-1",
    basis_hash: str = "basis-1",
    show_results: dict[str, Any] | None = None,
    extra_responses: dict[tuple[str, ...], Any] | None = None,
) -> ScriptedTrackerRunner:
    """A `ScriptedTrackerRunner` scripted for a fresh, successful promotion:
    the `dep add` call plus both audit-note `note` calls it triggers. Requires
    `_freeze_clock` so the note text (which embeds the wall clock) is
    deterministic and matchable ahead of time -- `ScriptedTrackerRunner` only
    answers exact-argv matches, it has no generic "succeed anything" mode.
    """
    note = _note_text(fact_id, basis_hash)
    responses: dict[tuple[str, ...], Any] = {
        ("dep", "add", from_bead, to_bead, "--type", edge_kind): tracker_ok(None),
        ("note", from_bead, note): tracker_ok(None),
        ("note", to_bead, note): tracker_ok(None),
    }
    if extra_responses:
        responses.update(extra_responses)
    return ScriptedTrackerRunner(show_results=show_results or {}, responses=responses)


# ── reject: verdict recorded, no tracker touch, no promotion ────────────────


def test_reject_records_verdict_and_never_touches_the_tracker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    # A decoy fact ahead of the target in edges.json so `_locate_fact`'s scan
    # actually iterates past a non-match before finding "edge-1".
    store.write_edges((_fact("edge-0"), _fact("edge-1")))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "reject"], tracker_runner=tracker)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["verdict"] == "reject"
    assert data["fact_class"] == "edge"
    assert data["promotion"] is None
    (recorded,) = store.read_verdicts()
    assert recorded.fact_id == "edge-1"
    assert recorded.verdict == Verdict.REJECT
    assert tracker.calls == []


# ── dependency promotion rows ────────────────────────────────────────────────


def test_accept_promotes_a_dependency_fact_to_a_real_blocks_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", endpoint_bead_ids=(("bead-a",), ("bead-b",))),))
    tracker = _promotion_tracker(show_results={"bead-b": tracker_show_ok("bead-b", deps=[])})

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    promotion = envelope["data"]["promotion"]
    assert promotion == {
        "from_bead": "bead-a",
        "to_bead": "bead-b",
        "tracker_edge_kind": "blocks",
        "already_promoted": False,
        "orphaned": False,
    }
    assert ("dep", "add", "bead-a", "bead-b", "--type", "blocks") in tracker.calls
    note_calls = {call[1]: call[2] for call in tracker.calls if call[0] == "note"}
    assert note_calls == {
        "bead-a": _note_text("edge-1", "basis-1"),
        "bead-b": _note_text("edge-1", "basis-1"),
    }
    (updated,) = store.read_edges()
    assert updated.payload["promotion"] == {
        "from_bead": "bead-a",
        "to_bead": "bead-b",
        "tracker_edge_kind": "blocks",
    }


def test_accept_dependency_fact_falls_back_to_related_to_on_a_type_wall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", endpoint_bead_ids=(("epic-a",), ("task-b",))),))
    tracker = _promotion_tracker(
        from_bead="epic-a",
        to_bead="task-b",
        edge_kind="related-to",
        show_results={"task-b": tracker_show_ok("task-b", deps=[])},
        extra_responses={
            ("dep", "add", "epic-a", "task-b", "--type", "blocks"): tracker_error(
                "E_TYPE_WALL", "blocks: epic may not block task"
            ),
        },
    )

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    promotion = envelope["data"]["promotion"]
    assert promotion["tracker_edge_kind"] == "related-to"
    assert ("dep", "add", "epic-a", "task-b", "--type", "blocks") in tracker.calls
    assert ("dep", "add", "epic-a", "task-b", "--type", "related-to") in tracker.calls
    (updated,) = store.read_edges()
    assert updated.payload["promotion"]["tracker_edge_kind"] == "related-to"
    # sidecar stays authoritative: the fact's own kind is still "dependency"
    assert updated.matching_descriptor.kind == "dependency"


def test_accept_propagates_a_non_type_wall_backend_error_without_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner(
        show_results={"bead-b": tracker_show_ok("bead-b", deps=[])},
        responses={
            ("dep", "add", "bead-a", "bead-b", "--type", "blocks"): tracker_error(
                "E_SOME_OTHER_ERROR", "boom"
            ),
        },
    )

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_TRACKER_BACKEND_ERROR"
    assert not any(call[-1] == "related-to" for call in tracker.calls if call[0] == "dep")
    assert store.read_verdicts() == ()


# ── conflict/overlap/synergy: related-to directly, no cycle check ──────────


@pytest.mark.parametrize("kind", ["conflict", "overlap", "synergy"])
def test_accept_discoverability_fact_writes_related_to_without_a_cycle_check(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", kind=kind),))
    # No show_results scripted at all -- a cycle-check read would raise.
    tracker = _promotion_tracker(edge_kind="related-to")

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["promotion"]["tracker_edge_kind"] == "related-to"
    assert not any(call[0] == "show" for call in tracker.calls)


def test_accept_raises_on_an_unrecognized_edge_fact_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", kind="mystery"),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "_UnrecognizedEdgeFactKindError" in stderr


# ── idempotency ──────────────────────────────────────────────────────────────


def test_accept_is_idempotent_no_duplicate_tracker_writes_on_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = _promotion_tracker(show_results={"bead-b": tracker_show_ok("bead-b", deps=[])})

    first_exit, first_envelope, _ = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)
    calls_after_first = list(tracker.calls)
    second_exit, second_envelope, _ = run_cli(
        ["verdict", "edge-1", "accept"], tracker_runner=tracker
    )

    assert first_exit == 0
    assert second_exit == 0
    assert first_envelope["data"]["promotion"]["already_promoted"] is False
    assert second_envelope["data"]["promotion"]["already_promoted"] is True
    assert second_envelope["data"]["promotion"]["orphaned"] is False
    assert tracker.calls == calls_after_first  # zero new tracker calls on replay


# ── cycle refusal ────────────────────────────────────────────────────────────


def test_accept_refuses_a_dependency_edge_that_would_close_a_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", endpoint_bead_ids=(("a",), ("b",))),))
    tracker = ScriptedTrackerRunner(
        show_results={"b": tracker_show_ok("b", deps=[("a", "blocks", "open")])}
    )

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_VERDICT_CYCLE_REFUSAL"
    assert envelope["error"]["detail"]["cycle"] == ["a", "b", "a"]
    assert not any(call[0] == "dep" for call in tracker.calls)
    assert store.read_verdicts() == ()


def test_accept_raises_on_an_unrecognized_cycle_check_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_verdict_module(), "find_cycle", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


def test_accept_cycle_check_gathers_other_promoted_dependency_edges_and_skips_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The cycle check's sidecar-edge input (spec §5.3/§5.7) is every OTHER
    # already-promoted `dependency`-kind fact -- a `conflict`-kind fact never
    # counts (it carries no logical dependency) and an unpromoted dependency
    # fact contributes nothing yet.
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    already_promoted = _fact(
        "edge-2",
        endpoint_bead_ids=(("x",), ("y",)),
        payload={"promotion": {"from_bead": "x", "to_bead": "y", "tracker_edge_kind": "blocks"}},
    )
    unrelated_conflict = _fact("edge-3", kind="conflict", endpoint_bead_ids=(("p",), ("q",)))
    target = _fact("edge-1", endpoint_bead_ids=(("a",), ("b",)))
    store.write_edges((already_promoted, unrelated_conflict, target))
    tracker = _promotion_tracker(
        from_bead="a",
        to_bead="b",
        show_results={"b": tracker_show_ok("b", deps=[])},
    )

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["promotion"]["tracker_edge_kind"] == "blocks"


# ── dismiss gating ───────────────────────────────────────────────────────────


def test_dismiss_succeeds_for_a_recommendation_class_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    # A decoy fact ahead of the target in recommendations.json so
    # `_locate_fact`'s scan actually iterates past a non-match.
    store.write_recommendations(
        (_fact("rec-0", kind="guardrail"), _fact("rec-1", kind="guardrail"))
    )
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "rec-1", "dismiss"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["fact_class"] == "recommendation"
    (recorded,) = store.read_verdicts()
    assert recorded.verdict == Verdict.DISMISS


@pytest.mark.parametrize("write_to", ["edges", "steps"])
def test_dismiss_is_refused_for_a_non_recommendation_class_fact(
    write_to: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    fact = _fact("some-fact")
    getattr(store, f"write_{write_to}")((fact,))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(
        ["verdict", "some-fact", "dismiss"], tracker_runner=tracker
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_VERDICT_DISMISS_NOT_RECOMMENDATION"
    assert store.read_verdicts() == ()
    assert tracker.calls == []


# ── not found ────────────────────────────────────────────────────────────────


def test_unknown_fact_id_is_a_typed_not_found_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "ghost", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_NOT_FOUND"


# ── non-edge classes: verdict recorded, no promotion attempted ─────────────


def test_accept_on_a_step_class_fact_records_verdict_without_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    # A decoy fact ahead of the target in steps.json so `_locate_fact`'s scan
    # actually iterates past a non-match.
    store.write_steps((_fact("step-0", kind="waypoint"), _fact("step-1", kind="waypoint")))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "step-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["fact_class"] == "step"
    assert envelope["data"]["promotion"] is None
    assert tracker.calls == []


def test_accept_on_a_recommendation_class_fact_records_verdict_without_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_recommendations((_fact("rec-1", kind="dependency"),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "rec-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert envelope["data"]["fact_class"] == "recommendation"
    assert envelope["data"]["promotion"] is None
    assert tracker.calls == []


# ── no bead anchor ───────────────────────────────────────────────────────────


def test_accept_raises_a_typed_error_when_the_edge_has_no_bead_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", endpoint_bead_ids=()),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_VERDICT_NO_BEAD_ANCHOR"
    assert tracker.calls == []


# ── malformed ledger ─────────────────────────────────────────────────────────


def test_accept_raises_sidecar_malformed_on_a_corrupt_promotion_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", payload={"promotion": "not-an-object"}),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


def test_accept_raises_sidecar_malformed_when_a_ledger_field_is_not_a_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges(
        (
            _fact(
                "edge-1",
                payload={
                    "promotion": {
                        "from_bead": "bead-a",
                        "to_bead": "bead-b",
                        "tracker_edge_kind": 42,  # must be a string
                    }
                },
            ),
        )
    )
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_MALFORMED"


# ── orphaned edge promotion ──────────────────────────────────────────────────


def test_reaccept_raises_an_orphan_flag_when_resynthesis_moved_the_bead_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    ledger_payload = {
        "promotion": {"from_bead": "bead-a", "to_bead": "bead-b", "tracker_edge_kind": "blocks"}
    }
    # The recorded pair (bead-a/bead-b) no longer resolves within the fact's
    # current anchor sets (bead-c/bead-d) -- as if re-synthesis moved them.
    resynthesized = _fact(
        "edge-1", endpoint_bead_ids=(("bead-c",), ("bead-d",)), payload=ledger_payload
    )
    store.write_edges((resynthesized,))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    promotion = envelope["data"]["promotion"]
    assert promotion["already_promoted"] is True
    assert promotion["orphaned"] is True
    (flag,) = store.read_flags()
    assert flag.kind == FlagKind.ORPHANED_EDGE_PROMOTION
    assert flag.fact_id == "edge-1"
    assert tracker.calls == []  # idempotent -- no tracker call at all


def test_reaccept_is_orphaned_when_resynthesis_collapsed_the_anchor_arity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Re-synthesis can also collapse a fact down to zero bead anchors (a plan
    # gone prose-only) rather than merely swapping which beads it names --
    # that is orphaned too, checked structurally before any membership test.
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    ledger_payload = {
        "promotion": {"from_bead": "bead-a", "to_bead": "bead-b", "tracker_edge_kind": "blocks"}
    }
    resynthesized = _fact("edge-1", endpoint_bead_ids=(), payload=ledger_payload)
    store.write_edges((resynthesized,))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    promotion = envelope["data"]["promotion"]
    assert promotion["already_promoted"] is True
    assert promotion["orphaned"] is True
    assert tracker.calls == []


def test_reaccepting_the_same_orphan_never_duplicates_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    ledger_payload = {
        "promotion": {"from_bead": "bead-a", "to_bead": "bead-b", "tracker_edge_kind": "blocks"}
    }
    resynthesized = _fact(
        "edge-1", endpoint_bead_ids=(("bead-c",), ("bead-d",)), payload=ledger_payload
    )
    store.write_edges((resynthesized,))
    tracker = ScriptedTrackerRunner()

    run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)
    run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert len(store.read_flags()) == 1


# ── flags.json resolution ───────────────────────────────────────────────────


def test_verdict_resolves_a_pending_doubt_flag_for_the_same_fact_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", kind="conflict"),))
    store.write_flags(
        (FlagRecord(flag_id="flag-1", fact_id="edge-1", kind=FlagKind.DOUBT, reason="churned"),)
    )
    tracker = _promotion_tracker(edge_kind="related-to")

    exit_code, _envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert store.read_flags() == ()


def test_verdict_preserves_unrelated_flags_for_other_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    _freeze_clock(monkeypatch)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1", kind="conflict"), _fact("edge-2", kind="conflict")))
    unrelated = FlagRecord(flag_id="flag-2", fact_id="edge-2", kind=FlagKind.DOUBT, reason="x")
    store.write_flags(
        (
            FlagRecord(flag_id="flag-1", fact_id="edge-1", kind=FlagKind.DOUBT, reason="churned"),
            unrelated,
        )
    )
    tracker = _promotion_tracker(edge_kind="related-to")

    exit_code, _envelope, _stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 0
    assert store.read_flags() == (unrelated,)


# ── dry-run ──────────────────────────────────────────────────────────────────


def test_dry_run_previews_a_fresh_dependency_promotion_with_zero_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner(show_results={"bead-b": tracker_show_ok("bead-b", deps=[])})

    exit_code, envelope, _stderr = run_cli(
        ["verdict", "edge-1", "accept", "--dry-run"], tracker_runner=tracker
    )

    assert exit_code == 0
    data = envelope["data"]
    assert data["dry_run"] is True
    preview = data["promotion"]
    assert preview["from_bead"] == "bead-a"
    assert preview["to_bead"] == "bead-b"
    assert preview["already_promoted"] is False
    assert preview["tracker_writes"]  # non-empty: the exact writes that would happen
    assert any(call[0] == "show" for call in tracker.calls)  # cycle-check read allowed
    assert not any(call[0] == "dep" for call in tracker.calls)
    assert not any(call[0] == "note" for call in tracker.calls)
    assert store.read_verdicts() == ()
    assert store.read_edges() == (_fact("edge-1"),)  # byte-for-byte unchanged


def test_dry_run_on_reject_reports_no_promotion_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(
        ["verdict", "edge-1", "reject", "--dry-run"], tracker_runner=tracker
    )

    assert exit_code == 0
    assert envelope["data"]["promotion"] is None
    assert store.read_verdicts() == ()
    assert tracker.calls == []


def test_dry_run_previews_an_orphaned_already_promoted_edge_without_writing_a_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    ledger_payload = {
        "promotion": {"from_bead": "bead-a", "to_bead": "bead-b", "tracker_edge_kind": "blocks"}
    }
    resynthesized = _fact(
        "edge-1", endpoint_bead_ids=(("bead-c",), ("bead-d",)), payload=ledger_payload
    )
    store.write_edges((resynthesized,))
    tracker = ScriptedTrackerRunner()

    exit_code, envelope, _stderr = run_cli(
        ["verdict", "edge-1", "accept", "--dry-run"], tracker_runner=tracker
    )

    assert exit_code == 0
    preview = envelope["data"]["promotion"]
    assert preview["already_promoted"] is True
    assert preview["orphaned"] is True
    assert preview["tracker_writes"] == []
    assert store.read_flags() == ()
    assert tracker.calls == []


def test_dry_run_never_enters_a_sidecar_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    setup_store = SidecarStore(tmp_path)
    setup_store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner(show_results={"bead-b": tracker_show_ok("bead-b", deps=[])})

    def _explode(_self: SidecarStore) -> None:
        raise AssertionError("dry-run must never acquire the sidecar transaction lock")

    monkeypatch.setattr(SidecarStore, "transaction", _explode)

    exit_code, _envelope, _stderr = run_cli(
        ["verdict", "edge-1", "accept", "--dry-run"], tracker_runner=tracker
    )

    assert exit_code == 0


def test_accept_raises_on_an_unrecognized_promotion_decision_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_verdict_module(), "_decide_edge_promotion", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(["verdict", "edge-1", "accept"], tracker_runner=tracker)

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


def test_dry_run_raises_on_an_unrecognized_promotion_decision_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    tracker = ScriptedTrackerRunner()
    monkeypatch.setattr(_verdict_module(), "_decide_edge_promotion", lambda *_a, **_kw: object())

    exit_code, envelope, stderr = run_cli(
        ["verdict", "edge-1", "accept", "--dry-run"], tracker_runner=tracker
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert "TypeError" in stderr


# ── CLI usage ────────────────────────────────────────────────────────────────


def test_verdict_rejects_an_unknown_verdict_value_as_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    exit_code, envelope, _stderr = run_cli(
        ["verdict", "edge-1", "bogus"], tracker_runner=ScriptedTrackerRunner()
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_USAGE"


def _make_fixed_datetime() -> Any:
    from datetime import UTC, datetime

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # noqa: ARG003 - mirrors datetime.now's signature
            return datetime(2026, 7, 15, 9, 30, tzinfo=UTC)

    return _FixedDatetime
