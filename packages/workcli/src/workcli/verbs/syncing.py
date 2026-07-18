"""sync — the sync verb.

Same shape as the other verb modules: a pure function over a `Backend`.
"""

from __future__ import annotations

import dataclasses
from argparse import Namespace
from typing import cast

from workcli.backend import Backend, SyncSupport
from workcli.envelope import JsonValue
from workcli.model import SyncResult


def sync(backend: Backend, args: Namespace) -> JsonValue:
    """`work sync [--pull]` (decision 9): default = commit+push; `--pull` = pull.

    `SERVER_AUTHORITATIVE` backends have nothing to sync -- an honest no-op
    success (`synced: false`, `mode: "noop"`) without ever calling
    `backend.sync`. `UNSUPPORTED` is already refused at the capability gate
    before this handler runs, so only `NATIVE` reaches the real call.
    """
    if backend.capabilities.sync is SyncSupport.SERVER_AUTHORITATIVE:
        result = SyncResult(synced=False, mode="noop")
    else:
        result = backend.sync(pull=args.pull)
    return cast("dict[str, JsonValue]", dataclasses.asdict(result))
