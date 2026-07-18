"""The config-loader seam: injected, lazy, --config passthrough (track spec §3)."""

from __future__ import annotations

import json

from tests.conftest import run_cli
from tests.fakes import ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig


def _exploding_loader(_explicit_path: str | None) -> TrackLayerConfig:
    # Underscore-prefixed unused param: house convention for test doubles
    # (ruff ARG001 is enabled package-wide).
    raise AssertionError("config loader invoked by a pre-existing verb (must be lazy)")


def test_pre_existing_verbs_never_touch_the_config_loader() -> None:
    # Criterion 17's laziness leg: `show` with no track flags must complete
    # without the loader ever running -- even with --config on the command line.
    step = ScriptedStep(
        ("show",),
        BdResult(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "id": "w-1",
                        "title": "T",
                        "issue_type": "task",
                        "status": "open",
                        "priority": 2,
                        "labels": [],
                    }
                ]
            ),
            stderr="",
        ),
    )
    exit_code, envelope, _ = run_cli(
        ["--config", "/tmp/anything.toml", "show", "w-1"],  # noqa: S108 -- never read; loader is fail-loud
        [step],
        config_loader=_exploding_loader,
    )
    assert exit_code == 0
    assert envelope["ok"] is True
