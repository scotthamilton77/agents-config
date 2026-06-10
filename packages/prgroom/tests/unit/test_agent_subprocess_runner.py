"""Subprocess lifecycle wrapper for agent dispatch (§5 subprocess wrapper).

The wrapper owns the plumbing for ``claude -p`` / ``codex exec`` / ``opencode run``
/ ``ollama``: it writes the contract JSON to a temp file passed by path, builds
the per-invoker argv, enforces a per-contract wall-clock budget (kills the child
and raises a timeout-tagged error on overrun), and terminates the child when a
``threading.Event`` cancel-token is set.

The single OS seam is the :class:`~prgroom.agent.subprocess_runner.ProcessHandle`
Protocol — a thin Popen facade. Tests inject a recorded-behavior fake so
kill-on-timeout and kill-on-cancel are proven without spawning a real CLI. This
mirrors the foundation's ``CommandRunner`` seam (recorded fakes, not mocks).
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest

from prgroom.agent.prompt_loader import PromptTemplate
from prgroom.agent.subprocess_runner import (
    AgentCancelledError,
    AgentRunResult,
    AgentSpec,
    AgentTimeoutError,
    SubprocessAgentRunner,
    build_invocation,
)
from prgroom.errors import ErrorCode

# A prompt template whose only placeholder is the runner-injected input path, so a
# test can assert the runner filled in the real temp-file path.
_PROMPT = PromptTemplate(name="t", text="process the input at {input_path}")


class FakeProcess:
    """A :class:`ProcessHandle` fake that records the full child lifecycle.

    ``finishes_after`` polls return ``None`` (running) before the process
    "completes" with ``returncode`` and the recorded ``stdout`` / ``stderr``. A
    ``finishes_after`` of ``None`` means it NEVER completes on its own — only a
    ``terminate``/``kill`` ends it (models a hung agent for the timeout/cancel
    paths). ``survives_sigterm`` makes :meth:`wait` raise ``TimeoutExpired`` on the
    SIGTERM-grace wait so the escalation-to-SIGKILL path is exercised.

    The fake records: the stdin delivered (:attr:`delivered_stdin`), whether the
    child was reaped (:attr:`reaped` — a ``communicate``/``wait`` after exit), and
    the ``terminate``/``kill`` signals — so tests pin delivery, reaping, and the
    SIGTERM-then-SIGKILL escalation, not just that a kwarg was passed.
    """

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        finishes_after: int | None = 0,
        survives_sigterm: bool = False,
    ) -> None:
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._finishes_after = finishes_after
        self._survives_sigterm = survives_sigterm
        self._polls = 0
        self.terminated = False
        self.killed = False
        self.reaped = False
        self.delivered_stdin: str | None = None
        self._signalled = False

    def poll(self) -> int | None:
        if self._signalled:
            return self._returncode
        if self._finishes_after is None:
            self._polls += 1
            return None
        if self._polls >= self._finishes_after:
            return self._returncode
        self._polls += 1
        return None

    def send_stdin(self, data: str) -> None:
        self.delivered_stdin = data

    def terminate(self) -> None:
        self.terminated = True
        self._signalled = True

    def kill(self) -> None:
        self.killed = True
        self._signalled = True

    def wait(self, timeout: float | None = None) -> int:
        # The SIGTERM grace wait: a child that survives SIGTERM forces the caller to
        # escalate to SIGKILL. A timeout-less wait (the final reap) always succeeds.
        if timeout is not None and self._survives_sigterm and not self.killed:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        self.reaped = True
        return self._returncode

    def communicate(self) -> tuple[str, str]:
        self.reaped = True
        return self._stdout, self._stderr


def _spec(cli: str = "claude", model: str = "haiku", **extra: object) -> AgentSpec:
    return AgentSpec(cli=cli, model=model, extra=extra)


# ── argv / stdin shapes per invoker (build_invocation) ──
#
# The contract input path lives in the PROMPT (the agent reads the file), never as
# an argv flag — none of the four real CLIs has an --input-file option. So each
# invoker carries the prompt as its message and the path is already inside it.


def test_claude_invocation_shape() -> None:
    inv = build_invocation(_spec("claude", "opus[1m]", effort="xhigh"), prompt="read /x")
    assert inv.argv[0] == "claude"
    assert "-p" in inv.argv
    assert "--model" in inv.argv and "opus[1m]" in inv.argv
    assert "--effort" in inv.argv and "xhigh" in inv.argv
    assert "read /x" in inv.argv  # prompt (carrying the path) is a positional


def test_codex_invocation_shape_maps_write_to_workspace_sandbox() -> None:
    inv = build_invocation(_spec("codex", "gpt-5.5", write=True), prompt="read /x")
    assert inv.argv[0] == "codex"
    assert "exec" in inv.argv
    assert "--model" in inv.argv and "gpt-5.5" in inv.argv
    # write=true grants edit permission via the sandbox policy, not a bare flag.
    assert "--sandbox" in inv.argv and "workspace-write" in inv.argv
    assert "read /x" in inv.argv


def test_codex_read_only_omits_sandbox_write() -> None:
    inv = build_invocation(_spec("codex", "gpt-5.4-mini"), prompt="P")
    assert "workspace-write" not in inv.argv


def test_opencode_invocation_shape() -> None:
    inv = build_invocation(_spec("opencode", "some-model"), prompt="read /x")
    assert inv.argv[0] == "opencode"
    assert "run" in inv.argv
    assert "--model" in inv.argv and "some-model" in inv.argv
    assert "read /x" in inv.argv


def test_ollama_invocation_shape_pipes_prompt_on_stdin() -> None:
    inv = build_invocation(_spec("ollama", "gemma4"), prompt="PROMPT-BODY")
    assert inv.argv[0] == "ollama"
    assert "run" in inv.argv
    assert "gemma4" in inv.argv
    # ollama reads the prompt on stdin, not as an argv positional.
    assert inv.stdin == "PROMPT-BODY"
    assert "PROMPT-BODY" not in inv.argv


def test_unknown_cli_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown agent cli"):
        build_invocation(_spec("borg", "model"), prompt="P")


# ── JSON-input-by-path ──


def test_runner_writes_contract_json_to_a_temp_file_and_names_it_in_the_prompt(
    tmp_path: Path,
) -> None:
    captured: dict[str, str] = {}

    def spawn(argv: Sequence[str], *, stdin: str | None) -> FakeProcess:  # noqa: ARG001
        # The rendered prompt (a claude positional) names the real temp path; that
        # path is the argv token that exists as a file on disk.
        prompt = next(t for t in argv if "input at" in t)
        path = prompt.removeprefix("process the input at ")
        captured["path"] = path
        captured["content"] = Path(path).read_text(encoding="utf-8")
        return FakeProcess(returncode=0, stdout='{"clusters": []}')

    runner = SubprocessAgentRunner(spawn=spawn, scratch_dir=tmp_path)
    result = runner.run(
        _spec(),
        prompt_template=_PROMPT,
        render_data={},
        contract_payload={"contract_version": 1, "items": []},
        time_budget_s=5.0,
    )
    assert json.loads(captured["content"]) == {"contract_version": 1, "items": []}
    assert result.stdout == '{"clusters": []}'


def test_runner_cleans_up_the_temp_input_file(tmp_path: Path) -> None:
    seen: dict[str, Path] = {}

    def spawn(argv: Sequence[str], *, stdin: str | None) -> FakeProcess:  # noqa: ARG001
        prompt = next(t for t in argv if "input at" in t)
        seen["path"] = Path(prompt.removeprefix("process the input at "))
        return FakeProcess(returncode=0, stdout="{}")

    runner = SubprocessAgentRunner(spawn=spawn, scratch_dir=tmp_path)
    runner.run(
        _spec(), prompt_template=_PROMPT, render_data={}, contract_payload={}, time_budget_s=5.0
    )
    assert not seen["path"].exists()  # temp input is removed after the run


def test_ollama_run_delivers_the_rendered_prompt_to_the_child_stdin(tmp_path: Path) -> None:
    # ollama reads the prompt on stdin; the runner must actually WRITE it to the
    # child (close the pipe), not merely carry it on the invocation. The fake
    # records what was delivered — without delivery a real ollama child blocks on an
    # unwritten stdin and dies at the budget (the default cluster primary DOA bug).
    proc = FakeProcess(returncode=0, stdout="{}")
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
    )
    runner.run(
        _spec("ollama", "gemma4"),
        prompt_template=_PROMPT,
        render_data={},
        contract_payload={},
        time_budget_s=5.0,
    )
    assert proc.delivered_stdin is not None
    assert "process the input at " in proc.delivered_stdin


def test_non_stdin_cli_delivers_no_stdin(tmp_path: Path) -> None:
    # claude/codex/opencode carry the prompt as an argv positional, so the runner
    # must NOT try to write to a child stdin that was never opened.
    proc = FakeProcess(returncode=0, stdout="OK")
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
    )
    runner.run(
        _spec("claude", "haiku"),
        prompt_template=_PROMPT,
        render_data={},
        contract_payload={},
        time_budget_s=5.0,
    )
    assert proc.delivered_stdin is None


def test_run_polls_repeatedly_until_a_slow_child_finishes(tmp_path: Path) -> None:
    # A child that needs two polls before completing exercises the poll-sleep-repoll
    # loop with a real (tiny) non-zero interval — not just the first-poll-done path.
    proc = FakeProcess(returncode=0, stdout="DONE", finishes_after=3)
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.001,
    )
    result = runner.run(
        _spec(), prompt_template=_PROMPT, render_data={}, contract_payload={}, time_budget_s=30.0
    )
    assert result.stdout == "DONE"
    assert not proc.killed and not proc.terminated  # finished on its own, no signal


def test_run_loops_without_sleeping_when_poll_interval_is_zero(tmp_path: Path) -> None:
    # A slow child with a 0.0 poll interval loops back immediately (the sleep is
    # skipped) — the "no-sleep" edge of the poll loop, distinct from the timeout
    # path which also runs at 0.0 but raises before completing.
    proc = FakeProcess(returncode=0, stdout="DONE", finishes_after=2)
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.0,
    )
    result = runner.run(
        _spec(), prompt_template=_PROMPT, render_data={}, contract_payload={}, time_budget_s=30.0
    )
    assert result.stdout == "DONE"


# ── success path returns a structured result ──


def _run_ok(runner: SubprocessAgentRunner) -> AgentRunResult:
    return runner.run(
        _spec(), prompt_template=_PROMPT, render_data={}, contract_payload={}, time_budget_s=5.0
    )


def test_successful_run_returns_result_with_duration_and_returncode(tmp_path: Path) -> None:
    proc = FakeProcess(returncode=0, stdout="OK")
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
    )
    result = _run_ok(runner)
    assert isinstance(result, AgentRunResult)
    assert result.returncode == 0
    assert result.stdout == "OK"
    assert result.duration_ms >= 0
    assert proc.reaped  # normal completion reaps the child (no zombie / leaked pipes)


def test_nonzero_exit_is_returned_not_raised(tmp_path: Path) -> None:
    # The runner does NOT classify exit codes — the dispatcher's fallback ladder
    # does. The runner reports the returncode + stderr faithfully.
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: FakeProcess(returncode=7, stderr="quota exceeded"),  # noqa: ARG005
        scratch_dir=tmp_path,
    )
    result = _run_ok(runner)
    assert result.returncode == 7
    assert "quota" in result.stderr


# ── timeout: SIGTERM-grace-then-SIGKILL, reap, raise timeout-tagged error ──


def test_timeout_escalates_sigterm_to_sigkill_and_reaps(tmp_path: Path) -> None:
    # A budget overrun on a child that IGNORES SIGTERM must escalate to SIGKILL and
    # then reap — never leave a zombie / leaked pipes.
    proc = FakeProcess(finishes_after=None, survives_sigterm=True)
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.0,
        sigterm_grace_s=0.0,
    )
    with pytest.raises(AgentTimeoutError) as excinfo:
        runner.run(
            _spec(),
            prompt_template=_PROMPT,
            render_data={},
            contract_payload={},
            time_budget_s=0.0,
        )
    assert proc.terminated and proc.killed  # SIGTERM first, then SIGKILL on survival
    assert proc.reaped  # reaped before the error propagates
    assert excinfo.value.code is ErrorCode.RUNTIME_AGENT_TIMEOUT


def test_timeout_lets_a_well_behaved_child_die_on_sigterm_alone(tmp_path: Path) -> None:
    # A child that exits on SIGTERM within the grace window is NOT SIGKILLed — the
    # grace gives the fix agent a chance to flush / release its .git/index.lock.
    proc = FakeProcess(finishes_after=None)  # survives_sigterm=False → SIGTERM suffices
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.0,
    )
    with pytest.raises(AgentTimeoutError):
        runner.run(
            _spec(), prompt_template=_PROMPT, render_data={}, contract_payload={}, time_budget_s=0.0
        )
    assert proc.terminated and not proc.killed
    assert proc.reaped


# ── cancel-token: terminate, grace, reap when the Event is set ──


def test_cancel_token_terminates_and_reaps_child(tmp_path: Path) -> None:
    proc = FakeProcess(finishes_after=None)
    cancel = threading.Event()
    cancel.set()  # already cancelled before the first poll

    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.0,
    )
    with pytest.raises(AgentCancelledError) as excinfo:
        runner.run(
            _spec(),
            prompt_template=_PROMPT,
            render_data={},
            contract_payload={},
            time_budget_s=30.0,
            cancel=cancel,
        )
    assert proc.terminated
    assert proc.reaped  # cancel path reaps too — no leaked child
    assert excinfo.value.code is ErrorCode.RUNTIME_CANCELLED_SIGTERM


def test_cancel_escalates_to_sigkill_when_child_survives_sigterm(tmp_path: Path) -> None:
    proc = FakeProcess(finishes_after=None, survives_sigterm=True)
    cancel = threading.Event()
    cancel.set()
    runner = SubprocessAgentRunner(
        spawn=lambda argv, *, stdin: proc,  # noqa: ARG005
        scratch_dir=tmp_path,
        poll_interval_s=0.0,
        sigterm_grace_s=0.0,
    )
    with pytest.raises(AgentCancelledError):
        runner.run(
            _spec(),
            prompt_template=_PROMPT,
            render_data={},
            contract_payload={},
            time_budget_s=30.0,
            cancel=cancel,
        )
    assert proc.terminated and proc.killed and proc.reaped


def test_run_builds_the_argv_for_the_specs_cli(tmp_path: Path) -> None:
    seen_argv: list[Sequence[str]] = []

    def spawn(argv: Sequence[str], *, stdin: str | None) -> FakeProcess:  # noqa: ARG001
        seen_argv.append(argv)
        return FakeProcess(returncode=0, stdout="{}")

    runner = SubprocessAgentRunner(spawn=spawn, scratch_dir=tmp_path)
    runner.run(
        _spec("claude", "haiku"),
        prompt_template=_PROMPT,
        render_data={},
        contract_payload={},
        time_budget_s=5.0,
    )
    assert seen_argv[0][0] == "claude"
