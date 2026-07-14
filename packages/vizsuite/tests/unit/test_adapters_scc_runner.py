"""`SubprocessSccRunner` preflight: a missing scc binary alarms before any scan.

The unit suite drives `ScriptedSccRunner`; the only real-`scc` code is the exec
itself (pragma no-cover — scc may be absent in CI). This test covers the
`shutil.which` preflight branch: with scc off PATH, `scan` raises a typed
`VizError(ADAPTER_FAILURE)` carrying an install hint rather than dying on a
cryptic subprocess error deep in the verb.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vizsuite.adapters.scc.runner import SubprocessSccRunner
from vizsuite.envelope import ErrorCode, VizError


def test_scan_without_scc_on_path_alarms_with_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(VizError) as excinfo:
        SubprocessSccRunner().scan(tmp_path)

    assert excinfo.value.code == ErrorCode.ADAPTER_FAILURE
    assert "scc" in excinfo.value.message.lower()
