"""`Runners` — the injected outside-world dependency bundle handed to verbs.

`cli.main` builds one `Runners` and passes it to the dispatched verb handler, so
every adapter (git today; scc + gh in later slices) arrives as an argument
rather than a module global. Pinning the bundle now keeps the verb→handler
contract stable as slices 2/3 add the scc and gh adapters.

`scc`/`gh` are typed `object | None` because their runner *protocols* do not
exist yet (they are created in slices 3 and 2 respectively); those slices narrow
these fields to the real `SccRunner`/`GhRunner` protocol types.
"""

from __future__ import annotations

from dataclasses import dataclass

from vizsuite.adapters.git.runner import GitRunner


@dataclass(frozen=True)
class Runners:
    git: GitRunner
    scc: object | None = None  # reserved: SubprocessSccRunner lands in slice 3
    gh: object | None = None  # reserved: SubprocessGhRunner lands in slice 2
