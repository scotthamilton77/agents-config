"""SubprocessGhRunner: real `gh` subprocess wiring.

`gh api graphql` needs auth + network in CI, so this test never calls the real
binary — it monkeypatches `subprocess.run` to capture the argv/cwd/kwargs the
method actually invokes. That still proves the load-bearing contract:
`repo_root` (never the process cwd) is what `gh` runs against, so `gh`'s own
owner/repo inference reads the injected repo, not wherever the process happens
to be.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from vizsuite.adapters.gh.runner import SubprocessGhRunner


class _RecordingCompletedProcess:
    returncode = 0
    stdout = "{}"
    stderr = ""


def _record_run(calls: list[dict[str, Any]]) -> Any:
    def _fake_run(argv: list[str], **kwargs: Any) -> _RecordingCompletedProcess:
        calls.append({"argv": argv, **kwargs})
        return _RecordingCompletedProcess()

    return _fake_run


def test_pr_graphql_runs_against_the_injected_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _record_run(calls))

    SubprocessGhRunner(repo_root=str(tmp_path)).pr_graphql(7)

    assert len(calls) == 1
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["argv"][:3] == ["gh", "api", "graphql"]


def test_default_repo_root_is_dot(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(subprocess, "run", _record_run(calls))

    SubprocessGhRunner().pr_graphql(1)

    assert calls[0]["cwd"] == "."
