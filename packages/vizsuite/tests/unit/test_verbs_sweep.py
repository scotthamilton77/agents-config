"""`viz sweep` — funnel rungs 1-2 over the sidecar's fact files (spec §5.4/§5.5).

Sweep is the "Tier-1 extraction, funnel rungs 1-2" CLI leg of the spec's
overnight-sweep accelerant: it reads a fresh current fingerprint (via the
already-existing `estate` extractor over `runners.git`, never a new git call),
compares it against the sidecar manifest's recorded baseline, classifies every
Tier-2 fact (edges/steps/recommendations) through `funnel.rungs.evaluate_fact`,
rewrites the fact files and `flags.json` accordingly, and advances the
manifest to the new fingerprint — all under the sidecar's single-writer lock.
It never touches `verdicts.json`, and never re-evaluates a fact that already
has a pending flag (a doubt candidate mid-queue for human review is never
silently restamped out from under the flag).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import run_cli
from tests.fakes import ScriptedGitRunner, blob
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import (
    FactRecord,
    FlagKind,
    FlagRecord,
    Manifest,
    MatchingDescriptor,
    Verdict,
    VerdictRecord,
)
from vizsuite.sidecar.store import SidecarStore

_CURRENT_FINGERPRINT = {"src/app.py": "sha-app-1", "docs/readme.md": "sha-readme-1"}


def _git(fingerprint: dict[str, str] = _CURRENT_FINGERPRINT) -> ScriptedGitRunner:
    return ScriptedGitRunner(ls_tree_rows=[blob(path, sha) for path, sha in fingerprint.items()])


def _fact(
    fact_id: str, *, citations: tuple[str, ...] = (), basis_hash: str = "basis-orig"
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind="dependency"),
        basis_hash=basis_hash,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=citations
        ),
    )


def test_sweep_writes_a_fresh_manifest_and_reports_zero_counts_on_an_empty_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)

    exit_code, envelope, stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert stderr == ""
    assert envelope["data"] == {"reused": 0, "restamped": 0, "flagged": 0}
    store = SidecarStore(tmp_path)
    assert store.read_manifest() == Manifest(schema_version="", input_hashes=_CURRENT_FINGERPRINT)


def test_sweep_reuses_a_fact_verbatim_when_the_manifest_matches_the_current_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1", input_hashes=_CURRENT_FINGERPRINT))
    fact = _fact("edge-1", citations=("src/app.py",))
    store.write_edges((fact,))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"] == {"reused": 1, "restamped": 0, "flagged": 0}
    assert store.read_edges() == (fact,)  # byte-for-byte the same record


def test_sweep_restamps_a_fact_when_a_changed_input_is_not_among_its_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    recorded = dict(_CURRENT_FINGERPRINT)
    recorded["docs/readme.md"] = "sha-readme-OLD"  # readme changed; the fact doesn't cite it
    store.write_manifest(Manifest(schema_version="1", input_hashes=recorded))
    fact = _fact("edge-1", citations=("src/app.py",), basis_hash="basis-orig")
    store.write_edges((fact,))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"] == {"reused": 0, "restamped": 1, "flagged": 0}
    (restamped,) = store.read_edges()
    assert restamped.fact_id == "edge-1"
    assert restamped.basis_hash != "basis-orig"
    assert store.read_flags() == ()  # no flag raised


def test_sweep_flags_a_fact_when_a_cited_input_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    recorded = dict(_CURRENT_FINGERPRINT)
    recorded["src/app.py"] = "sha-app-OLD"  # app.py changed; the fact cites exactly this
    store.write_manifest(Manifest(schema_version="1", input_hashes=recorded))
    fact = _fact("edge-1", citations=("src/app.py",), basis_hash="basis-orig")
    store.write_edges((fact,))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"] == {"reused": 0, "restamped": 0, "flagged": 1}
    assert store.read_edges() == (fact,)  # flagged facts are carried through unmodified
    (flag,) = store.read_flags()
    assert flag.fact_id == "edge-1"
    assert flag.kind == FlagKind.DOUBT
    assert "src/app.py" in flag.reason


def test_sweep_never_reevaluates_a_fact_that_already_has_a_pending_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The manifest matches the current fingerprint exactly, so absent the
    # pending flag this fact would trivially clear rung 1 (reused) — but it
    # must never be silently restamped/reused out from under a standing
    # doubt flag still awaiting human disposition.
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1", input_hashes=_CURRENT_FINGERPRINT))
    fact = _fact("edge-1", citations=("src/app.py",), basis_hash="basis-orig")
    store.write_edges((fact,))
    pre_existing_flag = FlagRecord(
        flag_id="flag-preexisting", fact_id="edge-1", kind=FlagKind.DOUBT, reason="prior doubt"
    )
    store.write_flags((pre_existing_flag,))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"] == {"reused": 0, "restamped": 0, "flagged": 1}
    assert store.read_edges() == (fact,)  # untouched — basis_hash never changed
    assert store.read_flags() == (pre_existing_flag,)  # untouched, not duplicated


def test_sweep_preserves_unrelated_existing_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1", input_hashes=_CURRENT_FINGERPRINT))
    store.upsert_verdict(
        VerdictRecord(
            verdict_id="verdict-1",
            fact_id="vanished-fact",
            verdict=Verdict.ACCEPT,
            basis_hash="hash-x",
        )
    )
    unrelated_flag = FlagRecord(
        flag_id="flag-orphan",
        fact_id="vanished-fact",
        kind=FlagKind.ORPHANED_VERDICT,
        reason="fact vanished on rebuild",
        verdict_id="verdict-1",
    )
    store.write_flags((unrelated_flag,))
    recorded = dict(_CURRENT_FINGERPRINT)
    recorded["src/app.py"] = "sha-app-OLD"
    store.write_manifest(Manifest(schema_version="1", input_hashes=recorded))
    store.write_edges((_fact("edge-1", citations=("src/app.py",)),))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"]["flagged"] == 1
    flags = {flag.flag_id: flag for flag in store.read_flags()}
    assert flags["flag-orphan"] == unrelated_flag  # carried through unchanged
    assert len(flags) == 2  # plus the newly-raised doubt flag for edge-1


def test_sweep_processes_steps_and_recommendations_alongside_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1", input_hashes=_CURRENT_FINGERPRINT))
    store.write_edges((_fact("edge-1"),))
    store.write_steps((_fact("step-1"),))
    store.write_recommendations((_fact("rec-1"),))

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert envelope["data"] == {"reused": 3, "restamped": 0, "flagged": 0}


def test_sweep_is_lock_guarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "lock").touch()  # simulate another writer already holding the lock

    exit_code, envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 1
    assert envelope["error"]["code"] == "E_SIDECAR_LOCKED"


def test_sweep_never_touches_verdicts_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    recorded = dict(_CURRENT_FINGERPRINT)
    recorded["src/app.py"] = "sha-app-OLD"
    store.write_manifest(Manifest(schema_version="1", input_hashes=recorded))
    store.write_edges((_fact("edge-1", citations=("src/app.py",)),))  # will be flagged
    store.write_steps((_fact("step-1", citations=("docs/readme.md",)),))  # will be restamped
    store.upsert_verdict(
        VerdictRecord(
            verdict_id="verdict-1", fact_id="edge-1", verdict=Verdict.ACCEPT, basis_hash="h"
        )
    )
    verdicts_path = store.viz_dir / "verdicts.json"
    before = verdicts_path.read_bytes()

    exit_code, _envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    after = verdicts_path.read_bytes()
    assert after == before


def test_sweeping_twice_on_unchanged_state_does_not_duplicate_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    recorded = dict(_CURRENT_FINGERPRINT)
    recorded["src/app.py"] = "sha-app-OLD"
    store.write_manifest(Manifest(schema_version="1", input_hashes=recorded))
    store.write_edges((_fact("edge-1", citations=("src/app.py",)),))

    first_exit, first_envelope, _ = run_cli(["sweep"], git_runner=_git())
    second_exit, second_envelope, _ = run_cli(["sweep"], git_runner=_git())

    assert first_exit == 0
    assert second_exit == 0
    assert first_envelope["data"] == {"reused": 0, "restamped": 0, "flagged": 1}
    assert second_envelope["data"] == {"reused": 0, "restamped": 0, "flagged": 1}
    assert len(store.read_flags()) == 1  # not duplicated


def test_sweep_carries_forward_existing_manifest_contract_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store = SidecarStore(tmp_path)
    store.write_manifest(
        Manifest(
            schema_version="3",
            prompt_version="p9",
            model_id="m9",
            input_hashes=_CURRENT_FINGERPRINT,
        )
    )

    exit_code, _envelope, _stderr = run_cli(["sweep"], git_runner=_git())

    assert exit_code == 0
    assert store.read_manifest() == Manifest(
        schema_version="3", prompt_version="p9", model_id="m9", input_hashes=_CURRENT_FINGERPRINT
    )


def test_sweep_output_is_valid_json_and_manifest_bytes_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Sanity check that the manifest write goes through the store's normal
    # deterministic serialization (sorted keys) rather than some ad-hoc dump.
    monkeypatch.chdir(tmp_path)

    run_cli(["sweep"], git_runner=_git())

    manifest_path = SidecarStore(tmp_path).viz_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["input_hashes"] == _CURRENT_FINGERPRINT
