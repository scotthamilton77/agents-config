"""`viz queue` — the reassessment queue read path (spec §5.3/§5.4 rung 4).

`viz queue` is exactly the unresolved flags in `flags.json`, joined to their
facts (across `edges.json`/`steps.json`/`recommendations.json`) and, for
`orphaned_verdict` flags, their verdict — a pure read path with no writes.
Every flag currently on disk *is* the unresolved set: `viz verdict` (a later
slice) resolves a flag by removing it from `flags.json`, so there is no
separate "resolved" marker to filter on here.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from tests.conftest import run_cli
from vizsuite.adapters.git.runner import LsTreeRow
from vizsuite.runners import Runners
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import (
    FactRecord,
    FlagKind,
    FlagRecord,
    MatchingDescriptor,
    Verdict,
    VerdictRecord,
)
from vizsuite.sidecar.store import SidecarStore
from vizsuite.verbs.queue import queue


class _ExplodingGitRunner:
    """Proves `viz queue` never touches git — a pure sidecar read path."""

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        raise AssertionError(f"queue must never call git, got rev={rev!r}")


def _fact(fact_id: str, *, kind: str = "dependency") -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind=kind),
        basis_hash=f"hash-{fact_id}",
        provenance=Provenance(kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH),
    )


def test_queue_is_empty_when_no_flags_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    exit_code, envelope, stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    assert stderr == ""
    assert envelope["data"] == {"count": 0, "entries": []}


def test_queue_joins_a_doubt_flag_to_its_fact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    store.write_flags(
        (FlagRecord(flag_id="flag-1", fact_id="edge-1", kind=FlagKind.DOUBT, reason="churned"),)
    )

    exit_code, envelope, _stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["count"] == 1
    entry = data["entries"][0]
    assert entry["flag"]["flag_id"] == "flag-1"
    assert entry["fact"]["fact_id"] == "edge-1"
    assert entry["verdict"] is None


def test_queue_joins_an_orphaned_verdict_flag_to_its_fact_and_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    store.upsert_verdict(
        VerdictRecord(
            verdict_id="verdict-1", fact_id="edge-1", verdict=Verdict.ACCEPT, basis_hash="hash-old"
        )
    )
    store.write_flags(
        (
            FlagRecord(
                flag_id="flag-1",
                fact_id="edge-1",
                kind=FlagKind.ORPHANED_VERDICT,
                reason="fact vanished on rebuild",
                verdict_id="verdict-1",
            ),
        )
    )

    exit_code, envelope, _stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    entry = data["entries"][0]
    assert entry["fact"]["fact_id"] == "edge-1"
    assert entry["verdict"]["verdict_id"] == "verdict-1"


def test_queue_entry_fact_and_verdict_are_none_when_referenced_records_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    # A flag surviving a rebuild that dropped its fact/verdict entirely — the
    # join degrades gracefully instead of crashing.
    store.write_flags(
        (
            FlagRecord(
                flag_id="flag-1",
                fact_id="missing-fact",
                kind=FlagKind.ORPHANED_VERDICT,
                reason="fact and verdict both gone",
                verdict_id="missing-verdict",
            ),
        )
    )

    exit_code, envelope, _stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    entry = data["entries"][0]
    assert entry["fact"] is None
    assert entry["verdict"] is None


def test_queue_resolves_facts_stored_in_steps_and_recommendations_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_steps((_fact("step-1", kind="waypoint"),))
    store.write_recommendations((_fact("rec-1", kind="dependency"),))
    store.write_flags(
        (
            FlagRecord(flag_id="flag-1", fact_id="step-1", kind=FlagKind.DOUBT, reason="a"),
            FlagRecord(flag_id="flag-2", fact_id="rec-1", kind=FlagKind.DOUBT, reason="b"),
        )
    )

    exit_code, envelope, _stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert data["count"] == 2
    fact_ids = {entry["fact"]["fact_id"] for entry in data["entries"]}
    assert fact_ids == {"step-1", "rec-1"}


def test_queue_reads_under_explicit_repo_root_without_chdir(tmp_path: Path) -> None:
    """`queue` takes `repo_root` as an explicit third argument -- its sidecar
    store must resolve from that argument alone. Never chdir'd here: if `queue`
    fell back to `Path.cwd()` internally it would read the real process cwd's
    (nonexistent) `.viz/`, not `tmp_path`, and see zero entries instead of one.
    """
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"),))
    store.write_flags(
        (FlagRecord(flag_id="flag-1", fact_id="edge-1", kind=FlagKind.DOUBT, reason="churned"),)
    )
    runners = Runners(git=_ExplodingGitRunner(), gh=None, scc=None, tracker=None)  # type: ignore[arg-type]

    data = queue(runners, Namespace(), tmp_path)

    assert isinstance(data, dict)
    assert data["count"] == 1


def test_queue_entries_are_sorted_by_flag_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"), _fact("edge-2")))
    store.write_flags(
        (
            FlagRecord(flag_id="flag-b", fact_id="edge-2", kind=FlagKind.DOUBT, reason="b"),
            FlagRecord(flag_id="flag-a", fact_id="edge-1", kind=FlagKind.DOUBT, reason="a"),
        )
    )

    exit_code, envelope, _stderr = run_cli(["queue"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert [entry["flag"]["flag_id"] for entry in data["entries"]] == ["flag-a", "flag-b"]
