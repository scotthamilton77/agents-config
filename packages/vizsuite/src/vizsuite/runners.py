"""`Runners` — the injected outside-world dependency bundle handed to verbs.

`cli.main` builds one `Runners` and passes it to the dispatched verb handler, so
every adapter (git today; scc + gh in later slices) arrives as an argument
rather than a module global. Pinning the bundle now keeps the verb→handler
contract stable as slices 2/3 add the scc and gh adapters.

`scc` is still typed `object | None` because its runner *protocol* does not exist
yet (it is created in slice 3, which narrows the field to the real `SccRunner`
type). `gh` is now the real `GhRunner` — slice 2's reconciler needs it on every
`viz pr`, so `cli.main` always constructs one.
"""

from __future__ import annotations

from dataclasses import dataclass

from vizsuite.adapters.gh.runner import GhRunner
from vizsuite.adapters.git.runner import GitRunner


@dataclass(frozen=True)
class Runners:
    git: GitRunner
    gh: GhRunner
    scc: object | None = None  # reserved: SubprocessSccRunner lands in slice 3
