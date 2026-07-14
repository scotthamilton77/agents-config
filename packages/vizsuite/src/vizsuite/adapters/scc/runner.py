"""The scc subprocess port — the fake's seam.

`SccRunner` is the interface every complexity test replaces with
`tests/fakes.ScriptedSccRunner`; `SubprocessSccRunner` (added with its preflight
test) is the sole implementation that shells out to the real `scc` binary. The
port returns a *raw* `SccResult` (returncode + stdout + stderr) exactly like the
gh port — every shape decision lives in `scc/parse.py` (`parse_scc`), so the
parse/drift logic is unit-tested against scripted `SccResult`s and the only
uncovered code is the thin `subprocess.run` exec (scc may be absent in CI). scc
scans a *materialized snapshot* dir, never the live checkout, invoked with
`cwd=<snapshot>` on `.` so each `Location` stays repo-relative (plan §3.5).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vizsuite.envelope import ErrorCode, VizError

_SCC_INSTALL_HINT = (
    "scc binary not found on PATH; install scc (https://github.com/boyter/scc) "
    "so `viz pr` can score per-file complexity"
)


@dataclass(frozen=True)
class SccResult:
    returncode: int
    stdout: str
    stderr: str


class SccRunner(Protocol):
    def scan(self, snapshot_dir: Path) -> SccResult: ...  # pragma: no cover


class SubprocessSccRunner:
    """Drives the real `scc` binary, scanning the materialized snapshot dir.

    Preflights `shutil.which("scc")` so a missing binary is a typed
    `VizError(ADAPTER_FAILURE)` with an install hint, not a cryptic subprocess
    error surfacing deep in the verb. scc runs with `cwd=<snapshot>` on `.`, so
    every `Location` it emits is repo-relative and joins the estate.
    """

    def scan(self, snapshot_dir: Path) -> SccResult:
        if shutil.which("scc") is None:
            raise VizError(ErrorCode.ADAPTER_FAILURE, _SCC_INSTALL_HINT)
        return self._run_scc(snapshot_dir)  # pragma: no cover - needs the scc binary on PATH

    def _run_scc(self, snapshot_dir: Path) -> SccResult:  # pragma: no cover - needs scc on PATH
        completed = subprocess.run(
            ["scc", "--by-file", "--format", "json", "."],
            cwd=snapshot_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return SccResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )
