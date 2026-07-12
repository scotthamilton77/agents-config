"""`_default_read_file` -- the default `--spec`/manifest reader that types its
own read failures.

`main()` defaults `args.read_file` to this helper. It reads the path as UTF-8
and converts the two expected boundary failures into typed `WorkError`s so the
CLI reports an actionable envelope instead of routing a bare
`OSError`/`UnicodeDecodeError` through main()'s catch-all as an opaque
`E_INTERNAL` "internal error":

- missing / unreadable path (`OSError`, incl. `FileNotFoundError`) -> `E_USAGE`
  (a bad `--spec` argument is user error);
- non-UTF-8 / undecodable file (`UnicodeDecodeError`) -> `E_MANIFEST`
  (a spec that can't be decoded is a malformed manifest input).

The injected `read_file` seam bypasses this helper entirely -- only the default
routes through here -- so fakes stay usable unchanged (covered by the existing
`deliver`/`reconcile` suites).
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.cli import _default_read_file, main
from workcli.envelope import ErrorCode, WorkError


def test_default_read_file_reads_utf8_file(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("## Continuations\n- none — done\n", encoding="utf-8")

    assert _default_read_file(str(spec)) == "## Continuations\n- none — done\n"


def test_default_read_file_missing_path_raises_usage(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"

    with pytest.raises(WorkError) as caught:
        _default_read_file(str(missing))

    assert caught.value.code is ErrorCode.USAGE
    # The message and detail name the offending path so the failure is actionable.
    assert str(missing) in caught.value.message
    assert caught.value.detail["path"] == str(missing)


def test_default_read_file_non_utf8_raises_manifest(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_bytes(b"\xff\xfe\x00 not utf-8")

    with pytest.raises(WorkError) as caught:
        _default_read_file(str(spec))

    assert caught.value.code is ErrorCode.MANIFEST
    assert str(spec) in caught.value.message
    assert caught.value.detail["path"] == str(spec)


def _show(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _raw(
    item_id: str,
    *,
    labels: list[str] | None = None,
    parent: str | None = None,
    children: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": "T",
        "issue_type": "task",
        "status": "open",
        "priority": 2,
        "labels": labels or [],
        "parent": parent,
        "notes": "",
        "dependencies": [],
        "dependents": [
            {"id": child_id, "dependency_type": "parent-child", "status": "open"}
            for child_id in (children or [])
        ],
    }


def test_deliver_missing_spec_yields_usage_envelope_not_internal(tmp_path: Path) -> None:
    """End-to-end: the default reader's `WorkError` becomes a typed envelope.

    With no injected `read_file`, `main()` uses `_default_read_file`. A missing
    `--spec` path must surface as an `E_USAGE` failure envelope on stdout, NOT
    the opaque `E_INTERNAL` the catch-all would have produced from a bare
    `FileNotFoundError`.
    """
    missing = tmp_path / "absent.md"
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show",), _show(_raw("d.1", labels=["shape-design"], parent="c.1"))),
            ScriptedStep(("show",), _show(_raw("c.1", children=["d.1", "p.1"]))),
            ScriptedStep(("show",), _show(_raw("p.1", labels=["impl-placeholder"]))),
        ]
    )
    out = StringIO()
    err = StringIO()

    exit_code = main(
        ["deliver", "d.1", "--spec", str(missing)],
        runner=runner,
        out=out,
        err=err,
    )

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == str(ErrorCode.USAGE)
    assert envelope["error"]["code"] != str(ErrorCode.INTERNAL)
    assert str(missing) in envelope["error"]["message"]
