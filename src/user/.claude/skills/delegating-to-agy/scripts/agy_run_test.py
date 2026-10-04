#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pytest>=8"]
# ///
"""Tests for the agy launcher.

Run: uv run agy_run_test.py

The suite never runs the real agy and never reads the real home. Every agy
process is a scripted Python stand-in launched through the spawn seam, every home
is a directory under pytest's temporary root, the settings file is a fixture,
and every wait the launcher makes runs on a fake clock.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT_PATH = HERE / "agy_run.py"


def _load():
    spec = importlib.util.spec_from_file_location(SCRIPT_PATH.stem, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agy = _load()

P = PurePosixPath
MODEL = "gemini-3.8-flash-high"
NOTICE = "[agy] print timeout after 1s with turn in progress; returning partial output\n"
AGY_ERROR = (
    'AGY_ERROR: {"short_error": "model unavailable", "status": "UNAVAILABLE", '
    '"error_code": 14, "code_kind": "server", "retryable": true, "error_id": "e-1"}\n'
)
REMEDY = "add this directory or an ancestor of it to trustedWorkspaces"
RELATIVE_ENTRY = "a relative entry trusts nothing"

# The lens agent definition, written out rather than read back from the launcher,
# so a drifted definition fails here instead of agreeing with itself.
AGENT_MD = """\
---
name: agy-lens
description: Read-only review lens. Reads, searches and lists files in this snapshot and nothing else.
tools: [view_file, grep_search, find_by_name, list_dir]
subagent: false
---

# Lens

You review a snapshot of a repository at one revision. You can read, search and list files in it and nothing else. The change under review is in .review/change.diff, a unified diff against the base revision, with original paths. Instruction files the change adds or modifies were renamed with the suffix .under-review; read them as ordinary files and cite them by their original names. Answer the request directly. Do not write a plan document.
"""


# --- canned stream-json, in the shapes agy 1.2.12 emits -----------------------


def init(agent: str | None = None, mode: str = "request-review") -> dict:
    body = {"cwd": "/snapshot", "tools": ["view_file", "run_command"], "permission_mode": mode}
    if agent:
        body["agent"] = agent
    return {"event": "init", "conversation_id": "c-1", "init": body}


def tool(index: int, name: str, **parameters: str) -> list[dict]:
    """One tool call as agy streams it: the step entering ACTIVE, then DONE."""
    step = {
        "conversation_id": "c-1",
        "step_index": index,
        "step_type": "tool",
        "tool_name": name,
        "tool_info": {"name": name, "parameters": parameters},
    }
    done = {**step, "state": "DONE", "tool_info": {**step["tool_info"], "output": "3 lines"}}
    return [
        {"event": "step_update", "step_update": {**step, "state": "ACTIVE"}},
        {"event": "step_update", "step_update": done},
    ]


def reply(index: int, text: str) -> list[dict]:
    """An agent response step, which also enters ACTIVE but is not a tool call."""
    step = {"conversation_id": "c-1", "step_index": index, "step_type": "agent_response"}
    return [
        {"event": "step_update", "step_update": {**step, "state": "ACTIVE", "text_delta": text}},
        {"event": "step_update", "step_update": {**step, "state": "DONE", "text_delta": ""}},
    ]


def result(
    response: str = "The answer is 42.\n",
    status: str = "SUCCESS",
    denied: tuple[str, ...] | list[str] = (),
    error: str | None = None,
) -> dict:
    body: dict = {
        "conversation_id": "c-1",
        "status": status,
        "response": response,
        "duration_seconds": 1.5,
        "num_turns": 1,
        "usage": {"input_tokens": 1000, "output_tokens": 234, "total_tokens": 1234},
    }
    if denied:
        body["denied_actions"] = [{"action": "write_file", "display_name": name} for name in denied]
    if error:
        body["error"] = error
    return {"event": "result", "result": body}


def stream(*parts: dict | list[dict]) -> str:
    events: list[dict] = []
    for part in parts:
        events.extend(part if isinstance(part, list) else [part])
    return "".join(json.dumps(event) + "\n" for event in events)


THREE_TOOLS = [
    *tool(2, "view_file", AbsolutePath="/snapshot/a.txt"),
    *tool(4, "grep_search", Query="needle", SearchPath="/snapshot"),
    *tool(6, "list_dir", DirectoryPath="/snapshot/src"),
]
TOOL_LEDGER = [
    "[agy-run] tool=view_file /snapshot/a.txt",
    "[agy-run] tool=grep_search needle",
    "[agy-run] tool=list_dir /snapshot/src",
]
STATUS_LINE = "[agy-run] status=SUCCESS turns=1 tokens=1234 denied="
# One file read, which a lens needs before its answer counts as a review.
READ = tool(1, "view_file", AbsolutePath="/snapshot/.review/change.diff")


# --- the fake agy, the fake clock and the rig that wires them in ----------------

FAKE_AGY = """\
import json, pathlib, signal, sys, time
spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
if spec["ignore_term"]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
sys.stdout.write(spec["stdout"])
sys.stdout.flush()
sys.stderr.write(spec["stderr"])
sys.stderr.flush()
pathlib.Path(spec["ready"]).touch()
if spec["sleep"]:
    time.sleep(3600)
sys.exit(spec["exit"])
"""


@dataclass
class Call:
    argv: list[str]
    cwd: Path
    env: dict[str, str]


class FakeAgy:
    """A spawn seam that records each launch, then runs a scripted stand-in for agy.

    The stand-in writes its canned stdout and stderr, touches a ready file, then
    either exits with the chosen code or sleeps, optionally ignoring SIGTERM. The
    ready file lets the fake clock hold still until the stand-in has installed its
    signal disposition, so a kill test never races the child's startup.
    """

    def __init__(self, root: Path) -> None:
        root.mkdir()
        self.script = root / "fake_agy.py"
        self.script.write_text(FAKE_AGY)
        self.spec = root / "spec.json"
        self.ready = root / "ready"
        self.calls: list[Call] = []
        self.procs: list[subprocess.Popen] = []
        self.on_spawn = None
        self.behave(stdout=stream(init(), READ, result()))

    def behave(self, stdout="", stderr="", exit=0, sleep=False, ignore_term=False) -> None:
        self.spec.write_text(
            json.dumps(
                {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit": exit,
                    "sleep": sleep,
                    "ignore_term": ignore_term,
                    "ready": str(self.ready),
                }
            )
        )

    def spawn(self, argv, **kwargs):
        call = Call(list(argv), Path(kwargs["cwd"]), dict(kwargs["env"]))
        self.calls.append(call)
        if self.on_spawn:
            self.on_spawn(call)
        self.ready.unlink(missing_ok=True)
        proc = subprocess.Popen([sys.executable, str(self.script), str(self.spec)], **kwargs)
        self.procs.append(proc)
        return proc


class FakeClock:
    """A clock that stands still until its gate file exists, then advances one step per reading.

    ``last`` is the value most recently returned, which is the launcher's idea of
    "now" when it acts on that reading. ``on_ready`` runs once, on the first
    reading after the gate opens, and is how a test delivers a signal mid-run.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.last = 0.0
        self.step = 1.0
        self.gate: Path | None = None
        self.on_ready = None

    def __call__(self) -> float:
        self.last = self.now
        if self.gate is None or self.gate.exists():
            if self.on_ready is not None:
                hook, self.on_ready = self.on_ready, None
                hook()
            self.now += self.step
        return self.last


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ledger(self) -> list[str]:
        return [line for line in self.err.splitlines() if line.startswith("[agy-run] ")]

    @property
    def reasons(self) -> list[str]:
        return [line for line in self.ledger if line.startswith("[agy-run] reason=")]


class Repo(NamedTuple):
    path: Path
    base: str
    head: str


class Rig:
    def __init__(self, tmp_path: Path, capsys) -> None:
        self.capsys = capsys
        self.tmp = tmp_path / "tmp"
        self.real_home = tmp_path / "real-home"
        (self.real_home / "Library" / "Keychains").mkdir(parents=True)
        self.trusted = tmp_path / "trusted"
        self.trusted.mkdir()
        self.settings = tmp_path / "settings.json"
        self.settings.write_text(json.dumps({"trustedWorkspaces": [str(self.trusted)]}))
        self.fake = FakeAgy(tmp_path / "fake")
        self.clock = FakeClock()
        self.runs: list[tuple[list[str], subprocess.CompletedProcess]] = []
        self.run_hook = None

    def run(self, argv, **kwargs):
        """The git seam: real git, recorded, unless a test's hook injects a result."""
        if self.run_hook:
            injected = self.run_hook(argv)
            if injected is not None:
                return injected
        done = subprocess.run(argv, **kwargs)
        self.runs.append((list(argv), done))
        return done

    def argv(self, mode, repo=None, *, extra=(), prompt="Do the task.", timeout="42", base=None, rev=None):
        if mode == "worker":
            return ["worker", *extra, "--model", MODEL, "--timeout", timeout, "-p", prompt]
        argv = ["lens", "--repo", str(repo.path), "--base", base or repo.base]
        if rev:
            argv += ["--rev", rev]
        return [*argv, *extra, "--model", MODEL, "-p", prompt]

    def launch(self, argv, spawn=None) -> Result:
        code = agy.main(
            argv,
            spawn=spawn or self.fake.spawn,
            run=self.run,
            clock=self.clock,
            real_home=self.real_home,
            settings=self.settings,
        )
        captured = self.capsys.readouterr()
        return Result(code, captured.out, captured.err)


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Isolate git from the user's config and point the launcher's temp root at a fixture."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Fixture")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "fixture@example.invalid")
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))


@pytest.fixture
def rig(tmp_path, capsys, monkeypatch):
    built = Rig(tmp_path, capsys)
    monkeypatch.chdir(built.trusted)
    return built


@pytest.fixture
def kills(rig, monkeypatch):
    """Record every signal the launcher sends to a process group, stamped with the fake clock."""
    recorded: list[tuple[float, int]] = []
    real = os.killpg

    def killpg(pgid, sig):
        if sig:
            recorded.append((rig.clock.last, sig))
        real(pgid, sig)

    monkeypatch.setattr(os, "killpg", killpg)
    return recorded


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def new_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    return path


def commit(repo: Path, files: dict[str, str | None]) -> str:
    for rel, text in files.items():
        target = repo / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")
    return git(repo, "rev-parse", "HEAD").decode().strip()


def commit_through_index(repo: Path, files: dict[str, str], links: dict[str, str] | None = None) -> str:
    """Commit files and symlinks on top of HEAD without writing them to the working tree, and return the commit.

    Two paths that differ only by case or Unicode form stay two paths this way,
    even on a filesystem where the working tree could hold only one. The paths
    travel on stdin, because git on macOS recomposes Unicode in its arguments.
    """
    entries = [("100644", rel, text) for rel, text in files.items()]
    entries += [("120000", rel, target) for rel, target in (links or {}).items()]
    lines = []
    for mode, rel, content in entries:
        argv = ["git", "-C", str(repo), "hash-object", "-w", "--stdin"]
        blob = subprocess.run(argv, input=content.encode(), check=True, capture_output=True).stdout.decode().strip()
        lines.append(f"{mode} blob {blob}\t{rel}\n")
    index_info = ["git", "-C", str(repo), "update-index", "--add", "--index-info"]
    subprocess.run(index_info, input="".join(lines).encode(), check=True, capture_output=True)
    tree = git(repo, "write-tree").decode().strip()
    has_head = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", "HEAD"], capture_output=True)
    parent = ["-p", "HEAD"] if has_head.returncode == 0 else []
    made = git(repo, "commit-tree", tree, *parent, "-m", "fixture").decode().strip()
    git(repo, "update-ref", "HEAD", made)
    return made


@pytest.fixture
def repo(tmp_path) -> Repo:
    """Two commits: the change modifies the root AGENTS.md; a hooks file sits unchanged."""
    root = new_repo(tmp_path / "repo")
    base = commit(
        root,
        {
            "AGENTS.md": "Accepted rules.\n",
            ".agents/hooks.json": "{}\n",
            "src/app.py": "print('v1')\n",
            "gone.txt": "deleted by the change\n",
        },
    )
    head = commit(root, {"AGENTS.md": "Rules under review.\n", "src/app.py": "print('v2')\n", "gone.txt": None})
    return Repo(root, base, head)


REPO_RENAMED = [
    (P(".agents/hooks.json"), P(".agents/hooks.json.under-review")),
    (P("AGENTS.md"), P("AGENTS.md.under-review")),
]


def assert_refused(r: Result, rig: Rig, *names: str) -> None:
    assert r.code == 78, r.err
    for name in names:
        assert name in r.err
    assert "[agy-run] reason=" not in r.err
    assert r.out == ""
    assert rig.fake.calls == []


def group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def listing(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


# --- slice A: launcher core and worker mode -------------------------------------


def test_a1_worker_spawns_the_exact_argv_in_the_invoking_directory_with_the_parent_env(rig):
    r = rig.launch(["worker", "--model", MODEL, "--timeout", "42", "-p", "Fix the failing test."])
    assert r.code == 0, r.err
    [call] = rig.fake.calls
    assert call.argv == [
        "agy", "-p", "Fix the failing test.", "--model", MODEL, "--output-format", "stream-json",
        "--print-timeout", "42s", "--mode", "accept-edits",
    ]  # fmt: skip
    assert call.cwd.resolve() == rig.trusted.resolve()
    assert call.env == dict(os.environ)
    assert call.env["HOME"] == os.environ["HOME"]
    for banned in (
        "sandbox-exec", "--agent", "--add-dir", "--effort", "--sandbox",
        "--dangerously-skip-permissions", "--disable-slash-commands",
    ):  # fmt: skip
        assert banned not in call.argv


BYPASS_FLAGS = ["--skip-permissions", "--dangerously-skip-permissions", "--sandbox"]


@pytest.mark.parametrize("flag", BYPASS_FLAGS)
@pytest.mark.parametrize("mode", ["worker", "lens"])
def test_a2_a_bypass_or_sandbox_flag_is_refused_before_anything_spawns(rig, repo, mode, flag):
    r = rig.launch(rig.argv(mode, repo, extra=[flag]))
    assert_refused(r, rig, flag)


@pytest.mark.parametrize(
    "prompt",
    ["--sandbox", "Check whether --skip-permissions, --dangerously-skip-permissions or --sandbox is safe."],
)
def test_a2_the_prompt_after_p_is_never_read_as_a_flag(rig, prompt):
    r = rig.launch(rig.argv("worker", prompt=prompt))
    assert r.code == 0, r.err
    [call] = rig.fake.calls
    assert call.argv[2] == prompt


A3_REFUSALS = {
    "worker-missing-model": (lambda R: ["worker", "--timeout", "42", "-p", "P"], "--model"),
    "lens-missing-model": (lambda R: ["lens", "--repo", str(R.path), "--base", R.base, "-p", "P"], "--model"),
    "worker-missing-p": (lambda R: ["worker", "--model", MODEL, "--timeout", "42"], "-p"),
    "lens-missing-p": (lambda R: ["lens", "--repo", str(R.path), "--base", R.base, "--model", MODEL], "-p"),
    "worker-missing-timeout": (lambda R: ["worker", "--model", MODEL, "-p", "P"], "--timeout"),
    "lens-missing-repo": (lambda R: ["lens", "--base", R.base, "--model", MODEL, "-p", "P"], "--repo"),
    "lens-missing-base": (lambda R: ["lens", "--repo", str(R.path), "--model", MODEL, "-p", "P"], "--base"),
    "worker-effort-without-a-value": (
        lambda R: ["worker", "--model", "gemini-3.8-flash", "--timeout", "42", "--effort", "-p", "P"],
        "--effort",
    ),
    "lens-effort-without-a-value": (
        lambda R: ["lens", "--repo", str(R.path), "--base", R.base, "--model", "gemini-3.8-flash", "--effort", "-p", "P"],
        "--effort",
    ),
    "agy-flag-disable-slash-commands": (
        lambda R: ["worker", "--disable-slash-commands", "--model", MODEL, "--timeout", "42", "-p", "P"],
        "--disable-slash-commands",
    ),
    "agy-flag-output-format": (
        lambda R: ["worker", "--output-format", "json", "--model", MODEL, "--timeout", "42", "-p", "P"],
        "--output-format",
    ),
    "element-after-prompt": (
        lambda R: ["worker", "--model", MODEL, "--timeout", "42", "-p", "P", "stray-element"],
        "stray-element",
    ),
    "worker-claude-model": (
        lambda R: ["worker", "--model", "claude-opus-4-5", "--timeout", "42", "-p", "P"],
        "claude-opus-4-5",
    ),
    "lens-claude-model": (
        lambda R: ["lens", "--repo", str(R.path), "--base", R.base, "--model", "claude-sonnet-5", "-p", "P"],
        "claude-sonnet-5",
    ),
}


@pytest.mark.parametrize("case", A3_REFUSALS, ids=list(A3_REFUSALS))
def test_a3_an_invalid_invocation_is_refused_with_78_before_anything_spawns(rig, repo, case):
    build, name = A3_REFUSALS[case]
    r = rig.launch(build(repo))
    assert_refused(r, rig, name)


@pytest.mark.parametrize("prompt", ["--effort", "Use --effort high on the retry."])
def test_a3_effort_as_or_inside_the_prompt_spawns_verbatim(rig, prompt):
    r = rig.launch(rig.argv("worker", prompt=prompt))
    assert r.code == 0, r.err
    [call] = rig.fake.calls
    assert call.argv[2] == prompt


# What agy 1.2.16 prints for each pairing it refuses, before any turn runs.
AGY_REFUSED_PAIRS = {
    "a-level-the-model-lacks": (
        "gemini-3.1-pro",
        "medium",
        (
            'error: invalid model selection (--model "gemini-3.1-pro" --effort "medium"): '
            'gemini-3.1-pro has no "medium" effort (available: low, high)\n'
        ),
    ),
    "a-variant-id-with-a-conflicting-effort": (
        "gemini-3.8-flash-low",
        "high",
        (
            'error: invalid model selection (--model "gemini-3.8-flash-low" --effort "high"): '
            "--model gemini-3.8-flash-low conflicts with --effort=high\n"
        ),
    ),
    "an-unknown-model": (
        "nope",
        "low",
        'error: invalid model selection (--model "nope" --effort "low"): --effort is not supported for model "nope"\n',
    ),
    "a-level-agy-never-offered": (
        "gemini-3.8-flash",
        "zzz",
        (
            'error: invalid model selection (--model "gemini-3.8-flash" --effort "zzz"): '
            'invalid --effort "zzz" (valid: low, medium, high, xhigh, max)\n'
        ),
    ),
}


def _with_model(argv: list[str], model: str, effort: str | None) -> list[str]:
    """Swap the rig's model for another and add an effort, both before -p."""
    at = argv.index("--model")
    return [*argv[:at], "--model", model, *([] if effort is None else ["--effort", effort]), *argv[at + 2 :]]


@pytest.mark.parametrize("mode", ["worker", "lens"])
def test_model_and_effort_reach_agy_unchanged(rig, repo, mode):
    r = rig.launch(_with_model(rig.argv(mode, repo), "gemini-3.8-flash", "low"))
    [call] = rig.fake.calls
    assert call.argv[call.argv.index("--model") + 1] == "gemini-3.8-flash"
    assert call.argv[call.argv.index("--effort") + 1] == "low"
    assert call.argv.count("--model") == call.argv.count("--effort") == 1
    assert r.code in (0, 70), r.err


@pytest.mark.parametrize("mode", ["worker", "lens"])
def test_without_effort_the_model_reaches_agy_alone(rig, repo, mode):
    rig.launch(_with_model(rig.argv(mode, repo), "gemini-3.8-flash-low", None))
    [call] = rig.fake.calls
    assert call.argv[call.argv.index("--model") + 1] == "gemini-3.8-flash-low"
    assert "--effort" not in call.argv


@pytest.mark.parametrize("case", AGY_REFUSED_PAIRS, ids=list(AGY_REFUSED_PAIRS))
def test_a_pairing_agy_refuses_is_spawned_as_given_and_reported_as_a_refused_invocation(rig, case):
    model, effort, message = AGY_REFUSED_PAIRS[case]
    rig.fake.behave(stderr=message, exit=1)
    r = rig.launch(_with_model(rig.argv("worker"), model, effort))
    [call] = rig.fake.calls
    assert call.argv[call.argv.index("--model") + 1] == model
    assert call.argv[call.argv.index("--effort") + 1] == effort
    assert r.code == 78
    assert r.reasons == []
    assert message in r.err
    assert "agy_run.py: agy refused the model and effort" in r.err
    assert r.out == ""


def test_a_bare_model_without_effort_is_agys_refusal_and_reported_as_a_refused_invocation(rig):
    message = (
        'error: invalid model selection (--model "gemini-3.8-flash" --effort ""): '
        "--model gemini-3.8-flash requires --effort (available: low, medium, high)\n"
    )
    rig.fake.behave(stderr=message, exit=1)
    r = rig.launch(_with_model(rig.argv("worker"), "gemini-3.8-flash", None))
    [call] = rig.fake.calls
    assert "--effort" not in call.argv
    assert r.code == 78
    assert message in r.err


def test_an_agy_too_old_for_the_effort_flag_is_reported_as_any_agy_error(rig):
    message = "flag provided but not defined: -effort\n"
    rig.fake.behave(stderr=message, exit=2)
    r = rig.launch(_with_model(rig.argv("worker"), "gemini-3.8-flash", "low"))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=error"]
    assert message in r.err


def test_a4_a_clean_run_exits_0_with_the_response_alone_on_stdout(rig):
    response = "First line.\n  Second line, indented, with a trailing space \n"
    rig.fake.behave(stdout=stream(init(mode="accept-edits"), reply(1, "Looking."), THREE_TOOLS, result(response)))
    r = rig.launch(rig.argv("worker"))
    assert r.code == 0
    assert r.out == response
    assert r.reasons == []


@pytest.mark.parametrize("mode, code, out, reasons", [
    ("lens", 70, "", ["[agy-run] reason=unread"]),
    ("worker", 0, "The answer is 42.\n", []),
])  # fmt: skip
def test_a4_a_run_without_a_tool_step_is_unread_in_a_lens_and_usable_in_a_worker(rig, repo, mode, code, out, reasons):
    rig.fake.behave(stdout=stream(init(), reply(1, "No need to look."), result()))
    r = rig.launch(rig.argv(mode, repo))
    assert r.code == code
    assert r.out == out
    assert r.reasons == reasons
    assert [line for line in r.ledger if line.startswith("[agy-run] status=")] == [STATUS_LINE]


A5_CASES = {
    "empty": (result(response=""), "empty", ""),
    "denied": (result(denied=["WriteToFile"]), "denied", "WriteToFile"),
    "denied-and-empty": (result(response="", denied=["WriteToFile"]), "denied", "WriteToFile"),
    "two-denied": (result(denied=["WriteToFile", "RunCommand"]), "denied", "WriteToFile,RunCommand"),
}


@pytest.mark.parametrize("case", A5_CASES, ids=list(A5_CASES))
def test_a5_an_unusable_run_exits_70_with_its_reason(rig, case):
    event, reason, denied = A5_CASES[case]
    rig.fake.behave(stdout=stream(init(), event))
    r = rig.launch(rig.argv("worker"))
    assert r.code == 70
    assert r.reasons == [f"[agy-run] reason={reason}"]
    [status] = [line for line in r.ledger if line.startswith("[agy-run] status=")]
    assert status.split(" denied=")[1] == denied
    assert r.out == ""


A6_CASES = {
    "status-error-exit-1": dict(
        stdout=stream(init(), result(status="ERROR", response="", error="unknown model gemini-9")),
        stderr="Error: unknown model gemini-9\n",
        exit=1,
    ),
    "agy-error-line-exit-3": dict(stdout=stream(init()), stderr=AGY_ERROR, exit=3),
    "status-error-exit-0": dict(
        stdout=stream(init(), result(status="ERROR", response="Partial text.")),
        stderr="agy: the turn failed\n",
        exit=0,
    ),
}


@pytest.mark.parametrize("case", A6_CASES, ids=list(A6_CASES))
def test_a6_an_error_exits_75_with_agy_s_stderr_verbatim(rig, case):
    rig.fake.behave(**A6_CASES[case])
    r = rig.launch(rig.argv("worker"))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=error"]
    assert A6_CASES[case]["stderr"] in r.err
    assert r.out == ""


def test_a6_an_absent_agy_binary_is_no_route_and_spawns_nothing(rig):
    def absent(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    r = rig.launch(rig.argv("worker"), spawn=absent)
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=no-route"]
    assert r.out == ""
    assert rig.fake.calls == []


def test_a7_the_watchdog_ends_a_silent_run_and_kills_its_group(rig, kills):
    rig.fake.behave(stdout=stream(init()), sleep=True, ignore_term=True)
    rig.clock.gate = rig.fake.ready
    rig.clock.step = 10
    r = rig.launch(rig.argv("worker", timeout="1"))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=timeout"]
    assert r.out == ""
    (term_at, first), (kill_at, second) = kills
    assert (first, second) == (signal.SIGTERM, signal.SIGKILL)
    assert term_at >= 1 + 30
    assert kill_at - term_at == 10
    assert group_gone(rig.fake.procs[0].pid)


@pytest.mark.parametrize("response", ["", "Partial answer, cut o"], ids=["empty", "partial"])
def test_a7_the_print_timeout_notice_is_a_timeout_whatever_the_result_holds(rig, response):
    rig.fake.behave(stdout=stream(init(), result(response=response)), stderr=NOTICE)
    r = rig.launch(rig.argv("worker"))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=timeout"]
    assert r.out == ""


def test_a8_two_identical_worker_runs_record_identical_argv(rig):
    for _ in range(2):
        assert rig.launch(rig.argv("worker")).code == 0
    first, second = rig.fake.calls
    assert first.argv == second.argv


def test_a8_two_identical_lens_runs_differ_only_in_their_own_snapshot_and_home(rig, repo):
    for _ in range(2):
        assert rig.launch(rig.argv("lens", repo)).code == 0
    first, second = rig.fake.calls

    def placeholder(call: Call) -> list[str]:
        assert str(call.cwd) in call.argv[8]
        return [*call.argv[:8], call.argv[8].replace(str(call.cwd), "<SNAPSHOT>"), *call.argv[9:]]

    assert placeholder(first) == placeholder(second)
    assert first.cwd != second.cwd
    assert first.env["HOME"] != second.env["HOME"]


def test_a8_classify_returns_an_equal_outcome_for_equal_inputs():
    events = [init(), *THREE_TOOLS, result()]
    first = agy.classify(0, events, "note\n", False)
    assert isinstance(first, agy.Outcome)
    assert first == agy.classify(0, copy.deepcopy(events), "note\n", False)


@pytest.mark.parametrize("where", ["listed", "descendant"])
def test_a9_a_worker_spawns_at_or_beneath_a_trusted_workspace(rig, monkeypatch, where):
    here = rig.trusted if where == "listed" else rig.trusted / "pkg" / "deep"
    here.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(here)
    r = rig.launch(rig.argv("worker"))
    assert r.code == 0, r.err
    assert len(rig.fake.calls) == 1


A9_REFUSED = ["prefix-sibling", "unrelated", "missing-file", "unparseable-file", "no-list"]


@pytest.mark.parametrize("case", A9_REFUSED)
def test_a9_a_worker_outside_every_trusted_workspace_is_refused(rig, monkeypatch, tmp_path, case):
    here = rig.trusted
    if case == "prefix-sibling":
        here = rig.trusted.with_name(rig.trusted.name + "-backup")
    elif case == "unrelated":
        here = tmp_path / "elsewhere"
    elif case == "missing-file":
        rig.settings.unlink()
    elif case == "unparseable-file":
        rig.settings.write_text("{not json")
    else:
        rig.settings.write_text(json.dumps({"colorScheme": "dark"}))
    here.mkdir(exist_ok=True)
    monkeypatch.chdir(here)
    r = rig.launch(rig.argv("worker"))
    assert_refused(r, rig, str(here.resolve()), str(rig.settings), REMEDY, RELATIVE_ENTRY)


def test_a9_lens_mode_performs_no_trusted_workspace_check(rig, repo, monkeypatch, tmp_path):
    rig.settings.unlink()
    monkeypatch.chdir(tmp_path)
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == 0, r.err
    assert len(rig.fake.calls) == 1


def test_a10_the_worker_ledger(rig):
    rig.fake.behave(
        stdout=stream(init(mode="accept-edits"), reply(1, "Reading."), THREE_TOOLS, result()),
        stderr="agy: a line of agy's own\n",
    )
    r = rig.launch(rig.argv("worker"))
    pid = rig.fake.procs[0].pid
    assert r.ledger == [f"[agy-run] pid={pid}", "[agy-run] permission_mode=accept-edits", *TOOL_LEDGER, STATUS_LINE]
    assert "agy: a line of agy's own\n" in r.err


def test_a10_the_lens_ledger_names_the_agent(rig, repo):
    rig.fake.behave(stdout=stream(init(agent="agy-lens"), reply(1, "Reading."), THREE_TOOLS, result()))
    r = rig.launch(rig.argv("lens", repo))
    pid = rig.fake.procs[0].pid
    assert r.ledger == [
        f"[agy-run] pid={pid}",
        "[agy-run] agent=agy-lens permission_mode=request-review",
        *TOOL_LEDGER,
        STATUS_LINE,
    ]


def test_a10_a_denied_run_ledger_names_the_action_then_the_reason(rig):
    rig.fake.behave(stdout=stream(init(), THREE_TOOLS, result(response="", denied=["WriteToFile"])))
    r = rig.launch(rig.argv("worker"))
    pid = rig.fake.procs[0].pid
    assert r.ledger == [
        f"[agy-run] pid={pid}",
        "[agy-run] permission_mode=request-review",
        *TOOL_LEDGER,
        "[agy-run] status=SUCCESS turns=1 tokens=1234 denied=WriteToFile",
        "[agy-run] reason=denied",
    ]


def test_a10_a_run_without_a_result_has_no_status_line_and_ends_in_no_result(rig):
    rig.fake.behave(stdout=stream(init(), THREE_TOOLS))
    r = rig.launch(rig.argv("worker"))
    pid = rig.fake.procs[0].pid
    assert r.ledger == [
        f"[agy-run] pid={pid}",
        "[agy-run] permission_mode=request-review",
        *TOOL_LEDGER,
        "[agy-run] reason=no-result",
    ]


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
@pytest.mark.parametrize("mode", ["worker", "lens"])
def test_a11_a_signal_while_agy_runs_kills_its_group_and_exits_75(rig, repo, kills, mode, signum):
    rig.fake.behave(stdout=stream(init()), sleep=True, ignore_term=True)
    rig.clock.gate = rig.fake.ready
    rig.clock.step = 5
    rig.clock.on_ready = lambda: os.kill(os.getpid(), signum)
    r = rig.launch(rig.argv(mode, repo))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=signal"]
    assert r.out == ""
    assert len(rig.fake.calls) == 1
    (term_at, first), (kill_at, second) = kills
    assert (first, second) == (signal.SIGTERM, signal.SIGKILL)
    assert kill_at - term_at == 10
    assert group_gone(rig.fake.procs[0].pid)


@pytest.mark.parametrize("ending", ["signal", "watchdog"])
def test_a11_a_run_after_a_signal_or_a_timeout_starts_clean(rig, ending):
    rig.fake.behave(stdout=stream(init()), sleep=True, ignore_term=True)
    rig.clock.gate = rig.fake.ready
    rig.clock.step = 5
    timeout = "42"
    if ending == "signal":
        rig.clock.on_ready = lambda: os.kill(os.getpid(), signal.SIGTERM)
    else:
        timeout = "1"
    first = rig.launch(rig.argv("worker", timeout=timeout))
    assert first.code == 75
    assert group_gone(rig.fake.procs[0].pid)
    rig.fake.behave(stdout=stream(init(), result()))
    second = rig.launch(rig.argv("worker"))
    assert second.code == 0
    assert second.reasons == []
    assert second.out == "The answer is 42.\n"


def test_a11_a_signal_before_the_spawn_ends_the_lens_with_nothing_spawned(rig, repo):
    def signal_during_the_diff(argv):
        if any(arg.startswith("--unified=") for arg in argv):
            os.kill(os.getpid(), signal.SIGINT)
        return None

    rig.run_hook = signal_during_the_diff
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=signal"]
    assert r.out == ""
    assert rig.fake.calls == []


A12_ROWS = {
    "signal-then-agy-dies-of-sigterm": (dict(stdout=stream(init()), sleep=True), "signal", 75, "signal"),
    "signal-after-the-notice": (dict(stdout=stream(init()), stderr=NOTICE, sleep=True), "signal", 75, "signal"),
    "watchdog-then-agy-dies-of-sigterm": (dict(stdout=stream(init()), sleep=True), "watchdog", 75, "timeout"),
    "notice-and-exit-1": (dict(stdout=stream(init()), stderr=NOTICE, exit=1), None, 75, "timeout"),
    "notice-and-agy-error-without-result": (
        dict(stdout=stream(init()), stderr=NOTICE + AGY_ERROR, exit=3),
        None,
        75,
        "timeout",
    ),
    "notice-and-denied-success": (
        dict(stdout=stream(init(), result(response="Partial.", denied=["WriteToFile"])), stderr=NOTICE),
        None,
        75,
        "timeout",
    ),
    "notice-and-empty-success": (dict(stdout=stream(init(), result(response="")), stderr=NOTICE), None, 75, "timeout"),
    "exit-1-beside-a-usable-success": (dict(stdout=stream(init(), result()), exit=1), None, 75, "error"),
    "agy-error-beside-a-usable-success": (dict(stdout=stream(init(), result()), stderr=AGY_ERROR), None, 75, "error"),
    "exit-1-without-result": (dict(stdout=stream(init()), stderr="agy: crashed\n", exit=1), None, 75, "error"),
    "status-error-empty-exit-1": (
        dict(stdout=stream(init(), result(status="ERROR", response="")), stderr="Error: boom\n", exit=1),
        None,
        75,
        "error",
    ),
    "exit-1-beside-denied-success": (
        dict(stdout=stream(init(), result(denied=["WriteToFile"])), exit=1),
        None,
        75,
        "error",
    ),
    "exit-0-without-result": (dict(stdout=stream(init(), THREE_TOOLS)), None, 75, "no-result"),
    "denied-and-empty-success": (
        dict(stdout=stream(init(), result(response="", denied=["RunCommand"]))),
        None,
        70,
        "denied",
    ),
}


@pytest.mark.parametrize("row", A12_ROWS, ids=list(A12_ROWS))
def test_a12_the_highest_ranked_cause_decides_the_exit_and_reason(rig, row):
    behaviour, trigger, code, reason = A12_ROWS[row]
    rig.fake.behave(**behaviour)
    rig.clock.gate = rig.fake.ready
    timeout = "42"
    if trigger == "signal":
        rig.clock.step = 5
        rig.clock.on_ready = lambda: os.kill(os.getpid(), signal.SIGTERM)
    elif trigger == "watchdog":
        timeout = "1"
        rig.clock.step = 31
    r = rig.launch(rig.argv("worker", timeout=timeout))
    assert r.code == code
    assert r.reasons == [f"[agy-run] reason={reason}"]
    assert r.out == ""
    if behaviour.get("stderr"):
        assert behaviour["stderr"] in r.err


# The same rows in a lens whose stream holds no tool step. Reading nothing ranks
# below every other cause, so it decides only a run that would otherwise succeed.
A12_LENS_ROWS = {
    "no-tool-step-beside-a-usable-success": (dict(stdout=stream(init(), result())), 70, "unread"),
    "no-tool-step-beside-an-empty-success": (dict(stdout=stream(init(), result(response=""))), 70, "empty"),
    "no-tool-step-beside-a-denied-success": (dict(stdout=stream(init(), result(denied=["WriteToFile"]))), 70, "denied"),
    "no-tool-step-and-no-result": (dict(stdout=stream(init())), 75, "no-result"),
    "no-tool-step-beside-exit-1": (dict(stdout=stream(init(), result()), exit=1), 75, "error"),
    "no-tool-step-under-the-notice": (dict(stdout=stream(init(), result()), stderr=NOTICE), 75, "timeout"),
}


@pytest.mark.parametrize("row", A12_LENS_ROWS, ids=list(A12_LENS_ROWS))
def test_a12_in_a_lens_reading_nothing_ranks_below_every_other_cause(rig, repo, row):
    behaviour, code, reason = A12_LENS_ROWS[row]
    rig.fake.behave(**behaviour)
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == code
    assert r.reasons == [f"[agy-run] reason={reason}"]
    assert r.out == ""


# --- slice B: lens mode ------------------------------------------------------------


def test_b1_lens_spawns_the_exact_argv_in_the_snapshot_with_only_home_changed(rig, repo):
    at_spawn: dict = {}
    rig.fake.on_spawn = lambda call: at_spawn.update(
        tmp=sorted(rig.tmp.iterdir()), diff=(call.cwd / ".review" / "change.diff").is_file()
    )
    argv = ["lens", "--repo", str(repo.path), "--base", repo.base, "--rev", repo.head]
    r = rig.launch([*argv, "--model", MODEL, "--timeout", "90", "-p", "Review it."])
    assert r.code == 0, r.err
    [call] = rig.fake.calls
    home = Path(call.env["HOME"])
    # The launcher creates exactly two directories under the temp root: the home
    # and the snapshot. The cwd must be the one that is not the home.
    [snapshot] = [d for d in at_spawn["tmp"] if d != home]
    assert at_spawn["diff"]
    assert call.cwd == snapshot
    assert call.cwd != home
    prompt = agy.lens_preamble(repo.path, repo.base, repo.head, snapshot, REPO_RENAMED, repo.base) + "Review it."
    assert call.argv == [
        "agy", "--agent", "agy-lens", "--mode", "plan", "--model", MODEL, "-p", prompt,
        "--output-format", "stream-json", "--print-timeout", "90s",
    ]  # fmt: skip
    assert call.env == {**os.environ, "HOME": str(home)}
    assert str(home) != os.environ["HOME"]


def test_b2_the_snapshot_holds_the_archive_with_the_change_s_instruction_files_renamed(tmp_path):
    repo = new_repo(tmp_path / "repo")
    base = commit(
        repo,
        {
            "AGENTS.md": "root rules v1\n",
            "GEMINI.md": "unchanged root gemini rules\n",
            "a/b/AGENTS.md": "deep rules v1\n",
            "c/d/AGENTS.md": "unchanged deep rules\n",
            "gone/AGENTS.md": "rules the change deletes\n",
            "old/AGENTS.md": "rules that move unchanged\n",
            ".agents/rules/changed.md": "rule v1\n",
            ".agents/rules/same.md": "unchanged rule\n",
            ".agents/hooks.json": '{"hooks": []}\n',
            "dir with space é/AGENTS.md": "quoted rules v1\n",
            "README.md": "readme\n",
            "src/app.py": "print(1)\n",
        },
    )
    rev = commit(
        repo,
        {
            "AGENTS.md": "root rules v2\n",
            "a/b/AGENTS.md": "deep rules v2\n",
            "gone/AGENTS.md": None,
            "old/AGENTS.md": None,
            "new/AGENTS.md": "rules that move unchanged\n",
            ".agents/rules/changed.md": "rule v2\n",
            "dir with space é/AGENTS.md": "quoted rules v2\n",
            "docs/agents.md": "lowercase rules the change adds\n",
            "src/app.py": "print(2)\n",
        },
    )
    (repo / "uncommitted.txt").write_text("working tree only\n")
    # The fixture exercises the two traps it names: git detects the move, and
    # quotes the non-ASCII path, unless told otherwise.
    name_status = git(repo, "diff", "--name-status", base, rev).decode()
    assert "R100\told/AGENTS.md\tnew/AGENTS.md" in name_status
    assert '"dir with space \\303\\251/AGENTS.md"' in name_status

    parent = tmp_path / "snapshots"
    parent.mkdir()
    snapshot = agy.make_snapshot(repo, base, rev, parent, subprocess.run)

    renamed = {
        "AGENTS.md",
        "a/b/AGENTS.md",
        "new/AGENTS.md",
        ".agents/rules/changed.md",
        ".agents/hooks.json",
        "dir with space é/AGENTS.md",
        "docs/agents.md",
    }
    archived = git(repo, "ls-tree", "-r", "-z", "--name-only", rev).decode().split("\0")[:-1]
    for path in archived:
        committed = git(repo, "show", f"{rev}:{path}")
        if path in renamed:
            assert (snapshot / f"{path}.under-review").read_bytes() == committed
            assert not (snapshot / path).exists()
        else:
            assert (snapshot / path).read_bytes() == committed
    files = {
        p.relative_to(snapshot).as_posix()
        for p in snapshot.rglob("*")
        if p.is_file() and p.relative_to(snapshot).parts[0] != ".git"
    }
    added = {".review/change.diff", ".agents/agents/agy-lens/agent.md"}
    assert files == {f"{p}.under-review" if p in renamed else p for p in archived} | added
    assert {f.removesuffix(".under-review") for f in files if f.endswith(".under-review")} == renamed
    assert "uncommitted.txt" not in files
    assert git(snapshot, "rev-parse", "--show-toplevel").decode().strip() == str(snapshot.resolve())
    unborn = subprocess.run(["git", "-C", str(snapshot), "rev-parse", "--verify", "-q", "HEAD"], check=False)
    assert unborn.returncode != 0
    assert (snapshot / ".agents" / "agents" / "agy-lens" / "agent.md").read_text() == AGENT_MD


# What the original name holds at spawn: nothing for AGENTS.md, and for .agents
# only the lens agent definition the launcher writes after the renames.
LAUNCHER_AGENT = ["agents", "agents/agy-lens", "agents/agy-lens/agent.md"]
B2_LINKS = {
    # A common layout: AGENTS.md is a link to CLAUDE.md, and the change edits CLAUDE.md.
    "file-link": ({"CLAUDE.md": "accepted\n"}, {"AGENTS.md": "CLAUDE.md"}, "CLAUDE.md", "AGENTS.md", None),
    "directory-link": (
        {"cfg/rules/x.md": "accepted\n"}, {".agents": "cfg"}, "cfg/rules/x.md", ".agents", LAUNCHER_AGENT,
    ),
}


@pytest.mark.parametrize("case", B2_LINKS)
def test_b2_a_link_that_reaches_the_change_is_renamed_with_its_target_kept(rig, tmp_path, case):
    files, links, edited, link, left = B2_LINKS[case]
    repo = new_repo(tmp_path / "linked")
    base = commit_through_index(repo, files, links)
    rev = commit_through_index(repo, {edited: "under review\n"})
    seen: dict = {}

    def look(call):
        original, renamed = call.cwd / link, call.cwd / f"{link}.under-review"
        # A regular file, a link or a directory left under the original name all
        # count as something left there, whatever its content.
        if original.is_dir() and not original.is_symlink():
            left_there = listing(original)
        else:
            left_there = "something" if os.path.lexists(original) else None
        seen.update(
            left=left_there,
            renamed=os.readlink(renamed) if renamed.is_symlink() else None,
            edited=(call.cwd / edited).read_text(),
            prompt=call.argv[8],
        )

    rig.fake.on_spawn = look
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert r.code == 0, r.err
    assert seen["left"] == left
    assert seen["renamed"] == links[link]
    assert seen["edited"] == "under review\n"
    assert f"  {link} -> {link}.under-review\n" in seen["prompt"]


def test_b2_link_targets_land_normalized_where_the_extraction_filter_keeps_them_verbatim(rig, tmp_path, monkeypatch):
    # Python's data filter writes a link target lexically normalized only from
    # 3.12.11 and 3.13.4 on. This stand-in for an earlier release checks each
    # member as the real filter does, then writes the target as the archive holds it.
    real = tarfile.data_filter

    def verbatim(member, path):
        return real(member, path).replace(linkname=member.linkname, deep=False)

    monkeypatch.setattr(tarfile, "data_filter", verbatim)
    monkeypatch.setitem(tarfile._NAMED_FILTERS, "data", verbatim)
    repo = new_repo(tmp_path / "verbatim")
    # Normalized, .agents leads to cfg, which launches nothing. Resolved through
    # the directory link foo instead, it leads to a/cfg and its hooks.json.
    files = {"a/cfg/hooks.json": "{}\n", "a/b/x.md": "x\n", "cfg/README.md": "config\n"}
    base = commit_through_index(repo, files, {"foo": "a/b", ".agents": "foo/../cfg"})
    rev = commit_through_index(repo, {"src/app.py": "print(1)\n"})
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(
        target=os.readlink(call.cwd / ".agents"), hooks=(call.cwd / ".agents" / "hooks.json").exists()
    )
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert r.code == 0, r.err
    assert seen == {"target": "cfg", "hooks": False}


def test_b2_a_changed_path_the_archive_omits_is_absent_and_renames_nothing(rig, tmp_path):
    repo = new_repo(tmp_path / "ignored")
    base = commit(repo, {"AGENTS.md": "accepted\n", "docs/AGENTS.md": "v1\n"})
    rev = commit(repo, {".gitattributes": "docs/AGENTS.md export-ignore\n", "docs/AGENTS.md": "v2\n"})
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(files=listing(call.cwd), prompt=call.argv[8])
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert r.code == 0, r.err
    assert [f for f in seen["files"] if f.startswith("docs/AGENTS.md")] == []
    assert "AGENTS.md" in seen["files"]
    assert "No file was renamed in the snapshot.\n" in seen["prompt"]


def test_b3_neutralized_names_renames_the_change_s_instruction_files_and_every_process_file():
    archived = [
        P(p)
        for p in (
            "AGENTS.md",
            "GEMINI.md",
            "docs/AGENTS.md",
            "CLAUDE.md",
            "README.md",
            "AGENTS.md.template",
            "rules/x.md",
            "_agents/rules/r.md",
            "deep/.agents/skills/s/SKILL.md",
            ".agents/hooks.json",
            ".agent/mcp_config.json",
            "x/_agent/mcp_config.json",
            ".agents/sub/hooks.json",
        )
    ]
    changed = [
        ("M", P("AGENTS.md")),
        ("A", P("GEMINI.md")),
        ("D", P("old/AGENTS.md")),
        ("M", P("CLAUDE.md")),
        ("M", P("README.md")),
        ("A", P("AGENTS.md.template")),
        ("M", P("rules/x.md")),
        ("T", P("_agents/rules/r.md")),
        ("M", P("deep/.agents/skills/s/SKILL.md")),
        ("M", P(".agents/hooks.json")),
        # An export-ignore attribute leaves a changed path out of the archive,
        # so there is nothing on disk to rename.
        ("M", P("ignored/AGENTS.md")),
    ]
    expected = [
        P(".agent/mcp_config.json"),
        P(".agents/hooks.json"),
        P("AGENTS.md"),
        P("GEMINI.md"),
        P("_agents/rules/r.md"),
        P("deep/.agents/skills/s/SKILL.md"),
        P("x/_agent/mcp_config.json"),
    ]
    assert agy.neutralized_names(archived, changed) == [(p, P(f"{p}.under-review")) for p in expected]


def test_b3_neutralized_names_matches_every_covered_name_in_any_case():
    # macOS's default filesystem is case-insensitive, so agy loads each of these
    # exactly as it loads the name in its usual case.
    names = ("agents.md", "Gemini.md", ".Agents/rules/x.md", ".AGENTS/Hooks.json", "Agents.md.template")
    archived = [P(p) for p in names]
    changed = [
        ("A", P("agents.md")),
        ("M", P("Gemini.md")),
        ("M", P(".Agents/rules/x.md")),
        ("M", P("Agents.md.template")),
    ]
    expected = [P(".AGENTS/Hooks.json"), P(".Agents/rules/x.md"), P("Gemini.md"), P("agents.md")]
    assert agy.neutralized_names(archived, changed) == [(p, P(f"{p}.under-review")) for p in expected]


NFC_CAFE = unicodedata.normalize("NFC", "café")
NFD_CAFE = unicodedata.normalize("NFD", "café")


def test_b3_neutralized_names_renames_every_instruction_link_that_reaches_the_change():
    files = [
        "CLAUDE.md", "notes/b.md", "n.md", "cfg/rules/x.md", "shared/r.md", "lib/s/SKILL.md",
        "tools/mcp_config.json", "lib2/s/SKILL.md", f"{NFC_CAFE}.md", "README.md",
    ]  # fmt: skip
    links = {
        P("AGENTS.md"): "CLAUDE.md",  # a file link to a changed file
        P("GEMINI.md"): "a/../hop",  # a chain, whose target the extraction normalizes to hop
        P("hop"): "notes/b.md",
        P("x/AGENTS.md"): "../m",  # a chain through a link the change retargets
        P("m"): "n.md",
        P(".agents"): "cfg",  # a customization root linked to a directory holding a change
        P(".agent/rules"): "../shared",  # a directory link beneath a customization root
        P("_agents"): "cfg2",  # a change reached through a second link beneath the first
        P("cfg2/skills"): "../lib",
        P("_agent"): "tools",  # a customization root linked to a directory holding a process file
        P("y/GEMINI.md"): f"../{NFD_CAFE}.md",  # a target in the other Unicode form of a changed file
        P("docs/guide.md"): "../CLAUDE.md",  # not an instruction path, so it stays
        P("z/.agents/skills"): "../../lib2",  # nothing beneath it is changed, so it stays
        P("z/AGENTS.md"): "../README.md",  # its target is unchanged, so it stays
    }
    changed = [
        ("M", P("CLAUDE.md")),
        ("M", P("notes/b.md")),
        ("M", P("m")),
        ("M", P("cfg/rules/x.md")),
        ("A", P("shared/r.md")),
        ("M", P("lib/s/SKILL.md")),
        ("M", P(f"{NFC_CAFE}.md")),
    ]
    archived = [P(p) for p in files] + list(links)
    expected = [
        P(".agent/rules"), P(".agents"), P("AGENTS.md"), P("GEMINI.md"), P("_agent"), P("_agents"),
        P("x/AGENTS.md"), P("y/GEMINI.md"),
    ]  # fmt: skip
    assert agy.neutralized_names(archived, changed, links) == [(p, P(f"{p}.under-review")) for p in expected]


@pytest.mark.parametrize("committed", ["AGENTS.md.under-review", "agents.md.UNDER-REVIEW"])
def test_b4_an_existing_rename_target_is_refused_before_renaming_or_spawning(rig, tmp_path, committed):
    repo = new_repo(tmp_path / "collide")
    base = commit(repo, {"AGENTS.md": "v1\n"})
    rev = commit(repo, {"AGENTS.md": "v2\n", committed: "committed on purpose\n"})
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert_refused(r, rig, committed)
    assert re.search(r"(?<![\w.])AGENTS\.md(?!\.under-review)", r.err)


@pytest.mark.parametrize(
    "accepted, added",
    [
        ("AGENTS.md", "agents.md"),
        (".agents/hooks.json", ".AGENTS/hooks.json"),
        (f"{NFC_CAFE}/AGENTS.md", f"{NFD_CAFE}/AGENTS.md"),
    ],
    ids=["instruction-file", "process-file", "unicode-form"],
)
def test_b4_two_paths_that_differ_only_by_case_or_unicode_form_are_refused_before_anything_spawns(
    rig, tmp_path, accepted, added
):
    repo = new_repo(tmp_path / "clash")
    base = commit_through_index(repo, {accepted: "accepted\n"})
    rev = commit_through_index(repo, {added: "under review\n"})
    assert git(repo, "ls-tree", "-r", "-z", "--name-only", rev).decode().split("\0")[:-1] == sorted([accepted, added])
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert_refused(r, rig, accepted, added)


B4_LINKS = {
    "outside": {"AGENTS.md": "../outside.md"},
    "absolute": {"docs/passwd": "/etc/passwd"},
    "loop": {"loop-one": "loop-two", "loop-two": "loop-one"},
}


@pytest.mark.parametrize("case", B4_LINKS)
def test_b4_a_link_that_leads_outside_the_snapshot_or_loops_is_refused_before_anything_spawns(rig, tmp_path, case):
    repo = new_repo(tmp_path / "links")
    base = commit_through_index(repo, {"README.md": "readme\n"})
    rev = commit_through_index(repo, {}, B4_LINKS[case])
    r = rig.launch(rig.argv("lens", Repo(repo, base, rev), rev=rev))
    assert_refused(r, rig, *B4_LINKS[case])


def test_b4_a_member_the_extraction_filter_refuses_is_refused_before_anything_spawns(rig, repo, monkeypatch):
    def refuse(self, path, *args, **kwargs):
        raise tarfile.LinkOutsideDestinationError(self.getmember("src/app.py"), "/elsewhere")

    monkeypatch.setattr(tarfile.TarFile, "extractall", refuse)
    r = rig.launch(rig.argv("lens", repo, rev=repo.head))
    assert_refused(r, rig, "src/app.py", "/elsewhere")


def test_b5_the_temporary_home_holds_only_an_empty_gemini_and_the_keychains_link(rig, repo):
    seen: dict = {}

    def inspect(call: Call) -> None:
        home = Path(call.env["HOME"])
        link = home / "Library" / "Keychains"
        seen.update(
            home=home,
            entries=sorted(p.name for p in home.iterdir()),
            gemini=(home / ".gemini").is_dir() and not any((home / ".gemini").iterdir()),
            library=sorted(p.name for p in (home / "Library").iterdir()),
            target=os.readlink(link) if link.is_symlink() else None,
        )

    rig.fake.on_spawn = inspect
    assert rig.launch(rig.argv("lens", repo)).code == 0
    assert seen["entries"] == [".gemini", "Library"]
    assert seen["gemini"] is True
    assert seen["library"] == ["Keychains"]
    assert seen["target"] == str(rig.real_home / "Library" / "Keychains")
    assert not seen["home"].resolve().is_relative_to(repo.path.resolve())
    assert seen["home"].resolve() != rig.real_home.resolve()


def sound_home(at: Path, real_home: Path) -> Path:
    (at / ".gemini").mkdir(parents=True)
    (at / "Library").mkdir()
    (at / "Library" / "Keychains").symlink_to(real_home / "Library" / "Keychains")
    return at


B6_CASES = {
    "gemini-has-an-entry": ("home-unproven", "is not an empty directory"),
    "keychains-missing": ("home-unproven", "is not a symlink to"),
    "keychains-elsewhere": ("home-unproven", "is not a symlink to"),
    "home-is-the-real-home": ("home-unproven", "is the real home"),
    "home-inside-the-repo": ("home-unproven", "inside the repository"),
    "env-home-differs": ("home-unproven", "HOME is not the temporary home"),
    "real-keychains-absent": ("no-route", "does not exist"),
}


@pytest.mark.parametrize("case", B6_CASES, ids=list(B6_CASES))
def test_b6_an_unsound_home_is_refused_before_the_spawn(rig, repo, monkeypatch, tmp_path, case):
    reason, condition = B6_CASES[case]
    build = agy.make_lens_home

    def unsound(parent: Path, real_home: Path) -> Path:
        home = build(parent, real_home)
        link = home / "Library" / "Keychains"
        if case == "gemini-has-an-entry":
            (home / ".gemini" / "GEMINI.md").write_text("house rules\n")
        elif case == "keychains-missing":
            link.unlink()
        elif case == "keychains-elsewhere":
            link.unlink()
            (tmp_path / "other-keychains").mkdir()
            link.symlink_to(tmp_path / "other-keychains")
        elif case == "home-is-the-real-home":
            return real_home
        elif case == "home-inside-the-repo":
            return sound_home(repo.path / "inner-home", real_home)
        return home

    monkeypatch.setattr(agy, "make_lens_home", unsound)
    if case == "env-home-differs":
        build_env = agy.lens_env
        monkeypatch.setattr(agy, "lens_env", lambda env, home: {**build_env(env, home), "HOME": str(tmp_path)})
    if case == "real-keychains-absent":
        (rig.real_home / "Library" / "Keychains").rmdir()
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == 75
    assert r.reasons == [f"[agy-run] reason={reason}"]
    assert condition in r.err
    assert r.out == ""
    assert rig.fake.calls == []
    # Cleanup removes only what the launcher created, never the real home.
    assert rig.real_home.is_dir()


def test_b6_a_sound_home_proceeds_to_the_spawn(rig, repo):
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == 0, r.err
    assert len(rig.fake.calls) == 1


def test_b7_the_preamble_precedes_the_prompt_and_names_what_the_lens_needs(rig, repo):
    prompt = "  Review this change.\n\tKeep odd spacing.  "
    assert rig.launch(rig.argv("lens", repo, rev=repo.head, prompt=prompt)).code == 0
    [call] = rig.fake.calls
    snapshot = call.cwd
    preamble = agy.lens_preamble(repo.path, repo.base, repo.head, snapshot, REPO_RENAMED, repo.base)
    assert call.argv[8] == preamble + prompt
    for needle in (
        str(snapshot),
        repo.base,
        repo.head,
        ".review/change.diff",
        "AGENTS.md -> AGENTS.md.under-review",
        ".agents/hooks.json -> .agents/hooks.json.under-review",
        "only in the diff",
    ):
        assert needle in preamble
    assert "stay inside the snapshot" in preamble.lower()


EXPLODING_DRIVER = """\
import importlib.util, sys, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location("agy_run", sys.argv[1])
agy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agy)
def exploding_spawn(argv, **kwargs):
    present = len(list(Path(tempfile.gettempdir()).iterdir()))
    raise RuntimeError(f"spawn failed on purpose with {present} directories present")
sys.exit(agy.main(sys.argv[4:], spawn=exploding_spawn, real_home=Path(sys.argv[2]), settings=Path(sys.argv[3])))
"""

B8_CASES = ["exit-0", "exit-70", "exit-75", "exit-78", "sigterm-while-running", "sigint-while-running", "sigint-before-spawn"]


@pytest.mark.parametrize("case", B8_CASES)
def test_b8_the_snapshot_and_home_are_gone_after_every_exit(rig, repo, tmp_path, case):
    present: list[int] = []
    rig.fake.on_spawn = lambda call: present.append(len(list(rig.tmp.iterdir())))
    target = repo
    expected = {"exit-0": 0, "exit-70": 70, "exit-75": 75, "exit-78": 78}.get(case, 75)
    if case == "exit-0":
        pass
    elif case == "exit-70":
        rig.fake.behave(stdout=stream(init(), result(response="")))
    elif case == "exit-75":
        rig.fake.behave(stdout=stream(init(), result()), exit=1)
    elif case == "exit-78":
        collide = new_repo(tmp_path / "collide")
        base = commit(collide, {"AGENTS.md": "v1\n"})
        rev = commit(collide, {"AGENTS.md": "v2\n", "AGENTS.md.under-review": "committed\n"})
        target = Repo(collide, base, rev)

        def count_during_git(argv):
            present.append(len(list(rig.tmp.iterdir())))

        rig.run_hook = count_during_git
    elif case.endswith("while-running"):
        signum = signal.SIGTERM if case.startswith("sigterm") else signal.SIGINT
        rig.fake.behave(stdout=stream(init()), sleep=True)
        rig.clock.gate = rig.fake.ready
        rig.clock.on_ready = lambda: os.kill(os.getpid(), signum)
    elif case == "sigint-before-spawn":

        def signal_during_the_diff(argv):
            present.append(len(list(rig.tmp.iterdir())))
            if any(arg.startswith("--unified=") for arg in argv):
                os.kill(os.getpid(), signal.SIGINT)

        rig.run_hook = signal_during_the_diff
    r = rig.launch(rig.argv("lens", target))
    assert r.code == expected, r.err
    # The directories existed while the launcher worked, so their absence now is cleanup.
    assert present and max(present) >= 1
    assert list(rig.tmp.iterdir()) == []
    assert not any(line.startswith("[agy-run] leak=") for line in r.ledger)


def test_b8_an_unhandled_exception_still_removes_both_directories(rig, repo):
    argv = rig.argv("lens", repo)
    proc = subprocess.run(
        [sys.executable, "-c", EXPLODING_DRIVER, str(SCRIPT_PATH), str(rig.real_home), str(rig.settings), *argv],
        env={**os.environ, "TMPDIR": str(rig.tmp)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "Traceback" in proc.stderr
    assert "RuntimeError: spawn failed on purpose with 2 directories present" in proc.stderr
    assert list(rig.tmp.iterdir()) == []


def test_b8_keep_snapshot_keeps_the_snapshot_and_still_removes_the_home(rig, repo):
    r = rig.launch(rig.argv("lens", repo, extra=["--keep-snapshot"]))
    assert r.code == 0, r.err
    [call] = rig.fake.calls
    assert list(rig.tmp.iterdir()) == [call.cwd]
    assert not Path(call.env["HOME"]).exists()
    assert f"[agy-run] snapshot={call.cwd}" in r.ledger


def test_b9_a_worker_creates_nothing_and_keeps_the_parent_home(rig):
    before = (listing(rig.tmp), listing(rig.trusted))
    assert rig.launch(rig.argv("worker")).code == 0
    assert (listing(rig.tmp), listing(rig.trusted)) == before
    [call] = rig.fake.calls
    assert call.env["HOME"] == os.environ["HOME"]


def diff_argv(repo: Path, base: str, rev: str) -> list[str]:
    return ["git", "-C", str(repo), "diff", "--no-color", "--no-ext-diff", "--find-renames", "--unified=10", base, rev]


def test_b10_the_diff_file_is_git_s_diff_output_byte_for_byte(rig, repo):
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(diff=(call.cwd / ".review" / "change.diff").read_bytes())
    assert rig.launch(rig.argv("lens", repo, rev=repo.head)).code == 0
    [done] = [done for argv, done in rig.runs if argv == diff_argv(repo.path, repo.base, repo.head)]
    assert done.stdout
    assert seen["diff"] == done.stdout


def test_b10_the_change_starts_at_the_merge_base_so_commits_base_gained_later_stay_out(rig, tmp_path):
    repo = new_repo(tmp_path / "moved")
    fork = commit(repo, {"AGENTS.md": "accepted rules\n", "src/app.py": "print(1)\n"})
    git(repo, "checkout", "-q", "-b", "feature")
    feature = commit(repo, {"src/app.py": "print(2)\n"})
    git(repo, "checkout", "-q", "-")
    # The base branch moves on after the feature branched: it edits an
    # instruction file the feature never touched.
    moved = commit(repo, {"AGENTS.md": "rules the base branch added later\n", "docs/later.md": "later\n"})
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(
        files=listing(call.cwd), diff=(call.cwd / ".review" / "change.diff").read_bytes(), prompt=call.argv[8]
    )
    r = rig.launch(rig.argv("lens", Repo(repo, moved, feature), rev=feature))
    assert r.code == 0, r.err
    assert seen["diff"] == git(repo, *diff_argv(repo, fork, feature)[3:])
    assert "AGENTS.md" in seen["files"]
    assert "AGENTS.md.under-review" not in seen["files"]
    assert f"goes from {fork}, the merge base of {moved} and {feature}, to {feature}." in seen["prompt"]


def test_b10_base_equal_to_rev_gives_an_empty_diff_and_only_the_process_file_renames(rig, repo):
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(
        diff=(call.cwd / ".review" / "change.diff").read_bytes(),
        renamed=sorted(p.relative_to(call.cwd).as_posix() for p in call.cwd.rglob(f"*{agy.RENAME_SUFFIX}")),
    )
    r = rig.launch(rig.argv("lens", repo, base=repo.head, rev=repo.head))
    assert r.code == 0, r.err
    assert seen["diff"] == b""
    assert seen["renamed"] == [".agents/hooks.json.under-review"]
    [call] = rig.fake.calls
    assert [line.strip() for line in call.argv[8].splitlines() if " -> " in line] == [
        ".agents/hooks.json -> .agents/hooks.json.under-review"
    ]


@pytest.mark.parametrize("timeout, print_timeout, fires_at", [(None, "600s", 630), (60, "60s", 90)])
def test_b11_the_lens_timeout_defaults_to_600_and_the_watchdog_arms_30_later(
    rig, repo, kills, timeout, print_timeout, fires_at
):
    rig.fake.behave(stdout=stream(init(agent="agy-lens")), sleep=True)
    rig.clock.step = 90
    extra = ["--timeout", str(timeout)] if timeout else []
    r = rig.launch(rig.argv("lens", repo, extra=extra))
    [call] = rig.fake.calls
    assert call.argv[-2:] == ["--print-timeout", print_timeout]
    assert kills[0] == (fires_at, signal.SIGTERM)
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=timeout"]


INJECTED = b"fatal: injected failure for the test\n"
B12_CASES = [
    "not-a-repository", "unknown-base", "unknown-rev", "review-path", "review-path-in-another-case",
    "no-merge-base", "init-fails", "name-status-fails", "diff-fails",
]  # fmt: skip


@pytest.mark.parametrize("case", B12_CASES)
def test_b12_a_git_failure_is_refused_with_git_s_own_stderr(rig, repo, tmp_path, case):
    target, base, rev, names = repo, repo.base, repo.head, []
    if case == "not-a-repository":
        plain = tmp_path / "plain"
        plain.mkdir()
        target, names = Repo(plain, base, rev), [str(plain)]
    elif case == "unknown-base":
        base, names = "no-such-base", ["no-such-base"]
    elif case == "unknown-rev":
        rev, names = "no-such-rev", ["no-such-rev"]
    elif case == "review-path":
        rev = commit(repo.path, {".review/notes.md": "a reviewer's notes\n"})
        names = [".review"]
    elif case == "review-path-in-another-case":
        rev = commit(repo.path, {".REVIEW/notes.md": "a reviewer's notes\n"})
        names = [".REVIEW"]
    elif case == "no-merge-base":
        # A commit with no parent shares no history with the base.
        rev = git(repo.path, "commit-tree", f"{repo.base}^{{tree}}", "-m", "unrelated").decode().strip()
        names = [repo.base, rev, "share no history"]
    else:
        marker = {"init-fails": "init", "name-status-fails": "--name-status", "diff-fails": "--unified=10"}[case]
        names = [marker, INJECTED.decode().strip()]

        def inject(argv):
            if marker in argv:
                return subprocess.CompletedProcess(argv, 1, b"", INJECTED)
            return None

        rig.run_hook = inject
    r = rig.launch(rig.argv("lens", target, base=base, rev=rev))
    assert_refused(r, rig, *names)
    failed = [done for _, done in rig.runs if done.returncode != 0]
    if case in ("not-a-repository", "unknown-base", "unknown-rev"):
        assert failed
        assert failed[-1].stderr.decode().strip() in r.err


def test_b12_an_absent_git_binary_is_no_route(rig, repo):
    def absent(argv):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    rig.run_hook = absent
    r = rig.launch(rig.argv("lens", repo))
    assert r.code == 75
    assert r.reasons == ["[agy-run] reason=no-route"]
    assert r.out == ""
    assert rig.fake.calls == []


@pytest.mark.parametrize("code", [0, 75])
def test_b13_a_cleanup_failure_keeps_the_run_s_exit_and_reports_each_leak(rig, repo, code):
    rig.fake.behave(stdout=stream(init(), READ, result()), exit=0 if code == 0 else 1)
    held: list[Path] = []

    def lock_the_temp_root(call: Call) -> None:
        held.extend(sorted(rig.tmp.iterdir()))
        rig.tmp.chmod(0o500)

    rig.fake.on_spawn = lock_the_temp_root
    try:
        r = rig.launch(rig.argv("lens", repo))
    finally:
        rig.tmp.chmod(0o700)
    assert r.code == code
    assert len(held) == 2
    leaks = [line for line in r.ledger if line.startswith("[agy-run] leak=")]
    assert sorted(leaks) == sorted(f"[agy-run] leak={d}" for d in held)
    assert all(d.exists() for d in held)


def test_b14_without_rev_the_lens_reviews_head(rig, tmp_path):
    repo = new_repo(tmp_path / "three")
    base = commit(repo, {"AGENTS.md": "rules v1\n", "src/app.py": "v1\n"})
    commit(repo, {"src/app.py": "v2\n"})
    commit(repo, {"AGENTS.md": "rules v3\n", "src/app.py": "v3\n"})
    seen: dict = {}
    rig.fake.on_spawn = lambda call: seen.update(
        app=(call.cwd / "src" / "app.py").read_text(),
        original=(call.cwd / "AGENTS.md").exists(),
        renamed=(call.cwd / "AGENTS.md.under-review").read_text(),
        diff=(call.cwd / ".review" / "change.diff").read_bytes(),
    )
    r = rig.launch(["lens", "--repo", str(repo), "--base", base, "--model", MODEL, "-p", "Review."])
    assert r.code == 0, r.err
    assert seen["app"] == "v3\n"
    assert seen["original"] is False
    assert seen["renamed"] == "rules v3\n"
    [done] = [done for argv, done in rig.runs if argv == diff_argv(repo, base, "HEAD")]
    assert seen["diff"] == done.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
