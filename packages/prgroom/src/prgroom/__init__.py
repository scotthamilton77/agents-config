"""prgroom — deterministic PR-grooming CLI.

This package is prgroom's MVP: state schema, the ``prsession.Store``
Protocol + adapters, the precondition/error tier model, the escalation sink, a
TOML config loader, the clock/randomness injection seam, the agent-dispatch
contract Protocols, and the wired CLI.
"""

from __future__ import annotations

__version__ = "0.1.0"
