"""Subprocess lifecycle wrapper for agent dispatch (§5 subprocess wrapper).

Owns the ``subprocess`` plumbing for the four agent CLIs (``claude -p`` /
``codex exec`` / ``opencode run`` / ``ollama``): it writes the contract JSON to a
temp file passed **by path** (§5 "JSON, written to a file passed by path") for the
file-capable CLIs — a tool-less ``ollama run`` child instead gets the payload and
referenced file contents INLINE in its prompt (see :func:`_input_section`) — builds
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

import contextlib
import json
import logging
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

# The render-data key the runner injects: the per-invoker payload-delivery section.
# The contract prompt templates name this placeholder; only the runner knows the
# delivery mode (file path for file-capable CLIs, inline content for ollama — see
# _input_section), so it fills this last, after writing the payload.
INPUT_SECTION_KEY = "input_section"

# The four agent CLIs §5 names. The value is the cli token in TOML config.
_KNOWN_CLIS = frozenset({"claude", "codex", "opencode", "ollama"})

# The `extra` keys each invoker actually consumes. Anything else in a provider
# table is warned about (a typo like `effrot` must not vanish silently) but NOT
# rejected — `extra` is a deliberate growth surface.
_RECOGNIZED_EXTRA: dict[str, frozenset[str]] = {
    "claude": frozenset({"effort"}),
    "codex": frozenset({"write"}),
    "opencode": frozenset(),
    "ollama": frozenset(),
}

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One provider's config: which CLI, which model, and CLI-specific extras.

    ``time_budget_s`` is the provider-level ``timeout`` TOML key: when set it
    overrides the contract's default budget for THIS chain link only; ``None``
    means "use the contract default". ``extra`` carries the per-provider TOML
    knobs that are not universal — ``effort`` (claude), ``write`` (codex).
    Unknown keys for a given CLI are warned about and ignored by its invoker,
    so the config surface can grow without breaking.
    """

    cli: str
    model: str
    extra: dict[str, Any] = field(default_factory=dict)
    time_budget_s: float | None = None


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
    forever), (b) REAP a signalled child and collect its captured output
    (``wait`` / ``communicate``), and (c) ``cleanup`` any capture scratch (the real
    handle redirects stdout/stderr to temp files to avoid a pipe-buffer deadlock —
    see :class:`_PopenHandle`). ``cleanup`` is called on every exit path.
    """

    def poll(self) -> int | None: ...  # pragma: no cover
    def send_stdin(self, data: str) -> None: ...  # pragma: no cover
    def terminate(self) -> None: ...  # pragma: no cover
    def kill(self) -> None: ...  # pragma: no cover
    def wait(self, timeout: float | None = None) -> int: ...  # pragma: no cover
    def communicate(self) -> tuple[str, str]: ...  # pragma: no cover
    def cleanup(self) -> None: ...  # pragma: no cover


# A spawn function: given argv + optional stdin, start the process and return a
# handle. The seam the runner depends on instead of `subprocess.Popen` directly.
SpawnFn = Callable[..., ProcessHandle]


def _input_section(cli: str, *, input_path: Path, payload: dict[str, Any]) -> str:
    """The per-invoker payload-delivery section rendered into the prompt template.

    File-capable CLIs (claude/codex/opencode spawn tool-using agents) get the §5
    pass-by-path shape: the section names the temp input file and the agent reads
    it. A bare ``ollama run`` child is a tool-less text generator that cannot open
    ANY file, so its section carries the content INLINE — the contract JSON plus
    the contents of every ``*_path`` file the payload references — and never
    instructs the model to read a path. (The HLD's "each invoker owns its own
    stdin/stdout serialisation" is what licenses the per-invoker delivery mode.)
    """
    if cli != "ollama":
        return f"from this file:\n\n  {input_path}"
    parts = [
        "inline below. You CANNOT read files — every file's content you need is",
        "already included in this prompt; any *_path values in the JSON are",
        "labels for the inline blocks that follow, not paths for you to open:",
        "",
        "```json",
        json.dumps(payload, indent=2),
        "```",
    ]
    for key, value in payload.items():
        # Inline each referenced document. Best-effort: a missing/unreadable file
        # (snapshot not assembled yet) is skipped, not a crash — the agent still
        # gets the contract JSON and can act on what is present.
        if not key.endswith("_path") or not isinstance(value, str):
            continue
        try:
            content = Path(value).read_text(encoding="utf-8")
        except OSError:
            continue
        parts += ["", f"Contents of {key} ({value}):", "```", content, "```"]
    return "\n".join(parts)


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
    # Gate on the literal boolean `true`, NOT truthiness: a mistyped string like
    # write = "false" is truthy and would silently grant edit rights — a
    # config-driven privilege escalation. `is True` accepts only the TOML boolean.
    argv = ["codex", "exec", "--model", spec.model]
    if spec.extra.get("write") is True:
        argv += ["--sandbox", "workspace-write"]
    argv += [prompt]
    return AgentInvocation(argv=argv)


def _invocation_for_opencode(spec: AgentSpec, prompt: str) -> AgentInvocation:
    return AgentInvocation(argv=["opencode", "run", "--model", spec.model, prompt])


def _invocation_for_ollama(spec: AgentSpec, prompt: str) -> AgentInvocation:
    # ollama reads the prompt on STDIN (`ollama run <model>`), so the prompt — which
    # carries the contract payload INLINE (see _input_section; a tool-less ollama
    # child cannot open files) — is fed on stdin, not as an argv positional.
    return AgentInvocation(argv=["ollama", "run", spec.model], stdin=prompt)


_INVOKERS: dict[str, Callable[[AgentSpec, str], AgentInvocation]] = {
    "claude": _invocation_for_claude,
    "codex": _invocation_for_codex,
    "opencode": _invocation_for_opencode,
    "ollama": _invocation_for_ollama,
}


def build_invocation(spec: AgentSpec, *, prompt: str) -> AgentInvocation:
    """Build the argv/stdin shape for ``spec.cli`` (§5 per-invoker shapes).

    ``prompt`` is the fully-rendered prompt whose payload-delivery section was
    already filled per-invoker (path for file-capable CLIs, inline content for
    ollama — none of the four CLIs has an ``--input-file`` flag, so delivery lives
    in the prompt). Raises :class:`ValueError` for a cli outside the four §5
    runtimes — a config typo must fail loudly at dispatch, not silently pick a
    default.
    """
    invoker = _INVOKERS.get(spec.cli)
    if invoker is None:
        msg = f"unknown agent cli: {spec.cli!r} (expected one of {sorted(_KNOWN_CLIS)})"
        raise ValueError(msg)
    unrecognized = sorted(set(spec.extra) - _RECOGNIZED_EXTRA[spec.cli])
    if unrecognized:
        _logger.warning(
            "ignoring unrecognized config keys for cli %r: %s",
            spec.cli,
            ", ".join(unrecognized),
        )
    return invoker(spec, prompt)


class _PopenHandle:  # pragma: no cover - OS boundary; tests inject a fake handle
    """Adapts ``subprocess.Popen`` to :class:`ProcessHandle`.

    The child's stdout/stderr are redirected to **temp files**, NOT pipes. A pipe
    has a bounded OS buffer (~64KB); a chatty agent that writes more than that while
    the runner is still polling (not yet draining) would block on the full pipe and
    never exit — a false budget timeout on a job that would succeed. Files never
    block the writer, so the poll-until-exit loop stays deadlock-free. ``stdin``
    stays a pipe (``send_stdin`` writes the prompt and closes it). ``communicate``
    reaps the child then reads the two files; ``cleanup`` unlinks them and is called
    by the runner on every exit path. Not unit-tested — it IS the OS boundary the
    ``spawn`` seam keeps out of the tested path.
    """

    def __init__(self, proc: subprocess.Popen[bytes], *, out_path: Path, err_path: Path) -> None:
        self._proc = proc
        self._out_path = out_path
        self._err_path = err_path

    def poll(self) -> int | None:
        return self._proc.poll()

    def send_stdin(self, data: str) -> None:
        assert self._proc.stdin is not None  # noqa: S101  # only called when stdin=PIPE was opened
        # Close the pipe even if the write throws (child exited first → BrokenPipe),
        # so the fd never leaks; the caller swallows BrokenPipeError as best-effort.
        try:
            self._proc.stdin.write(data.encode())
        finally:
            self._proc.stdin.close()

    def terminate(self) -> None:
        self._proc.terminate()

    def kill(self) -> None:
        self._proc.kill()

    def wait(self, timeout: float | None = None) -> int:
        return self._proc.wait(timeout=timeout)

    def communicate(self) -> tuple[str, str]:
        # Reap the child, then read what it wrote to the capture files. The child's
        # stdout/stderr fds are closed on exit, so the files are complete here.
        self._proc.wait()
        out = self._out_path.read_text(encoding="utf-8", errors="replace")
        err = self._err_path.read_text(encoding="utf-8", errors="replace")
        return out, err

    def cleanup(self) -> None:
        self._out_path.unlink(missing_ok=True)
        self._err_path.unlink(missing_ok=True)


def _popen_spawn(argv: Sequence[str], *, stdin: str | None) -> ProcessHandle:  # pragma: no cover
    """Production spawn: start a real child via ``subprocess.Popen``.

    stdout/stderr are redirected to temp files (deadlock-free capture — see
    :class:`_PopenHandle`); stdin stays a pipe only when there is input to deliver.
    Not covered by unit tests — it IS the OS boundary the ``spawn`` seam exists to
    keep out of the tested code path; tests inject a fake handle instead.
    """
    out_fd, out_name = tempfile.mkstemp(suffix=".out", prefix="prgroom-agent-")
    err_fd, err_name = tempfile.mkstemp(suffix=".err", prefix="prgroom-agent-")
    out_path, err_path = Path(out_name), Path(err_name)
    try:
        with os.fdopen(out_fd, "wb") as out_fh, os.fdopen(err_fd, "wb") as err_fh:
            proc = subprocess.Popen(  # noqa: S603  # argv is internally built per-invoker, never shell-interpolated user input
                list(argv),
                stdin=subprocess.PIPE if stdin is not None else None,
                stdout=out_fh,
                stderr=err_fh,
            )
    except BaseException:
        out_path.unlink(missing_ok=True)
        err_path.unlink(missing_ok=True)
        raise
    return _PopenHandle(proc, out_path=out_path, err_path=err_path)


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
        ``prompt_template`` with ``render_data`` plus the per-invoker payload
        delivery section (under :data:`INPUT_SECTION_KEY` — pass-by-path for the
        file-capable CLIs, inline content for ollama), builds the per-invoker argv,
        spawns the child, delivers any stdin, and waits — polling the cancel-token
        and the wall-clock deadline. A budget overrun raises
        :class:`AgentTimeoutError`; a cancel-token set raises
        :class:`AgentCancelledError`; both stop and reap the child first. The temp
        input file is always cleaned up. The runner owns the temp path and the
        delivery mode, so it is the only place that can fill the prompt's
        ``{input_section}`` placeholder.
        """
        input_path = self._write_payload(contract_payload)
        try:
            section = _input_section(spec.cli, input_path=input_path, payload=contract_payload)
            prompt = prompt_template.render({**render_data, INPUT_SECTION_KEY: section})
            invocation = build_invocation(spec, prompt=prompt)
            return self._spawn_and_wait(invocation, time_budget_s=time_budget_s, cancel=cancel)
        finally:
            input_path.unlink(missing_ok=True)

    def _write_payload(self, payload: dict[str, Any]) -> Path:
        fd, name = tempfile.mkstemp(suffix=".json", prefix="prgroom-agent-", dir=self._scratch_dir)
        # Write through the fd mkstemp returned: reopening by path would leave a
        # TOCTOU window where the path could be swapped between close and open.
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return Path(name)

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
        # cleanup() unlinks the handle's stdout/stderr capture files; run it on EVERY
        # exit path (success, timeout, cancel, exception), so the scratch never leaks.
        try:
            # Deliver stdin (and close the pipe) immediately so a stdin-reading child
            # (ollama) can make progress; without this it blocks until the budget.
            # Best-effort: a child that already exited (e.g. ollama erroring out before
            # reading stdin) makes the write hit a closed pipe — swallow it so the child
            # is reported via its returncode/stderr and falls through, not a crash.
            if invocation.stdin is not None:
                with contextlib.suppress(BrokenPipeError):
                    proc.send_stdin(invocation.stdin)
            return self._poll_until_done(proc, start=start, deadline=deadline, cancel=cancel)
        finally:
            proc.cleanup()

    def _poll_until_done(
        self,
        proc: ProcessHandle,
        *,
        start: float,
        deadline: float,
        cancel: threading.Event | None,
    ) -> AgentRunResult:
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
                    detail=f"agent exceeded its {deadline - start:.0f}s time budget",
                )
            if self._poll_interval_s:
                time.sleep(self._poll_interval_s)

    def _terminate(self, proc: ProcessHandle) -> None:
        """Stop and REAP a child: SIGTERM, grace, SIGKILL-on-survival, then reap.

        SIGTERM first, giving the child ``sigterm_grace_s`` to exit cleanly (flush
        buffers, release its ``.git/index.lock``). Only if it ignores SIGTERM do we
        SIGKILL. Either way a final ``communicate`` reaps the child and reads its
        stdout/stderr capture files (stdin was already closed in ``send_stdin``), so
        no zombie lingers before the error propagates; ``cleanup`` unlinks the files.

        Both signals are best-effort: a child that already exited between the poll
        loop and here (a fast-failure race) makes ``terminate``/``kill`` raise
        ``ProcessLookupError``. There is nothing left to signal, so we suppress it and
        let ``communicate`` reap — keeping the timeout/cancel error deterministic.
        """
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        try:
            proc.wait(timeout=self._sigterm_grace_s)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        proc.communicate()


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
