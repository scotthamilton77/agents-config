"""Cross-language matcher parity: the bash matcher (scripts/lib/installignore.sh)
and the Python matcher (installer.core.installignore) must agree on every fixture
path. Guards the only duplicated logic in the two-installer world. Retires with
bash at the parity gate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from installer.core.installignore import load_installignore

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LIB = _REPO_ROOT / "scripts" / "lib" / "installignore.sh"
# Resolve bash to a full path so the subprocess call carries no partial executable
# path (S607). The golden-master suite already requires bash on PATH.
_BASH = shutil.which("bash") or "bash"

# (name, is_dir, expected) — keep/drop verdicts the two matchers must share.
_CASES = [
    ("AGENTS.md", False, "drop"),
    ("CLAUDE.md", False, "drop"),
    ("GEMINI.md", False, "drop"),
    ("README.md", False, "drop"),
    ("SESSION-PRIMER-README.md", False, "drop"),
    ("AGENTS.md.template", False, "keep"),  # the real instruction file
    ("brainstorming.md", False, "keep"),  # ordinary content
    ("rules-readmes", True, "drop"),
    ("rules-readmes", False, "keep"),  # dir entry must not match a file query
    ("real-skill", True, "keep"),
]


def _bash_verdict(manifest: Path, name: str, is_dir: bool) -> str:
    flag = "true" if is_dir else "false"
    script = (
        f'source "{_LIB}"; load_installignore "{manifest}"; '
        f'if is_installignored "{name}" {flag}; then echo drop; else echo keep; fi'
    )
    out = subprocess.run(  # noqa: S603 — fixed argv, no shell injection (paths are test-local)
        [_BASH, "-c", script], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


@pytest.mark.parametrize(("name", "is_dir", "expected"), _CASES)
def test_bash_and_python_matchers_agree(
    tmp_path: Path, name: str, is_dir: bool, expected: str
) -> None:
    manifest = tmp_path / ".installignore"
    manifest.write_text(
        "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nSESSION-PRIMER-README.md\nrules-readmes/\n",
        encoding="utf-8",
    )
    ignore = load_installignore(manifest)

    python_verdict = "drop" if ignore.excludes(name, is_dir=is_dir) else "keep"
    bash_verdict = _bash_verdict(manifest, name, is_dir)

    assert python_verdict == expected
    assert bash_verdict == expected
    assert python_verdict == bash_verdict
