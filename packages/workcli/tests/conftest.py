"""Shared pytest fixtures and helpers for the workcli test suite."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from io import StringIO

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.cli import main
from workcli.config import TrackLayerConfig
from workcli.envelope import JsonValue

# A fixed instant for tests that don't care about "now" but still need a
# deterministic, non-wall-clock default -- mirrors _NO_READS below: a test
# that DOES care injects `now=` explicitly rather than relying on real time.
_FIXED_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)


def fake_reader(paths: dict[str, str]) -> Callable[[str], str]:
    """A dict-backed fake `read_file`: tests script exact spec text per path.

    Never touches the real filesystem -- a lookup miss raises `KeyError`
    loudly rather than falling through to `main()`'s real-disk default, so a
    test that forgets to script a path a code path actually reads fails
    clearly instead of silently reading whatever happens to be on disk.
    """

    def read(path: str) -> str:
        return paths[path]

    return read


_NO_READS = fake_reader({})


def _no_config_loads(_explicit_path: str | None) -> TrackLayerConfig:
    raise AssertionError("config loader unexpectedly invoked; inject config_loader= explicitly")


def run_cli(
    argv: Sequence[str],
    steps: Sequence[ScriptedStep],
    *,
    sleep: Callable[[float], None] | None = None,
    read_file: Callable[[str], str] | None = None,
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[int, dict[str, JsonValue], str]:
    """Invoke `main()` against a `ScriptedBdRunner`, capturing stdout/stderr.

    Returns ``(exit_code, envelope, stderr_text)``. Parsing the entire
    captured stdout as one JSON value enforces the "exactly one envelope"
    invariant implicitly: any extra output on stdout fails the `json.loads`
    call with a clear error instead of silently reading the first line.

    `steps` scripts the `ScriptedBdRunner`'s bd responses so each behavioral
    test stays pure (verb in, envelope + call log out) without touching this
    helper. `read_file` defaults to a dict-backed fake with no paths scripted
    (see `fake_reader`) -- never `main()`'s own real-filesystem default.
    `now` defaults to a fixed instant (`_FIXED_NOW`) -- never the real wall
    clock -- so a test that doesn't care about "now" still stays deterministic.
    """
    out = StringIO()
    err = StringIO()
    runner = ScriptedBdRunner(steps=list(steps))
    exit_code = main(
        argv,
        runner=runner,
        out=out,
        err=err,
        sleep=sleep,
        read_file=read_file if read_file is not None else _NO_READS,
        config_loader=config_loader if config_loader is not None else _no_config_loads,
        now=now if now is not None else (lambda: _FIXED_NOW),
    )
    envelope: dict[str, JsonValue] = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()


def run_cli_with_runner(
    argv: Sequence[str],
    runner: ScriptedBdRunner,
    *,
    sleep: Callable[[float], None] | None = None,
    read_file: Callable[[str], str] | None = None,
    config_loader: Callable[[str | None], TrackLayerConfig] | None = None,
    now: Callable[[], datetime] | None = None,
) -> tuple[int, dict[str, JsonValue], str]:
    """Like `run_cli`, but takes a caller-built `ScriptedBdRunner`.

    `run_cli` builds and discards its own runner, so tests that need to
    assert against `.calls` after dispatch (the fake's call-log surface)
    construct the runner themselves and pass it in here instead.
    """
    out = StringIO()
    err = StringIO()
    exit_code = main(
        argv,
        runner=runner,
        out=out,
        err=err,
        sleep=sleep,
        read_file=read_file if read_file is not None else _NO_READS,
        config_loader=config_loader if config_loader is not None else _no_config_loads,
        now=now if now is not None else (lambda: _FIXED_NOW),
    )
    envelope: dict[str, JsonValue] = json.loads(out.getvalue())
    return exit_code, envelope, err.getvalue()
