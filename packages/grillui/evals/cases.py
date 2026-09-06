"""The recorded turns this suite replays, and how one is read off disk.

A case is read from three files: the dispatch as it was recorded, the log
entries that dispatch's prompt is composed from, and what the reply is expected
to satisfy. The whole session it was trimmed from is not here, and a case that
reached for one would be replaying something no checkout has.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grillui.schemas import DispatchContext, LogEntry

CASES = Path(__file__).resolve().parent / "cases"
FILES = ("dispatch.json", "log.jsonl", "case.json")


class CaseRefusedError(ValueError):
    """A case directory this suite will not load."""

    def __init__(self, case: str, why: str) -> None:
        super().__init__(f"{case}: {why}")


@dataclass(frozen=True)
class Case:
    """One recorded turn, and what its reply owes.

    `channel` is the dispatch's, because the driver reads it off that record and
    the seat is chosen by it: stated a second time, the two can only disagree.
    """

    name: str
    tier: str
    channel: str
    samples: int
    owed_rulings: tuple[str, ...]
    speech_limit: int
    stop: bool
    context_bytes: int | None
    prompt_tokens: int | None
    recorded: str
    context: DispatchContext
    entries: tuple[LogEntry, ...]


def _within(path: Path, root: Path, case: str, named: str) -> Path:
    """`path`, once it is known to lie inside the cases tree.

    The containment is anchored on the tree and not on the case, because a case
    directory is itself a path a link can point out of, and a comparison made
    against it would follow that link on both sides and agree with itself. What
    a case reads is composed into a prompt and sent to a third party, so the
    only thing it may read is what the checkout carries.
    """
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise CaseRefusedError(case, f"{named} lies outside the cases directory")
    return resolved


def _inside(where: Path, root: Path, named: str) -> Path:
    """One of the case's own three files.

    A name is a name and never a route: anything carrying a separator, a parent
    reference or a root would let a case read a file the checkout does not carry
    and replay a turn nobody can see.
    """
    if named not in FILES:
        raise CaseRefusedError(where.name, f"{named!r} is not one of {', '.join(FILES)}")
    path = where / named
    if not path.is_file():
        raise CaseRefusedError(where.name, f"{named} is missing")
    return _within(path, root, where.name, named)


def _stated(where: Path, case: dict[str, Any], key: str) -> Any:
    if key not in case:
        raise CaseRefusedError(where.name, f"case.json states no {key}")
    return case[key]


def load_case(where: Path, root: Path | None = None) -> Case:
    """The case this directory holds.

    `root` is the tree the case must lie in, and defaults to the directory the
    case sits in, so a case loaded on its own is contained by where it was found.
    """
    root = where.parent if root is None else root
    _within(where, root, where.name, "the case directory")
    case = json.loads(_inside(where, root, "case.json").read_text(encoding="utf-8"))
    named = {one for one in case.values() if isinstance(one, str)}
    outside = {one for one in named if "/" in one or one == ".." or Path(one).is_absolute()}
    if outside:
        raise CaseRefusedError(
            where.name,
            f"case.json names {', '.join(sorted(outside))}, and a case reads "
            "nothing outside its own directory",
        )
    recorded = _inside(where, root, "dispatch.json").read_text(encoding="utf-8")
    context = DispatchContext.model_validate_json(recorded)
    entries = tuple(
        LogEntry.model_validate_json(line)
        for line in _inside(where, root, "log.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    samples = int(case.get("samples", 1))
    if samples < 1:
        raise CaseRefusedError(where.name, f"a run takes at least one sample, not {samples}")
    stop = _stated(where, case, "stop")
    if not isinstance(stop, bool):
        raise CaseRefusedError(where.name, f"stop is {stop!r}, not true or false")
    owed = () if context.mootness is None else tuple(context.mootness.ids)
    stated = tuple(_stated(where, case, "owed_rulings"))
    if stated != owed:
        raise CaseRefusedError(where.name, f"case.json owes {stated} and the dispatch owes {owed}")
    return Case(
        name=where.name,
        tier=_stated(where, case, "tier"),
        channel=context.channel,
        samples=samples,
        owed_rulings=owed,
        speech_limit=int(case.get("speech_limit", 1)),
        stop=stop,
        context_bytes=case.get("context_bytes"),
        prompt_tokens=case.get("prompt_tokens"),
        recorded=recorded,
        context=context,
        entries=entries,
    )


def load_cases(root: Path = CASES) -> list[Case]:
    """Every case checked in, in name order."""
    return [load_case(one, root) for one in sorted(root.iterdir()) if one.is_dir()]
