"""Profiles manifest + pure scope-routing resolver.

`profiles.toml` declares default destination scopes per selector (`[scopes]`)
and named profiles (`[profiles.*]`) whose include entries may override scope
per selector and whose exclude entries subtract content unconditionally. The
resolver in this module is the single pure function that maps a selected
profile set onto the staged universe and emits per-scope, scope-partitioned
results — every "why did X install to Y?" answer lives in its inputs and
output.

See docs/specs/2026-07-06-profiles-scope-routing.md §§3, 5, 6, 7, 10 for the
design contract this module implements.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.model import FileKind, StagingPlan

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from installer.core.model import StagedItem, Tool


class Scope(StrEnum):
    """A destination realm for a resolved profile entry. Closed set for v1."""

    USER = "user"
    PROJECT = "project"


class ProfilesError(ValueError):
    """Fail-loud manifest/resolution error. The message always names the
    offending profile, selector, item, or scope."""


@dataclass(frozen=True, slots=True)
class IncludeEntry:
    """One `include` entry from a profile: a selector and an optional scope
    override. `scope is None` means "derive from `[scopes]` at resolve time"."""

    selector: str
    scope: Scope | None


@dataclass(frozen=True, slots=True)
class Profile:
    """A named set of include entries (may override scope per selector) and
    exclude entries (selectors only — exclusion is scope-agnostic)."""

    name: str
    includes: tuple[IncludeEntry, ...]
    excludes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Manifest:
    """A loaded, merged profiles manifest: the shipped `[scopes]` defaults
    and every profile (shipped + optional user-merged)."""

    schema: int
    scopes: Mapping[str, Scope]
    profiles: Mapping[str, Profile]


def _coerce_scope(value: object, *, context: str) -> Scope:
    if not isinstance(value, str):
        msg = f"{context}: scope must be a string, got {value!r}"
        raise ProfilesError(msg)
    try:
        return Scope(value)
    except ValueError:
        msg = f"{context}: unknown scope {value!r}"
        raise ProfilesError(msg) from None


def _parse_include(profile_name: str, item: object, path: Path) -> IncludeEntry:
    if isinstance(item, str):
        return IncludeEntry(selector=item, scope=None)
    if isinstance(item, dict) and set(item) == {"select", "scope"}:
        selector = item["select"]
        if not isinstance(selector, str):
            msg = f"{path}: [profiles.{profile_name}] include 'select' must be a string"
            raise ProfilesError(msg)
        scope = _coerce_scope(
            item["scope"], context=f"{path}: [profiles.{profile_name}] include {selector!r}"
        )
        return IncludeEntry(selector=selector, scope=scope)
    msg = f"{path}: [profiles.{profile_name}] include entry has invalid shape: {item!r}"
    raise ProfilesError(msg)


def _parse_exclude(profile_name: str, item: object, path: Path) -> str:
    if not isinstance(item, str):
        msg = f"{path}: [profiles.{profile_name}] exclude entry must be a string, got {item!r}"
        raise ProfilesError(msg)
    return item


def _parse_profile(name: str, entry: object, path: Path) -> Profile:
    if not isinstance(entry, dict):
        msg = f"{path}: [profiles.{name}] must be a table"
        raise ProfilesError(msg)
    includes = tuple(_parse_include(name, item, path) for item in entry.get("include", []))
    excludes = tuple(_parse_exclude(name, item, path) for item in entry.get("exclude", []))
    return Profile(name=name, includes=includes, excludes=excludes)


def _parse_manifest_file(path: Path, *, allow_scopes: bool) -> Manifest:
    with path.open("rb") as handle:
        data = tomllib.load(handle)

    schema = data.get("schema")
    if schema != 1:
        msg = f"{path}: unsupported schema {schema!r} (expected 1)"
        raise ProfilesError(msg)

    scopes_table = data.get("scopes", {})
    if not allow_scopes and scopes_table:
        msg = f"{path}: a user manifest may not declare [scopes]"
        raise ProfilesError(msg)
    scopes: dict[str, Scope] = {
        selector: _coerce_scope(value, context=f"{path}: [scopes] {selector!r}")
        for selector, value in scopes_table.items()
    }

    profiles_table = data.get("profiles", {})
    profiles: dict[str, Profile] = {
        name: _parse_profile(name, entry, path) for name, entry in profiles_table.items()
    }
    return Manifest(schema=schema, scopes=scopes, profiles=profiles)


def load_manifest(shipped: Path, user: Path | None = None) -> Manifest:
    """Load the shipped manifest, optionally merging an optional user-owned
    manifest by profile name.

    The user file is read-only to the installer — never written here. It may
    not declare `[scopes]`; a profile name present in both files is a
    collision (no silent shadowing) — compose or rename instead. The merged
    `Manifest.scopes` comes only from the shipped file.
    """
    manifest = _parse_manifest_file(shipped, allow_scopes=True)
    if user is None or not user.is_file():
        return manifest

    user_manifest = _parse_manifest_file(user, allow_scopes=False)
    collisions = set(manifest.profiles) & set(user_manifest.profiles)
    if collisions:
        names = ", ".join(sorted(collisions))
        msg = f"profile name(s) defined in both {shipped} and {user}: {names}"
        raise ProfilesError(msg)

    return Manifest(
        schema=manifest.schema,
        scopes=manifest.scopes,
        profiles={**manifest.profiles, **user_manifest.profiles},
    )


@dataclass(frozen=True, slots=True)
class UniverseRef:
    """One staged item's tool + destination path, indexed under its
    normalized selector key by `project_universe`."""

    tool: Tool
    dest_relpath: Path


def _selector_key(item: StagedItem) -> str:
    """Normalize one staged item's `dest_relpath` into the §3 selector
    vocabulary: `.md`/`.template` suffixes stripped for namespaced items;
    the synthetic `instructions`/`settings` selectors for tool-root items."""
    if item.namespace is not None:
        path = item.dest_relpath
        while path.suffix in (".md", ".template"):
            path = path.with_suffix("")
        return path.as_posix()
    if item.kind in (FileKind.SETTINGS_JSON, FileKind.JSONC, FileKind.TOML):
        return "settings"
    if item.kind is FileKind.OTHER:
        return "instructions"
    msg = (
        f"staged item {item.dest_relpath} has no namespace and an unexpected "
        f"kind {item.kind!r}; refusing to guess its selector key"
    )
    raise ProfilesError(msg)


def project_universe(plans: Iterable[StagingPlan]) -> dict[str, list[UniverseRef]]:
    """Project the union of every given tool plan into the normalized
    selector vocabulary.

    The universe is the union across ALL given tool plans, not per-tool: a
    manifest is authored once for the whole install, so a selector like
    `commands/**` is valid even though only some tools stage commands.
    Multiple items collapse onto one key by design (e.g. `instructions`,
    `settings`) — the key maps to a list of refs, not a single one.
    """
    universe: dict[str, list[UniverseRef]] = {}
    for plan in plans:
        for item in plan.items.values():
            key = _selector_key(item)
            universe.setdefault(key, []).append(
                UniverseRef(tool=plan.tool, dest_relpath=item.dest_relpath)
            )
    return universe


def _selector_matches(selector: str, candidate_key: str) -> bool:
    """Segment-based glob match: `**` = zero-or-more segments, `*` = exactly
    one segment (any content), a literal segment matches an equal segment.

    Deliberately not `fnmatch`/`PurePath.match` — their `**` semantics
    differ from the zero-or-more-segments contract this resolver needs.
    """
    return _match_segments(selector.split("/"), candidate_key.split("/"))


def _match_segments(pattern: list[str], key: list[str]) -> bool:
    if not pattern:
        return not key
    head, *rest = pattern
    if head == "**":
        if not rest:
            return True
        return any(_match_segments(rest, key[i:]) for i in range(len(key) + 1))
    if not key:
        return False
    if head != "*" and head != key[0]:
        return False
    return _match_segments(rest, key[1:])


def _specificity(selector: str) -> tuple[bool, int]:
    """`(is_literal, literal_prefix_len)`. Any literal selector beats any
    glob; among globs, more literal leading segments wins; equal tuples are
    a tie the caller must resolve explicitly (never silently)."""
    segments = selector.split("/")
    is_literal = "*" not in selector
    if is_literal:
        return (True, len(segments))
    prefix_len = 0
    for segment in segments:
        if "*" in segment:
            break
        prefix_len += 1
    return (False, prefix_len)


@dataclass(frozen=True, slots=True)
class ResolvedPlan:
    """The resolver's output: refs partitioned by bound scope, plus a count
    of how many refs were dropped per unbound scope they resolved to."""

    included: Mapping[Scope, tuple[UniverseRef, ...]]
    dropped_counts: Mapping[Scope, int]


def _break_specificity_tie(
    key: str, matches: Sequence[tuple[str, Scope, str]], *, source: str
) -> Scope:
    """`matches` is `(selector, scope, label)`. Picks the scope of the
    most-specific selector; a tie among equally-specific selectors that
    carry *different* scopes is a `ProfilesError` naming every tied label —
    a tie assigning the *same* scope is fine (not an error)."""
    scored = [(_specificity(m[0]), m) for m in matches]
    best = max(spec for spec, _ in scored)
    winners = [m for spec, m in scored if spec == best]
    scopes = {scope for _selector, scope, _label in winners}
    if len(scopes) > 1:
        labels = ", ".join(label for _selector, _scope, label in winners)
        msg = f"{source}: conflicting scopes for {key!r} at equal specificity: {labels}"
        raise ProfilesError(msg)
    return winners[0][1]


def _assign_scope(
    key: str, manifest: Manifest, contributing_includes: Sequence[tuple[str, IncludeEntry]]
) -> Scope:
    """Explicit-scope include entries matching `key` win, most-specific
    first; absent those, the most-specific `[scopes]` entry applies. No
    match at all is a `ProfilesError` — new namespaces route deliberately."""
    explicit: list[tuple[str, Scope, str]] = []
    for profile_name, entry in contributing_includes:
        if entry.scope is None or not _selector_matches(entry.selector, key):
            continue
        explicit.append((entry.selector, entry.scope, f"{profile_name}:{entry.selector}"))
    if explicit:
        return _break_specificity_tie(key, explicit, source="include")

    defaults: list[tuple[str, Scope, str]] = []
    for selector, scope in manifest.scopes.items():
        if _selector_matches(selector, key):
            defaults.append((selector, scope, selector))
    if not defaults:
        msg = f"no [scopes] entry matches {key!r}; new namespaces must be routed deliberately"
        raise ProfilesError(msg)
    return _break_specificity_tie(key, defaults, source="[scopes]")


def resolve(
    manifest: Manifest,
    selection: Sequence[str],
    universe: Mapping[str, Sequence[UniverseRef]],
    bound_scopes: frozenset[Scope],
) -> ResolvedPlan:
    """The one pure resolver: `(manifest, selected profiles, staged universe,
    bound scopes) -> per-scope refs + dropped counts`. Every failure raises
    `ProfilesError` naming the offending profile, selector, or key — see
    docs/specs/2026-07-06-profiles-scope-routing.md §6 for the algorithm.
    """
    names = list(selection) or ["full"]
    for name in names:
        if name not in manifest.profiles:
            known = ", ".join(sorted(manifest.profiles))
            msg = f"unknown profile {name!r} (known profiles: {known})"
            raise ProfilesError(msg)

    contributing_includes: list[tuple[str, IncludeEntry]] = []
    excludes: set[str] = set()
    for name in names:
        profile = manifest.profiles[name]
        for entry in profile.includes:
            contributing_includes.append((name, entry))
        excludes.update(profile.excludes)

    matched_includes: set[str] = set()
    for profile_name, entry in contributing_includes:
        keys = {key for key in universe if _selector_matches(entry.selector, key)}
        if not keys:
            msg = (
                f"include selector {entry.selector!r} (profile {profile_name!r}) "
                "matches nothing in the staged universe"
            )
            raise ProfilesError(msg)
        matched_includes.update(keys)

    matched_excludes: set[str] = set()
    for selector in excludes:
        keys = {key for key in universe if _selector_matches(selector, key)}
        if not keys:
            msg = f"exclude selector {selector!r} matches nothing in the staged universe"
            raise ProfilesError(msg)
        matched_excludes.update(keys)

    result_keys = matched_includes - matched_excludes
    if not result_keys:
        msg = "selected profiles resolve to zero items"
        raise ProfilesError(msg)

    included: dict[Scope, list[UniverseRef]] = {}
    dropped_counts: dict[Scope, int] = {}
    for key in sorted(result_keys):
        scope = _assign_scope(key, manifest, contributing_includes)
        for ref in universe[key]:
            if scope in bound_scopes:
                included.setdefault(scope, []).append(ref)
            else:
                dropped_counts[scope] = dropped_counts.get(scope, 0) + 1

    if not included:
        msg = "resolved profiles produced zero items for any bound scope; the run would do nothing"
        raise ProfilesError(msg)

    final_included = {
        scope: tuple(sorted(refs, key=lambda r: (r.tool.value, r.dest_relpath.as_posix())))
        for scope, refs in included.items()
    }
    return ResolvedPlan(included=final_included, dropped_counts=dropped_counts)


def filter_plan_to_scope(plan: StagingPlan, kept_dest_relpaths: Iterable[Path]) -> StagingPlan:
    """A new `StagingPlan` holding only the items whose `dest_relpath` is in
    `kept_dest_relpaths`, carrying over `dir_overrides` for kept paths. Pure —
    does not mutate `plan`. This realizes "a run only writes the scopes bound
    for that run": given a `ResolvedPlan`, the caller filters each tool plan
    to the refs of the bound scope before sync.
    """
    kept = set(kept_dest_relpaths)
    items = {relpath: item for relpath, item in plan.items.items() if relpath in kept}
    dir_overrides = {
        relpath: overrides for relpath, overrides in plan.dir_overrides.items() if relpath in kept
    }
    return StagingPlan(items=items, tool=plan.tool, dir_overrides=dir_overrides)
