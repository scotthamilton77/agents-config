"""`viz sweep` — funnel rungs 1-2 over the sidecar's fact files (spec §5.4/§5.5).

Sweep is the "Tier-1 extraction, funnel rungs 1-2" CLI leg of the spec's
overnight-sweep accelerant (rung 3's agentic doubt check and rung 4's human
queue are out of scope — a future `viz` skill layers rung 3 on top of this
same verb). It computes a fresh current fingerprint via the already-existing
`estate` extractor over `runners.git` (no new git call — `git ls-tree -r
HEAD` is exactly the Tier-1 file-fingerprint source the codebase already
has), compares it against the sidecar manifest's recorded `input_hashes`
baseline, classifies every Tier-2 fact (`edges.json`/`steps.json`/
`recommendations.json`) through `funnel.rungs.evaluate_fact`, rewrites the
fact files and `flags.json` accordingly, and advances the manifest to the new
fingerprint (closing rung 1's own loop: the next sweep's baseline is this
sweep's current, so only genuinely new changes register as "changed"). Every
write goes through `SidecarStore`, so it is lock-guarded and atomic exactly
like every other sidecar writer; `verdicts.json` is never opened.

**A fact with an already-pending flag is never re-evaluated.** Absent this
guard, a fact sitting in the reassessment queue (rung 4) awaiting a human
verdict could be silently restamped or reused by a later sweep the moment an
unrelated input drifts back into alignment — contradicting the standing doubt
flag out from under the human review it is waiting on. Such a fact is instead
carried through unmodified and counted in the `flagged` bucket alongside any
newly-flagged fact from this run; a fact is removed from that bucket only by
an explicit `viz verdict` resolving its flag (a later slice), never by sweep.

Flag ids are minted deterministically from `fact_id` alone (`_mint_flag_id`),
so re-running sweep never mints a second flag for the same fact.
"""

from __future__ import annotations

import hashlib
from argparse import Namespace
from collections.abc import Callable, Sequence
from pathlib import Path

from vizsuite.envelope import JsonValue
from vizsuite.extract.estate import estate
from vizsuite.funnel.rungs import FlaggedForReassessment, Restamped, Reused, evaluate_fact
from vizsuite.runners import Runners
from vizsuite.sidecar.models import FactRecord, FlagKind, FlagRecord, Manifest
from vizsuite.sidecar.store import SidecarStore

_FactFileEntry = tuple[tuple[FactRecord, ...], Callable[[Sequence[FactRecord]], None]]


def _mint_flag_id(fact_id: str) -> str:
    """Deterministic doubt-flag id: purely a function of `fact_id`.

    Guarantees a fact maps to the same flag id across sweeps, so upserting by
    `flag_id` (below) is a true idempotent merge rather than an accumulating
    duplicate.
    """
    digest = hashlib.sha256(fact_id.encode("utf-8")).hexdigest()
    return f"flag-{digest[:16]}"


def sweep(runners: Runners, _args: Namespace) -> JsonValue:
    """Handle `viz sweep`: classify every Tier-2 fact through funnel rungs 1-2.

    Returns the envelope `data`: `reused`/`restamped`/`flagged` counts across
    all three fact files combined.
    """
    store = SidecarStore(Path.cwd())

    manifest = store.read_manifest()
    if manifest is not None:
        recorded_input_hashes = manifest.input_hashes
        schema_version, prompt_version, model_id = (
            manifest.schema_version,
            manifest.prompt_version,
            manifest.model_id,
        )
    else:
        recorded_input_hashes = {}
        schema_version, prompt_version, model_id = "", "", ""

    current_input_hashes = estate(runners.git, "HEAD")

    existing_flags = store.read_flags()
    already_flagged_fact_ids = {flag.fact_id for flag in existing_flags}

    reused_count = restamped_count = flagged_count = 0
    new_flags_by_id: dict[str, FlagRecord] = {}

    fact_files: tuple[_FactFileEntry, ...] = (
        (store.read_edges(), store.write_edges),
        (store.read_steps(), store.write_steps),
        (store.read_recommendations(), store.write_recommendations),
    )
    for records, write in fact_files:
        rewritten: list[FactRecord] = []
        for record in records:
            if record.fact_id in already_flagged_fact_ids:
                flagged_count += 1
                rewritten.append(record)
                continue

            outcome = evaluate_fact(
                record,
                recorded_input_hashes=recorded_input_hashes,
                current_input_hashes=current_input_hashes,
            )
            if isinstance(outcome, Reused):
                reused_count += 1
                rewritten.append(outcome.fact)
            elif isinstance(outcome, Restamped):
                restamped_count += 1
                rewritten.append(outcome.fact)
            elif isinstance(outcome, FlaggedForReassessment):
                flagged_count += 1
                rewritten.append(outcome.fact)
                flag_id = _mint_flag_id(outcome.fact.fact_id)
                new_flags_by_id[flag_id] = FlagRecord(
                    flag_id=flag_id,
                    fact_id=outcome.fact.fact_id,
                    kind=FlagKind.DOUBT,
                    reason=outcome.reason,
                )
            else:
                raise TypeError(outcome)
        write(rewritten)

    if new_flags_by_id:
        merged = {flag.flag_id: flag for flag in existing_flags}
        merged.update(new_flags_by_id)
        store.write_flags(tuple(merged.values()))

    store.write_manifest(
        Manifest(
            schema_version=schema_version,
            prompt_version=prompt_version,
            model_id=model_id,
            input_hashes=current_input_hashes,
        )
    )

    return {"reused": reused_count, "restamped": restamped_count, "flagged": flagged_count}
