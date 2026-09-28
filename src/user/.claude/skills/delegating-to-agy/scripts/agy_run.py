#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Launch an Antigravity CLI (agy) run as a full worker or as a fresh-context review lens.

Usage:
  agy_run.py worker --model ID --timeout SECONDS -p PROMPT
  agy_run.py lens   --repo PATH --base BASE [--rev REV] --model ID
                    [--timeout SECONDS] [--keep-snapshot] -p PROMPT

A worker runs agy in the current directory with the real home, so the user's and
the repository's instruction files load as they do for any first-class session.
The directory must lie at or beneath a path in trustedWorkspaces of agy's settings
file, because agy denies every headless edit anywhere else.

A lens runs agy read-only over a snapshot of one revision, under a temporary home
that holds only an empty .gemini directory and a link to the real Keychains. In
the snapshot, the instruction files the change adds or modifies are renamed with
the suffix .under-review, and so is every hook or MCP configuration under a
customization root and every link at an instruction file's path that reaches
either, so nothing under review instructs the reviewer and nothing launches a
process. The change runs from the merge base of BASE and REV to REV, as git diff
BASE...REV shows it, and its diff sits beside them in .review/change.diff.

-p must be the last launcher flag. The single argument after it is the prompt,
taken verbatim whatever its text.

stdout carries agy's final response and nothing else. stderr carries the
launcher's [agy-run] ledger lines and agy's own stderr as it arrives.

Exit codes:
  0   agy succeeded with a non-empty response and no denied action.
  70  agy finished but the output is unusable (reason=empty, reason=denied, or
      reason=unread for a lens that called no tool). Re-brief, or move to another route.
  75  the route did not serve the run (reason=error, no-route, timeout, signal,
      home-unproven or no-result). Fail over to the next route or model.
  78  the launcher refused the invocation. Fix it; do not fail over.
Any other exit is a launcher defect reported with a traceback. Treat it as 78.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import posixpath
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import IO, NamedTuple, NoReturn

EXIT_OK = 0
EXIT_UNUSABLE = 70
EXIT_ROUTE = 75
EXIT_CONFIG = 78

LENS_AGENT = "agy-lens"
LENS_TOOLS = ("view_file", "grep_search", "find_by_name", "list_dir")
LENS_TIMEOUT_DEFAULT_S = 600
RENAME_SUFFIX = ".under-review"
# The names the snapshot rules cover are held in folded form, and a path is folded
# before it is compared with them. macOS's default filesystem ignores letter case and
# Unicode form, so agy loads agents.md or .Agents/rules/x.md exactly as it loads
# AGENTS.md or .agents/rules/x.md, and a rule that matched one spelling would let another through.
CUSTOMIZATION_ROOTS = (".agents", ".agent", "_agents", "_agent")
PROCESS_FILES = ("hooks.json", "mcp_config.json")
DIFF_PATH = PurePosixPath(".review/change.diff")
DIFF_CONTEXT_LINES = 10
WATCHDOG_GRACE_S = 30
KILL_GRACE_S = 10
AGY_SETTINGS = Path("~/.gemini/antigravity-cli/settings.json")

_PROG = "agy_run.py"
_INSTRUCTION_FILES = ("agents.md", "gemini.md")
_BYPASS_FLAGS = ("--skip-permissions", "--dangerously-skip-permissions", "--sandbox")

# A walk that passes more links than this is a loop. POSIX systems give up at a similar depth.
_MAX_LINK_HOPS = 40

# How long the run loop waits for a line from agy before it reads the clock again.
# It bounds how late the watchdog and a signal are noticed, not how fast output flows.
_POLL_S = 0.05

# agy reports its own print timeout and its API failures on stderr, one per line.
_PRINT_TIMEOUT_NOTICE = re.compile(r"^\[agy\] print timeout", re.MULTILINE)
_AGY_ERROR_LINE = re.compile(r"^AGY_ERROR:", re.MULTILINE)

# The signals the launcher received during the current run. The handler only
# appends here, because anything heavier would run in the middle of whatever code
# it interrupted; the setup steps and the run loop read the list and act on it.
_signals: list[int] = []

# The directories the current run created. Each is registered the moment it
# exists, so a refusal or an exception raised halfway through building a snapshot
# still leaves nothing behind once the run's cleanup has walked this list.
_owned: list[Path] = []


class Outcome(NamedTuple):
    """How a run ended: the launcher's exit code, its reason word, agy's response and the ledger lines printed."""

    exit_code: int
    # error | no-route | timeout | signal | home-unproven | no-result | empty | denied | unread | None
    reason: str | None
    response: str
    ledger: list[str]


class _Refused(Exception):
    """The invocation cannot run as given. The message names the refused element and the remedy."""


class _NoRoute(Exception):
    """A binary the route needs is not on this machine."""


class _Parser(argparse.ArgumentParser):
    """An argument parser that refuses instead of exiting 2, so every bad invocation exits 78."""

    def error(self, message: str) -> NoReturn:
        raise _Refused(f"{message}. Run {_PROG} --help for the flags this launcher takes.")


def _seconds(text: str) -> int:
    if not text.isdigit() or int(text) == 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive whole number of seconds")
    return int(text)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=_PROG,
        usage=f"{_PROG} {{worker,lens}} FLAGS -p PROMPT",
        description="Launch agy as a worker in this checkout or as a read-only lens over a snapshot.",
        epilog="-p must come last; the single argument after it is the prompt, taken verbatim.",
        allow_abbrev=False,
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    worker = modes.add_parser(
        "worker",
        usage=f"{_PROG} worker --model ID --timeout SECONDS -p PROMPT",
        help="run agy in the current directory with the real home",
        allow_abbrev=False,
    )
    worker.add_argument("--model", required=True, help="the full agy model id, which also carries the effort")
    worker.add_argument("--timeout", required=True, type=_seconds, help="seconds before the run is stopped")
    lens = modes.add_parser(
        "lens",
        usage=(
            f"{_PROG} lens --repo PATH --base BASE [--rev REV] --model ID [--timeout SECONDS] [--keep-snapshot] -p PROMPT"
        ),
        help="run agy read-only over a snapshot of one revision",
        allow_abbrev=False,
    )
    lens.add_argument("--repo", required=True, type=Path, help="the repository under review")
    lens.add_argument("--base", required=True, help="the revision the change is compared with, from its merge base")
    lens.add_argument("--rev", default="HEAD", help="the revision to snapshot (default HEAD)")
    lens.add_argument("--model", required=True, help="the full agy model id, which also carries the effort")
    lens.add_argument(
        "--timeout",
        type=_seconds,
        default=LENS_TIMEOUT_DEFAULT_S,
        help=f"seconds before the run is stopped (default {LENS_TIMEOUT_DEFAULT_S})",
    )
    lens.add_argument("--keep-snapshot", action="store_true", help="keep the snapshot directory after the run")
    return parser


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the launcher's command line, raising _Refused for anything it will not run.

    Every element before the first -p is a launcher flag. The single element after
    it is the prompt, so a prompt that looks like a flag is still only a prompt.
    """
    flags, rest = argv, []
    if "-p" in argv:
        at = argv.index("-p")
        flags, rest = argv[:at], argv[at + 1 :]
    # These two refusals come before the parser so their message carries the
    # remedy, where the parser would only call the flag unrecognized.
    for element in flags:
        name = element.split("=", 1)[0]
        if name in _BYPASS_FLAGS:
            raise _Refused(
                f"{name} is refused: this launcher defines no permission bypass and no sandbox flag. "
                f"To let a worker run more commands unattended, widen permissions.allow in {AGY_SETTINGS}."
            )
        if name == "--effort":
            raise _Refused(
                "--effort is refused: agy carries the effort in the model id, "
                "so pass the id that names it, for example gemini-3.8-flash-high."
            )
    args = _parser().parse_args(flags)
    if not rest:
        raise _Refused("-p PROMPT is missing: end the command line with -p and the prompt as one argument.")
    if len(rest) > 1:
        raise _Refused(
            f"{rest[1]!r} follows the prompt: -p takes exactly one argument and comes last, "
            "so pass the whole prompt as one quoted argument."
        )
    args.prompt = rest[0]
    refusal = refuse_model(args.model)
    if refusal is not None:
        raise _Refused(refusal)
    return args


def refuse_model(model: str) -> str | None:
    """Return why a model id is refused, or None when agy may be asked to run it."""
    if model.startswith("claude-"):
        return (
            f"--model {model} is refused: a Claude model runs natively in the harness that launched this run. "
            "Run it there, or pass an agy model id such as gemini-3.8-flash-high."
        )
    return None


def trusted_workspace(cwd: Path, settings: Path) -> bool:
    """Tell whether cwd is a path in trustedWorkspaces of agy's settings file, or lies beneath one.

    A missing or unparseable file, or one without the list, trusts nothing.
    Ancestry is compared by path component, so a sibling whose name merely
    extends a listed path is not beneath it.
    """
    try:
        listed = json.loads(settings.read_text(encoding="utf-8")).get("trustedWorkspaces")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(listed, list):
        return False
    here = cwd.resolve()
    for entry in listed:
        # A relative entry names no fixed directory, so it trusts nothing rather
        # than whatever directory the launcher happens to run from.
        if isinstance(entry, str) and Path(entry).expanduser().is_absolute():
            if here.is_relative_to(Path(entry).expanduser().resolve()):
                return True
    return False


def build_worker_argv(model: str, timeout_s: int, prompt: str) -> list[str]:
    """Return agy's command line for a worker: accept-edits mode, stream-json output, agy's own timeout."""
    return [
        "agy", "-p", prompt, "--model", model, "--output-format", "stream-json",
        "--print-timeout", f"{timeout_s}s", "--mode", "accept-edits",
    ]  # fmt: skip


def build_lens_argv(model: str, timeout_s: int, prompt: str) -> list[str]:
    """Return agy's command line for a lens: the read-only agent, plan mode, stream-json output.

    It never carries --disable-slash-commands, because agy turns plan mode off
    when that flag is present while its init event still reports plan mode.
    """
    return [
        "agy", "--agent", LENS_AGENT, "--mode", "plan", "--model", model, "-p", prompt,
        "--output-format", "stream-json", "--print-timeout", f"{timeout_s}s",
    ]  # fmt: skip


def _own(path: str) -> Path:
    owned = Path(path)
    _owned.append(owned)
    return owned


def make_lens_home(parent: Path, real_home: Path) -> Path:
    """Create a temporary home holding only an empty .gemini directory and a link to the real Keychains.

    Nothing user-level exists there, so no user rule, skill or setting loads.
    The Keychains link is what lets agy sign in without a browser.
    """
    home = _own(tempfile.mkdtemp(prefix="agy-lens-home-", dir=parent))
    (home / ".gemini").mkdir()
    (home / "Library").mkdir()
    (home / "Library" / "Keychains").symlink_to(real_home / "Library" / "Keychains")
    return home


def lens_env(parent_env: Mapping[str, str], home: Path) -> dict[str, str]:
    """Return the parent's environment with HOME pointed at the temporary home and nothing else changed."""
    return {**parent_env, "HOME": str(home)}


def prove_home(home: Path, real_home: Path, repo: Path, env: Mapping[str, str]) -> Outcome | None:
    """Check the temporary home before agy sees it, and return the refusing Outcome, or None when it is sound.

    Every failed condition is named on stderr. A missing real Keychains is its own
    case: no home built on this machine could sign in headlessly.
    """
    keychains = real_home / "Library" / "Keychains"
    if not keychains.exists():
        _say(f"{keychains} does not exist, so agy cannot sign in from a temporary home on this machine.")
        return Outcome(EXIT_ROUTE, "no-route", "", [])
    gemini = home / ".gemini"
    link = home / "Library" / "Keychains"
    linked = link.is_symlink() and link.resolve() == keychains.resolve() and keychains.is_dir()
    checks = (
        (gemini.is_dir() and not any(gemini.iterdir()), f"{gemini} is not an empty directory"),
        (linked, f"{link} is not a symlink to the directory {keychains}"),
        (home.resolve() != real_home.resolve(), f"{home} is the real home"),
        (not home.resolve().is_relative_to(repo.resolve()), f"{home} lies inside the repository under review"),
        (env.get("HOME") == str(home), f"the child environment's HOME is not the temporary home {home}"),
    )
    failed = [condition for sound, condition in checks if not sound]
    for condition in failed:
        _say(f"the temporary home failed its check: {condition}.")
    return Outcome(EXIT_ROUTE, "home-unproven", "", []) if failed else None


def lens_agent_definition() -> str:
    """Return the agent.md that limits a lens to reading, searching and listing files in its snapshot."""
    return f"""\
---
name: {LENS_AGENT}
description: Read-only review lens. Reads, searches and lists files in this snapshot and nothing else.
tools: [{", ".join(LENS_TOOLS)}]
subagent: false
---

# Lens

You review a snapshot of a repository at one revision. You can read, search and list files in it and nothing else. \
The change under review is in {DIFF_PATH}, a unified diff against the base revision, with original paths. \
Instruction files the change adds or modifies were renamed with the suffix {RENAME_SUFFIX}; \
read them as ordinary files and cite them by their original names. \
Answer the request directly. Do not write a plan document.
"""


def lens_preamble(
    repo: Path,
    base: str,
    rev: str,
    snapshot: Path,
    renamed: list[tuple[PurePosixPath, PurePosixPath]],
    merge_base: str,
) -> str:
    """Return the text a lens prompt starts with: where the snapshot is, what changed, and what was renamed."""
    if renamed:
        renames = (
            "These files were renamed in the snapshot, so that nothing under review instructs you "
            "and nothing launches a process:\n" + "".join(f"  {original} -> {target}\n" for original, target in renamed)
        )
    else:
        renames = "No file was renamed in the snapshot.\n"
    return (
        f"You are reviewing a snapshot of the repository {repo.resolve().name} at revision {rev}. "
        f"The snapshot is the directory {snapshot}, and it has no history.\n"
        f"The change under review goes from {merge_base}, the merge base of {base} and {rev}, to {rev}. "
        f"Its unified diff, with original paths, is {DIFF_PATH} in the snapshot.\n"
        "A file the change deletes is absent from the snapshot and appears only in the diff.\n"
        f"{renames}"
        "Read a renamed file as an ordinary file and cite it by its original name.\n"
        f"Stay inside the snapshot: read, search and list files under {snapshot} and nowhere else.\n\n"
    )


def _git(
    run: Callable[..., subprocess.CompletedProcess], *args: str, meaning: Mapping[int, str] | None = None
) -> bytes:
    """Run one git command through the run seam and return its stdout.

    A failure refuses the invocation and carries git's own stderr, since the
    repository, the revision or the base named on the command line is the
    likely cause. meaning explains an exit code whose cause git's stderr does
    not state.
    """
    argv = ["git", *args]
    try:
        done = run(argv, capture_output=True)
    except FileNotFoundError:
        raise _NoRoute("git is not on PATH, and a lens needs it to snapshot the repository.") from None
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", errors="replace").strip()
        why = (meaning or {}).get(done.returncode, "")
        raise _Refused(f"`{shlex.join(argv)}` exited {done.returncode}: {why}{detail}")
    return done.stdout


def _merge_base(repo: Path, base: str, rev: str, run: Callable[..., subprocess.CompletedProcess]) -> str:
    """Return the commit where rev's history meets base's, which is where the change under review starts.

    Diffing from it, as git diff BASE...REV does, keeps out every commit base
    gained after rev branched from it. Diffing from base itself would show those
    commits reversed, as if the change had undone them.
    """
    no_history = {1: f"{base} and {rev} share no history, so no merge base marks where the change starts. "
                     "Pass a --base that shares history with --rev."}  # fmt: skip
    return _git(run, "-C", str(repo), "merge-base", base, rev, meaning=no_history).decode().strip()


def changed_paths(
    repo: Path, base: str, rev: str, run: Callable[..., subprocess.CompletedProcess]
) -> list[tuple[str, PurePosixPath]]:
    """List every path the change from base to rev touches, with git's status letter for it.

    Rename detection is off, so a file moved with its bytes unchanged reads as a
    deletion plus an addition, and its new path counts as added. NUL-separated
    output keeps git from quoting a path that holds a space or non-ASCII text.
    """
    out = _git(run, "-C", str(repo), "diff", "--name-status", "--no-renames", "--no-color", "-z", base, rev)
    fields = out.split(b"\0")[:-1]
    return [(fields[i].decode(), PurePosixPath(os.fsdecode(fields[i + 1]))) for i in range(0, len(fields), 2)]


def _fold(name: str) -> str:
    """Return the key under which macOS's default filesystem treats names as one: letter case and Unicode form ignored."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", name).casefold())


def _is_instruction_file(path: PurePosixPath) -> bool:
    folded = PurePosixPath(_fold(str(path)))
    return folded.name in _INSTRUCTION_FILES or any(part in CUSTOMIZATION_ROOTS for part in folded.parts)


def _is_process_file(path: PurePosixPath) -> bool:
    folded = PurePosixPath(_fold(str(path)))
    return folded.name in PROCESS_FILES and folded.parent.name in CUSTOMIZATION_ROOTS


def _folded_links(links: Mapping[PurePosixPath, str]) -> dict[str, str]:
    """Key every link by its folded path, with its target lexically normalized as extraction writes it, then folded."""
    return {_fold(str(path)): _fold(posixpath.normpath(target)) for path, target in links.items()}


def _resolve(path: str, links: Mapping[str, str]) -> tuple[str | None, list[str]]:
    """Follow every link along a folded snapshot path, and return where the walk ends and the links it passed.

    A .. steps out of the directory the walk has actually reached, as the kernel
    resolves it. The end is None when the walk leaves the snapshot, through an
    absolute target or a .. above its root, or passes more than _MAX_LINK_HOPS
    links, which only a loop does. The end is "" when the walk ends at the root.
    """
    pending, reached, passed = path.split("/"), [], []
    while pending:
        part = pending.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not reached:
                return None, passed
            reached.pop()
            continue
        here = "/".join([*reached, part])
        if here not in links:
            reached.append(part)
            continue
        passed.append(here)
        if links[here].startswith("/") or len(passed) > _MAX_LINK_HOPS:
            return None, passed
        pending = links[here].split("/") + pending
    return "/".join(reached), passed


def neutralized_names(
    archived: Iterable[PurePosixPath],
    changed: Iterable[tuple[str, PurePosixPath]],
    links: Mapping[PurePosixPath, str] | None = None,
) -> list[tuple[PurePosixPath, PurePosixPath]]:
    """Pair every path the snapshot must rename with its new name, sorted by path.

    archived lists every path the archive holds apart from directories, and links
    maps each of those that is a symlink to its target. Three classes are renamed.
    An instruction file the change adds, modifies or retypes is renamed so that it
    cannot instruct the lens that reviews it; an unchanged one is accepted and
    stays. A hook or MCP configuration directly under a customization root is
    renamed whether the change touches it or not, because it launches processes
    and a lens launches nothing. A link at an instruction file's path is renamed
    when agy, following it, would load either of those: content under review, or
    a process file through a link named as a customization root.

    A changed path the archive omits, as an export-ignore attribute makes it,
    has nothing on disk that could instruct the lens, so it is not renamed.
    """
    archived = list(archived)
    links = links or {}
    folded_links = _folded_links(links)
    present = {_fold(str(path)) for path in archived}
    under_review = present & {_fold(str(path)) for status, path in changed if status in ("A", "M", "T")}
    process_dirs = {PurePosixPath(path).parent for path in present if PurePosixPath(path).name in PROCESS_FILES}

    def exposes(link: PurePosixPath) -> bool:
        end, passed = _resolve(_fold(str(link)), folded_links)
        if end is not None and _fold(link.name) in CUSTOMIZATION_ROOTS and PurePosixPath(end) in process_dirs:
            return True
        # A directory link exposes everything beneath its target, including what
        # further links beneath it reach, so the walk visits each of those too.
        pending, seen = [(end, passed)], set()
        while pending:
            end, passed = pending.pop()
            if end is None or end in seen:
                continue
            seen.add(end)
            inside = f"{end}/" if end else ""
            if under_review & {end, *passed} or any(path.startswith(inside) for path in under_review):
                return True
            pending += [_resolve(path, folded_links) for path in folded_links if path.startswith(inside)]
        return False

    targets = {path for path in archived if _fold(str(path)) in under_review and _is_instruction_file(path)}
    targets |= {path for path in archived if _is_process_file(path)}
    targets |= {link for link in links if _is_instruction_file(link) and exposes(link)}
    return [(path, path.with_name(path.name + RENAME_SUFFIX)) for path in sorted(targets, key=str)]


def change_diff(repo: Path, base: str, rev: str, run: Callable[..., subprocess.CompletedProcess]) -> bytes:
    """Return git's unified diff of the change, which is the lens's only view of what changed.

    --no-ext-diff keeps a diff driver the repository configures from running.
    """
    return _git(
        run, "-C", str(repo), "diff", "--no-color", "--no-ext-diff", "--find-renames",
        f"--unified={DIFF_CONTEXT_LINES}", base, rev,
    )  # fmt: skip


def make_snapshot(
    repo: Path, base: str, rev: str, parent: Path, run: Callable[..., subprocess.CompletedProcess]
) -> Path:
    """Build the directory a lens reviews, under parent, and return it."""
    return _build_snapshot(repo, base, rev, parent, run)[0]


def _build_snapshot(
    repo: Path, base: str, rev: str, parent: Path, run: Callable[..., subprocess.CompletedProcess]
) -> tuple[Path, list[tuple[PurePosixPath, PurePosixPath]], str]:
    """Build a lens snapshot and also return the renames it made and the merge base the change starts at.

    The lens preamble lists both. The change is the one from the merge base of
    base and rev to rev, which is what the renames and the diff file describe.

    The snapshot is the archive of rev, extracted fresh, with its own empty git
    repository so agy's search for a repository root stops inside it, the lens
    agent definition, and the change's diff. Every refusal is raised before the
    first rename, so a refused snapshot is never half-neutralized.

    Paths are compared in folded form throughout, because a filesystem that
    ignores letter case and Unicode form extracts two paths that differ only in
    those as one path. Its name and bytes then depend on extraction order, so
    such a revision is refused. So is a link that leads outside the snapshot or
    loops, since no rename can say what agy would load through it.
    """
    snapshot = _own(tempfile.mkdtemp(prefix="agy-lens-snapshot-", dir=parent))
    review_root = DIFF_PATH.parts[0]
    with tarfile.open(fileobj=io.BytesIO(_git(run, "-C", str(repo), "archive", "--format=tar", rev))) as archive:
        members = archive.getmembers()
        taken = [m.name for m in members if PurePosixPath(_fold(m.name)).parts[:1] == (review_root,)]
        if taken:
            raise _Refused(
                f"{rev} already holds {taken[0]}, and {review_root} is where the launcher writes the change's diff. "
                f"Review a revision without a {review_root} directory in any letter case."
            )
        present: dict[str, str] = {}
        collisions = []
        for member in members:
            first = present.setdefault(_fold(member.name), member.name)
            if first != member.name:
                collisions.append(
                    f"{first} and {member.name} in {rev} differ only by letter case or Unicode form "
                    "and extract as one path"
                )
        links = {PurePosixPath(m.name): m.linkname for m in members if m.issym()}
        folded_links = _folded_links(links)
        collisions += [
            f"{link} in {rev} is a link to {target} that leads outside the snapshot or loops"
            for link, target in links.items()
            if _resolve(_fold(str(link)), folded_links)[0] is None
        ]
        archived = [PurePosixPath(m.name) for m in members if not m.isdir()]
        start = _merge_base(repo, base, rev, run)
        renamed = neutralized_names(archived, changed_paths(repo, start, rev, run), links)
        collisions += [
            f"{present[_fold(str(target))]} already exists in {rev}, so {original} cannot be renamed to {target}"
            for original, target in renamed
            if _fold(str(target)) in present
        ]
        if collisions:
            raise _Refused("; ".join(collisions) + ". Rename or remove the committed file before running a lens.")
        try:
            archive.extractall(snapshot, filter="data")
        except tarfile.FilterError as refused:
            # The extraction filter judges a link against the links extracted before
            # it, so it can refuse one the check above accepts. Its refusal is still
            # a revision the launcher cannot snapshot, not a launcher defect.
            raise _Refused(
                f"{rev} cannot be extracted safely: {refused}. Remove that path before running a lens."
            ) from None
    for original, target in renamed:
        (snapshot / original).rename(snapshot / target)
    _git(run, "init", "--quiet", str(snapshot))
    agent = snapshot / ".agents" / "agents" / LENS_AGENT / "agent.md"
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_text(lens_agent_definition(), encoding="utf-8")
    diff = snapshot / DIFF_PATH
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_bytes(change_diff(repo, start, rev, run))
    return snapshot, renamed, start


def _ledger_line(event: dict) -> str | None:
    """Return the ledger line one stream-json event contributes, or None when the ledger does not record it."""
    kind = event.get("event")
    body = event.get(kind) if isinstance(kind, str) else None
    if not isinstance(body, dict):
        return None
    if kind == "init":
        agent = f"agent={body['agent']} " if body.get("agent") else ""
        return f"[agy-run] {agent}permission_mode={body.get('permission_mode')}"
    if kind == "step_update" and body.get("state") == "ACTIVE" and body.get("tool_name"):
        # The first parameter is the path or query the tool acted on, which is
        # the read evidence a caller checks the run against.
        parameters = (body.get("tool_info") or {}).get("parameters") or {}
        line = f"[agy-run] tool={body['tool_name']}"
        if parameters:
            first = next(iter(parameters.values()))
            line += f" {first if isinstance(first, str) else json.dumps(first)}"
        return line
    if kind == "result":
        denied = ",".join(str(action.get("display_name")) for action in body.get("denied_actions") or [])
        tokens = (body.get("usage") or {}).get("total_tokens")
        return f"[agy-run] status={body.get('status')} turns={body.get('num_turns')} tokens={tokens} denied={denied}"
    return None


def classify(exit_code: int, events: list[dict], stderr_text: str, timed_out: bool) -> Outcome:
    """Decide the exit code and reason of a finished agy run from its exit code, events and stderr.

    When several causes hold, the highest decides: a timeout (the watchdog or
    agy's own print-timeout notice), then an error (a non-zero exit, a status
    other than SUCCESS, or an AGY_ERROR line), then a missing result event, then
    a denied action, then an empty response. A timed-out run is never reported
    as agy's error, and a result beside an error is never a usable output. A
    signal to the launcher outranks all of these, and run_agy applies it.
    """
    ledger = [line for event in events if (line := _ledger_line(event)) is not None]
    result = None
    for event in events:
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
    if timed_out or _PRINT_TIMEOUT_NOTICE.search(stderr_text):
        reason = "timeout"
    elif exit_code != 0 or _AGY_ERROR_LINE.search(stderr_text) or (result and result.get("status") != "SUCCESS"):
        reason = "error"
    elif result is None:
        reason = "no-result"
    elif result.get("denied_actions"):
        reason = "denied"
    elif not str(result.get("response") or "").strip():
        reason = "empty"
    else:
        return Outcome(EXIT_OK, None, str(result["response"]), ledger)
    return Outcome(EXIT_UNUSABLE if reason in ("denied", "empty") else EXIT_ROUTE, reason, "", ledger)


def _say(message: str) -> None:
    print(f"{_PROG}: {message}", file=sys.stderr, flush=True)


def _emit(line: str) -> str:
    print(line, file=sys.stderr, flush=True)
    return line


def _pump(stream: IO[bytes], sink: Callable[[str], None]) -> None:
    """Hand each line of a child's output to sink as it arrives, until the child closes the stream."""
    with stream:
        for raw in stream:
            sink(raw.decode("utf-8", errors="replace"))


def _take(line: str, events: list[dict]) -> None:
    """Record one line of agy's stdout as an event and print the ledger line it contributes."""
    if not line.strip():
        return
    try:
        event = json.loads(line)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        # stdout is reserved for the response, so a line outside the event
        # stream moves to stderr rather than being dropped.
        sys.stderr.write(line)
        return
    events.append(event)
    entry = _ledger_line(event)
    if entry is not None:
        _emit(entry)


# A process group signal fails in two harmless ways. ESRCH means every process in
# the group is gone. EPERM is what macOS answers for a group whose remaining
# members have exited but are not yet reaped, and a member the launcher may not
# signal is beyond its reach either way, so both mean there is nothing left to stop.
_GROUP_GONE = (ProcessLookupError, PermissionError)


def _group_alive(proc: subprocess.Popen) -> bool:
    if proc.poll() is None:
        return True
    try:
        os.killpg(proc.pid, 0)
    except _GROUP_GONE:
        return False
    return True


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(proc.pid, sig)
    except _GROUP_GONE:
        pass


def _end_group(proc: subprocess.Popen, clock: Callable[[], float], since: float) -> None:
    """Stop agy's whole process group: SIGTERM now, then SIGKILL once KILL_GRACE_S passes if any of it survives."""
    _signal_group(proc, signal.SIGTERM)
    while _group_alive(proc):
        if clock() - since >= KILL_GRACE_S:
            _signal_group(proc, signal.SIGKILL)
            return
        time.sleep(_POLL_S)


def run_agy(
    argv: list[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: int,
    spawn: Callable[..., subprocess.Popen],
    clock: Callable[[], float],
) -> Outcome:
    """Run agy under a watchdog, print its ledger to stderr as the stream arrives, and classify how it ended.

    agy leads a new session, so its pid is also its process group, and a
    timeout or a signal to the launcher ends every process agy started. The
    watchdog fires WATCHDOG_GRACE_S after agy's own print timeout should have.
    """
    if _signals:
        return Outcome(EXIT_ROUTE, "signal", "", [])
    try:
        proc = spawn(
            argv,
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except FileNotFoundError:
        _say(f"{argv[0]} is not on PATH. Install agy and sign in, or use another route.")
        return Outcome(EXIT_ROUTE, "no-route", "", [])
    pid_line = _emit(f"[agy-run] pid={proc.pid}")
    lines: queue.Queue[str] = queue.Queue()
    agy_stderr: list[str] = []

    def pass_through(text: str) -> None:
        agy_stderr.append(text)
        sys.stderr.write(text)
        sys.stderr.flush()

    pumps = [
        threading.Thread(target=_pump, args=(proc.stdout, lines.put), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, pass_through), daemon=True),
    ]
    for pump in pumps:
        pump.start()
    events: list[dict] = []
    deadline = clock() + timeout_s + WATCHDOG_GRACE_S
    while True:
        now = clock()
        if _signals or now >= deadline:
            timed_out = not _signals
            _end_group(proc, clock, now)
            break
        try:
            _take(lines.get(timeout=_POLL_S), events)
        except queue.Empty:
            if proc.poll() is not None and not any(pump.is_alive() for pump in pumps):
                timed_out = False
                break
    # A process outside the group can hold the pipes open after the group is
    # gone, so the wait for the last lines is bounded.
    for pump in pumps:
        pump.join(KILL_GRACE_S)
    while not lines.empty():
        _take(lines.get_nowait(), events)
    proc.wait()
    outcome = classify(proc.returncode, events, "".join(agy_stderr), timed_out)
    if _signals:
        outcome = outcome._replace(exit_code=EXIT_ROUTE, reason="signal", response="")
    return outcome._replace(ledger=[pid_line, *outcome.ledger])


def _on_signal(signum: int, frame: object) -> None:
    _signals.append(signum)


def _worker(
    args: argparse.Namespace,
    spawn: Callable[..., subprocess.Popen],
    clock: Callable[[], float],
    settings: Path,
) -> Outcome:
    cwd = Path.cwd()
    if not trusted_workspace(cwd, settings):
        raise _Refused(
            f"{cwd} is not at or beneath a path in trustedWorkspaces of {settings}, or that file is missing or "
            "unreadable, so agy would deny every edit this worker makes. "
            f"Remedy: add this directory or an ancestor of it to trustedWorkspaces in {settings}. "
            "Use an absolute path, because a relative entry trusts nothing."
        )
    argv = build_worker_argv(args.model, args.timeout, args.prompt)
    return run_agy(argv, cwd, os.environ, args.timeout, spawn, clock)


def _lens(
    args: argparse.Namespace,
    spawn: Callable[..., subprocess.Popen],
    run: Callable[..., subprocess.CompletedProcess],
    clock: Callable[[], float],
    real_home: Path,
) -> tuple[Outcome, Path]:
    parent = Path(tempfile.gettempdir())
    snapshot, renamed, start = _build_snapshot(args.repo, args.base, args.rev, parent, run)
    home = make_lens_home(parent, real_home)
    env = lens_env(os.environ, home)
    outcome = prove_home(home, real_home, args.repo, env)
    if outcome is None:
        prompt = lens_preamble(args.repo, args.base, args.rev, snapshot, renamed, start) + args.prompt
        outcome = run_agy(build_lens_argv(args.model, args.timeout, prompt), snapshot, env, args.timeout, spawn, clock)
    # A lens that answered without a single tool call read nothing, not even the
    # diff, so its answer is not a review. The check applies only to a run that
    # would otherwise succeed, which ranks it below every other cause. A worker
    # may answer without a tool, so it is not checked.
    if outcome.exit_code == EXIT_OK and not any(line.startswith("[agy-run] tool=") for line in outcome.ledger):
        outcome = Outcome(EXIT_UNUSABLE, "unread", "", outcome.ledger)
    return outcome, snapshot


def _clean_up(kept: Path | None) -> None:
    """Remove every directory this run created, except a snapshot the caller keeps, and report what survives.

    A directory that cannot be removed is reported rather than turned into a
    failure, so a good response is never discarded over a leftover directory.
    """
    for directory in _owned:
        if directory == kept:
            _emit(f"[agy-run] snapshot={directory}")
            continue
        shutil.rmtree(directory, ignore_errors=True)
        if directory.exists():
            _emit(f"[agy-run] leak={directory}")
    _owned.clear()


def main(
    argv: list[str],
    *,
    spawn: Callable[..., subprocess.Popen] = subprocess.Popen,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    real_home: Path | None = None,
    settings: Path = AGY_SETTINGS,
) -> int:
    """Run the launcher on argv and return its exit code.

    The keyword arguments are the seams a test replaces: how agy is spawned, how
    git runs, the watchdog's clock, the real home a lens links its Keychains
    from, and agy's settings file.
    """
    try:
        args = parse_args(argv)
    except _Refused as refusal:
        _say(str(refusal))
        return EXIT_CONFIG
    _signals.clear()
    _owned.clear()
    previous = {sig: signal.signal(sig, _on_signal) for sig in (signal.SIGTERM, signal.SIGINT)}
    kept = None
    try:
        try:
            if args.mode == "worker":
                outcome = _worker(args, spawn, clock, settings.expanduser())
            else:
                outcome, snapshot = _lens(args, spawn, run, clock, real_home or Path.home())
                kept = snapshot if args.keep_snapshot else None
        except _Refused as refusal:
            _say(str(refusal))
            outcome = Outcome(EXIT_CONFIG, None, "", [])
        except _NoRoute as missing:
            _say(str(missing))
            outcome = Outcome(EXIT_ROUTE, "no-route", "", [])
        # A signal ends the run whatever else happened, including one that
        # arrived while the snapshot or the home was being built.
        if _signals:
            outcome = outcome._replace(exit_code=EXIT_ROUTE, reason="signal", response="")
        if outcome.reason is not None:
            _emit(f"[agy-run] reason={outcome.reason}")
        if outcome.exit_code == EXIT_OK:
            sys.stdout.write(outcome.response)
            sys.stdout.flush()
    finally:
        _clean_up(kept)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
