#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests that the fence in conftest.py keeps every suite here off the network.

Run: uv run conftest_test.py
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent

# Top-level module names that open a connection themselves. A file importing one
# could reach the network without going through an executable the fence controls.
NETWORK_MODULES = frozenset({
    "aiohttp", "ftplib", "http", "httpx", "requests", "smtplib", "socket",
    "socketserver", "ssl", "urllib", "urllib3", "websocket", "websockets", "xmlrpc",
})

# The request runs in a child interpreter because no file here may import a
# network module. The host is under a reserved top-level domain, so the request
# reaches nothing even when the fence is broken.
HTTP_PROBE = "import urllib.request; urllib.request.urlopen('{scheme}://change-record.invalid/', timeout=5)"


def declared_dependencies(path: Path) -> set[str]:
    """Return the dependencies the file's inline script metadata declares."""
    line = re.search(r"^# dependencies = (\[.*\])$", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert line, f"{path.name} declares no dependencies"
    return set(json.loads(line.group(1)))


def imported_modules(path: Path) -> set[str]:
    """Return the top-level name of every module the file imports, at any depth."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.fixture(scope="module")
def path_a_wider_fixture_saw() -> str:
    """Record the search path as a fixture set up before any test of this module sees it."""
    return os.environ["PATH"]


class TestCrL16Fence:
    def test_a_fixture_of_wider_scope_runs_inside_the_fence(
        self, path_a_wider_fixture_saw: str, shim_dir: Path
    ):
        assert path_a_wider_fixture_saw == os.environ["PATH"]
        assert path_a_wider_fixture_saw.split(os.pathsep)[0] == str(shim_dir)

    def test_the_path_holds_only_the_shims_the_interpreter_and_git(self, shim_dir: Path):
        shims, tools = os.environ["PATH"].split(os.pathsep)
        assert Path(shims) == shim_dir
        assert os.listdir(shims) == []
        assert sorted(os.listdir(tools)) == ["git", "python3"]

    def test_the_interpreter_and_git_on_the_path_both_run(self):
        git = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False)
        assert git.returncode == 0, git.stderr
        python = subprocess.run(
            ["python3", "-c", "import jsonschema"], capture_output=True, text=True, check=False
        )
        assert python.returncode == 0, python.stderr

    def test_the_proxy_variables_point_at_a_closed_local_port(self):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            assert os.environ[name] == "http://127.0.0.1:9"
            assert os.environ[name.lower()] == "http://127.0.0.1:9"
        assert os.environ["NO_PROXY"] == ""
        assert os.environ["no_proxy"] == ""

    @pytest.mark.parametrize("name", ["gh", "work"])
    def test_a_call_that_misses_a_shim_fails(self, shim_dir: Path, name: str):
        other = "work" if name == "gh" else "gh"
        shim = shim_dir / other
        shim.write_text("#!/bin/sh\necho shimmed\n", encoding="utf-8")
        shim.chmod(0o755)
        shimmed = subprocess.run([other], capture_output=True, text=True, check=False)
        assert shimmed.stdout == "shimmed\n"
        with pytest.raises(FileNotFoundError):
            subprocess.run([name, "--version"], capture_output=True, check=False)

    @pytest.mark.parametrize("scheme", ["http", "https"])
    def test_a_direct_http_request_fails_at_the_closed_proxy(self, scheme: str):
        probe = subprocess.run(
            [sys.executable, "-c", HTTP_PROBE.format(scheme=scheme)],
            capture_output=True, text=True, check=False,
        )
        assert probe.returncode != 0
        # A refused connection is the proxy's answer. Any other failure, such as a
        # name that does not resolve, would mean the request went past the proxy.
        assert "ConnectionRefusedError" in probe.stderr, probe.stderr

    def test_each_suite_resolves_the_scripts_dependencies_and_pytest(self):
        # The suites run the script on their own interpreter, because the fence
        # keeps the launcher that would resolve the script's metadata off the
        # path. A dependency only a suite declares would hide a script that
        # cannot start on its own.
        script = declared_dependencies(HERE / "change_record.py")
        suites = sorted(HERE.glob("*_test.py"))
        assert len(suites) >= 2
        for suite in suites:
            extra = declared_dependencies(suite) - script
            assert [name for name in extra if not name.startswith("pytest")] == [], suite.name
            assert script <= declared_dependencies(suite), suite.name

    def test_no_script_or_suite_here_imports_an_http_or_socket_module(self):
        sources = sorted(HERE.glob("*.py"))
        expected = {"change_record.py", "change_record_test.py", "conftest.py", "conftest_test.py"}
        assert expected <= {path.name for path in sources}
        for path in sources:
            assert not imported_modules(path) & NETWORK_MODULES, path.name


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
