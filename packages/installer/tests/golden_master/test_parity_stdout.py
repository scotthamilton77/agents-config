"""Golden-master stdout parity beyond the Summary block: bash ``install.sh`` vs
Python ``install.py``.

``test_parity_summary.py`` pins the verbose Summary region. This module pins the
output the tree-diff scenarios are blind to in the OTHER modes:

- **default (non-verbose) mode** — the whole transcript: the run-mode notice, the
  excluded-plugin warning, the trailing ``Done.`` and the per-tool count footer.
  Non-verbose mode emits no per-file chatter, so the full transcript is a clean
  parity contract.
- **prune mode** — the orphan list (header framing, per-namespace grouping, the
  ``[dir]``/``[file]`` type tags), the ``Pruned`` line, and the count footer.

Both run with the beads fixture and ``--plugins=`` so the excluded-plugin universe
agrees (bash hardcodes ``ALL_PLUGINS=(beads)``; the Python port discovers from the
source root — they only agree when beads is present in the plugin source), and with
a wide ``COLUMNS`` so the Python ``rich`` console does not hard-wrap path-bearing
lines against the captured pipe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity
from tests.golden_master._stdout import normalize

pytestmark = pytest.mark.golden_master

# beads-bearing plugin source so both installers agree on the plugin universe
# (see module docstring). Same fixture the summary / route parity scenarios use.
_FIXTURE_BASIC = Path(__file__).parent / "fixtures" / "plugins" / "basic"

# Pin the rich console wide enough that no line wraps against the captured pipe.
_WIDE_ENV = {"COLUMNS": "1000"}


def test_default_mode_transcript_is_parity(tmp_path: Path) -> None:
    """Default (non-verbose) install: the ENTIRE stdout transcript byte-matches
    the bash installer once the systemic differences are normalized. This is the
    regression net for the run-mode notice ('Auto-yes mode …'), the excluded-plugin
    warning, the trailing 'Done.', and the per-tool count footer — none of which a
    tree-diff scenario can see.
    """
    result = run_parity(
        tmp_path,
        args=["--tools=claude", "--plugins=", "--yes"],
        plugins_src=_FIXTURE_BASIC,
        env=_WIDE_ENV,
    )

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr

    homes = (result.home_a, result.home_b)
    bash = normalize(result.bash_stdout, homes=homes)
    python = normalize(result.python_stdout, homes=homes)

    # Anchor the systemic-difference assumptions: the run-mode notice and the
    # excluded-plugin warning are the lines the Python port was missing/diverging
    # on, so prove they are present in the bash oracle before the line-for-line
    # compare makes them load-bearing.
    assert "Auto-yes mode -- prompts and diffs suppressed" in bash
    assert any("Plugin 'beads' excluded via --plugins=" in line for line in bash)
    assert bash[-1] == "   claude: <count> installed"

    assert python == bash, (
        "Default-mode stdout diverged from the bash oracle.\n"
        f"bash:\n{chr(10).join(bash)}\n\n"
        f"python:\n{chr(10).join(python)}"
    )


def _seed_orphans(home: Path) -> None:
    """Seed two retired entries (a skill dir + an agent file) into the Claude tree.

    Both globs are on the bash prune-list and the Python ``installer.toml`` prune
    list, so a ``--prune-only`` run finds exactly these two orphans on both sides.
    Mirrors ``test_parity_prune._seed_orphans``.
    """
    skills = home / ".claude" / "skills"
    agents = home / ".claude" / "agents"
    skills.mkdir(parents=True, exist_ok=True)
    agents.mkdir(parents=True, exist_ok=True)
    orphan_skill = skills / "condition-based-waiting"
    orphan_skill.mkdir()
    (orphan_skill / "SKILL.md").write_text("# retired skill\n")
    (agents / "bead-implementor.md").write_text("# retired agent\n")


def test_prune_only_transcript_is_parity(tmp_path: Path) -> None:
    """--prune-only with two seeded orphans: the ENTIRE prune transcript byte-matches
    the bash installer once systemic differences are normalized. This is the
    regression net for the orphan-list framing ('-- Orphans detected (N total) --'),
    the per-namespace grouping, the '[dir]'/'[file]' type tags, the 'Pruned' line,
    and the count footer — none visible to a tree-diff scenario.
    """
    result = run_parity(
        tmp_path,
        args=["--tools=claude", "--plugins=", "--yes", "--prune-only"],
        seed=_seed_orphans,
        plugins_src=_FIXTURE_BASIC,
        env=_WIDE_ENV,
    )

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr

    homes = (result.home_a, result.home_b)
    bash = normalize(result.bash_stdout, homes=homes)
    python = normalize(result.python_stdout, homes=homes)

    # Anchor: the orphan-list framing + the type tags are exactly what the Python
    # port diverged on, so prove they are present in the bash oracle before the
    # line-for-line compare makes them load-bearing.
    assert "-- Orphans detected (2 total) --" in bash
    assert any(line.startswith("    [dir] ") for line in bash)
    assert any(line.startswith("    [file] ") for line in bash)
    assert "   claude: 2 backed up, 2 pruned" in bash

    assert python == bash, (
        "Prune-only stdout diverged from the bash oracle.\n"
        f"bash:\n{chr(10).join(bash)}\n\n"
        f"python:\n{chr(10).join(python)}"
    )
