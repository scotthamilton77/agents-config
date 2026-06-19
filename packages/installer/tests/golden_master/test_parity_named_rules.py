"""Golden-master parity for the named-RULES subset DYNAMIC-INCLUDE form.

No live ``src/`` template carries a ``<!-- DYNAMIC-INCLUDE-RULES: a,b -->``
marker, so the full end-to-end parity suite (``test_parity.py``) never exercises
the named-subset path. This module closes that gap with a *function-level*
differential: it drives the real bash ``flatten_agents_md`` (extracted verbatim
from ``scripts/install.sh``) and the Python ``flatten_template`` over the same
template and rules tree.

INTENTIONAL DIVERGENCE — the bash reference is buggy here. The ``flatten_agents_md``
inner rules loop omits the ``|| [[ -n "$rule_name" ]]`` guard that its outer loop
has, so the last comma-field of a named-RULES marker (which arrives with no
trailing newline after ``tr ',' '\\n'``) is dropped: a single-name subset inlines
nothing, and ``a,b`` inlines only ``a``. The Python port corrects this — it
inlines every listed rule. So this module:

- asserts byte-for-byte parity ONLY on inputs whose trailing field is a no-op
  anyway (a trailing empty / missing entry — where the bash bug has no
  observable effect), and
- asserts the Python port's *correct* behaviour on a single-name subset, the
  exact input where bash silently drops the rule.

See ``scripts/AGENTS.md`` for the bash-bug write-up.

Marked ``golden_master`` (it spawns bash) so it stays out of the fast coverage
gate; the Python branch coverage for ``_resolve_named_rules`` is carried by the
unit tests in ``tests/unit/test_templates.py``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from installer.core.io_port import ScriptedIO
from installer.core.templates import flatten_template

pytestmark = pytest.mark.golden_master

# ``test_parity_named_rules.py`` lives at
# ``<repo>/packages/installer/tests/golden_master/``; the fourth parent is the
# repo root that holds ``scripts/install.sh``.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_INSTALL_SH = _REPO_ROOT / "scripts" / "install.sh"
_BASH = shutil.which("bash") or "bash"

# The fixed source dir the named-RULES form resolves from (relative to the
# project root the bash function receives as its third argument).
_RULES_RELDIR = "src/user/.claude/rules"


def _extract_flatten_fn() -> str:
    """The verbatim ``flatten_agents_md`` function body from the real install.sh.

    install.sh has no ``BASH_SOURCE`` main-guard, so sourcing it whole would run
    the entire installer. Slicing out just the function lets the harness call it
    in isolation without that side effect, while keeping the bash under test the
    exact bytes that ship.
    """
    text = _INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r"^flatten_agents_md\(\) \{.*?^\}$", text, re.DOTALL | re.MULTILINE)
    assert match is not None, "could not locate flatten_agents_md in install.sh"
    return match.group(0)


def _run_bash_flatten(template: str, project_root: Path) -> str:
    """Run the extracted bash ``flatten_agents_md`` and return the flattened text."""
    (project_root / "template.md").write_text(template, encoding="utf-8")
    harness = (
        "warn() { :; }\n"  # stub the installer's warn so missing rules don't abort
        f"{_extract_flatten_fn()}\n"
        'flatten_agents_md "$1/template.md" "$1/out.md" "$1" "$1/.staging"\n'
    )
    (project_root / "harness.sh").write_text(harness, encoding="utf-8")
    subprocess.run(  # noqa: S603 — fixed argv, no shell, hermetic input
        [_BASH, str(project_root / "harness.sh"), str(project_root)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (project_root / "out.md").read_text(encoding="utf-8")


def _write_rule(project_root: Path, name: str, body: str) -> None:
    rules = project_root / _RULES_RELDIR
    rules.mkdir(parents=True, exist_ok=True)
    (rules / f"{name}.md").write_text(body, encoding="utf-8")


def test_named_rules_subset_matches_bash_on_bug_neutral_input(tmp_path: Path) -> None:
    """Given a named-RULES marker whose TRAILING field is a no-op (a missing
    rule), the Python ``flatten_template`` output is byte-identical to the real
    bash ``flatten_agents_md`` output. The trailing ``absent`` shields the input
    from the bash inner-loop drop-last-field bug, so order, whitespace-trimming,
    empty-entry skipping, and the ``\\n---\\n`` separator can be compared directly
    against bash."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _write_rule(project_root, "second", "SECOND\n")
    _write_rule(project_root, "first", "FIRST\n")
    template = "top\n<!-- DYNAMIC-INCLUDE-RULES:  second , first ,,absent -->\nbottom\n"

    bash_out = _run_bash_flatten(template, project_root)
    python_out = flatten_template(template, base_dir=project_root, io=ScriptedIO())

    assert python_out == bash_out == "top\nSECOND\n\n---\nFIRST\nbottom\n"


def test_named_rules_single_name_python_correct_where_bash_drops_it(tmp_path: Path) -> None:
    """Given a single-name named-RULES subset — the exact input the bash
    inner-loop bug mishandles — the Python port inlines the rule (correct), while
    the real bash drops it (buggy). This pins the *intentional* divergence: it
    fails if the Python port ever regresses to bash's drop-last-field behaviour,
    and it documents (via the bash assertion) that bash is the broken side."""
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _write_rule(project_root, "solo", "SOLO\n")
    template = "top\n<!-- DYNAMIC-INCLUDE-RULES: solo -->\nbottom\n"

    bash_out = _run_bash_flatten(template, project_root)
    python_out = flatten_template(template, base_dir=project_root, io=ScriptedIO())

    assert python_out == "top\nSOLO\nbottom\n"  # Python: correct
    assert bash_out == "top\nbottom\n"  # bash: drops the only/last field (the bug)
    assert python_out != bash_out  # the divergence is real, not accidental
