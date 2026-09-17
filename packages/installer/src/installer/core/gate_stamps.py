"""Gate stamps: what content a package's gate saw, and whether a commit may carry it.

A stamped gate target records, under the package it gates, which gate ran, the
status it exited with, and a digest of the package's content as the gate saw it.
The pre-commit hook recomputes that digest over the staged content and refuses a
commit carrying package content no gate has seen exit green. The two sides
compute the same digest from different places, so a gate run against other
content cannot vouch for what is being committed.

Every question the refusal turns on is asked of the index, never of the working
tree: the index is what the commit will carry, and an edit left unstaged must
not be able to change the answer. A git command that cannot answer raises, so a
question that goes unanswered refuses the commit rather than waving it through.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from stat import S_ISLNK
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Stamps sit beside the package they describe and are gitignored, which also
# keeps them out of the digest they record.
STAMP_DIR = ".gate-stamps"

# Paths are handed to `git hash-object` as arguments, so a batch bounds how long
# one command line gets.
_HASH_BATCH = 256

_GATE_TARGET = re.compile(r"(?m)^ci-([A-Za-z0-9_]+):")

# The path the hook tests for, and the module that answers it. Naming it here
# keeps the stanza and the checker from drifting apart.
CHECKER_PATH = "packages/installer/src/installer/core/gate_stamps.py"

HOOK_BEGIN = "# --- BEGIN GATE STAMP CHECK ---"
HOOK_END = "# --- END GATE STAMP CHECK ---"

# The stanza runs the checker out of the tree being committed, so a tree that
# carries no checker has none to run. It says so and passes through, because the
# alternative blocks every older branch and every bisect that shares this
# checkout's hooks. Presence is read from the index for the same reason the
# checker reads it there: the commit carries the index.
HOOK_STANZA = f"""{HOOK_BEGIN}
# Refuses a commit carrying package content that no `make ci-<pkg>` run has seen
# exit green. A tree whose index carries no checker -- an older branch, a bisect
# -- prints one line and passes through, so this hook never blocks a commit on a
# worktree that predates it.
gate_stamp_root=$(git rev-parse --show-toplevel) || exit 1
(
  cd "$gate_stamp_root" || exit 1
  if git cat-file -e ":{CHECKER_PATH}" 2>/dev/null; then
    exec uv --project packages/installer run python -m installer.gate_stamp_cli check .
  fi
  echo "gate-stamp check: this tree carries no gate-stamp checker; skipped."
) || exit 1
{HOOK_END}
"""


class GateStampError(RuntimeError):
    """A question the refusal depends on that git could not answer."""


def package_of(gate: str) -> str:
    """The package a gate name gates: everything after its phase prefix.

    Gate names are ``<phase>-<package>``, so ``ci-installer`` and
    ``e2e-grillui`` both name the package that owns them and the stamp they
    write.
    """
    _, _, package = gate.partition("-")
    return package


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo_root`` and hand back its output as text that survives any path.

    Git writes a path as the bytes it is, and those bytes need not be valid in
    the locale's encoding. A strict decode would raise on such a path before its
    content could be hashed, so undecodable bytes are escaped instead.

    A failed command raises unless the caller asks otherwise, because an empty
    answer read as "nothing to check" is how a broken git turns into a commit
    nobody gated.
    """
    done = subprocess.run(  # noqa: S603  # fixed argv; only the root and the pathspec vary
        ["git", "-C", str(repo_root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        errors="surrogateescape",
        check=False,
    )
    if check and done.returncode != 0:
        msg = f"git {args[0]} failed ({done.returncode}): {done.stderr.strip()}"
        raise GateStampError(msg)
    return done


def _digest(entries: Iterable[tuple[str, str, str]]) -> str:
    """A digest over (path, file mode, git blob id) triples, ordered by path.

    Sorting is what makes the two sides comparable: git lists the working tree
    and the index in its own order, and only the set of triples is the content.
    The mode is in there because git records the executable bit and a blob id
    does not carry it, so a chmod would otherwise leave a stamp looking current.
    """
    running = hashlib.sha256()
    for path, mode, blob in sorted(entries):
        running.update(f"{mode} {blob} {path}\n".encode(errors="surrogateescape"))
    return running.hexdigest()


def _mode(path: Path) -> str:
    """The mode git records for a path, which distinguishes only three kinds of file."""
    status = path.lstat()
    if S_ISLNK(status.st_mode):
        return "120000"
    return "100755" if status.st_mode & 0o111 else "100644"


def _blob_ids(repo_root: Path, paths: list[str]) -> list[str]:
    """Git's blob id for each path, in the order given.

    The paths go as arguments rather than down stdin, because ``--stdin-paths``
    separates them by newline and a newline is a legal byte in a filename. A
    count that does not match the paths asked about means the ids cannot be
    paired with them, which raises rather than pairing them wrongly.
    """
    ids: list[str] = []
    for start in range(0, len(paths), _HASH_BATCH):
        hashed = _git(repo_root, "hash-object", "--", *paths[start : start + _HASH_BATCH])
        ids.extend(hashed.stdout.split())
    if len(ids) != len(paths):
        msg = f"git hashed {len(ids)} of {len(paths)} files"
        raise GateStampError(msg)
    return ids


def worktree_digest(repo_root: Path, package: str) -> str:
    """The digest of a package's content as it sits in the working tree.

    Tracked files and untracked files git would not ignore both count, because
    that is exactly what a gate run over the package sees. A tracked file
    deleted on disk contributes nothing, which is what the index will say about
    it once the deletion is staged.
    """
    listed = _git(
        repo_root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        f"packages/{package}",
    )
    paths = sorted({p for p in listed.stdout.split("\0") if p and (repo_root / p).is_file()})
    if not paths:
        return _digest([])
    blobs = _blob_ids(repo_root, paths)
    return _digest(
        (path, _mode(repo_root / path), blob) for path, blob in zip(paths, blobs, strict=True)
    )


def index_digest(repo_root: Path, package: str) -> str:
    """The digest of a package's content as the index holds it, which is what a commit carries.

    The index already stores a mode and a blob id per path, so nothing is hashed
    here; both are the ones git wrote when the content was staged.
    """
    listed = _git(repo_root, "ls-files", "-s", "-z", "--", f"packages/{package}")
    entries = []
    for record in listed.stdout.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        mode, blob, _stage = meta.split()
        entries.append((path, mode, blob))
    return _digest(entries)


def stamp_path(repo_root: Path, gate: str) -> Path:
    """Where the named gate's stamp lives."""
    return repo_root / "packages" / package_of(gate) / STAMP_DIR / f"{gate}.json"


def write_stamp(repo_root: Path, gate: str, exit_code: int) -> Path:
    """Record what the named gate exited with and the content it ran over.

    A red run is stamped as readily as a green one. The stamp is what the gate
    saw, and a gate whose failure left no trace would let the next commit read
    an older green run as current.
    """
    path = stamp_path(repo_root, gate)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = {
        "gate": gate,
        "exit": exit_code,
        "content": worktree_digest(repo_root, package_of(gate)),
    }
    path.write_text(json.dumps(stamp, indent=2) + "\n")
    return path


def read_stamp(repo_root: Path, gate: str) -> dict[str, object] | None:
    """The named gate's stamp, or None when there is no readable one.

    A stamp that will not parse is no stamp. It records nothing about the
    content being committed, and treating it as one would turn a truncated
    write into a pass.
    """
    path = stamp_path(repo_root, gate)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def gated_packages(repo_root: Path) -> set[str]:
    """The packages the Makefile in the index defines a `ci-` target for.

    A package with no such target has no stamp any run would write, so the check
    has nothing to compare against and lets it through. The hook knows only the
    gates the Makefile stamps. The Makefile is read from the index because the
    index is what the commit carries: a target deleted only in the working tree
    still gates the commit that keeps it.
    """
    shown = _git(repo_root, "show", ":Makefile", check=False)
    if shown.returncode != 0:
        return set()
    return set(_GATE_TARGET.findall(shown.stdout))


def staged_packages(repo_root: Path) -> list[str]:
    """The packages whose files the pending commit touches.

    Paths come back NUL-separated because git's default output quotes a path
    carrying an unusual byte, and a quoted path names no package.
    """
    head = _git(repo_root, "rev-parse", "--verify", "HEAD", check=False)
    # A repository with no commit yet has nothing to diff against but the tree
    # every repository shares for "nothing".
    base = (
        head.stdout.strip() if head.returncode == 0 else "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    )
    listed = _git(repo_root, "diff", "--cached", "--name-only", "-z", base)
    packages = set()
    for path in listed.stdout.split("\0"):
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "packages":
            packages.add(parts[1])
    return sorted(packages)


def refusals(repo_root: Path) -> list[str]:
    """One line per package whose staged content no green gate has vouched for.

    An empty list is a commit that may land: either it touches no gated package,
    or every gated package it touches has a green stamp over the very content
    the index holds.
    """
    gated = gated_packages(repo_root)
    messages = []
    for package in staged_packages(repo_root):
        if package not in gated:
            continue
        gate = f"ci-{package}"
        stamp = read_stamp(repo_root, gate)
        if stamp is None:
            reason = "no gate run is recorded"
        elif stamp.get("exit") != 0:
            reason = f"the recorded run exited {stamp.get('exit')}"
        elif stamp.get("content") != index_digest(repo_root, package):
            reason = "the recorded run covered different content"
        else:
            continue
        messages.append(f"packages/{package}: {reason}. Run `make {gate}`, then commit again.")
    return messages


def install_hook(hooks_dir: Path) -> Path:
    """Put the check into the checkout's pre-commit hook, replacing any earlier copy.

    Whatever else the hook holds is left where it is, so a stanza another tool
    manages keeps running. Installing twice leaves one copy of this one.
    """
    hook = hooks_dir / "pre-commit"
    existing = hook.read_text() if hook.is_file() else "#!/usr/bin/env sh\n"
    before, marked, rest = existing.partition(HOOK_BEGIN)
    if marked:
        _, _, after = rest.partition(HOOK_END)
        existing = before.rstrip("\n") + "\n" + after.lstrip("\n")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook.write_text(existing.rstrip("\n") + "\n\n" + HOOK_STANZA)
    hook.chmod(0o755)
    return hook
