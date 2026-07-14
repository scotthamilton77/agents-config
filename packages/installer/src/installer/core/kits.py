from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from installer.core.profiles import UniverseRef
from installer.plugins.base import PluginRoute


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


def kit_routes(kits_root: Path, project_root: Path) -> dict[str, list[PluginRoute]]:
    """Per kit, one PluginRoute per (destination directory x exec-bit). Mirrors
    PluginAdapter.routes(home) but grouped by kit name for per-kit owners."""
    result: dict[str, list[PluginRoute]] = {}
    if not kits_root.is_dir():
        return result
    for kit_dir in sorted(p for p in kits_root.iterdir() if p.is_dir()):
        groups: dict[tuple[Path, bool], list[str]] = {}
        for f in sorted(p for p in kit_dir.rglob("*") if p.is_file()):
            rel = f.relative_to(kit_dir)
            execbit = bool(f.stat().st_mode & 0o111)
            groups.setdefault((rel.parent, execbit), []).append(rel.suffix)
        routes: list[PluginRoute] = []
        for (destdir, execbit), _suffixes in groups.items():
            routes.append(
                PluginRoute(
                    source_dir=kit_dir / destdir,
                    dest_dir=project_root / destdir,
                    glob="*",
                    executable=execbit,
                )
            )
        result[kit_dir.name] = routes
    return result


@dataclass(frozen=True, slots=True)
class _KitRouteAdapter:
    """A selected kit presented as a PluginAdapter so it rides the existing
    install_plugin_routes / prune_pipeline / receipt machinery unchanged."""

    _name: str  # "kit:<name>"
    _source_path: Path  # the kit source dir
    _routes: tuple[PluginRoute, ...]

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_path(self) -> Path:
        return self._source_path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002 — always active (explicitly selected)
        return True

    def routes(self, home: Path) -> tuple[PluginRoute, ...]:  # noqa: ARG002 — dest baked in
        return self._routes


def kit_adapters(
    kits_root: Path, project_root: Path, *, selected: set[str]
) -> list[_KitRouteAdapter]:
    routes_by_kit = kit_routes(kits_root, project_root)
    return [
        _KitRouteAdapter(_name=f"kit:{name}", _source_path=kits_root / name, _routes=tuple(routes))
        for name, routes in routes_by_kit.items()
        if name in selected
    ]
