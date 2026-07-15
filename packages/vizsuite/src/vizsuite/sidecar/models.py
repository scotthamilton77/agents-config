"""Sidecar record dataclasses — the five `.viz/*.json` record files' typed
shapes (spec §5.3).

`FactRecord` is the shared Tier-2 envelope for `edges.json`/`steps.json`/
`recommendations.json`: a durable `fact_id`, the identity-reconciliation
`MatchingDescriptor` snapshot, `basis_hash` (the cited-inputs stamp, tracked
separately from identity), and per-fact `Provenance` (reused from
`vizsuite.scene.model` — the sidecar's provenance axis is the same concept the
scene envelope carries, not a second one). `payload` holds the record-kind-
specific fields; this foundation slice does not yet model V2's per-kind
domain shapes (§7.2) — later slices read typed views over `payload` without
changing this envelope (the verdict slice's `payload["promotion"]`
edge-promotion ledger is one such typed view, see `vizsuite.verbs.verdict`).
`FlagRecord` models a `flags.json` entry (`doubt`, `orphaned_verdict`, or
`orphaned_edge_promotion`); `VerdictRecord` models a `verdicts.json` entry;
`Manifest` models `manifest.json`.

Every `*_to_json`/`*_from_json` pair is a pure mapping function, mirroring
`vizsuite.scene.model.scene_to_json`'s style. `*_from_json` raises a plain
`TypeError`/`ValueError`/`KeyError` on a malformed shape — the sidecar store
(the actual file-I/O boundary) is what converts that into a typed
`VizError(SIDECAR_MALFORMED)` so a raw parse exception never reaches a CLI
caller (spec §5.3: "parse/validate at the boundary").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from vizsuite.envelope import JsonValue
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind, provenance_to_json


class FlagKind(StrEnum):
    """The three `flags.json` record kinds (spec §5.3): `doubt`,
    `orphaned_verdict`, or `orphaned_edge_promotion`."""

    DOUBT = "doubt"
    ORPHANED_VERDICT = "orphaned_verdict"
    # verdict slice: a previously-promoted edge's recorded bead pair fell
    # outside the fact's current bead-id anchors after re-synthesis. A
    # promoted tracker edge is never auto-removed (spec §5.3), so this flags
    # the mismatch for human disposition instead of silently dropping it.
    ORPHANED_EDGE_PROMOTION = "orphaned_edge_promotion"


class Verdict(StrEnum):
    """The three Tier-3 verdict values a human can record (spec §5.7/§10 item 3)."""

    ACCEPT = "accept"
    REJECT = "reject"
    DISMISS = "dismiss"


@dataclass(frozen=True)
class MatchingDescriptor:
    """The identity-reconciliation snapshot taken at inference time (spec §5.3).

    `endpoint_bead_ids` snapshots each endpoint's bead-id anchor set as it
    resolved *at that moment* — reconciliation on rebuild matches against this
    snapshot and never depends on re-reading Tier-2 files. Prose-only plans
    (zero-bead anchors) fall back to `plan_pair` + `kind` alone, so
    `endpoint_bead_ids` defaults to empty.
    """

    plan_pair: tuple[str, str]
    kind: str
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class FactRecord:
    """One Tier-2 fact shared by `edges.json`/`steps.json`/`recommendations.json`."""

    fact_id: str
    matching_descriptor: MatchingDescriptor
    basis_hash: str
    provenance: Provenance
    payload: dict[str, JsonValue] = field(default_factory=dict)


class _FlagVerdictInvariantError(ValueError):
    """Raised when a `FlagRecord`'s `verdict_id` presence disagrees with its `kind`.

    An `orphaned_verdict` flag must carry a `verdict_id`; a `doubt` flag must not.
    Subclassing `ValueError` lets the sidecar store wrap a violation from a
    deserialized record into a `VizError(SIDECAR_MALFORMED)` at the read
    boundary (the message is fixed on the class per ruff TRY003).
    """

    def __init__(self) -> None:
        super().__init__("verdict_id must be set iff kind is ORPHANED_VERDICT")


@dataclass(frozen=True)
class FlagRecord:
    """A `flags.json` entry: a `doubt` flag or an `orphaned_verdict` flag (spec §5.3).

    `verdict_id` is set only for an `orphaned_verdict` flag (the verdict whose
    subject fact changed or vanished on rebuild); a doubt flag references only
    its fact. `__post_init__` enforces this invariant in both directions so both
    directly-constructed and deserialized records are guaranteed consistent.
    """

    flag_id: str
    fact_id: str
    kind: FlagKind
    reason: str
    verdict_id: str | None = None

    def __post_init__(self) -> None:
        if (self.kind == FlagKind.ORPHANED_VERDICT) != (self.verdict_id is not None):
            raise _FlagVerdictInvariantError


@dataclass(frozen=True)
class VerdictRecord:
    """A `verdicts.json` entry: the durable human judgment on one fact (spec §5.3).

    `basis_hash` snapshots the fact's `basis_hash` *at verdict time* — the
    rejection-memory comparison (same basis ⇒ suppressed, changed basis ⇒
    resurfaces annotated with the prior rejection) reads this stamp, never a
    re-derivation from the current fact.
    """

    verdict_id: str
    fact_id: str
    verdict: Verdict
    basis_hash: str
    annotation: str = ""


@dataclass(frozen=True)
class Manifest:
    """`manifest.json`: the fingerprint manifest (spec §5.3/§5.4).

    `input_hashes` covers the Tier-1 inputs the sidecar build hash-checked
    (funnel rung 1); `prompt_version`/`model_id` pin the inference-contract
    version that a fact's `basis_hash` also covers (§5.2), so a contract
    change is visible as a manifest change too.
    """

    schema_version: str
    prompt_version: str = ""
    model_id: str = ""
    input_hashes: dict[str, str] = field(default_factory=dict)


# ---- parse-boundary helpers (raise on a shape mismatch) --------------------


class _ExpectedStringError(TypeError):
    """Raised by `_as_str` when a sidecar JSON value is not a string.

    The message is fixed on the class (ruff TRY003: no message argument at the
    `raise` site) while `isinstance(exc, TypeError)` still holds for callers
    matching on the vanilla type.
    """

    def __init__(self) -> None:
        super().__init__("expected a string")


class _ExpectedObjectError(TypeError):
    """Raised by `_as_dict` when a sidecar JSON value is not an object."""

    def __init__(self) -> None:
        super().__init__("expected an object")


class _ExpectedArrayError(TypeError):
    """Raised by `_as_list` when a sidecar JSON value is not an array."""

    def __init__(self) -> None:
        super().__init__("expected an array")


class _InvalidPlanPairLengthError(ValueError):
    """Raised when a matching descriptor's `plan_pair` isn't exactly 2 entries."""

    def __init__(self) -> None:
        super().__init__("plan_pair must have exactly 2 entries")


def _as_str(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise _ExpectedStringError
    return value


def _as_dict(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise _ExpectedObjectError
    return value


def _as_list(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise _ExpectedArrayError
    return value


# ---- Provenance (reused shape from vizsuite.scene.model) -------------------


def _provenance_from_json(data: JsonValue) -> Provenance:
    mapping = _as_dict(data)
    citations = [_as_str(item) for item in _as_list(mapping["citations"])]
    return Provenance(
        kind=ProvenanceKind(_as_str(mapping["kind"])),
        freshness=Freshness(_as_str(mapping["freshness"])),
        citations=tuple(citations),
    )


# ---- MatchingDescriptor -----------------------------------------------------


def _matching_descriptor_to_json(descriptor: MatchingDescriptor) -> dict[str, JsonValue]:
    return {
        "plan_pair": list(descriptor.plan_pair),
        "kind": descriptor.kind,
        "endpoint_bead_ids": [list(ids) for ids in descriptor.endpoint_bead_ids],
    }


def _matching_descriptor_from_json(data: JsonValue) -> MatchingDescriptor:
    mapping = _as_dict(data)
    plan_pair = [_as_str(item) for item in _as_list(mapping["plan_pair"])]
    if len(plan_pair) != 2:
        raise _InvalidPlanPairLengthError
    endpoint_bead_ids = tuple(
        tuple(_as_str(bead_id) for bead_id in _as_list(ids))
        for ids in _as_list(mapping["endpoint_bead_ids"])
    )
    return MatchingDescriptor(
        plan_pair=(plan_pair[0], plan_pair[1]),
        kind=_as_str(mapping["kind"]),
        endpoint_bead_ids=endpoint_bead_ids,
    )


# ---- FactRecord (public: read by the sidecar store) ------------------------


def fact_record_to_json(record: FactRecord) -> dict[str, JsonValue]:
    return {
        "fact_id": record.fact_id,
        "matching_descriptor": _matching_descriptor_to_json(record.matching_descriptor),
        "basis_hash": record.basis_hash,
        "provenance": provenance_to_json(record.provenance),
        "payload": dict(record.payload),
    }


def fact_record_from_json(data: JsonValue) -> FactRecord:
    mapping = _as_dict(data)
    return FactRecord(
        fact_id=_as_str(mapping["fact_id"]),
        matching_descriptor=_matching_descriptor_from_json(mapping["matching_descriptor"]),
        basis_hash=_as_str(mapping["basis_hash"]),
        provenance=_provenance_from_json(mapping["provenance"]),
        payload=_as_dict(mapping["payload"]),
    )


# ---- FlagRecord (public: read by the sidecar store) ------------------------


def flag_record_to_json(record: FlagRecord) -> dict[str, JsonValue]:
    return {
        "flag_id": record.flag_id,
        "fact_id": record.fact_id,
        "kind": str(record.kind),
        "reason": record.reason,
        "verdict_id": record.verdict_id,
    }


def flag_record_from_json(data: JsonValue) -> FlagRecord:
    mapping = _as_dict(data)
    verdict_id = mapping.get("verdict_id")
    return FlagRecord(
        flag_id=_as_str(mapping["flag_id"]),
        fact_id=_as_str(mapping["fact_id"]),
        kind=FlagKind(_as_str(mapping["kind"])),
        reason=_as_str(mapping["reason"]),
        verdict_id=_as_str(verdict_id) if verdict_id is not None else None,
    )


# ---- VerdictRecord (public: read by the sidecar store) ---------------------


def verdict_record_to_json(record: VerdictRecord) -> dict[str, JsonValue]:
    return {
        "verdict_id": record.verdict_id,
        "fact_id": record.fact_id,
        "verdict": str(record.verdict),
        "basis_hash": record.basis_hash,
        "annotation": record.annotation,
    }


def verdict_record_from_json(data: JsonValue) -> VerdictRecord:
    mapping = _as_dict(data)
    return VerdictRecord(
        verdict_id=_as_str(mapping["verdict_id"]),
        fact_id=_as_str(mapping["fact_id"]),
        verdict=Verdict(_as_str(mapping["verdict"])),
        basis_hash=_as_str(mapping["basis_hash"]),
        annotation=_as_str(mapping.get("annotation", "")),
    )


# ---- Manifest (public: read by the sidecar store) --------------------------


def manifest_to_json(manifest: Manifest) -> dict[str, JsonValue]:
    return {
        "schema_version": manifest.schema_version,
        "prompt_version": manifest.prompt_version,
        "model_id": manifest.model_id,
        "input_hashes": dict(manifest.input_hashes),
    }


def manifest_from_json(data: JsonValue) -> Manifest:
    mapping = _as_dict(data)
    input_hashes = _as_dict(mapping.get("input_hashes", {}))
    return Manifest(
        schema_version=_as_str(mapping["schema_version"]),
        prompt_version=_as_str(mapping.get("prompt_version", "")),
        model_id=_as_str(mapping.get("model_id", "")),
        input_hashes={key: _as_str(value) for key, value in input_hashes.items()},
    )
