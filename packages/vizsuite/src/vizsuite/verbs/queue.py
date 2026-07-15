"""`viz queue` — the reassessment queue read path (spec §5.3/§5.4 rung 4).

Rung 4 is "a queue, not a process": every flag currently in `flags.json` *is*
the unresolved set — `viz verdict` (a later slice) resolves a flag by
removing it from the file atomically, so there is no separate "resolved"
marker to filter on here. `viz queue` is therefore a pure read-and-join: every
flag, joined to its fact (searched across `edges.json`/`steps.json`/
`recommendations.json` — the same `fact_id` namespace `reconcile.py` mints
into) and, for an `orphaned_verdict` flag, its verdict. Never writes anything,
never touches an adapter.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from vizsuite.envelope import JsonValue
from vizsuite.runners import Runners
from vizsuite.sidecar.models import FactRecord, VerdictRecord, fact_record_to_json
from vizsuite.sidecar.models import flag_record_to_json as _flag_to_json
from vizsuite.sidecar.models import verdict_record_to_json as _verdict_to_json
from vizsuite.sidecar.store import SidecarStore


def _facts_by_id(store: SidecarStore) -> dict[str, FactRecord]:
    """Merge the three Tier-2 fact files into one `fact_id -> FactRecord` map.

    `fact_id` is minted from a namespace shared across edges/steps/
    recommendations (`reconcile.content_fact_id`), so a collision across the
    three files would itself be a sidecar defect; the last file read wins in
    that case rather than raising, since this is a best-effort read path.
    """
    merged: dict[str, FactRecord] = {}
    for record in (*store.read_edges(), *store.read_steps(), *store.read_recommendations()):
        merged[record.fact_id] = record
    return merged


def queue(_runners: Runners, _args: Namespace) -> JsonValue:
    """Handle `viz queue`: read `flags.json`, join to facts and verdicts.

    Returns the envelope `data`: `count` and `entries`, each entry carrying
    the raw flag plus its joined `fact`/`verdict` (`None` when the referenced
    record is missing — a flag can outlive the record it points to across a
    rebuild). Entries are sorted by `flag_id` for deterministic output.
    """
    store = SidecarStore(Path.cwd())
    facts_by_id = _facts_by_id(store)
    verdicts_by_id: dict[str, VerdictRecord] = {
        verdict.verdict_id: verdict for verdict in store.read_verdicts()
    }

    entries: list[JsonValue] = []
    for flag in sorted(store.read_flags(), key=lambda flag: flag.flag_id):
        fact = facts_by_id.get(flag.fact_id)
        verdict = verdicts_by_id.get(flag.verdict_id) if flag.verdict_id is not None else None
        entry: dict[str, JsonValue] = {
            "flag": _flag_to_json(flag),
            "fact": fact_record_to_json(fact) if fact is not None else None,
            "verdict": _verdict_to_json(verdict) if verdict is not None else None,
        }
        entries.append(entry)

    return {"count": len(entries), "entries": entries}
