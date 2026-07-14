"""Complexity heat axis — scc baseline + never-cool churn boost (spec §6.2, slice 3).

The full §6.2 Complexity axis, not the scc baseline alone: each estate file's scc
complexity is normalized to a 0-1 estate-wide baseline, then the PR-touched (net)
files get a churn-scaled boost on top — clamped to 1.0 and never below the
baseline (churn only heats, never cools). Files outside the estate are ignored; an
empty estate∩scc overlap is a loud `VizError(ADAPTER_FAILURE)` — a silently-empty
complexity axis is exactly the join failure this guard prevents. The cross-axis
weighted average of the three finished axes lives in `.2.2`, not here.
"""

from __future__ import annotations

from vizsuite.adapters.scc.parse import SccRecord
from vizsuite.envelope import ErrorCode, VizError
from vizsuite.extract.churn import FileChurn

# Tunable heat-model constant: the fraction of the 0-1 range the most-churned net
# file may add on top of its baseline. The spec-mandated invariants (never-cool
# clamp, touched-files-only application) are what the tests pin — not this weight.
CHURN_BOOST_WEIGHT = 0.5


def complexity(
    estate: dict[str, str],
    scc_records: dict[str, SccRecord],
    pr_files: dict[str, FileChurn],
) -> dict[str, float]:
    """Per-file 0-1 complexity heat over the estate scope.

    `estate` is the canonical `{path: blob_sha}` file set; only its keys are
    scored. `scc_records` supplies each file's complexity; `pr_files` (the
    reconciled net set with churn) selects which files get the churn boost.
    """
    scored = {path: record for path, record in scc_records.items() if path in estate}
    if not scored:
        raise VizError(
            ErrorCode.ADAPTER_FAILURE,
            "no scc record joins the estate scope; the complexity axis would be empty",
            detail={"estate_size": len(estate), "scc_records": len(scc_records)},
        )

    max_complexity = max(record.complexity for record in scored.values())
    net_churn = {
        path: pr_files[path].added + pr_files[path].deleted for path in scored if path in pr_files
    }
    max_churn = max(net_churn.values(), default=0)

    heat: dict[str, float] = {}
    for path, record in scored.items():
        baseline = record.complexity / max_complexity if max_complexity > 0 else 0.0
        boost = 0.0
        if max_churn > 0 and net_churn.get(path, 0) > 0:
            boost = CHURN_BOOST_WEIGHT * (net_churn[path] / max_churn)
        heat[path] = min(1.0, baseline + boost)  # boost only heats; never below baseline
    return heat
