#!/usr/bin/env python3
"""Single-attempt codex arm runner for the bake-off workflow.

Executes exactly ONE codex attempt (initial launch or session resume) under an
in-code watchdog, then prints a one-line state JSON to stdout. Every recovery
decision — resume, fresh retry, stop — belongs to the calling workflow
(bake-off.js), never to this script and never to the wrapper agent running it.

The watchdog must be strictly below the harness Bash-call timeout the wrapper
uses: the script then always exits inside its one foreground call, so the
harness's background-on-timeout branch is unreachable rather than merely
unlikely.

Script-level failures use enumerated exit codes (state JSON still printed):
  0  attempt executed (codex_exit in the JSON tells how codex itself fared)
  2  argparse usage error
 12  dispatch guard: dispatch file does not name this arm's worktree + report
 13  pidfile guard: a codex process for this arm is still alive
 14  codex binary not found
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

CONTINUATION = (
    "Continue where you left off and finish the original dispatch; your "
    "working root, report path, and constraints are unchanged."
)
LOG_TAIL_LINES = 25


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dir", required=True, help="run directory (DIR)")
    p.add_argument("--worktree", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", required=True)
    p.add_argument("--base", required=True, help="pinned base commit")
    p.add_argument("--brief", help="brief file; required on the first attempt")
    p.add_argument("--report-path", default=None)
    p.add_argument("--run-tag", default="1")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--kind", choices=["initial", "resume", "retry"], default=None)
    p.add_argument("--resume-session", default=None, help="codex session UUID to resume")
    p.add_argument("--watchdog-seconds", type=int, default=1200)
    p.add_argument("--codex-bin", default="codex")
    return p.parse_args(argv)


def emit(state: dict, code: int = 0) -> int:
    print(json.dumps(state, separators=(",", ":")))
    return code


def emit_guard(state: dict, message: str, code: int) -> int:
    """Guard/launch failures still emit the full rung-state shape: the caller's
    schema requires those fields, and a short JSON would push the ladder into
    probe/retry instead of the deliberate stop that guard_exit signals."""
    state.update(
        codex_exit=-1,
        watchdog_fired=False,
        session_id="",
        report_exists=False,
        report_copied=False,
        worktree_touched=False,
        tokens_used=0,
        wall_seconds=0,
        total_wall_seconds=-1,
        log_tail="",
        rung_error=message,
        guard_exit=code,
    )
    return emit(state, code)


def tail(path: Path, lines: int = LOG_TAIL_LINES) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])


def first_session_id(log: Path) -> str:
    if not log.exists():
        return ""
    m = re.search(r"session id: ([0-9a-f-]+)", log.read_text(errors="replace"))
    return m.group(1) if m else ""


def last_tokens_used(log: Path) -> int:
    if not log.exists():
        return 0
    hits = re.findall(r"tokens used[:= ]+([0-9,]+)", log.read_text(errors="replace"))
    return int(hits[-1].replace(",", "")) if hits else 0


def git(worktree: str, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", worktree, *args], capture_output=True, text=True, timeout=60
    )
    return r.stdout.strip()


def worktree_touched(worktree: str, base: str) -> bool:
    return bool(git(worktree, "status", "--porcelain")) or bool(
        git(worktree, "log", "--oneline", f"{base}..HEAD")
    )


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    d = Path(a.dir)
    label = a.label
    report = Path(a.report_path or d / "reports" / f"arm-{label}.md")
    last_msg = d / "reports" / f"arm-{label}.last.md"
    dispatch = d / f"dispatch-{label}.md"
    exec_log = d / f"{label}.exec.log"
    pidfile = d / f"{label}.pid"
    ladder_log = d / f"{label}.ladder.jsonl"
    kind = a.kind or ("resume" if a.resume_session else ("initial" if a.attempt == 1 else "retry"))

    state: dict = {"label": label, "attempt": a.attempt, "kind": kind, "run_tag": a.run_tag}

    # Pidfile guard: never start a second codex while one may still be running
    # for this arm — resuming under a live process would race it on the worktree.
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            pidfile.unlink(missing_ok=True)
        else:
            return emit_guard(state, f"pidfile guard: codex pid {pid} for arm {label} is still alive", 13)

    # First attempt owns the dispatch file and truncates the log; later
    # attempts reuse both so the session's full history stays in one place.
    (d / "reports").mkdir(parents=True, exist_ok=True)
    if a.attempt == 1 or not dispatch.exists():
        if not a.brief:
            return emit_guard(state, "dispatch guard: --brief is required to write the dispatch file", 12)
        preamble = (
            f"Dispatch preamble (run tag {a.run_tag}): your working root is "
            f"{a.worktree}. Your report path is {report}. The brief follows."
        )
        dispatch.write_text(preamble + "\n\n" + Path(a.brief).read_text())
    if a.attempt == 1:
        exec_log.write_text("")
        (d / f"{label}.start").write_text(f"{int(time.time())}\n")

    # Dispatch guard: the file this attempt feeds to codex must name this arm's
    # own worktree and report path — a mispaired dispatch stops here, loudly,
    # instead of silently running another arm's task.
    text = dispatch.read_text(errors="replace")
    if a.worktree not in text or str(report) not in text:
        return emit_guard(
            state,
            f"dispatch guard: {dispatch} does not name worktree {a.worktree} "
            f"and report path {report}",
            12,
        )

    if a.resume_session:
        cmd = [a.codex_bin, "exec", "resume", a.resume_session, "-o", str(last_msg), "-"]
        stdin_bytes = CONTINUATION.encode()
    else:
        cmd = [
            a.codex_bin, "exec", "-C", a.worktree, "-m", a.model,
            "-c", f"model_reasoning_effort={a.effort}",
            "-s", "workspace-write", "--add-dir", str(d / "reports"),
            "-o", str(last_msg), "-",
        ]
        stdin_bytes = dispatch.read_bytes()

    started = int(time.time())
    watchdog_fired = False
    try:
        with exec_log.open("ab") as logf:
            logf.write(f"--- attempt {a.attempt} ({kind}) ---\n".encode())
            logf.flush()
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=logf, stderr=logf,
                start_new_session=True,
            )
            pidfile.write_text(str(proc.pid))
            try:
                proc.communicate(input=stdin_bytes, timeout=a.watchdog_seconds)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                watchdog_fired = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=30)
                rc = 137
    except FileNotFoundError:
        pidfile.unlink(missing_ok=True)
        return emit_guard(state, f"codex binary not found: {a.codex_bin}", 14)
    finally:
        pidfile.unlink(missing_ok=True)

    ended = int(time.time())
    (d / f"{label}.end").write_text(f"{ended}\n")
    with exec_log.open("a") as logf:
        logf.write(f"CODEX_EXIT={rc}\n")

    report_copied = False
    if not report.exists() and last_msg.exists() and last_msg.stat().st_size > 0:
        shutil.copyfile(last_msg, report)
        report_copied = True

    start_file = d / f"{label}.start"
    total_wall = ended - int(start_file.read_text().strip()) if start_file.exists() else -1
    state.update(
        codex_exit=rc,
        watchdog_fired=watchdog_fired,
        session_id=first_session_id(exec_log),
        report_exists=report.exists(),
        report_copied=report_copied,
        worktree_touched=worktree_touched(a.worktree, a.base),
        tokens_used=last_tokens_used(exec_log),
        wall_seconds=ended - started,
        total_wall_seconds=total_wall,
        log_tail=tail(exec_log),
    )
    with ladder_log.open("a") as f:
        f.write(json.dumps(state, separators=(",", ":")) + "\n")
    return emit(state, 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
