"""The JSON envelope contract: `{"protocol","ok","data","error"}` on stdout.

Structural mirror of ``workcli``'s envelope. `VizError`/`ErrorCode` model every
*expected* failure so callers handle them from the type without reading the
implementation; unexpected state raises a plain exception that `cli.main`
converts to an `INTERNAL` envelope. The full `ErrorCode` enum is pinned now and
stays stable across all `.2.1` slices even though slice 1 only exercises some
members (a stable contract for the extractors/reconciler that land later).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TextIO

from vizsuite import PROTOCOL_VERSION

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ErrorCode(StrEnum):
    NOT_FOUND = "E_NOT_FOUND"
    USAGE = "E_USAGE"
    INTERNAL = "E_INTERNAL"
    # scc/gh/git subprocess failure, or a materialized-snapshot defect (slice 3).
    ADAPTER_FAILURE = "E_ADAPTER_FAILURE"
    # slice 2: local net file/commit sets disagree with GitHub's un-truncated
    # scalar counts (changedFiles / commits.totalCount).
    RECONCILER_DRIFT = "E_RECONCILER_DRIFT"
    # slice 2: the PR base/head OID is still absent locally after fetch (a stale
    # clone or unreachable remote), so the snapshot cannot be built.
    SNAPSHOT_MISMATCH = "E_SNAPSHOT_MISMATCH"
    # slice 5: a Tier-2/Tier-3-touched scene fact is missing its provenance or
    # citations — the assembler's schema gate refuses to assemble it silently.
    SCHEMA_INVALID = "E_SCHEMA_INVALID"


@dataclass(frozen=True)
class VizError(Exception):
    code: ErrorCode
    message: str
    detail: dict[str, JsonValue] = field(default_factory=dict)


def emit_success(data: JsonValue, out: TextIO = sys.stdout) -> int:
    json.dump({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, out)
    out.write("\n")
    return 0


def emit_failure(err: VizError, out: TextIO = sys.stdout) -> int:
    json.dump(
        {
            "protocol": PROTOCOL_VERSION,
            "ok": False,
            "data": None,
            "error": {"code": str(err.code), "message": err.message, "detail": err.detail},
        },
        out,
    )
    out.write("\n")
    return 1
