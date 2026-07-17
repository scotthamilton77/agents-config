"""VERBS registry: maps a verb name to its handler
`(Runners, Namespace, repo_root: Path) -> JsonValue`.

`cli.main` looks the handler up here after argparse has already rejected any
unknown subcommand, so a name reaching dispatch is always registered. Slice 1
shipped `pr`; the .2.3 sidecar slices register more here (`queue`, `sweep`,
`verdict`). `repo_root` is resolved from `Path.cwd()` exactly once, in
`cli.main` — no verb may read `Path.cwd()` itself.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

from vizsuite.envelope import JsonValue
from vizsuite.runners import Runners
from vizsuite.verbs.apply import apply
from vizsuite.verbs.pr import pr
from vizsuite.verbs.queue import queue
from vizsuite.verbs.sweep import sweep
from vizsuite.verbs.verdict import verdict

VERBS: dict[str, Callable[[Runners, Namespace, Path], JsonValue]] = {
    "pr": pr,
    "queue": queue,
    "sweep": sweep,
    "verdict": verdict,
    "apply": apply,
}
