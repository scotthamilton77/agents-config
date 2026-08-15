"""Tests for run_codex_arm.py against a fake `codex` binary.

The stub's behavior is selected via FAKE_CODEX_MODE: success (writes the -o
file and exits 0), hang (prints a session id then sleeps past any watchdog),
fail-launch (transport-style failure: exit 1, no session id). A `resume`
subcommand always completes successfully.

Run: uvx pytest .claude/workflows/bake-off/tests/ -q
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parent.parent / "run_codex_arm.py"

STUB = r'''#!/usr/bin/env python3
import os, sys, time
mode = os.environ.get("FAKE_CODEX_MODE", "success")
args = sys.argv[1:]
sys.stdin.read()
out = args[args.index("-o") + 1]
if "resume" in args:
    print("session id: resumed0-dead-beef-0000-000000000000")
    open(out, "w").write("resumed final message report\n")
    print("tokens used: 4321")
    sys.exit(0)
if mode == "fail-launch":
    print("stream error: HTTP 520")
    sys.exit(1)
print("session id: deadbeef-0000-0000-0000-000000000000", flush=True)
if mode == "hang":
    time.sleep(300)
    sys.exit(0)
open(out, "w").write("arm final message report\n")
print("tokens used: 1234")
sys.exit(0)
'''


@pytest.fixture()
def env(tmp_path):
    """A run dir, a tiny git worktree at a base commit, a brief, and the stub."""
    d = tmp_path / "run"
    d.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
    (wt / "f.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(wt), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-qm", "base"], check=True)
    base = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief\ndo the thing\n")
    stub = tmp_path / "codex"
    stub.write_text(STUB)
    stub.chmod(0o755)
    return {"dir": d, "wt": wt, "base": base, "brief": brief, "stub": stub}


def run(env_, *extra, mode="success", watchdog=30):
    cmd = [
        sys.executable, str(RUNNER),
        "--dir", str(env_["dir"]), "--worktree", str(env_["wt"]),
        "--label", "X", "--model", "fake-model", "--effort", "low",
        "--base", env_["base"], "--brief", str(env_["brief"]),
        "--watchdog-seconds", str(watchdog), "--codex-bin", str(env_["stub"]),
        *extra,
    ]
    e = dict(os.environ, FAKE_CODEX_MODE=mode)
    r = subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=120)
    state = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    return r.returncode, state


def test_clean_pass(env):
    code, s = run(env)
    assert code == 0
    assert s["codex_exit"] == 0 and s["watchdog_fired"] is False
    assert s["kind"] == "initial" and s["attempt"] == 1
    assert s["session_id"] == "deadbeef-0000-0000-0000-000000000000"
    assert s["report_exists"] is True and s["report_copied"] is True
    assert s["tokens_used"] == 1234
    assert s["worktree_touched"] is False
    log = (env["dir"] / "X.exec.log").read_text()
    assert "CODEX_EXIT=0" in log
    ladder = (env["dir"] / "X.ladder.jsonl").read_text().splitlines()
    assert len(ladder) == 1 and json.loads(ladder[0])["codex_exit"] == 0
    assert (env["dir"] / "X.start").exists() and (env["dir"] / "X.end").exists()


def test_watchdog_kill(env):
    t0 = time.time()
    code, s = run(env, mode="hang", watchdog=2)
    assert code == 0
    assert s["watchdog_fired"] is True and s["codex_exit"] == 137
    assert s["session_id"] == "deadbeef-0000-0000-0000-000000000000"
    assert s["report_exists"] is False
    assert time.time() - t0 < 60  # killed by watchdog, not by test timeout


def test_launch_failure_leaves_clean_state(env):
    code, s = run(env, mode="fail-launch")
    assert code == 0
    assert s["codex_exit"] == 1
    assert s["session_id"] == ""  # nothing to resume — fresh-retry territory
    assert s["worktree_touched"] is False and s["report_exists"] is False


def test_resume_after_watchdog(env):
    run(env, mode="hang", watchdog=2)
    code, s = run(env, "--attempt", "2", "--resume-session",
                  "deadbeef-0000-0000-0000-000000000000")
    assert code == 0
    assert s["kind"] == "resume" and s["codex_exit"] == 0
    assert s["report_exists"] is True
    ladder = (env["dir"] / "X.ladder.jsonl").read_text().splitlines()
    assert len(ladder) == 2
    log = (env["dir"] / "X.exec.log").read_text()
    assert "--- attempt 1 (initial) ---" in log and "--- attempt 2 (resume) ---" in log


def test_dispatch_guard_trips_on_mispaired_dispatch(env):
    (env["dir"] / "dispatch-X.md").write_text("some other arm's dispatch\n")
    code, s = run(env, "--attempt", "2")
    assert code == 12
    assert "dispatch guard" in s["error"]


def test_pidfile_guard_refuses_live_process(env):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (env["dir"] / "X.pid").write_text(str(p.pid))
    try:
        code, s = run(env)
        assert code == 13
        assert "pidfile guard" in s["error"]
    finally:
        p.kill()
        p.wait()


def test_pidfile_guard_clears_dead_pid(env):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    (env["dir"] / "X.pid").write_text(str(p.pid))
    code, s = run(env)
    assert code == 0 and s["codex_exit"] == 0


def test_worktree_touched_detected(env):
    (env["wt"] / "new.txt").write_text("dirty\n")
    code, s = run(env)
    assert code == 0
    assert s["worktree_touched"] is True
