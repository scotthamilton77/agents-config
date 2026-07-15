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
    # sidecar slice: a `.viz/*.json` record file's content doesn't parse into its
    # typed record shape (bad JSON, missing/mistyped field) — never a raw
    # KeyError/JSONDecodeError escaping the sidecar read boundary.
    SIDECAR_MALFORMED = "E_SIDECAR_MALFORMED"
    # sidecar slice: the single-writer advisory lock (`.viz/lock`) is still held
    # by another writer after the bounded retry window — never an unbounded
    # block.
    SIDECAR_LOCKED = "E_SIDECAR_LOCKED"
    # tracker slice: the `work` CLI's protocol-version handshake returned a
    # major version this port was not built against (work-facade contract
    # spec §5: additive fields bump MINOR, a breaking change bumps MAJOR).
    TRACKER_PROTOCOL_MISMATCH = "E_TRACKER_PROTOCOL_MISMATCH"
    # tracker slice: `work`'s stdout did not parse as JSON, or parsed JSON did
    # not match the envelope/data shape this port expects.
    TRACKER_MALFORMED_ENVELOPE = "E_TRACKER_MALFORMED_ENVELOPE"
    # tracker slice: `work` emitted `ok: false` -- the facade's own error code
    # and message are carried in this error's `detail`.
    TRACKER_BACKEND_ERROR = "E_TRACKER_BACKEND_ERROR"
    # tracker slice: the port verb has no mapped `work` verb today (e.g.
    # resequence, spec §5.7) -- never a `bd` shell-out fallback (spec §5.6).
    TRACKER_NOT_SUPPORTED = "E_TRACKER_NOT_SUPPORTED"
    # verdict slice: `dismiss` recorded against a fact that isn't in
    # `recommendations.json` (spec §5.3/§10 item 3: "dismiss is valid only for
    # recommendation-class facts").
    VERDICT_DISMISS_NOT_RECOMMENDATION = "E_VERDICT_DISMISS_NOT_RECOMMENDATION"
    # verdict slice: an edge-class fact's matching descriptor has no bead-id
    # anchor on one (or both) endpoints -- a prose-only plan's edge can be
    # reconciled and verdicted, but never edge-promoted until it gains a real
    # bead anchor.
    VERDICT_NO_BEAD_ANCHOR = "E_VERDICT_NO_BEAD_ANCHOR"
    # verdict slice: an accept-time `blocks` promotion would close a cycle in
    # the full accepted logical dependency graph (spec §5.3/§5.7, test item
    # 17) -- refused with the cycle path in `detail`; no tracker edge written.
    VERDICT_CYCLE_REFUSAL = "E_VERDICT_CYCLE_REFUSAL"


@dataclass
class VizError(Exception):
    """`frozen=True` was previously used here but is unsafe for an `Exception`
    subclass: CPython's exception machinery mutates `__traceback__`/
    `__context__`/`__cause__` on the instance during propagation, and on
    Python 3.14 a nested `@contextmanager` teardown (e.g. `SidecarStore.
    transaction()` wrapping `_locked()`) explicitly assigns `exc.__traceback__`
    while re-throwing into the generator — a frozen dataclass's `__setattr__`
    override turns that assignment into a `FrozenInstanceError`, masking the
    real error with an unrelated crash. Field values still behave as
    immutable by convention (nothing in this codebase mutates a `VizError`
    after construction); only the enforcement is gone.
    """

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
