"""Tests for the CliDeployPort fake and real implementation (spec §4)."""

import subprocess
from pathlib import Path

import pytest

from installer.core.clis import CommandResult, ScriptedCliDeploy, UvCliDeploy


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


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_uv_version_parses_semver(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Given `uv --version` printing 'uv 0.10.4 (Homebrew 2026-02-17)'
    When uv_version() runs
    Then it returns (0, 10, 4); an unparseable output returns None.

    Pins spec §4/§6: the MIN_UV_VERSION guard input.
    """
    port = UvCliDeploy()
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: _FakeCompleted(stdout="uv 0.10.4 (Homebrew)")
    )
    assert port.uv_version() == (0, 10, 4)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _FakeCompleted(stdout="garbage"))
    assert port.uv_version() is None


def test_bin_dir_fallback_chain(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Given `uv tool dir --bin` failing
    When bin_dir() resolves
    Then it honors UV_TOOL_BIN_DIR, then XDG_BIN_HOME, then
    XDG_DATA_HOME/../bin, then ~/.local/bin.

    Pins spec §4 / item 17 (full documented uv precedence).
    """

    def _boom(*_a: object, **_k: object) -> _FakeCompleted:
        raise FileNotFoundError("uv")

    port = UvCliDeploy()
    monkeypatch.setattr(subprocess, "run", _boom)
    for var in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "uvbin"))
    assert port.bin_dir() == tmp_path / "uvbin"
    monkeypatch.delenv("UV_TOOL_BIN_DIR")
    monkeypatch.setenv("XDG_BIN_HOME", str(tmp_path / "xdgbin"))
    assert port.bin_dir() == tmp_path / "xdgbin"
    monkeypatch.delenv("XDG_BIN_HOME")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert port.bin_dir() == (tmp_path / "data" / ".." / "bin").resolve()
    monkeypatch.delenv("XDG_DATA_HOME")
    assert port.bin_dir() == Path.home() / ".local" / "bin"


def test_tool_list_parses_names_and_executables(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Given `uv tool list` output with tools and '- exe' lines
    When tool_list() runs
    Then it returns {tool: frozenset(executables)}; a failed query returns
    None.

    Pins spec §4: the provenance mapping gating promptless heal (item 19).
    """
    out = "workcli v0.1.0\n- work\nprgroom v0.1.0\n- prgroom\n"
    port = UvCliDeploy()
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _FakeCompleted(stdout=out))
    assert port.tool_list() == {
        "workcli": frozenset({"work"}),
        "prgroom": frozenset({"prgroom"}),
    }
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _FakeCompleted(returncode=2))
    assert port.tool_list() is None


def test_tool_install_exports_constraints_when_lock_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Given a package dir with a uv.lock
    When tool_install runs
    Then it first runs `uv export --frozen --no-dev --no-emit-project`, then
    `uv tool install --constraints <file> <dir>`; force=True adds --force;
    a lock-less package installs unconstrained.

    Pins spec §4 / items 16, 18 (lock-respecting + non-forcing fresh).
    """
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_k: object) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", _record)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "uv.lock").write_text("lock")
    port = UvCliDeploy()
    assert port.tool_install(pkg, force=False).ok
    assert calls[0][:2] == ["uv", "export"]
    assert "--frozen" in calls[0] and "--no-emit-project" in calls[0]
    assert calls[1][:3] == ["uv", "tool", "install"]
    assert "--constraints" in calls[1] and "--force" not in calls[1]

    calls.clear()
    lockless = tmp_path / "lockless"
    lockless.mkdir()
    assert port.tool_install(lockless, force=True).ok
    assert calls[0][:3] == ["uv", "tool", "install"]
    assert "--force" in calls[0] and "--constraints" not in calls[0]


def test_subprocess_failures_map_to_not_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Given TimeoutExpired / FileNotFoundError / non-zero exit from uv
    When tool_uninstall or smoke runs
    Then CommandResult(ok=False, output=...) is returned, never an exception.

    Pins spec §4/§8: fail loud via the result, no exception leakage.
    """
    port = UvCliDeploy()

    def _timeout(*_a: object, **_k: object) -> _FakeCompleted:
        raise subprocess.TimeoutExpired(cmd="uv", timeout=1)

    monkeypatch.setattr(subprocess, "run", _timeout)
    assert not port.tool_uninstall("workcli").ok

    def _missing(*_a: object, **_k: object) -> _FakeCompleted:
        raise FileNotFoundError("no shim")  # noqa: TRY003  # test double

    monkeypatch.setattr(subprocess, "run", _missing)
    assert not port.smoke(tmp_path / "bin" / "work", ("--protocol-version",)).ok
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: _FakeCompleted(returncode=1, stderr="boom")
    )
    result = port.tool_uninstall("workcli")
    assert not result.ok and "boom" in result.output


def test_update_shell_already_configured_counts_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given `uv tool update-shell` exiting non-zero because the shell config
    already contains the PATH entry
    When update_shell() runs
    Then the result is ok=True (expected steady state — repeat installs
    from an un-restarted shell stay green); a genuinely different failure
    stays ok=False.

    Pins spec §6 already-configured classification / item 20 (real-impl
    branch; the stage-level behavior is driven through the fake in Task 9).
    """
    port = UvCliDeploy()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: _FakeCompleted(returncode=1, stderr="PATH entry already exists"),
    )
    assert port.update_shell().ok
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_k: _FakeCompleted(returncode=1, stderr="permission denied"),
    )
    assert not port.update_shell().ok


def test_bin_dir_uses_uv_tool_dir_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Given `uv tool dir --bin` succeeding
    When bin_dir() resolves
    Then the printed path wins over every env fallback.

    Pins spec §4: the uv query is the primary source; the env chain is
    fallback only (success arm of item 17).
    """
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "ignored"))
    monkeypatch.setattr(
        subprocess, "run", lambda *_a, **_k: _FakeCompleted(stdout=f"{tmp_path / 'uvdir'}\n")
    )
    assert UvCliDeploy().bin_dir() == tmp_path / "uvdir"


def test_tool_install_export_failure_aborts_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Given a locked package whose `uv export` fails
    When tool_install runs
    Then the failing export result is returned and `uv tool install` never
    runs — a lock-respecting install refuses to proceed unconstrained.

    Pins spec §4 / item 16 export-failure arm.
    """
    calls: list[list[str]] = []

    def _record(cmd: list[str], **_k: object) -> _FakeCompleted:
        calls.append(cmd)
        if cmd[:2] == ["uv", "export"]:
            return _FakeCompleted(returncode=1, stderr="lock out of date")
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", _record)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "uv.lock").write_text("lock")
    result = UvCliDeploy().tool_install(pkg, force=False)
    assert not result.ok and "lock out of date" in result.output
    assert all(c[:3] != ["uv", "tool", "install"] for c in calls)
