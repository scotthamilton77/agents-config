"""Tests for the CliDeployPort fake and real implementation (spec §4)."""

from pathlib import Path

import pytest

from installer.core.clis import CommandResult, ScriptedCliDeploy


def test_scripted_fake_stable_reads_and_stateful_queues(tmp_path: Path) -> None:
    """
    Given a ScriptedCliDeploy configured with stable query values and
    mutation queues
    When port methods are called
    Then idempotent queries (uv_version/bin_dir/tool_list/which) return the
    SAME configured value on every call (repeatable reads — tests never
    count internal call sites for them), state-bearing calls
    (shim_path/install/smoke/...) pop per-method queues, and the transcript
    records (method, key-arg) tuples.

    Pins spec §4 fake contract (queue semantics reserved for calls whose
    sequence matters — ralf plan-review cycle 1 M3).
    """
    bin_dir = tmp_path / "bin"
    fake = ScriptedCliDeploy(
        uv_version=(0, 10, 4),
        bin_dir=bin_dir,
        tool_list={"workcli": frozenset({"work"})},
        which_map={"work": bin_dir / "work"},
        shims=[bin_dir / "work"],
        installs=[CommandResult(ok=True, output="")],
        smokes=[CommandResult(ok=True, output="")],
    )
    assert fake.uv_version() == (0, 10, 4)
    assert fake.uv_version() == (0, 10, 4)  # stable, not consumed
    assert fake.bin_dir() == bin_dir
    assert fake.bin_dir() == bin_dir  # stable, not consumed
    assert fake.tool_list() == {"workcli": frozenset({"work"})}
    assert fake.which("work") == bin_dir / "work"
    assert fake.which("unknown") is None  # missing key -> not on PATH
    assert fake.shim_path("work") == bin_dir / "work"
    assert fake.tool_install(tmp_path / "pkg", force=False).ok
    assert fake.smoke(bin_dir / "work", ("--protocol-version",)).ok
    assert ("tool_install", str(tmp_path / "pkg"), False) in fake.transcript
    assert ("smoke", str(bin_dir / "work")) in fake.transcript


def test_scripted_fake_exhaustion_is_loud(tmp_path: Path) -> None:
    """
    Given a fake with an empty installs queue (and an empty shims queue)
    When tool_install / shim_path are called
    Then each raises with a message naming the exhausted queue.

    Pins spec §4: exhaustion-error self-diagnosis mirrors ScriptedIO.
    """
    fake = ScriptedCliDeploy()
    with pytest.raises(RuntimeError, match="installs"):
        fake.tool_install(tmp_path / "pkg", force=True)
    with pytest.raises(RuntimeError, match="shims"):
        fake.shim_path("work")
