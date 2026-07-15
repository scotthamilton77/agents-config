"""tracker/port.py — the sole beads boundary (spec §5.6 tracker quarantine).

`TrackerPort` speaks the `work` CLI's JSON-envelope contract
(docs/specs/2026-07-04-work-facade-cli-contract.md) via an injected
`TrackerRunner`, mirroring the gh/git adapter seam (a `Protocol` port plus a
`SubprocessTrackerRunner` implementation and `tests/fakes.ScriptedTrackerRunner`
fake). vizsuite never shells `bd` directly: a verb this port cannot map onto a
`work` verb today (e.g. `resequence` -- the facade has no resequence verb,
spec §5.7) raises a typed `VizError(TRACKER_NOT_SUPPORTED)` rather than
falling back to a direct `bd` invocation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from vizsuite.adapters.subprocess_util import run
from vizsuite.envelope import ErrorCode, VizError

# workcli's PROTOCOL_VERSION is semver MAJOR.MINOR (work-facade contract spec
# §5): additive fields bump MINOR, any breaking envelope/data change bumps
# MAJOR. This port is built against MAJOR "1" -- a mismatch here means a
# breaking contract change the port has not been updated for; a MINOR bump is
# always compatible and never trips this check.
_EXPECTED_PROTOCOL_MAJOR = "1"

DepKind = Literal["blocks", "related-to"]


@dataclass(frozen=True)
class TrackerResult:
    """One `work` subprocess invocation's raw result -- mirrors `gh.runner.GhResult`."""

    returncode: int
    stdout: str
    stderr: str


class TrackerRunner(Protocol):
    def run(self, argv: Sequence[str]) -> TrackerResult: ...  # pragma: no cover


class SubprocessTrackerRunner:
    """Drives the real `work` binary against an injected `repo_root` (default
    ``"."``) -- never the process's actual working directory. One `work`
    invocation per call; the raw result comes back unparsed (every shape
    decision lives in this module's `_run_and_parse`, mirroring how
    `SubprocessGhRunner` defers all parsing to `gh/parse.py`)."""

    def __init__(self, repo_root: str = ".") -> None:
        self._root = repo_root

    def run(self, argv: Sequence[str]) -> TrackerResult:
        completed = run(["work", *argv], cwd=self._root, timeout=60, check=False)
        return TrackerResult(
            returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
        )


@dataclass(frozen=True)
class DepEdgeRecord:
    """One dependency edge exactly as `work show`'s `deps` field carries it."""

    id: str
    type: str
    status: str


@dataclass(frozen=True)
class BeadRecord:
    """The subset of `work show`'s item shape the cycle guard needs.

    Only id/status/labels/deps are modeled here -- every other field
    workcli's `Item` carries (title, type, priority, description, ...) is
    intentionally ignored, so an additive envelope change (a MINOR bump)
    never breaks this port.
    """

    id: str
    status: str
    labels: tuple[str, ...]
    deps: tuple[DepEdgeRecord, ...]


def _result_detail(argv: Sequence[str], result: TrackerResult) -> dict[str, Any]:
    """Diagnostic fields every malformed-envelope error carries (house
    convention — the scc/gh adapters include the same trio): a raw subprocess
    failure (missing binary, crash, permission) is diagnosable from the error
    alone, without rerunning under a debugger."""
    return {
        "argv": list(argv),
        "returncode": result.returncode,
        "stderr_excerpt": result.stderr[:200],
        "raw_excerpt": result.stdout[:200],
    }


def _malformed_json_error(argv: Sequence[str], result: TrackerResult) -> VizError:
    return VizError(
        ErrorCode.TRACKER_MALFORMED_ENVELOPE,
        "work CLI stdout did not parse as JSON",
        detail=_result_detail(argv, result),
    )


def _malformed_shape_error(argv: Sequence[str], result: TrackerResult) -> VizError:
    return VizError(
        ErrorCode.TRACKER_MALFORMED_ENVELOPE,
        "work CLI stdout did not match the envelope shape",
        detail=_result_detail(argv, result),
    )


def _inconsistent_exit_error(argv: Sequence[str], result: TrackerResult) -> VizError:
    return VizError(
        ErrorCode.TRACKER_MALFORMED_ENVELOPE,
        "work CLI exited nonzero while emitting an ok envelope",
        detail=_result_detail(argv, result),
    )


def _backend_error(argv: Sequence[str], error: dict[str, Any]) -> VizError:
    return VizError(
        ErrorCode.TRACKER_BACKEND_ERROR,
        f"work CLI returned an error envelope: {error.get('message', '<no message>')}",
        detail={
            "argv": list(argv),
            "code": error.get("code"),
            "backend_detail": error.get("detail"),
        },
    )


def _run_and_parse(runner: TrackerRunner, argv: Sequence[str]) -> Any:
    """Run `argv` through `runner`, parse the JSON envelope, and return `data`.

    Mirrors `adapters/gh/parse.py`'s discipline: every failure mode -- non-JSON
    stdout, a shape that isn't the envelope contract, or the facade's own
    `ok: false` error envelope -- raises a typed `VizError`, never a silent
    default or a raw `KeyError`/`TypeError` escaping this boundary.
    """
    result = runner.run(argv)
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise _malformed_json_error(argv, result) from exc
    try:
        ok = envelope["ok"]
    except (KeyError, TypeError) as exc:
        raise _malformed_shape_error(argv, result) from exc
    if not isinstance(ok, bool):
        # `ok` must be a JSON boolean — a null/string here is contract drift,
        # not a backend error; misclassifying it would mask the drift.
        raise _malformed_shape_error(argv, result)
    if ok is False:
        error = envelope.get("error")
        if not isinstance(error, dict):
            # An `ok: false` envelope whose `error` is not an object violates
            # the contract — refuse it as malformed rather than crash on a
            # `.get` of a string/list (or invent a backend message).
            raise _malformed_shape_error(argv, result)
        raise _backend_error(argv, error)
    if result.returncode != 0:
        # An `ok: true` envelope from a nonzero exit is an inconsistent state
        # (partial output, crash after print) — refuse it rather than treat
        # it as success and hide a real subprocess failure.
        raise _inconsistent_exit_error(argv, result)
    try:
        # The envelope contract always carries `data` — a missing key is
        # drift, distinct from a contract-valid `data: null`.
        return envelope["data"]
    except KeyError as exc:
        raise _malformed_shape_error(argv, result) from exc


def _malformed_bead_error(bead_id: str, exc: Exception, data: Any) -> VizError:
    return VizError(
        ErrorCode.TRACKER_MALFORMED_ENVELOPE,
        f"work show {bead_id} returned an unexpected bead shape",
        detail={
            "bead_id": bead_id,
            "reason": type(exc).__name__,
            "raw_data_excerpt": repr(data)[:200],
        },
    )


class _NotAListError(TypeError):
    """Raised when a bead field that must be a JSON array is some other type.

    Iterating a string/dict would silently yield characters/keys instead of
    failing loud on shape drift (the message is fixed on the class per ruff
    TRY003); `_parse_bead_record`'s except clause converts it to the typed
    malformed error.
    """

    def __init__(self) -> None:
        super().__init__("expected a JSON array")


def _parse_dep_edge(raw: Any) -> DepEdgeRecord:
    return DepEdgeRecord(id=str(raw["id"]), type=str(raw["type"]), status=str(raw["status"]))


def _parse_bead_record(data: Any, *, bead_id: str) -> BeadRecord:
    """Parse `work show <id>`'s single-object `data` into a `BeadRecord`."""
    try:
        labels = data["labels"]
        deps = data["deps"]
        if not isinstance(labels, list) or not isinstance(deps, list):
            raise _NotAListError
        return BeadRecord(
            id=str(data["id"]),
            status=str(data["status"]),
            labels=tuple(str(label) for label in labels),
            deps=tuple(_parse_dep_edge(entry) for entry in deps),
        )
    except (KeyError, TypeError) as exc:
        raise _malformed_bead_error(bead_id, exc, data) from exc


class TrackerPort:
    """The sole beads boundary vizsuite is permitted to use (spec §5.6).

    Verifies the `work` CLI's protocol-version handshake before the first
    real verb dispatch (once per instance, then cached); every verb call
    after that goes through the same JSON-envelope parsing.
    """

    def __init__(self, runner: TrackerRunner) -> None:
        self._runner = runner
        self._handshake_ok = False

    def _ensure_handshake(self) -> None:
        if self._handshake_ok:
            return
        data = _run_and_parse(self._runner, ["--protocol-version"])
        try:
            protocol = data["protocol"]
        except (KeyError, TypeError) as exc:
            raise VizError(
                ErrorCode.TRACKER_MALFORMED_ENVELOPE,
                "work --protocol-version returned no protocol field",
                detail={"raw_data_excerpt": repr(data)[:200]},
            ) from exc
        if not isinstance(protocol, str):
            raise VizError(
                ErrorCode.TRACKER_MALFORMED_ENVELOPE,
                "work --protocol-version's protocol field is not a string",
                detail={"protocol": protocol},
            )
        major = protocol.split(".", 1)[0]
        if major != _EXPECTED_PROTOCOL_MAJOR:
            raise VizError(
                ErrorCode.TRACKER_PROTOCOL_MISMATCH,
                f"work CLI protocol {protocol!r} is incompatible with this tracker "
                f"port (expects major version {_EXPECTED_PROTOCOL_MAJOR}.x)",
                detail={"actual_protocol": protocol, "expected_major": _EXPECTED_PROTOCOL_MAJOR},
            )
        self._handshake_ok = True

    def read_bead(self, bead_id: str) -> BeadRecord:
        """`work show <id>` -- the read primitive the cycle guard traverses on."""
        self._ensure_handshake()
        data = _run_and_parse(self._runner, ["show", bead_id])
        return _parse_bead_record(data, bead_id=bead_id)

    def add_edge(self, from_id: str, to_id: str, kind: DepKind) -> None:
        """`work dep add <from_id> <to_id> --type <kind>` (`from_id` depends on `to_id`,
        spec §3: "dep add A B = A depends on B")."""
        self._ensure_handshake()
        _run_and_parse(self._runner, ["dep", "add", from_id, to_id, "--type", kind])

    def append_note(self, bead_id: str, text: str) -> None:
        """`work note <id> <text>` -- append-only, never a clobbering update."""
        self._ensure_handshake()
        _run_and_parse(self._runner, ["note", bead_id, text])

    def mint_bead(
        self,
        noun: str,
        title: str,
        *,
        parent: str | None = None,
        orphan: bool = False,
        description: str | None = None,
        priority: str | None = None,
        acceptance: str | None = None,
    ) -> str:
        """`work create <noun> --title T (--parent ID | --orphan) [...]`.

        Exactly one of `parent`/`orphan` is required by the facade itself
        (`E_USAGE` otherwise) -- this port does not re-validate that rule; the
        facade is the single source of truth for tracker business logic
        (spec §5.6 tracker quarantine).
        """
        self._ensure_handshake()
        argv = ["create", noun, "--title", title]
        if orphan:
            argv.append("--orphan")
        elif parent is not None:
            argv.extend(["--parent", parent])
        if description is not None:
            argv.extend(["--description", description])
        if priority is not None:
            argv.extend(["--priority", priority])
        if acceptance is not None:
            argv.extend(["--acceptance", acceptance])
        data = _run_and_parse(self._runner, argv)
        try:
            return str(data["id"])
        except (KeyError, TypeError) as exc:
            raise VizError(
                ErrorCode.TRACKER_MALFORMED_ENVELOPE,
                "work create did not return a bead id",
                detail={"argv": list(argv)},
            ) from exc

    def relabel(self, bead_id: str, labels: Sequence[str], *, remove: bool = False) -> None:
        """`work label {add,remove} <id> <label>...`."""
        self._ensure_handshake()
        action = "remove" if remove else "add"
        _run_and_parse(self._runner, ["label", action, bead_id, *labels])

    def resequence(self) -> None:
        """No facade verb exists for resequencing (spec §5.7: `ruling-needed`,
        never `one-click`, "the `work` facade has no resequence verb"). Raises
        `TRACKER_NOT_SUPPORTED` without ever touching the runner -- not even
        the protocol handshake -- and never falls back to a direct `bd`
        shell-out (spec §5.6 tracker quarantine).
        """
        raise VizError(
            ErrorCode.TRACKER_NOT_SUPPORTED,
            "resequence: the work facade exposes no resequence verb; vizsuite "
            "never shells `bd` directly to fill the gap (spec §5.6/§5.7)",
        )
