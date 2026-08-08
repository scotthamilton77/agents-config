"""Which grind directory a command acts on -- the `--dir` resolution rule.

A `default="."` on every subcommand would make the omitted-flag path
*silently* different from the explicit-flag path: create with `--dir run/`,
omit the flag on a later `status`, and the CLI folds an empty cwd and reports
an empty board as fact. Nothing fails; the run looks like lost work.

The rule here removes that class of failure by construction. For every verb
that reads or appends to an existing grind, the omitted-flag path either
resolves to the same directory the explicit flag would have named, or it
fails loudly -- it never silently lands on a different (empty) state:

1. `--dir` wins, always, verbatim.
2. Otherwise `GRIND_DIR`, verbatim -- the ambient way to pin a long-lived
   run for a whole session without threading the flag through every call.
3. Otherwise search cwd and its ancestors for the first directory holding a
   non-empty `events.jsonl`. A grind directory is the only thing this can
   find, so a hit is the state the caller meant.
4. Otherwise: a command error naming what was searched.

A resolved path that holds no state is a command error too, whatever
resolved it -- "act on the empty state you didn't mean" is exactly the
failure, and an explicit `--dir` typo produces it just as readily as a
missing flag.

`create` is the one verb whose target legitimately has no state yet, so it
skips steps 3-4 and keeps the documented `default: cwd` (spec CLI contract).
Searching upward on its behalf would answer the wrong question -- create asks
"where should this new grind live", not "where does the existing one live".

`cwd` and `env` arrive as arguments, never read from the process here -- same
injection seam as the CLI's `now`/`read_file`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from grind.envelope import GrindError
from grind.store import EVENTS_FILENAME, is_log_nonempty

GRIND_DIR_ENV = "GRIND_DIR"

# What decided the directory -- carried so an error can name the input the
# caller can actually correct.
DirSource = Literal["--dir", "GRIND_DIR", "search", "cwd"]


@dataclass(frozen=True)
class ResolvedDir:
    path: Path
    source: DirSource


def _explicit(flag: str | None, env: Mapping[str, str]) -> ResolvedDir | None:
    """The caller-named directory, if any: the flag, else `GRIND_DIR`.

    An all-whitespace `GRIND_DIR` is treated as unset rather than as the
    directory `""` -- an exported-but-empty variable is a shell artifact, not
    a request to act on the filesystem root of a relative path.
    """
    if flag is not None:
        return ResolvedDir(Path(flag), "--dir")
    from_env = env.get(GRIND_DIR_ENV, "").strip()
    if from_env:
        return ResolvedDir(Path(from_env), "GRIND_DIR")
    return None


def search_upward(start: Path) -> Path | None:
    """The nearest directory at or above `start` holding a non-empty log."""
    for candidate in (start, *start.parents):
        if is_log_nonempty(candidate):
            return candidate
    return None


def resolve_for_create(flag: str | None, *, cwd: Path, env: Mapping[str, str]) -> ResolvedDir:
    """`create`'s target: flag, else `GRIND_DIR`, else cwd. Never searched."""
    explicit = _explicit(flag, env)
    return explicit if explicit is not None else ResolvedDir(cwd, "cwd")


def resolve_existing(flag: str | None, *, cwd: Path, env: Mapping[str, str]) -> ResolvedDir:
    """The directory of an existing grind, or a command error.

    Raises `GrindError` rather than returning an empty-state directory: every
    verb but `create` is meaningless against a grind that was never created,
    and folding zero events into a confident "empty board" answer is the
    silent-state-split failure itself.
    """
    explicit = _explicit(flag, env)
    if explicit is not None:
        if not is_log_nonempty(explicit.path):
            raise GrindError(
                f"no grind state at {explicit.path} (from {explicit.source}): "
                f"{EVENTS_FILENAME} is missing or empty. `grind create --file <seed>` "
                f"seeds a new grind; every other verb acts on an existing one."
            )
        return explicit

    found = search_upward(cwd)
    if found is None:
        raise GrindError(
            f"no grind state found: neither {cwd} nor any parent directory holds a "
            f"non-empty {EVENTS_FILENAME}. Pass --dir <grind-dir>, or set "
            f"{GRIND_DIR_ENV}, to name the grind to act on."
        )
    return ResolvedDir(found, "search")
