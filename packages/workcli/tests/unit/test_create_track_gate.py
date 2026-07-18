"""create track gate (track spec §4; criteria 1-5, 9, 17)."""

from __future__ import annotations

import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult


def test_create_raw_refuses_track_flag() -> None:
    # --raw is the documented track bypass; a silently-ignored --track would
    # look tracked while creating an untracked bead. E_USAGE, creates nothing.
    exit_code, envelope, _ = run_cli(
        ["create", "--raw", "--title", "T", "--track", "alpha"], []
    )
    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_USAGE"
    assert "--track" in str(error["message"])
