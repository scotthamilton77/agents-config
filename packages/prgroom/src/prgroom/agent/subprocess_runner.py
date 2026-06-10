"""Subprocess lifecycle wrapper for agent dispatch (§5 subprocess wrapper).

Owns the ``subprocess`` plumbing for the four agent CLIs (``claude -p`` /
``codex exec`` / ``opencode run`` / ``ollama``): it writes the contract JSON to a
temp file passed **by path** (§5 "JSON, written to a file passed by path"), builds
the per-invoker argv/stdin shape, enforces a per-contract wall-clock budget
(kills the child and raises a timeout-tagged error on overrun), and terminates the
child when a :class:`threading.Event` cancel-token is set.

The single OS seam is the :class:`ProcessHandle` Protocol — a thin ``Popen``
facade — injected as the ``spawn`` callable. Production wires :func:`_popen_spawn`;
tests inject a fake that returns recorded behavior, so kill-on-timeout and
kill-on-cancel are proven without spawning a real CLI. This mirrors the
foundation's ``CommandRunner`` seam (recorded fakes, not mocks).

The runner is intentionally **classification-free**: it reports the child's
returncode + stderr faithfully and raises only for timeout/cancel. Mapping a
non-zero exit (quota/auth/network) onto the fallback ladder is the dispatcher's
job — keeping that policy out of the boundary keeps this layer a pure mechanism.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.errors import ErrorCode, PrgroomError, Tier

# Default poll cadence while waiting on a child: tight enough that a cancel-token
# or budget overrun is noticed promptly, loose enough not to busy-spin. Tests
# inject 0.0 to make the wait deterministic and instant.
DEFAULT_POLL_INTERVAL_S = 0.1

# Grace given to a SIGTERMed child to exit (flush buffers, release its
# .git/index.lock) before escalating to SIGKILL. Tests inject 0.0 for an instant,
# deterministic escalation.
DEFAULT_SIGTERM_GRACE_S = 5.0

# The render-data key the runner injects: the temp input-file path. The contract
# prompt templates name this placeholder; only the runner knows the real path
# (it owns the temp file), so it fills this last, after writing the payload.
INPUT_PATH_KEY = "input_path"

# The four agent CLIs §5 names. The value is the cli token in TOML config.
_KNOWN_CLIS = frozenset({"claude", "codex", "opencode", "ollama"})


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One provider's config: which CLI, which model, and CLI-specific extras.

    ``extra`` carries the per-provider TOML knobs that are not universal —
    ``effort`` (claude), ``write`` (codex). Unknown keys for a given CLI are
    ignored by its invoker, so the config surface can grow without breaking.
    """

    cli: str
    model: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentInvocation:
    """A built command: the argv to spawn and the optional stdin to feed it."""

    argv: list[str]
    stdin: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """The captured outcome of one agent invocation."""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: int


class AgentTimeoutError(PrgroomError):
    """The agent exceeded its per-contract time budget (``RUNTIME_AGENT_TIMEOUT``).

    A budget overrun on one provider is a **fallback trigger**: the dispatcher
    catches this and tries the next link in the chain (§5). It is distinct from
    :class:`AgentCancelledError` precisely so the dispatcher can route the two
    differently — try-next vs. abort-all.
    """


class AgentCancelledError(PrgroomError):
    """A cancel-token (operator/scheduler shutdown) killed the agent mid-run.

    Carries ``RUNTIME_CANCELLED_SIGTERM``. Unlike a timeout, this is **not** a
    per-provider failure — it propagates past the dispatcher's fallback ladder to
    abort the whole dispatch, since shutdown means "stop", not "try another model".
    """


@runtime_checkable
class AgentRunner(Protocol):
    """The single-invocation surface the dispatcher depends on (§5).

    :class:`SubprocessAgentRunner` is the production implementation; tests inject a
    recorded-outcome fake. Typing the dispatcher against this Protocol (not the
    concrete class) keeps the dispatcher's fallback-ladder tests free of real
    subprocess machinery — the same fakes-not-mocks discipline as ``CommandRunner``.
    """

    def run(
        self,
        spec: AgentSpec,
        *,
        prompt_template: PromptTemplate,
        render_data: dict[str, str],
        contract_payload: dict[str, Any],
        time_budget_s: float,
        cancel: threading.Event | None = ...,
    ) -> AgentRunResult: ...  # pragma: no cover


@runtime_checkable
class ProcessHandle(Protocol):
    """A thin ``subprocess.Popen`` facade — the single OS seam this wrapper needs.

    Beyond poll/terminate/kill, the wrapper needs to (a) DELIVER stdin to the child
    (``send_stdin`` — ollama reads the prompt there; without it the child blocks
    forever), and (b) REAP a signalled child (``wait`` / ``communicate``) so no
    zombie lingers and no PIPE fd leaks.
    """

    def poll(self) -> int | None: ...  # pragma: no cover
    def send_stdin(self, data: str) -> None: ...  # pragma: no cover
    def terminate(self) -> None: ...  # pragma: no cover
    def kill(self) -> None: ...  # pragma: no cover
    def wait(self, timeout: float | None = None) -> int: ...  # pragma: no cover
    def communicate(self) -> tuple[str, str]: ...  # pragma: no cover


# A spawn function: given argv + optional stdin, start the process and return a
# handle. The seam the runner depends on instead of `subprocess.Popen` directly.
SpawnFn = Callable[..., ProcessHandle]


def _invocation_for_claude(spec: AgentSpec, prompt: str) -> AgentInvocation:
    # `claude -p <prompt>` runs headless. The contract input path is already inside
    # `prompt` (the agent reads the file) — claude has no --input-file flag.
    argv = ["claude", "-p", prompt, "--model", spec.model]
    effort = spec.extra.get("effort")
    if effort:
        argv += ["--effort", str(effort)]
    return AgentInvocation(argv=argv)


def _invocation_for_codex(spec: AgentSpec, prompt: str) -> AgentInvocation:
    # `codex exec` is the non-interactive entry point; the config `write = true`
    # grants edit permission via the sandbox POLICY (`--sandbox workspace-write`),
    # not a bare flag. Read-only specs leave the default sandbox in place.
    argv = ["codex", "exec", "--model", spec.model]
    if spec.extra.get("write"):
        argv += ["--sandbox", "workspace-write"]
    argv += [prompt]
    return AgentInvocation(argv=argv)


def _invocation_for_opencode(spec: AgentSpec, prompt: str) -> AgentInvocation:
    return AgentInvocation(argv=["opencode", "run", "--model", spec.model, prompt])


def _invocation_for_ollama(spec: AgentSpec, prompt: str) -> AgentInvocation:
    # ollama reads the prompt on STDIN (`ollama run <model>`), so the prompt — which
    # carries the input path — is fed on stdin, not as an argv positional.
    return AgentInvocation(argv=["ollama", "run", spec.model], stdin=prompt)


_INVOKERS: dict[str, Callable[[AgentSpec, str], AgentInvocation]] = {
    "claude": _invocation_for_claude,
    "codex": _invocation_for_codex,
    "opencode": _invocation_for_opencode,
    "ollama": _invocation_for_ollama,
}


def build_invocation(spec: AgentSpec, *, prompt: str) -> AgentInvocation:
    """Build the argv/stdin shape for ``spec.cli`` (§5 per-invoker shapes).

    ``prompt`` is the fully-rendered prompt that already names the contract input
    file by path (none of the four CLIs has an ``--input-file`` flag — the agent
    reads the path out of the prompt). Raises :class:`ValueError` for a cli outside
    the four §5 runtimes — a config typo must fail loudly at dispatch, not silently
    pick a default.
    """
    invoker = _INVOKERS.get(spec.cli)
    if invoker is None:
        msg = f"unknown agent cli: {spec.cli!r} (expected one of {sorted(_KNOWN_CLIS)})"
        raise ValueError(msg)
    return invoker(spec, prompt)


class _PopenHandle:  # pragma: no cover - OS boundary; tests inject a fake handle
    """Adapts ``subprocess.Popen`` to :class:`ProcessHandle`.

    ``send_stdin`` writes the prompt to the child and CLOSES the pipe (an ollama
    child blocks on an open-but-unwritten stdin); ``communicate`` (called with no
    further input) then drains stdout/stderr and reaps. Not unit-tested — it is the
    OS boundary the ``spawn`` seam exists to keep out of the tested path.
    """

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc

    def poll(self) -> int | None:
        return self._proc.poll()

    def send_stdin(self, data: str) -> None:
        assert self._proc.stdin is not None  # noqa: S101  # only called when stdin=PIPE was opened
        self._proc.stdin.write(data)
        self._proc.stdin.close()

    def terminate(self) -> None:
        self._proc.terminate()

    def kill(self) -> None:
        self._proc.kill()

    def wait(self, timeout: float | None = None) -> int:
        return self._proc.wait(timeout=timeout)

    def communicate(self) -> tuple[str, str]:
        return self._proc.communicate()


def _popen_spawn(argv: Sequence[str], *, stdin: str | None) -> ProcessHandle:  # pragma: no cover
    """Production spawn: start a real child via ``subprocess.Popen``.

    Not covered by unit tests — it IS the OS boundary the ``spawn`` seam exists to
    keep out of the tested code path; tests inject a fake handle instead.
    """
    proc = subprocess.Popen(  # noqa: S603  # argv is internally built per-invoker, never shell-interpolated user input
        list(argv),
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return _PopenHandle(proc)


class SubprocessAgentRunner:
    """Runs one agent invocation under a budget + cancel-token. Owns the temp-file dance."""

    def __init__(
        self,
        *,
        spawn: SpawnFn = _popen_spawn,
        scratch_dir: Path | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        sigterm_grace_s: float = DEFAULT_SIGTERM_GRACE_S,
    ) -> None:
        self._spawn = spawn
        self._scratch_dir = scratch_dir
        self._poll_interval_s = poll_interval_s
        self._sigterm_grace_s = sigterm_grace_s

    def run(
        self,
        spec: AgentSpec,
        *,
        prompt_template: PromptTemplate,
        render_data: dict[str, str],
        contract_payload: dict[str, Any],
        time_budget_s: float,
        cancel: threading.Event | None = None,
    ) -> AgentRunResult:
        """Dispatch ``spec`` against ``contract_payload``, returning the captured result.

        Writes ``contract_payload`` to a temp ``.json`` file, renders
        ``prompt_template`` with ``render_data`` plus the temp path (under
        :data:`INPUT_PATH_KEY`), builds the per-invoker argv, spawns the child,
        delivers any stdin, and waits — polling the cancel-token and the wall-clock
        deadline. A budget overrun raises :class:`AgentTimeoutError`; a cancel-token
        set raises :class:`AgentCancelledError`; both stop and reap the child first.
        The temp input file is always cleaned up. The runner owns the temp path, so
        it is the only place that can fill the prompt's ``{input_path}`` placeholder.
        """
        input_path = self._write_payload(contract_payload)
        try:
            prompt = prompt_template.render({**render_data, INPUT_PATH_KEY: str(input_path)})
            invocation = build_invocation(spec, prompt=prompt)
            return self._spawn_and_wait(invocation, time_budget_s=time_budget_s, cancel=cancel)
        finally:
            input_path.unlink(missing_ok=True)

    def _write_payload(self, payload: dict[str, Any]) -> Path:
        fd, name = tempfile.mkstemp(suffix=".json", prefix="prgroom-agent-", dir=self._scratch_dir)
        os.close(fd)
        path = Path(name)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def _spawn_and_wait(
        self,
        invocation: AgentInvocation,
        *,
        time_budget_s: float,
        cancel: threading.Event | None,
    ) -> AgentRunResult:
        start = time.monotonic()
        deadline = start + time_budget_s
        proc = self._spawn(invocation.argv, stdin=invocation.stdin)
        # Deliver stdin (and close the pipe) immediately so a stdin-reading child
        # (ollama) can make progress; without this it blocks until the budget.
        if invocation.stdin is not None:
            proc.send_stdin(invocation.stdin)
        while True:
            if cancel is not None and cancel.is_set():
                self._terminate(proc)
                raise AgentCancelledError(
                    tier=Tier.RUNTIME_CANCELLED,
                    code=ErrorCode.RUNTIME_CANCELLED_SIGTERM,
                    signum=15,
                    detail="agent dispatch cancelled via cancel-token",
                )
            returncode = proc.poll()
            if returncode is not None:
                stdout, stderr = proc.communicate()
                return AgentRunResult(
                    returncode=returncode,
                    stdout=stdout,
                    stderr=stderr,
                    duration_ms=_elapsed_ms(start),
                )
            if time.monotonic() >= deadline:
                self._terminate(proc)
                raise AgentTimeoutError(
                    tier=Tier.RUNTIME_TRANSIENT,
                    code=ErrorCode.RUNTIME_AGENT_TIMEOUT,
                    detail=f"agent exceeded its {time_budget_s}s time budget",
                )
            if self._poll_interval_s:
                time.sleep(self._poll_interval_s)

    def _terminate(self, proc: ProcessHandle) -> None:
        """Stop and REAP a child: SIGTERM, grace, SIGKILL-on-survival, then reap.

        SIGTERM first, giving the child ``sigterm_grace_s`` to exit cleanly (flush
        buffers, release its ``.git/index.lock``). Only if it ignores SIGTERM do we
        SIGKILL. Either way a final ``communicate`` drains the stdout/stderr/stdin
        pipes and reaps the child, so no zombie lingers and no PIPE fd leaks before
        the error propagates.
        """
        proc.terminate()
        try:
            proc.wait(timeout=self._sigterm_grace_s)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc.communicate()


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
