"""CLI dispatch + envelope invariants (spec test item 12).

Every machine invocation emits exactly one JSON envelope on stdout with the exit
code mirroring `ok`, on both the success and failure paths. Usage errors reach
the `E_USAGE` envelope (never argparse's stderr-and-exit), and the protocol
handshake never touches any adapter.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

import pytest

from tests.conftest import run_cli
from vizsuite import PROTOCOL_VERSION
from vizsuite.adapters.git.runner import LsTreeRow
from vizsuite.cli import main


class _ExplodingGitRunner:
    """A `GitRunner` that fails the test the instant it is asked to do anything.

    Proves `--protocol-version` never constructs/uses an adapter: if the
    handshake path regresses into touching git, this raises instead of silently
    passing.
    """

    def ls_tree(self, rev: str) -> list[LsTreeRow]:
        raise AssertionError(f"handshake/usage path must never call git, got rev={rev!r}")


def test_protocol_version_success_envelope_touches_no_adapter():
    exit_code, envelope, stderr = run_cli(["--protocol-version"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    assert stderr == ""
    assert envelope == {
        "protocol": PROTOCOL_VERSION,
        "ok": True,
        "data": {"protocol": "1"},
        "error": None,
    }


def test_unknown_verb_yields_usage_envelope_not_argparse_stderr_dump():
    exit_code, envelope, stderr = run_cli(["bogus-verb"], git_runner=_ExplodingGitRunner())

    assert exit_code == 1
    assert stderr == ""
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"


def test_unknown_flag_inside_pr_yields_usage_envelope():
    exit_code, envelope, stderr = run_cli(["pr", "--bogus"], git_runner=_ExplodingGitRunner())

    assert exit_code == 1
    assert stderr == ""
    assert envelope["error"]["code"] == "E_USAGE"


def test_missing_verb_reads_as_missing_not_none():
    exit_code, envelope, stderr = run_cli([], git_runner=_ExplodingGitRunner())

    assert exit_code == 1
    assert stderr == ""
    assert envelope["error"]["code"] == "E_USAGE"
    assert "no verb given" in envelope["error"]["message"]
    assert "None" not in envelope["error"]["message"]


def test_invalid_format_value_yields_usage_envelope_with_clean_stderr():
    # The invalid --format value fails the main parse; the lenient peek also
    # cannot resolve it and falls back to json, so nothing renders to stderr.
    exit_code, envelope, stderr = run_cli(["--format", "bogus"], git_runner=_ExplodingGitRunner())

    assert exit_code == 1
    assert stderr == ""
    assert envelope["error"]["code"] == "E_USAGE"


def _run(argv: Sequence[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    exit_code = main(argv, git_runner=_ExplodingGitRunner(), out=out, err=err)
    return exit_code, out.getvalue(), err.getvalue()


def test_format_human_renders_success_to_stderr_alongside_stdout_envelope():
    exit_code, stdout, stderr = _run(["--protocol-version", "--format", "human"])

    assert exit_code == 0
    assert json.loads(stdout)["ok"] is True  # stdout still carries the envelope
    assert stderr.startswith("ok\n")  # human view added on stderr


def test_format_human_renders_error_to_stderr_on_missing_verb():
    exit_code, stdout, stderr = _run(["--format", "human"])

    assert exit_code == 1
    assert json.loads(stdout)["error"]["code"] == "E_USAGE"
    assert stderr.startswith("error\n")


def test_format_human_recovered_by_peek_on_usage_error():
    # The parse fails on the unknown verb *before* argparse records --format, so
    # the lenient peek recovers "human" and still renders the error to stderr.
    exit_code, stdout, stderr = _run(["--format", "human", "bogus-verb"])

    assert exit_code == 1
    assert json.loads(stdout)["error"]["code"] == "E_USAGE"
    assert stderr.startswith("error\n")


def test_main_defaults_to_real_streams(capsys: pytest.CaptureFixture[str]):
    exit_code = main(["--protocol-version"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["data"] == {"protocol": "1"}
    assert captured.err == ""


def test_handler_receives_main_s_resolved_repo_root_as_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`cli.main` resolves `Path.cwd()` exactly once and threads it into the
    dispatched handler's third positional argument as a `Path` — verbs must
    never re-resolve `Path.cwd()` themselves."""
    monkeypatch.chdir(tmp_path)
    captured: list[Path] = []

    def _fake_pr(_runners: object, _args: object, repo_root: Path) -> dict[str, object]:
        captured.append(repo_root)
        return {"ok": True}

    import vizsuite.cli as cli_module

    monkeypatch.setitem(cli_module.VERBS, "pr", _fake_pr)

    exit_code, envelope, _stderr = run_cli(["pr", "1"], git_runner=_ExplodingGitRunner())

    assert exit_code == 0
    assert envelope["data"] == {"ok": True}
    assert captured == [Path.cwd()]
    assert isinstance(captured[0], Path)


def test_default_runners_pin_repo_root_to_invocation_cwd(monkeypatch: pytest.MonkeyPatch):
    """The default runners get an absolute repo root captured at construction —
    `cwd="."` would re-resolve against the live process cwd on every subprocess
    spawn, so a mid-process `chdir` could silently retarget them."""
    captured: list[str] = []

    class _RecordingRunner:
        def __init__(self, repo_root: str = ".") -> None:
            captured.append(repo_root)

    monkeypatch.setattr("vizsuite.cli.SubprocessGitRunner", _RecordingRunner)
    monkeypatch.setattr("vizsuite.cli.SubprocessGhRunner", _RecordingRunner)

    exit_code, envelope, _ = run_cli(["pr", "1"])

    # The recorder has no verb methods, so the handler dies after construction;
    # the envelope invariant must still hold (single E_INTERNAL envelope).
    assert exit_code == 1
    assert envelope["error"]["code"] == "E_INTERNAL"
    assert len(captured) == 2
    assert all(root == str(Path.cwd()) and Path(root).is_absolute() for root in captured)
