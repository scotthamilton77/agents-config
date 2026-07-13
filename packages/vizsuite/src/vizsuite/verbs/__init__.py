"""VERBS registry: maps a verb name to its handler `(Runners, Namespace) -> JsonValue`.

`cli.main` looks the handler up here after argparse has already rejected any
unknown subcommand, so a name reaching dispatch is always registered. Slice 1
ships one verb, `pr`; later slices register more here.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable

from vizsuite.envelope import JsonValue
from vizsuite.runners import Runners
from vizsuite.verbs.pr import pr

VERBS: dict[str, Callable[[Runners, Namespace], JsonValue]] = {
    "pr": pr,
}
