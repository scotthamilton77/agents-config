"""`.viz/` sidecar store: read/write, locking, atomic writes, and the Tier
discipline in the API shape itself (spec §5.3, test items 16).

No live process/thread races beyond what's needed to prove the lock actually
serializes writers; every test drives `SidecarStore` directly against a
`tmp_path` root — the store never assumes a module-global cwd (root is always
injected).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from vizsuite.envelope import ErrorCode, VizError
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

_PROVENANCE = Provenance(
    kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=("spec:5.2",)
)


def _fact(fact_id: str, *, kind: str = "dependency") -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind=kind),
        basis_hash=f"hash-{fact_id}",
        provenance=_PROVENANCE,
    )


def _verdict(verdict_id: str, fact_id: str, *, annotation: str = "") -> VerdictRecord:
    return VerdictRecord(
        verdict_id=verdict_id,
        fact_id=fact_id,
        verdict=Verdict.ACCEPT,
        basis_hash=f"hash-{fact_id}",
        annotation=annotation,
    )


# ---- manifest + the five record files: round-trip with validation ---------


def test_read_manifest_returns_none_when_absent(tmp_path: Path):
    store = SidecarStore(tmp_path)

    assert store.read_manifest() is None


def test_manifest_round_trips_through_the_store(tmp_path: Path):
    store = SidecarStore(tmp_path)
    manifest = Manifest(schema_version="1", prompt_version="p1", model_id="m1")

    store.write_manifest(manifest)

    assert store.read_manifest() == manifest


@pytest.mark.parametrize(
    ("write_method", "read_method", "records"),
    [
        ("write_edges", "read_edges", (_fact("edge-1"), _fact("edge-2", kind="conflict"))),
        ("write_steps", "read_steps", (_fact("step-1"),)),
        ("write_recommendations", "read_recommendations", (_fact("rec-1"),)),
    ],
)
def test_fact_record_files_round_trip_and_default_empty(
    tmp_path: Path, write_method: str, read_method: str, records: tuple[FactRecord, ...]
):
    store = SidecarStore(tmp_path)

    assert getattr(store, read_method)() == ()

    getattr(store, write_method)(records)

    assert getattr(store, read_method)() == records


def test_flags_round_trip_and_default_empty(tmp_path: Path):
    store = SidecarStore(tmp_path)
    flags = (
        FlagRecord(flag_id="flag-1", fact_id="edge-1", kind=FlagKind.DOUBT, reason="churned"),
        FlagRecord(
            flag_id="flag-2",
            fact_id="edge-2",
            kind=FlagKind.ORPHANED_VERDICT,
            reason="vanished",
            verdict_id="verdict-1",
        ),
    )

    assert store.read_flags() == ()

    store.write_flags(flags)

    assert store.read_flags() == flags


def test_fact_record_files_rewrite_wholesale_and_drop_omitted_records(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.write_edges((_fact("edge-1"), _fact("edge-2")))

    store.write_edges((_fact("edge-3"),))

    assert store.read_edges() == (_fact("edge-3"),)


# ---- deterministic serialization: byte-stable rewrites ---------------------


def test_rewriting_unchanged_content_is_byte_stable(tmp_path: Path):
    store = SidecarStore(tmp_path)
    records = (_fact("edge-2"), _fact("edge-1"))  # deliberately unsorted input

    store.write_edges(records)
    first_bytes = (store.viz_dir / "edges.json").read_bytes()

    store.write_edges(records)
    second_bytes = (store.viz_dir / "edges.json").read_bytes()

    assert first_bytes == second_bytes
    # sorted by fact_id, not insertion order — proves the store sorts, not the caller.
    assert [entry["fact_id"] for entry in json.loads(first_bytes)] == ["edge-1", "edge-2"]


def test_manifest_write_is_byte_stable_across_rewrites(tmp_path: Path):
    store = SidecarStore(tmp_path)
    manifest = Manifest(schema_version="1", input_hashes={"b": "2", "a": "1"})

    store.write_manifest(manifest)
    first_bytes = (store.viz_dir / "manifest.json").read_bytes()
    store.write_manifest(manifest)
    second_bytes = (store.viz_dir / "manifest.json").read_bytes()

    assert first_bytes == second_bytes


# ---- malformed sidecar content: typed error, never a raw parse exception ---


def test_read_edges_on_invalid_json_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "edges.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(VizError) as exc_info:
        store.read_edges()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


def test_read_edges_on_wrong_shape_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    # a JSON object where an array of records is expected.
    (store.viz_dir / "edges.json").write_text(json.dumps({"oops": True}), encoding="utf-8")

    with pytest.raises(VizError) as exc_info:
        store.read_edges()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


def test_read_edges_on_record_missing_field_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "edges.json").write_text(json.dumps([{"fact_id": "x"}]), encoding="utf-8")

    with pytest.raises(VizError) as exc_info:
        store.read_edges()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


def test_read_manifest_on_invalid_json_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "manifest.json").write_text("not json at all", encoding="utf-8")

    with pytest.raises(VizError) as exc_info:
        store.read_manifest()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


def test_read_manifest_on_valid_json_wrong_shape_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    # valid JSON, but missing the required `schema_version` key.
    (store.viz_dir / "manifest.json").write_text(
        json.dumps({"prompt_version": "p1"}), encoding="utf-8"
    )

    with pytest.raises(VizError) as exc_info:
        store.read_manifest()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


def test_read_verdicts_on_malformed_content_raises_typed_error(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "verdicts.json").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(VizError) as exc_info:
        store.read_verdicts()
    assert exc_info.value.code == ErrorCode.SIDECAR_MALFORMED


# ---- gitignore bootstrap: lock (and by extension out/) never committed ----


def test_write_ensures_lock_is_gitignored(tmp_path: Path):
    store = SidecarStore(tmp_path)

    store.write_manifest(Manifest(schema_version="1"))

    lines = (store.viz_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "lock" in lines


def test_write_preserves_existing_gitignore_content(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / ".gitignore").write_text("out/\n", encoding="utf-8")

    store.write_manifest(Manifest(schema_version="1"))

    lines = (store.viz_dir / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines == ["out/", "lock"]


# ---- Tier discipline in the API shape: no wholesale verdicts.json rewrite --


def test_store_exposes_no_wholesale_verdict_rewrite_api():
    assert not hasattr(SidecarStore, "write_verdicts")
    assert hasattr(SidecarStore, "upsert_verdict")


def test_upsert_verdict_appends_a_new_verdict(tmp_path: Path):
    store = SidecarStore(tmp_path)

    store.upsert_verdict(_verdict("verdict-1", "edge-1"))

    assert store.read_verdicts() == (_verdict("verdict-1", "edge-1"),)


def test_upsert_verdict_updates_in_place_and_preserves_unrelated_verdicts(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.upsert_verdict(_verdict("verdict-1", "edge-1", annotation="first"))
    store.upsert_verdict(_verdict("verdict-2", "edge-2", annotation="unrelated"))

    store.upsert_verdict(_verdict("verdict-1", "edge-1", annotation="revised"))

    verdicts = {record.verdict_id: record for record in store.read_verdicts()}
    assert len(verdicts) == 2
    assert verdicts["verdict-1"].annotation == "revised"
    assert verdicts["verdict-2"].annotation == "unrelated"  # untouched by the update


# ---- locking + atomic writes -----------------------------------------------


def test_lock_contention_raises_typed_error_after_bounded_retry(tmp_path: Path):
    store = SidecarStore(tmp_path, lock_timeout=0.05, lock_poll_interval=0.01)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "lock").touch()  # simulate another writer already holding the lock

    with pytest.raises(VizError) as exc_info:
        store.write_manifest(Manifest(schema_version="1"))
    assert exc_info.value.code == ErrorCode.SIDECAR_LOCKED


def test_failed_lock_acquisition_writes_no_gitignore(tmp_path: Path):
    store = SidecarStore(tmp_path, lock_timeout=0.05, lock_poll_interval=0.01)
    store.viz_dir.mkdir(parents=True)
    (store.viz_dir / "lock").touch()  # another writer already holds the lock

    with pytest.raises(VizError) as exc_info:
        store.write_manifest(Manifest(schema_version="1"))

    assert exc_info.value.code == ErrorCode.SIDECAR_LOCKED
    # The `.gitignore` rewrite is deferred until the lock is held, so a failed
    # acquisition leaves the working tree untouched.
    assert not (store.viz_dir / ".gitignore").exists()


def test_lock_is_released_after_a_successful_write(tmp_path: Path):
    store = SidecarStore(tmp_path)

    store.write_manifest(Manifest(schema_version="1"))

    assert not (store.viz_dir / "lock").exists()


def test_lock_is_released_after_a_failed_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = SidecarStore(tmp_path)

    def _boom(_self: Path, _target: Path) -> Path:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(Path, "replace", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        store.write_manifest(Manifest(schema_version="1"))

    monkeypatch.undo()
    assert not (store.viz_dir / "lock").exists()
    # the lock is usable again for the next write.
    store.write_manifest(Manifest(schema_version="2"))
    assert store.read_manifest() == Manifest(schema_version="2")


def test_crash_before_rename_leaves_canonical_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1"))
    canonical = store.viz_dir / "manifest.json"
    original_bytes = canonical.read_bytes()

    def _boom(_self: Path, _target: Path) -> Path:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(Path, "replace", _boom)
    with pytest.raises(OSError):
        store.write_manifest(Manifest(schema_version="2"))
    monkeypatch.undo()

    assert canonical.read_bytes() == original_bytes
    # a stray temp file is left behind by the crashed write...
    leftovers = [p for p in store.viz_dir.iterdir() if ".manifest.json." in p.name]
    assert len(leftovers) == 1
    # ...but it is inert: a fresh read still sees only the canonical content...
    assert store.read_manifest() == Manifest(schema_version="1")
    # ...and a later successful write is unaffected by the stray leftover.
    store.write_manifest(Manifest(schema_version="3"))
    assert store.read_manifest() == Manifest(schema_version="3")


def test_stray_leftover_temp_file_is_ignored_on_read(tmp_path: Path):
    store = SidecarStore(tmp_path)
    store.write_manifest(Manifest(schema_version="1"))
    # plant a stray temp file as a crashed writer would leave behind.
    (store.viz_dir / ".manifest.json.99999.stray.tmp").write_text("garbage", encoding="utf-8")

    assert store.read_manifest() == Manifest(schema_version="1")


def test_concurrent_writers_do_not_interleave(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store_a = SidecarStore(tmp_path, lock_timeout=2.0, lock_poll_interval=0.01)
    store_b = SidecarStore(tmp_path, lock_timeout=2.0, lock_poll_interval=0.01)
    events: list[str] = []
    original_dumps = json.dumps

    def _slow_dumps(*args: object, **kwargs: object) -> str:
        events.append("start")
        time.sleep(0.05)
        result = original_dumps(*args, **kwargs)
        events.append("end")
        return result

    monkeypatch.setattr("vizsuite.sidecar.store.json.dumps", _slow_dumps)

    def _write(store: SidecarStore, tag: str) -> None:
        store.write_manifest(Manifest(schema_version=tag))

    t1 = threading.Thread(target=_write, args=(store_a, "a"))
    t2 = threading.Thread(target=_write, args=(store_b, "b"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # The lock serializes the two writers: a second "start" never appears
    # before the first "end" — no interleaved writes.
    assert events == ["start", "end", "start", "end"]


# ---- root injection: no module-global cwd assumption -----------------------


def test_store_reads_and_writes_are_scoped_to_the_injected_root(tmp_path: Path):
    root_a = tmp_path / "repo-a"
    root_b = tmp_path / "repo-b"
    root_a.mkdir()
    root_b.mkdir()
    store_a = SidecarStore(root_a)
    store_b = SidecarStore(root_b)

    store_a.write_manifest(Manifest(schema_version="a"))

    assert store_a.read_manifest() == Manifest(schema_version="a")
    assert store_b.read_manifest() is None
