"""Staleness funnel rungs 1-2 — pure fact-reassessment classification (spec §5.4).

The spec's funnel has four rungs, each strictly cheaper than the next; a fact
exits at the first rung that clears it. This module implements only the two
rungs the spec pins as "pure CLI code" — rung 3 (the agentic doubt check)
belongs to the future `viz` skill/cron and is never invoked from here; rung 4
(human reassessment) is just the `viz queue` read path over `flags.json`, not a
rung this module evaluates.

**Rung 1 (hash check)** is a single equality check over the *entire* tracked
input-fingerprint set, not a per-fact check — every fact trivially clears it
whenever nothing tracked changed at all, which is exactly why the spec calls
it "free" and strictly cheaper than rung 2's per-fact citation-intersection
test. `evaluate_fact` still takes one fact at a time (the sweep verb calls it
once per Tier-2 record), but the *changed-key computation* is the same set
for every call in one sweep.

**Rung 2 (provenance-intersection)** compares that changed-key set against
`fact.provenance.citations` (spec §5.2: a fact's citations are exactly the
inputs it was derived from). The matching rule is deliberately simple: a
tracked input key is "changed" if it is present in exactly one of
`recorded_input_hashes`/`current_input_hashes`, or present in both with a
different value; rung 2 clears when the changed-key set does not intersect
the fact's citations, using plain string-equality set membership — no path
normalization, no fuzzy matching. Both mappings are opaque `{input-key: hash}`
snapshots the caller supplies (the sweep verb sources them from the sidecar
manifest and a fresh Tier-1 fingerprint read respectively); this module never
touches git, a file, or the sidecar itself.

**Restamping** sets the fact's `basis_hash` to a deterministic hash of the
entire `current_input_hashes` mapping — the spec's "new fingerprint" is the
whole tracked input set, not just the fact's own cited subset (which, by rung
2's own passing condition, did not change). This keeps `basis_hash`
synchronized with the sidecar's global fingerprint state for future
rejection-memory comparisons (§5.3), even though the fact's own citations
were untouched by the change that tripped rung 1. The accompanying audit note
is carried on the returned `Restamped` outcome only — this module never
writes it anywhere; persisting or reporting it is the caller's job.

**Contract-version invalidation is out of scope here.** Spec §5.2 warns that
"rung 2 must never silently restamp facts produced under an obsolete
inference contract" (a `prompt_version`/`model_id`/`schema_version` change).
`evaluate_fact` never inspects those fields — a caller that must honor that
invariant folds a contract-version key into both hash mappings (a version
bump then changes that key, and any fact effectively "citing" it is caught by
the same intersection test) or enforces it upstream. Documented here rather
than silently assumed away.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from vizsuite.sidecar.models import FactRecord


@dataclass(frozen=True)
class Reused:
    """Rung 1 cleared: no tracked input changed since the fact's manifest baseline."""

    fact: FactRecord


@dataclass(frozen=True)
class Restamped:
    """Rung 2 cleared: inputs changed, but none the fact cites — auto-restamped.

    `fact` carries the new `basis_hash`; every other field is unchanged from
    the input record. `note` is the audit note the spec requires alongside the
    restamp — the caller decides how (or whether) to persist/report it.
    """

    fact: FactRecord
    note: str


@dataclass(frozen=True)
class FlaggedForReassessment:
    """Neither rung cleared: a doubt candidate for rung 3/4 (the future skill + queue).

    `fact` is the original, unmodified record — this outcome never writes
    anything; the caller (the sweep verb) is responsible for raising a doubt
    flag referencing `fact.fact_id`.
    """

    fact: FactRecord
    changed_citations: frozenset[str]
    reason: str


RungOutcome = Reused | Restamped | FlaggedForReassessment


def _changed_keys(recorded: Mapping[str, str], current: Mapping[str, str]) -> frozenset[str]:
    """Every input key whose value differs (or is present in only one mapping)."""
    keys = set(recorded) | set(current)
    return frozenset(key for key in keys if recorded.get(key) != current.get(key))


def _restamped_basis_hash(current_input_hashes: Mapping[str, str]) -> str:
    """Deterministic hash of the entire current fingerprint set — "the new fingerprint"."""
    content = json.dumps(dict(current_input_hashes), sort_keys=True)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"basis-{digest[:16]}"


def evaluate_fact(
    fact: FactRecord,
    *,
    recorded_input_hashes: Mapping[str, str],
    current_input_hashes: Mapping[str, str],
) -> RungOutcome:
    """Run `fact` through funnel rungs 1-2 and return its typed exit outcome."""
    changed = _changed_keys(recorded_input_hashes, current_input_hashes)
    if not changed:
        return Reused(fact=fact)

    intersecting = changed & frozenset(fact.provenance.citations)
    if not intersecting:
        restamped_fact = FactRecord(
            fact_id=fact.fact_id,
            matching_descriptor=fact.matching_descriptor,
            basis_hash=_restamped_basis_hash(current_input_hashes),
            provenance=fact.provenance,
            payload=fact.payload,
        )
        note = (
            f"auto-restamped: {len(changed)} tracked input(s) changed but none "
            "intersect this fact's citations"
        )
        return Restamped(fact=restamped_fact, note=note)

    return FlaggedForReassessment(
        fact=fact,
        changed_citations=intersecting,
        reason=f"cited input(s) changed: {', '.join(sorted(intersecting))}",
    )
