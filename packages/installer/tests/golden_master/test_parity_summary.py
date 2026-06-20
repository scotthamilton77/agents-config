"""Golden-master Summary-stdout parity: bash ``install.sh`` vs Python ``install.py``.

The other golden-master scenarios compare the installed FILE TREES (``ParityResult.
diff()`` over the two HOME dirs); none of them looks at stdout. The install Summary
block (``scripts/install.sh:1801-1869``) is terminal output, not a file, so without
a stdout oracle the renderer's byte-parity with bash has no regression net — header
wrapping, leading blank lines, and field padding could all drift while every
tree-diff test stayed green. This module is that oracle for the VERBOSE Summary
region; ``test_parity_stdout.py`` covers the default-mode and prune transcripts.

The comparison is scoped to the ``-- Summary --`` region: in verbose mode the
pre-Summary per-file install chatter legitimately differs line-for-line (an
intended divergence of the rewrite). The shared normalizer (``_stdout.normalize``)
canonicalizes the systemic differences — ANSI styling, the ``ok()`` glyph, and the
volatile install count (bash counts a prgroom-adjacent file the Python port does
not stage); see that module for the full, documented rule set.

The beads fixture (``INSTALLER_PLUGINS_SRC`` -> a tree containing ``beads/``) is
required: bash hardcodes ``ALL_PLUGINS=(beads)`` while the Python port *discovers*
plugins from the source root, so the two only agree on the ``-- beads (not detected,
skipped) --`` footer when beads is actually present in the plugin source tree (real
``src/plugins/beads`` is archived out, mirroring ``test_parity_plugins.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.golden_master._runner import run_parity
from tests.golden_master._stdout import normalize, region_from

pytestmark = pytest.mark.golden_master

# A beads-bearing plugin source so both installers agree on the plugin universe
# (bash's hardcoded ALL_PLUGINS=(beads) vs the Python port's discovery). Same
# fixture the route/overlay plugin-parity scenarios use.
_FIXTURE_BASIC = Path(__file__).parent / "fixtures" / "plugins" / "basic"

# claude only, no active plugins, verbose -> the full per-tool block form with
# '(not detected, skipped)' footers for every other tool and for beads.
_VERBOSE_ARGS = ["--tools=claude", "--plugins=", "--yes", "--verbose"]

# Pin the rich console wide enough that no line wraps against the captured pipe.
_WIDE_ENV = {"COLUMNS": "1000"}


def test_verbose_summary_stdout_is_byte_parity(tmp_path: Path) -> None:
    """The verbose Summary block printed by the Python renderer byte-matches the
    bash installer's, once the shared systemic differences are normalized. This is
    the load-bearing parity proof for the Summary renderer: header wrapping
    ('-- Summary --', '-- claude --'), the leading blank line before every
    block/footer, the six field labels + padding, the '(not detected, skipped)'
    footers, and the blank line before Done. — any drift in those fails here, where
    the tree-diff scenarios are blind.
    """
    result = run_parity(tmp_path, args=_VERBOSE_ARGS, plugins_src=_FIXTURE_BASIC, env=_WIDE_ENV)

    assert result.bash_returncode == 0, result.bash_stderr
    assert result.python_returncode == 0, result.python_stderr

    homes = (result.home_a, result.home_b)
    bash_summary = region_from(normalize(result.bash_stdout, homes=homes), "-- Summary --")
    python_summary = region_from(normalize(result.python_stdout, homes=homes), "-- Summary --")

    assert bash_summary, f"bash emitted no Summary block:\n{result.bash_stdout}"
    assert python_summary, f"python emitted no Summary block:\n{result.python_stdout}"
    # Anchor the systemic-difference assumptions: a per-tool block (proving the
    # field rows are present to be compared) and the canonicalized footer/Done.
    assert "-- claude --" in bash_summary
    assert "-- beads (not detected, skipped) --" in bash_summary
    assert bash_summary[-1] == "Done."
    # The load-bearing assertion: the Summary regions match line-for-line.
    assert python_summary == bash_summary, (
        "Summary stdout diverged from bash oracle.\n"
        f"bash:\n{chr(10).join(bash_summary)}\n\n"
        f"python:\n{chr(10).join(python_summary)}"
    )
