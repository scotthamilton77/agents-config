"""`Runners` — the injected outside-world dependency bundle handed to verbs.

`cli.main` builds one `Runners` and passes it to the dispatched verb handler, so
every adapter (git, gh, scc, tracker) arrives as an argument rather than a module
global. Pinning the bundle keeps the verb→handler contract stable across slices.

All four adapters are required: `viz pr` reconciles (gh), reads the head-OID
estate + snapshot (git), and scores complexity from a materialized snapshot (scc)
on every run; `viz verdict` drives edge promotion through `tracker` (wrapped in a
`TrackerPort` by the verb itself, mirroring how `viz pr` wraps `scc`/`gh`). `cli.main`
always constructs each adapter regardless of which verb dispatches.
"""

from __future__ import annotations

from dataclasses import dataclass

from vizsuite.adapters.gh.runner import GhRunner
from vizsuite.adapters.git.runner import GitRunner
from vizsuite.adapters.scc.runner import SccRunner
from vizsuite.tracker.port import TrackerRunner


@dataclass(frozen=True)
class Runners:
    git: GitRunner
    gh: GhRunner
    scc: SccRunner
    tracker: TrackerRunner
