"""scc JSON shape parsing → typed `SccRecord`s keyed by normalized `Location`.

`SubprocessSccRunner.scan` returns the raw `SccResult`; this module turns scc's
`--by-file --format json` shape (per-language elements, each embedding a `Files`
array of FileJobs) into a flat `{location: SccRecord}` map. It is the single place
a failed or malformed scc run becomes a loud `VizError(ADAPTER_FAILURE)` (mirrors
gh/parse). Each `Location` is normalized — a leading ``./`` stripped — so keys are
repo-relative and join the estate (scc prefixes every `Location` with the `.` path
argument it was invoked on).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from vizsuite.adapters.scc.runner import SccResult
from vizsuite.envelope import ErrorCode, VizError


@dataclass(frozen=True)
class SccRecord:
    complexity: int
    code: int
    lines: int
    language: str


def _shape_error(stdout: str, *, reason: str) -> VizError:
    return VizError(
        ErrorCode.ADAPTER_FAILURE,
        "scc returned an unparseable or unexpected shape",
        detail={"reason": reason, "raw_excerpt": stdout[:200]},
    )


def parse_scc(result: SccResult) -> dict[str, SccRecord]:
    """Parse one scc `--by-file --format json` response into `{location: SccRecord}`.

    A nonzero scc exit, non-JSON stdout, or a missing FileJob scalar all funnel to
    the same `VizError(ADAPTER_FAILURE)` — never a silent default (a silently-empty
    complexity axis is the failure class §6.2's join sanity exists to prevent).
    """
    if result.returncode != 0:
        raise VizError(
            ErrorCode.ADAPTER_FAILURE,
            "scc exited nonzero",
            detail={"returncode": result.returncode, "stderr": result.stderr.strip()},
        )
    try:
        languages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _shape_error(result.stdout, reason="invalid_json") from exc

    records: dict[str, SccRecord] = {}
    try:
        for language in languages:
            for file_job in language["Files"]:
                location = file_job["Location"].removeprefix("./")
                records[location] = SccRecord(
                    complexity=file_job["Complexity"],
                    code=file_job["Code"],
                    lines=file_job["Lines"],
                    language=file_job["Language"],
                )
    except (KeyError, TypeError) as exc:
        raise _shape_error(result.stdout, reason=type(exc).__name__) from exc
    return records
