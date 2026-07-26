"""S9T1-A10: the executor addresses the tracker only through the facade.

A source scan, not a behavioural test, because the property is about what the
package is *able* to do: a single call site reaching past the facade would be
invisible to any test that did not happen to exercise it.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "executor"

# The facade's backend command, as a whole word. Matching the bare token rather
# than an argv shape is deliberate: a comment or a docstring naming it as
# something to call is the same drift as calling it.
_BACKEND_COMMAND = re.compile(r"\bbd\b")


def _sources() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def test_the_scan_actually_has_sources_to_scan() -> None:
    """
    Given the package source tree
    When it is enumerated
    Then it is not empty.

    The control for the scan below: an empty file list would let the
    never-invoked assertion pass while proving nothing.
    """
    assert len(_sources()) >= 5


def test_no_source_module_names_the_facades_backend() -> None:
    """
    Given every module under the package's source tree
    When each is scanned for the tracker backend's command name
    Then none names it.

    The facade exists to quarantine the backend; an executor that can reach
    past it has un-quarantined it for every consumer downstream.
    """
    offenders = [
        path.name
        for path in _sources()
        if _BACKEND_COMMAND.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_every_outward_invocation_names_a_known_console_script() -> None:
    """
    Given the only module that shells out
    When its argv literals are read
    Then the commands it can spawn are exactly `grind` and `work`.

    Pins the outward surface at its single seam: a third command appearing
    here is a new dependency, not a detail.
    """
    ports = (_SRC / "ports.py").read_text(encoding="utf-8")
    spawned = set(re.findall(r'\[\s*"([a-z][a-z0-9-]*)"', ports))

    assert spawned == {"grind", "work"}
