"""Drive one interactive Claude Code session on a pseudo-terminal and record what it does.

Agent teams do not exist under `claude -p`: a named Agent runs there as an ordinary
subagent and no teammate idle ever fires. Measuring teammate behaviour therefore needs a
real interactive session, which is what the pseudo-terminal is for.

Every decision the driver makes about the screen is a pure function here, so the parts
that can be wrong are testable without launching anything. Only `run_session` itself
touches a terminal.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]")

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
HOOKLOG = Path(__file__).parent / "hooklog.py"

# Accepting the trust dialog repaints the whole screen. Keystrokes sent while that repaint
# is still in flight are dropped, so the driver waits this long before typing anything.
TRUST_SETTLE_SECONDS = 6.0

# How much of the typed instruction has to be read back before it counts as landed. The
# input box wraps a long path across lines and draws a border in the middle of it, so only
# a prefix short enough to stay on the first line can be matched.
ECHO_PREFIX_CHARS = 24

# How long the event log must go untouched before the session counts as finished.
DEFAULT_QUIET_SECONDS = 25
DEFAULT_MAX_SECONDS = 600

# The one outcome that makes a run measurable. Anything else means the scenario did not
# happen, and counting it as a run where no behaviour appeared would read as a release
# having fixed something.
COMPLETED = "completed"

HOOK_EVENTS = (
    "SessionStart",
    "SubagentStart",
    "SubagentStop",
    "TeammateIdle",
    "TaskCompleted",
    "Stop",
)


def scenario_names() -> list[str]:
    """Return every scenario shipped with the package."""
    return sorted(path.stem for path in SCENARIOS_DIR.glob("*.md"))


def scenario_prompt(scenario: str, run_dir: Path) -> str:
    """Return a scenario's prompt with the run directory substituted into it.

    A scenario writes its output into the run directory, so the directory has to reach the
    prompt text rather than being implied by the working directory.
    """
    path = SCENARIOS_DIR / f"{scenario}.md"
    if not path.exists():
        raise FileNotFoundError(f"no scenario named {scenario!r}; have {', '.join(scenario_names())}")
    return path.read_text(encoding="utf-8").replace("{RUN_DIR}", str(run_dir))


def scrub_env(environ: dict[str, str], events_path: Path) -> dict[str, str]:
    """Return the environment the probed session runs under.

    Every variable naming the launching Claude Code session is dropped, because inheriting
    one makes the child a continuation of this session rather than a fresh one. The config
    directory stays: it holds the credentials and the mitigations being measured, and a
    fresh config directory cannot authenticate without a human at the keyboard.
    """
    env = {
        key: value
        for key, value in environ.items()
        if not key.startswith(("CLAUDE", "CODEX_COMPANION")) or key == "CLAUDE_CONFIG_DIR"
    }
    env["AGENTPROBE_EVENTS"] = str(events_path)
    env["TERM"] = "xterm-256color"
    return env


def hook_settings() -> dict[str, Any]:
    """Return a Claude Code settings document that logs every event the detectors read.

    The hook writes to whatever `AGENTPROBE_EVENTS` names, so the settings document is the
    same for every run and carries no run-specific path.
    """
    command = {"type": "command", "command": f"python3 {HOOKLOG}"}
    hooks: dict[str, Any] = {event: [{"hooks": [command]}] for event in HOOK_EVENTS}
    hooks["PreToolUse"] = [{"matcher": "SendMessage|Write", "hooks": [command]}]
    hooks["PostToolUse"] = [{"matcher": "SendMessage|Agent|Write", "hooks": [command]}]
    return {"hooks": hooks}


def visible_text(raw: bytes) -> str:
    """Strip terminal escape sequences so the screen can be matched as plain text."""
    return ANSI.sub(b"", raw).decode("utf-8", "replace")


def _squashed(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def awaiting_trust(tail: str) -> bool:
    """Whether the workspace-trust dialog is on screen."""
    return "itrustthisfolder" in _squashed(tail)


def input_ready(tail: str, trusted: bool = False) -> bool:
    """Whether the main screen is up and the input line is accepting text.

    The dialog and the main screen both draw the prompt glyph, so an untrusted session has
    to rule the dialog out by its text. Once trust has been accepted the dialog is gone by
    definition, and the check must stop looking for it: accepting it makes the terminal
    echo the chosen line back, so "I trust this folder" stays in the captured screen for
    the rest of the run and would otherwise block the session forever.
    """
    squashed = _squashed(tail)
    if not trusted and "itrustthisfolder" in squashed[-1500:]:
        return False
    return "❯" in tail[-2500:] or "?forshortcuts" in squashed


def trust_settled(trusted_at: float | None, now: float) -> bool:
    """Whether enough time has passed since the trust dialog for typing to land."""
    if trusted_at is None:
        return True
    return now - trusted_at >= TRUST_SETTLE_SECONDS


def prompt_echoed(tail: str, prompt_path: Path) -> bool:
    """Whether the typed instruction actually appeared on the input line.

    Dropped keystrokes are silent, so the only way to know the instruction landed is to
    read it back off the screen. Path separators and whitespace are removed from both
    sides because the input line breaks a long path wherever it likes.
    """
    needle = _squashed(f"Read {prompt_path}").replace("/", "")[:ECHO_PREFIX_CHARS]
    return needle in _squashed(tail).replace("/", "")


def finish_reason(
    event_log_age: float, tail: str, seconds_since_prompt: float, quiet_seconds: float
) -> str | None:
    """How the scenario ended, or None while it is still running.

    The normal ending is a quiet event log plus the lead printing its done word. The
    fallback covers a lead that stopped without saying so: a log quiet for three times as
    long, well after the prompt was sent. Those two are not the same outcome. A lead that
    never reached its terminal state did not finish the scenario.
    """
    if event_log_age > quiet_seconds and "done" in _squashed(tail[-600:]):
        return COMPLETED
    if event_log_age > quiet_seconds * 3 and seconds_since_prompt > 120:
        return "no-terminal-state"
    return None


# Two tries at typing, because the first can be swallowed by a screen still being drawn.
ECHO_ATTEMPTS = 2
ECHO_WAIT_SECONDS = 1.5


def type_instruction(
    prompt_path: Path,
    write: Callable[[bytes], object],
    read_tail: Callable[[], str],
    pause: Callable[[float], object],
    attempts: int = ECHO_ATTEMPTS,
) -> bool:
    """Type the instruction, confirm it echoed, and submit it. Return whether it was sent.

    Return is pressed only after the instruction has been read back off the screen.
    Submitting an unconfirmed line would run the session on whatever fragment survived the
    dropped keystrokes, and that run would look like a scenario that found nothing.
    """
    line = f"Read {prompt_path} and follow it exactly.".encode()
    for _attempt in range(attempts):
        write(line)
        pause(ECHO_WAIT_SECONDS)
        if prompt_echoed(read_tail(), prompt_path):
            write(b"\r")
            return True
    return False


def claude_version() -> str:
    """Return the `claude --version` string, or a note that it could not be read."""
    try:
        result = subprocess.run(
            ["claude", "--version"],  # noqa: S607 - the caller's PATH selects the toolchain deliberately
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


@dataclass(frozen=True)
class Launch:
    """Everything needed to start one probed session, resolved before anything is started."""

    run_dir: Path
    prompt_path: Path
    settings_path: Path
    events_path: Path
    argv: list[str]
    env: dict[str, str]

    def describe(self) -> str:
        """Render the launch for a dry run, so the command and environment can be read."""
        lines = [
            f"run directory: {self.run_dir}",
            f"command: {' '.join(self.argv)}",
            f"prompt: Read {self.prompt_path} and follow it exactly.",
            "environment (scrubbed):",
        ]
        lines += [f"  {key}={self.env[key]}" for key in sorted(self.env)]
        return "\n".join(lines)


def prepare(run_dir: Path, scenario: str, environ: dict[str, str], model: str) -> Launch:
    """Write a run directory's inputs and resolve how the session will be launched."""
    run_dir.mkdir(parents=True, exist_ok=True)
    events_path = run_dir / "events.jsonl"
    prompt_path = run_dir / "prompt.md"
    settings_path = run_dir / "settings.json"
    prompt_path.write_text(scenario_prompt(scenario, run_dir), encoding="utf-8")
    settings_path.write_text(json.dumps(hook_settings(), indent=1), encoding="utf-8")
    argv = [
        "claude",
        "--settings",
        str(settings_path),
        "--model",
        model,
        "--permission-mode",
        "acceptEdits",
    ]
    return Launch(
        run_dir=run_dir,
        prompt_path=prompt_path,
        settings_path=settings_path,
        events_path=events_path,
        argv=argv,
        env=scrub_env(environ, events_path),
    )


def session_id_of(events_path: Path) -> str:
    """Return the session id the first recorded event carries, or the empty string."""
    try:
        with events_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                value = record.get("payload", {}).get("session_id")
                return value if isinstance(value, str) else ""
    except (OSError, json.JSONDecodeError):
        return ""
    return ""


def run_session(  # pragma: no cover - drives a real terminal; the decisions it makes are tested above
    launch: Launch,
    quiet_seconds: float = DEFAULT_QUIET_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> str:
    """Launch Claude Code, drive the scenario, and return how the run ended."""
    import fcntl
    import os
    import pty
    import select
    import signal
    import struct
    import termios
    import time

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(launch.run_dir)
        # A fixed argv and never a shell; PATH resolves `claude` so the caller's own
        # toolchain selection is respected.
        os.execvpe(  # noqa: S606
            "claude",  # noqa: S607
            launch.argv,
            launch.env,
        )
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 220, 0, 0))
    tty_log = (launch.run_dir / "tty.log").open("ab")
    # The child's own stderr is merged into the pseudo-terminal, so this file holds the
    # driver's account of the run: what it saw, what it typed, and why it stopped.
    notes = (launch.run_dir / "claude.err").open("w", encoding="utf-8")

    def note(text: str) -> None:
        notes.write(f"{time.time() - started:8.1f}s {text}\n")
        notes.flush()

    seen = ""
    started = time.time()
    sent_at: float | None = None
    trusted_at: float | None = None
    outcome = "timed-out"

    def drain() -> None:
        nonlocal seen
        while True:
            readable, _, _ = select.select([fd], [], [], 0.2)
            if not readable:
                return
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            tty_log.write(chunk)
            tty_log.flush()
            seen = (seen + visible_text(chunk))[-200000:]

    def read_tail() -> str:
        """Take in whatever the terminal has produced, and return the end of the screen."""
        drain()
        return seen[-3000:]

    try:
        while time.time() - started < max_seconds:
            drain()
            tail = seen[-4000:]
            if sent_at is None:
                if trusted_at is None and awaiting_trust(tail):
                    os.write(fd, b"\x1b[B")
                    time.sleep(0.5)
                    os.write(fd, b"\r")
                    trusted_at = time.time()
                    note("accepted the workspace-trust dialog")
                    # The repaint invalidates everything captured so far, including the
                    # dialog text the readiness check would otherwise still match.
                    seen = ""
                    time.sleep(3)
                    continue
                ready = trust_settled(trusted_at, time.time()) and input_ready(
                    tail, trusted=trusted_at is not None
                )
                if ready and time.time() - started > 8:
                    submitted = type_instruction(
                        launch.prompt_path,
                        lambda data: os.write(fd, data),
                        read_tail,
                        time.sleep,
                    )
                    if not submitted:
                        note("the instruction never echoed back, so it was not submitted")
                        outcome = "instruction-never-typed"
                        break
                    sent_at = time.time()
                    note("typed the instruction and confirmed it echoed back")
                    continue
                if time.time() - started > 120:
                    note("gave up waiting for an input line; the instruction was never typed")
                    outcome = "instruction-never-typed"
                    break
                time.sleep(1)
                continue
            if launch.events_path.exists():
                age = time.time() - launch.events_path.stat().st_mtime
                reason = finish_reason(age, tail, time.time() - sent_at, quiet_seconds)
                if reason is not None:
                    note(f"event log quiet for {age:.0f}s; ending the session as {reason}")
                    outcome = reason
                    break
            time.sleep(3)
        drain()
        os.write(fd, b"/exit\r")
        for _ in range(20):
            drain()
            finished, _ = os.waitpid(pid, os.WNOHANG)
            if finished:
                break
            time.sleep(0.5)
        else:
            os.kill(pid, signal.SIGTERM)
    finally:
        note(f"session closed as {outcome}")
        notes.close()
        tty_log.close()
        os.close(fd)
    return outcome
