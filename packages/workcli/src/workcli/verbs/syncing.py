"""sync — the sync verb.

Same shape as the other verb modules: a pure function over a `Backend`.
"""

from __future__ import annotations

import dataclasses
from argparse import Namespace
from typing import cast

from workcli.backend import Backend
from workcli.envelope import JsonValue


def sync(backend: Backend, args: Namespace) -> JsonValue:
    """`work sync [--pull]` (decision 9): default = commit+push; `--pull` = pull."""
    result = backend.sync(pull=args.pull)
    return cast("dict[str, JsonValue]", dataclasses.asdict(result))
