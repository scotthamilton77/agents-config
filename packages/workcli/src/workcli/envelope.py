from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TextIO, cast

from workcli import PROTOCOL_VERSION

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ErrorCode(StrEnum):
    NOT_FOUND = "E_NOT_FOUND"
    TYPE_WALL = "E_TYPE_WALL"
    DEP_CYCLE = "E_DEP_CYCLE"
    FIELD_CLOBBER_GUARD = "E_FIELD_CLOBBER_GUARD"
    LOCK_CONTENTION = "E_LOCK_CONTENTION"
    SYNC_BEHIND = "E_SYNC_BEHIND"
    BACKEND_DRIFT = "E_BACKEND_DRIFT"
    UNSUPPORTED_CAPABILITY = "E_UNSUPPORTED_CAPABILITY"
    USAGE = "E_USAGE"
    INTERNAL = "E_INTERNAL"
    DUPLICATE_TITLE = "E_DUPLICATE_TITLE"
    NOT_CLAIMABLE = "E_NOT_CLAIMABLE"
    EVIDENCE = "E_EVIDENCE"
    MANIFEST = "E_MANIFEST"
    TIMEOUT = "E_TIMEOUT"
    TRACK_REQUIRED = "E_TRACK_REQUIRED"
    UNKNOWN_TRACK = "E_UNKNOWN_TRACK"
    NOT_CONFIGURED = "E_NOT_CONFIGURED"
    TRIAGE_INCOMPLETE = "E_TRIAGE_INCOMPLETE"


@dataclass(frozen=True)
class WorkError(Exception):
    code: ErrorCode
    message: str
    detail: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class StepProgress:
    """A `label_mutate`/`sync` mid-sequence failure's replayable progress.

    The seam's only two irreducibly multi-call `Backend` primitives
    (`label_mutate` -- one `bd label` call per label; `sync` --
    `dolt commit` then `dolt push`) can fail after some sub-steps already
    applied. `with_progress` attaches this record to the raised `WorkError`
    so a caller can tell "nothing applied" (no `partial_progress` key --
    contract per decision "absence means atomic") from "these sub-steps
    already applied, retry from the top is safe" (this record present).
    """

    operation: str  # "label_mutate" | "sync"
    steps_total: int
    completed: tuple[str, ...]  # replayable sub-step ids (labels applied; ["commit"])
    failed: str  # the sub-step that failed
    remaining: tuple[str, ...]

    def as_detail(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "operation": self.operation,
            "steps_total": self.steps_total,
            "completed": cast("list[JsonValue]", list(self.completed)),
            "failed": self.failed,
            "remaining": cast("list[JsonValue]", list(self.remaining)),
        }
        return {"partial_progress": payload}


def with_progress(err: WorkError, progress: StepProgress) -> WorkError:
    """Attach `progress` to `err.detail`, preserving `err`'s cause unchanged.

    The cause (`code`/`message`) is preserved, not replaced -- only `detail`
    gains the additive `partial_progress` key.
    """
    return WorkError(err.code, err.message, {**err.detail, **progress.as_detail()})


def emit_success(data: JsonValue, out: TextIO = sys.stdout) -> int:
    json.dump({"protocol": PROTOCOL_VERSION, "ok": True, "data": data, "error": None}, out)
    out.write("\n")
    return 0


def emit_failure(err: WorkError, out: TextIO = sys.stdout) -> int:
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
