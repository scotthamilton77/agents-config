"""`scc --by-file --format json` shape parsing → typed per-file `SccRecord`s.

Mirrors `gh/parse`'s drift discipline: a nonzero scc exit or unparseable stdout
is a loud `VizError(ADAPTER_FAILURE)`, and each `FileJob` `Location` is normalized
(a leading ``./`` stripped) so the keys join the repo-relative estate.
"""

from __future__ import annotations

import json

import pytest

from vizsuite.adapters.scc.parse import parse_scc
from vizsuite.adapters.scc.runner import SccResult
from vizsuite.envelope import ErrorCode, JsonValue, VizError


def _scc_result(payload: JsonValue, *, returncode: int = 0, stderr: str = "") -> SccResult:
    return SccResult(returncode=returncode, stdout=json.dumps(payload), stderr=stderr)


def test_parse_flattens_language_files_and_normalizes_locations() -> None:
    # scc groups files under per-language elements; each FileJob's Location is
    # prefixed with the path scc was invoked on (`.`), so keys arrive as `./x`.
    payload: JsonValue = [
        {
            "Name": "Python",
            "Files": [
                {
                    "Location": "./src/app.py",
                    "Language": "Python",
                    "Lines": 120,
                    "Code": 100,
                    "Complexity": 7,
                },
                {
                    "Location": "./util.py",
                    "Language": "Python",
                    "Lines": 40,
                    "Code": 30,
                    "Complexity": 2,
                },
            ],
        },
        {
            "Name": "Go",
            "Files": [
                {
                    "Location": "main.go",
                    "Language": "Go",
                    "Lines": 50,
                    "Code": 45,
                    "Complexity": 3,
                }
            ],
        },
    ]

    records = parse_scc(_scc_result(payload))

    assert set(records) == {"src/app.py", "util.py", "main.go"}  # ./ stripped, flattened
    app = records["src/app.py"]
    assert app.complexity == 7
    assert app.code == 100
    assert app.lines == 120
    assert app.language == "Python"
    assert records["main.go"].complexity == 3  # a location with no ./ prefix is untouched


def test_parse_nonzero_exit_alarms() -> None:
    with pytest.raises(VizError) as excinfo:
        parse_scc(SccResult(returncode=1, stdout="", stderr="scc: boom"))
    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def test_parse_invalid_json_alarms() -> None:
    with pytest.raises(VizError) as excinfo:
        parse_scc(SccResult(returncode=0, stdout="not json{", stderr=""))
    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE


def test_parse_missing_filejob_scalar_alarms() -> None:
    # A FileJob missing a required scalar (Complexity) is scc drift — a loud
    # VizError, never a silent skip that would thin the complexity axis.
    payload: JsonValue = [
        {"Name": "Python", "Files": [{"Location": "./a.py", "Language": "Python", "Lines": 10}]}
    ]
    with pytest.raises(VizError) as excinfo:
        parse_scc(_scc_result(payload))
    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE
