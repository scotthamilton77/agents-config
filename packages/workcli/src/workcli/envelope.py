from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TextIO

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


@dataclass(frozen=True)
class WorkError(Exception):
    code: ErrorCode
    message: str
    detail: dict[str, JsonValue] = field(default_factory=dict)


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
