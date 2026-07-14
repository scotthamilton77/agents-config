from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from installer.core.profiles import UniverseRef


def kit_name_of(selector_key: str) -> str:
    """The kit name is the segment directly under ``kits/`` — the single source of
    identity shared by the selector side and the receipt/prune owner (``kit:<name>``)."""
    parts = selector_key.split("/")
    if len(parts) < 2 or parts[0] != "kits":
        raise ValueError(f"not a kit selector key: {selector_key!r}")  # noqa: TRY003  # single call-site
    return parts[1]


@dataclass(frozen=True, slots=True)
class StagedKitRef:
    selector_key: str  # kits/<kit>/<subpath> — for the resolver universe
    ref: UniverseRef  # tool=None, dest_relpath=<subpath> (verbatim tree-mirror)


def stage_kits(kits_root: Path) -> list[StagedKitRef]:
    """Walk ``src/kits/<kit>/**``; one StagedKitRef per file. dest_relpath is verbatim
    (no suffix strip); selector_key is source-relative (``kits/<kit>/<subpath>``)."""
    if not kits_root.is_dir():
        return []
    out: list[StagedKitRef] = []
    for kit_dir in sorted(p for p in kits_root.iterdir() if p.is_dir()):
        name = kit_dir.name
        for f in sorted(p for p in kit_dir.rglob("*") if p.is_file()):
            dest_relpath = f.relative_to(kit_dir)
            selector = f"kits/{name}/{dest_relpath.as_posix()}"
            out.append(
                StagedKitRef(
                    selector_key=selector,
                    ref=UniverseRef(tool=None, dest_relpath=dest_relpath),
                )
            )
    return out


def kit_universe(staged: Iterable[StagedKitRef]) -> dict[str, list[UniverseRef]]:
    universe: dict[str, list[UniverseRef]] = {}
    for sk in staged:
        universe.setdefault(sk.selector_key, []).append(sk.ref)
    return universe
