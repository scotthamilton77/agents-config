"""Stdout normalization for golden-master parity tests.

The tree-diff scenarios (``ParityResult.diff()``) compare installed FILE TREES;
none looks at stdout. Terminal output therefore had no regression net beyond the
Summary block (``test_parity_summary.py``). This module is the shared normalizer
that lets a test byte-compare a region of BOTH installers' stdout for MEANINGFUL
parity — content and structure — without tripping on incidental rendering.

Each rule is a documented, blessed exception. Where bash emits a cosmetic wart
the Python port need not reproduce (a missing space after a comma, trailing
whitespace), the wart is normalized away on BOTH sides rather than mirrored into
the Python output — meaningful-parity, not byte-mimicry.

Normalized (everything else must match line-for-line):

- **ANSI SGR escapes** — bash colorizes via ``${CYAN}``…; the Python ``rich``
  console strips styling against a captured (non-TTY) pipe. Pure decoration.
- **Leading status glyph** — bash prints ``i``/``+``/``!`` + two spaces; the
  Python ``IOPort`` prints ``✓``/``⚠`` + one space (and emits no glyph at all
  for ``info``/``header``). The glyph CHARACTER divergence is a pre-existing
  ``IOPort`` property tracked separately; the message text is the parity
  contract, so the glyph is stripped on both sides. Severity is therefore not
  asserted by these oracles — a known, accepted limitation.
- **Volatile install count** — bash counts a prgroom-adjacent file the Python
  port does not stage, so ``N installed`` / ``Installed:  N`` differ by a small
  constant. The SHAPE of the line is pinned, not the value. Every OTHER count
  (backed up / pruned / updated / merged / skipped) is deterministic and is
  left intact so the oracle still asserts it.
- **Comma spacing** — bash's count footer omits the space after the comma
  (``2 backed up,2 pruned``); the Python port emits the (nicer) space. Cosmetic
  bash wart — comma spacing is canonicalized on both sides.
- **Temp HOME path** — the two installers write into sibling temp homes
  (``home_a`` / ``home_b``); the absolute path is replaced with ``<HOME>`` so a
  path-bearing line (e.g. an orphan entry) compares by structure.
- **Trailing whitespace** — stripped per line (printf padding can leave it).

Callers MUST pin the rich console width (``COLUMNS`` in ``run_parity(env=…)``)
so the Python port does not hard-wrap long lines mid-token against the captured
pipe — a non-TTY artifact whose break point is path-length-volatile.
"""

from __future__ import annotations

import re
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Leading status glyph: bash 'i'/'+'/'!'/'x' + two spaces, or the Python IOPort's
# '✓'/'⚠'/'✗' + one space. Anchored so only a true status prefix is stripped:
# namespace ('  skills/'), orphan ('    [dir] …'), header ('-- … --'), and footer
# ('   claude: …') lines do not start with a glyph+spacing and are left intact.
_GLYPH = re.compile(r"^(?:[i+!x]  |[✓⚠✗] )")
# The volatile install count (footer 'N installed' and the verbose 'Installed:' field).
_INSTALLED_FOOTER = re.compile(r"\b\d+ installed\b")
_INSTALLED_FIELD = re.compile(r"^(\s*Installed:\s+)\d+$")
# bash's count footer omits the space after the comma ('2 backed up,2 pruned'); the
# Python port emits it. The canon is anchored to the count vocabulary (lookahead) so
# it ONLY ever touches that footer — never a comma inside a path or message body,
# which would silently mask a real divergence in this regression net.
_COMMA = re.compile(r",\s*(?=\d+ (?:installed|updated|merged|backed up|pruned|skipped))")


def normalize(stdout: str, *, homes: tuple[Path, ...]) -> list[str]:
    """Canonicalize one installer's stdout to a list of comparable lines."""
    lines = _ANSI.sub("", stdout).splitlines()
    out: list[str] = []
    for raw in lines:
        line = raw
        for home in homes:
            line = line.replace(str(home), "<HOME>")
        line = _GLYPH.sub("", line)
        line = _INSTALLED_FIELD.sub(r"\1<count>", line)
        line = _INSTALLED_FOOTER.sub("<count> installed", line)
        line = _COMMA.sub(", ", line)
        out.append(line.rstrip())
    return out


def region_from(lines: list[str], marker: str) -> list[str]:
    """Slice ``lines`` from the first occurrence of ``marker`` to the end.

    Used to scope a comparison to a region (e.g. the verbose Summary block) when
    earlier lines legitimately diverge (the verbose per-file install chatter is
    an accepted, intended divergence). Returns ``[]`` when the marker is absent
    so the caller's emptiness assertion gives a clear failure.
    """
    try:
        start = lines.index(marker)
    except ValueError:  # pragma: no cover - absence is an assertion failure in the caller
        return []
    return lines[start:]
