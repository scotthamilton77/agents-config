"""`Runners` — the injected outside-world dependency bundle handed to verbs.

`cli.main` builds one `Runners` and passes it to the dispatched verb handler, so
every adapter (git, gh, scc) arrives as an argument rather than a module global.
Pinning the bundle keeps the verb→handler contract stable across slices.

All three adapters are required: `viz pr` reconciles (gh), reads the head-OID
estate + snapshot (git), and scores complexity from a materialized snapshot (scc)
on every run, so `cli.main` always constructs each one.
"""

from __future__ import annotations

from dataclasses import dataclass

from vizsuite.adapters.gh.runner import GhRunner
from vizsuite.adapters.git.runner import GitRunner
from vizsuite.adapters.scc.runner import SccRunner


@dataclass(frozen=True)
class Runners:
    git: GitRunner
    gh: GhRunner
    scc: SccRunner
