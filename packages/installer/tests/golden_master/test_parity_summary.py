"""Golden-master Summary-stdout parity: bash ``install.sh`` vs Python ``install.py``.

The other golden-master scenarios compare the installed FILE TREES (``ParityResult.
diff()`` over the two HOME dirs); none of them looks at stdout. The install Summary
block (``scripts/install.sh:1801-1869``) is terminal output, not a file, so without
a stdout oracle the renderer's byte-parity with bash has no regression net — header
wrapping, leading blank lines, and field padding could all drift while every
tree-diff test stayed green. This module is that oracle: it captures BOTH installers'
stdout, normalizes the *known-systemic* differences, and byte-compares the Summary
region.

Two systemic differences are normalized away (everything else must match byte-for-byte):

- **The volatile install count.** ``Installed:  N`` differs by a small constant
  (bash counts a prgroom-adjacent file the Python port does not yet stage). The
  count is not what this test pins — the *shape* of the Summary is — so the numeric
  value on the ``Installed:`` line is canonicalized.
- **The ``ok()`` glyph.** bash prints ``+  Done.`` and the Python ``TerminalIO.ok``
  prints ``✓ Done.``. That glyph divergence is a pre-existing ``IOPort`` property
  (not introduced by the Summary renderer) tracked separately; it is canonicalized
  on the ``Done.`` line so it does not mask a real Summary regression.

The beads fixture (``INSTALLER_PLUGINS_SRC`` -> a tree containing ``beads/``) is
required: bash hardcodes ``ALL_PLUGINS=(beads)`` while the Python port *discovers*
plugins from the source root, so the two only agree on the ``-- beads (not detected,
skipped) --`` footer when beads is actually present in the plugin source tree (real
``src/plugins/beads`` is archived out, mirroring ``test_parity_plugins.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity

pytestmark = pytest.mark.golden_master

# A beads-bearing plugin source so both installers agree on the plugin universe
# (bash's hardcoded ALL_PLUGINS=(beads) vs the Python port's discovery). Same
# fixture the route/overlay plugin-parity scenarios use.
_FIXTURE_BASIC = Path(__file__).parent / "fixtures" / "plugins" / "basic"

# claude only, no active plugins, verbose -> the full per-tool block form with
# '(not detected, skipped)' footers for every other tool and for beads.
_VERBOSE_ARGS = ["--tools=claude", "--plugins=", "--yes", "--verbose"]

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# The volatile install count on the 'Installed:' field line (verbose block).
_INSTALLED_LINE = re.compile(r"^(\s*Installed:\s+)\d+$")
# The ok() 'Done.' line, whichever glyph/spacing the IOPort used.
_DONE_LINE = re.compile(r"^[+✓]\s+Done\.$")


def _normalize_summary(stdout: str) -> list[str]:
    """Reduce raw installer stdout to the Summary region, ANSI-stripped, with the
    two systemic differences (install count, ok() glyph) canonicalized.

    Returns the Summary lines from the ``-- Summary --`` header onward so the
    pre-Summary install chatter (which legitimately differs line-for-line) is
    excluded — this test pins the Summary block's shape, not the whole transcript.
    """
    lines = _ANSI.sub("", stdout).splitlines()
    try:
        start = lines.index("-- Summary --")
    except ValueError:  # pragma: no cover - a missing header is an assertion failure below
        return []
    normalized: list[str] = []
    for line in lines[start:]:
        line = _INSTALLED_LINE.sub(r"\1<count>", line)
        if _DONE_LINE.match(line):
            line = "<ok> Done."
        normalized.append(line)
    return normalized


def test_verbose_summary_stdout_is_byte_parity(tmp_path: Path) -> None:
    """The verbose Summary block printed by the Python renderer byte-matches the
    bash installer's, once the install count and the pre-existing ok() glyph are
    canonicalized. This is the load-bearing parity proof for the Summary renderer:
    header wrapping ('-- Summary --', '-- claude --'), the leading blank line
    before every block/footer, the six field labels + padding, the
    '(not detected, skipped)' footers, and the blank line before Done. — any drift
    in those fails here, where the tree-diff scenarios are blind.
    """
    result = run_parity(tmp_path, args=_VERBOSE_ARGS, plugins_src=_FIXTURE_BASIC)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr

    bash_summary = _normalize_summary(result.bash_stdout)
    python_summary = _normalize_summary(result.python_stdout)

    assert bash_summary, f"bash emitted no Summary block:\n{result.bash_stdout}"
    assert python_summary, f"python emitted no Summary block:\n{result.python_stdout}"
    # Anchor the systemic-difference assumptions: a per-tool block (proving the
    # field rows are present to be compared) and the canonicalized footer/Done.
    assert "-- claude --" in bash_summary
    assert "-- beads (not detected, skipped) --" in bash_summary
    assert bash_summary[-1] == "<ok> Done."
    # The load-bearing assertion: the Summary regions match line-for-line.
    assert python_summary == bash_summary, (
        "Summary stdout diverged from bash oracle.\n"
        f"bash:\n{chr(10).join(bash_summary)}\n\n"
        f"python:\n{chr(10).join(python_summary)}"
    )
