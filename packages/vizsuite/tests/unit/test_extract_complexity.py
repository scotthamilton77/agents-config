"""Complexity heat axis (spec §6.2): scc baseline + never-cool churn boost.

The axis normalizes scc per-file complexity to a 0-1 estate-wide baseline, then
heats the PR-touched (net) files by a churn-scaled boost that never cools a file
below its baseline. The tests pin the *invariants* — baseline normalization,
context files unaffected, touched-with-churn strictly hotter, zero-churn net files
unchanged, non-estate files ignored, empty overlap alarms — not the tunable boost
weight.
"""

from __future__ import annotations

import pytest
from vizsuite.extract.complexity import complexity

from vizsuite.adapters.scc.parse import SccRecord
from vizsuite.envelope import ErrorCode, VizError
from vizsuite.extract.churn import FileChurn


def _record(complexity_value: int) -> SccRecord:
    # Only Complexity drives the axis; the other scc fields ride along for later axes.
    return SccRecord(complexity=complexity_value, code=1, lines=1, language="Python")


def test_complexity_baseline_with_never_cool_churn_boost() -> None:
    estate = {"ctx.py": "s1", "touched.py": "s2", "quiet.py": "s3", "peak.py": "s4"}
    scc_records = {
        "ctx.py": _record(5),  # context file, in estate, not in the net set
        "touched.py": _record(4),  # net file with churn → must heat above baseline
        "quiet.py": _record(7),  # net file, zero churn → must stay at baseline
        "peak.py": _record(10),  # estate-wide max complexity → baseline 1.0
        "vendored.py": _record(9),  # NOT in the estate → must be ignored
    }
    pr_files = {
        "touched.py": FileChurn(added=30, deleted=0),  # the only churn → max_churn
        "quiet.py": FileChurn(added=0, deleted=0),  # a pure-rename net file: zero churn
    }

    heat = complexity(estate, scc_records, pr_files)

    assert "vendored.py" not in heat  # outside the estate scope → dropped
    assert heat["peak.py"] == 1.0  # normalized to the estate-wide max
    assert heat["ctx.py"] == 0.5  # 5/10 baseline, untouched by any boost
    assert heat["quiet.py"] == 0.7  # 7/10 baseline; zero churn → no boost (never-cool)
    assert heat["touched.py"] > 0.4  # 4/10 baseline heated by churn (strictly above)
    assert heat["touched.py"] <= 1.0  # clamped to the 0-1 range


def test_complexity_high_baseline_zero_churn_never_cools() -> None:
    # A net file that is complex (high scc baseline) but had zero churn must never
    # score below its baseline — churn only heats, it never cools (§6.2).
    estate = {"complex.py": "s1", "simple.py": "s2"}
    scc_records = {"complex.py": _record(10), "simple.py": _record(2)}
    pr_files = {"complex.py": FileChurn(added=0, deleted=0)}  # touched, but no churn

    heat = complexity(estate, scc_records, pr_files)

    assert heat["complex.py"] == 1.0  # baseline preserved, not cooled by the zero churn


def test_complexity_empty_estate_scc_overlap_alarms() -> None:
    # scc scored only files outside the estate → the axis would be silently empty.
    estate = {"src/app.py": "s1"}
    scc_records = {"vendored/lib.py": _record(3)}

    with pytest.raises(VizError) as excinfo:
        complexity(estate, scc_records, pr_files={})

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE
