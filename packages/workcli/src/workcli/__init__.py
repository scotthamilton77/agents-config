"""workcli — the `work` CLI transport layer.

Quarantines the issue-tracker backend (bd) behind a stable, versioned JSON
envelope contract. See ``docs/specs/2026-07-04-work-facade-cli-contract.md``
for the behavioral spec this package implements.
"""

from __future__ import annotations

PROTOCOL_VERSION = "1.3"
