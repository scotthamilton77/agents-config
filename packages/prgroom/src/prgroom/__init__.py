"""prgroom — deterministic PR-grooming CLI.

This package is prgroom's MVP: state schema, the ``prsession.Store``
Protocol + adapters, the precondition/error tier model, the escalation sink, a
TOML config loader, the clock/randomness injection seam, the agent-dispatch
contract Protocols, and the wired CLI.
"""

from __future__ import annotations

from importlib.metadata import version

# Read from the installed distribution's metadata rather than written twice: a
# literal here and a version in the project file drift, and the version is what a
# caller compares an installed prgroom against to see that it went stale.
__version__ = version("prgroom")
