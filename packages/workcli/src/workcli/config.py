"""Track-layer config: discovery, parsing, validation (track spec §3).

Loaded lazily -- only when a track-layer surface (a §4 flag, verb, or gate)
needs it -- so pre-existing verbs never trigger a load. Every failure is the
single typed `E_NOT_CONFIGURED`, its message naming the specific parse or
validation problem; `detail.reason` distinguishes "not-found" from "invalid"
so the create gate can stay fail-safe (spec §3: a broken config fails only
the track layer, never an existing verb). Parse and validate once here;
everything inward trusts the frozen dataclass.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from workcli.envelope import ErrorCode, WorkError

CONFIG_FILENAME = "project-config.toml"

Reason = Literal["not-found", "invalid"]


@dataclass(frozen=True)
class TrackLayerConfig:
    names: tuple[str, ...]
    organizing_only: tuple[str, ...]
    enforcement: str  # "advisory" | "required"; omitted key parses to "advisory"
    milestone_wip_cap: (
        int | None
    )  # None: [operating-model] absent/key omitted -> lint skips WIP check
    wip_exempt_milestones: tuple[str, ...]
    extraction_max_track_backlog: (
        int | None
    )  # None: [extraction.pressure] absent/key omitted -> backlog pressure never fires
    extraction_external_consumer_tracks: tuple[str, ...]
    extraction_independent_release_tracks: tuple[str, ...]
    extraction_max_cross_track_edges: (
        int | None
    )  # None: [extraction.eligibility] absent/key omitted -> eligibility never proven (fail-safe)


def _not_configured(problem: str, reason: Reason) -> WorkError:
    return WorkError(
        ErrorCode.NOT_CONFIGURED,
        f"track layer not configured: {problem}",
        detail={"reason": reason},
    )


def _find_config(start_dir: Path) -> Path | None:
    """Upward search from `start_dir`, bounded by the enclosing git root (spec §3).

    The git root is located FIRST: with no git root on the walk -- the working
    directory lies outside any repo -- the search finds nothing, even when a
    project-config.toml exists in some parent directory (adopting an unrelated
    parent config would be the fail-unsafe path). The directory containing
    `.git` (a dir, or a file in linked worktrees) is the last one searched.
    """
    current = start_dir.resolve()
    lineage = (current, *current.parents)
    git_root = next(
        (candidate_dir for candidate_dir in lineage if (candidate_dir / ".git").exists()),
        None,
    )
    if git_root is None:
        return None
    for candidate_dir in lineage:
        candidate = candidate_dir / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
        if candidate_dir == git_root:
            break
    return None


def load_config(start_dir: Path, explicit_path: str | None = None) -> TrackLayerConfig:
    """Resolve, parse, and validate `[tracks]`/`[operating-model]`.

    `explicit_path` (the `--config` flag) overrides the search in every case.
    """
    if explicit_path is not None:
        config_path = Path(explicit_path)
        if not config_path.is_file():
            raise _not_configured(f"--config path not found: {explicit_path}", "not-found")
    else:
        found = _find_config(start_dir)
        if found is None:
            raise _not_configured(
                f"no {CONFIG_FILENAME} between {start_dir} and the enclosing git root",
                "not-found",
            )
        config_path = found
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as read_error:
        raise _not_configured(f"cannot read {config_path}: {read_error}", "invalid") from read_error
    except UnicodeDecodeError as decode_error:
        raise _not_configured(
            f"{config_path} is not valid UTF-8: {decode_error}", "invalid"
        ) from decode_error
    except tomllib.TOMLDecodeError as parse_error:
        raise _not_configured(
            f"malformed TOML in {config_path}: {parse_error}", "invalid"
        ) from parse_error
    return _validate(raw, config_path)


def _string_tuple(value: object, where: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise _not_configured(f"{where} must be a list of strings in {path}", "invalid")
    return tuple(value)


def _validate(raw: dict[str, object], path: Path) -> TrackLayerConfig:
    tracks = raw.get("tracks")
    if not isinstance(tracks, dict):
        raise _not_configured(f"no [tracks] table in {path}", "not-found")
    names = _string_tuple(tracks.get("names", []), "[tracks].names", path)
    if not names:
        raise _not_configured(f"[tracks].names is empty or missing in {path}", "invalid")
    organizing_only = _string_tuple(
        tracks.get("organizing-only", []), "[tracks].organizing-only", path
    )
    unknown_organizing = [name for name in organizing_only if name not in names]
    if unknown_organizing:
        raise _not_configured(
            f"[tracks].organizing-only entries not in names: {unknown_organizing} in {path}",
            "invalid",
        )
    enforcement = tracks.get("enforcement", "advisory")
    if enforcement not in ("advisory", "required"):
        raise _not_configured(
            f"[tracks].enforcement must be 'advisory' or 'required', got {enforcement!r} in {path}",
            "invalid",
        )

    operating = raw.get("operating-model")
    if operating is not None and not isinstance(operating, dict):
        # A non-table [operating-model] is malformed config, not an omitted
        # optional section -- silently ignoring it would silently disable
        # the lint WIP check.
        raise _not_configured(f"[operating-model] must be a table in {path}", "invalid")
    operating_table = operating if isinstance(operating, dict) else {}
    cap = operating_table.get("milestone-wip-cap")
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int)):
        raise _not_configured(
            f"[operating-model].milestone-wip-cap must be an integer in {path}", "invalid"
        )
    exempt = _string_tuple(
        operating_table.get("wip-exempt-milestones", []),
        "[operating-model].wip-exempt-milestones",
        path,
    )
    extraction = raw.get("extraction")
    if extraction is not None and not isinstance(extraction, dict):
        raise _not_configured(f"[extraction] must be a table in {path}", "invalid")
    extraction_table = extraction if isinstance(extraction, dict) else {}

    pressure = extraction_table.get("pressure")
    if pressure is not None and not isinstance(pressure, dict):
        raise _not_configured(f"[extraction.pressure] must be a table in {path}", "invalid")
    pressure_table = pressure if isinstance(pressure, dict) else {}
    max_track_backlog = pressure_table.get("max-track-backlog")
    if max_track_backlog is not None and (
        isinstance(max_track_backlog, bool) or not isinstance(max_track_backlog, int)
    ):
        raise _not_configured(
            f"[extraction.pressure].max-track-backlog must be an integer in {path}", "invalid"
        )
    external_consumer_tracks = _string_tuple(
        pressure_table.get("external-consumer-tracks", []),
        "[extraction.pressure].external-consumer-tracks",
        path,
    )
    independent_release_tracks = _string_tuple(
        pressure_table.get("independent-release-tracks", []),
        "[extraction.pressure].independent-release-tracks",
        path,
    )

    eligibility = extraction_table.get("eligibility")
    if eligibility is not None and not isinstance(eligibility, dict):
        raise _not_configured(f"[extraction.eligibility] must be a table in {path}", "invalid")
    eligibility_table = eligibility if isinstance(eligibility, dict) else {}
    max_cross_track_edges = eligibility_table.get("max-cross-track-edges")
    if max_cross_track_edges is not None and (
        isinstance(max_cross_track_edges, bool) or not isinstance(max_cross_track_edges, int)
    ):
        raise _not_configured(
            f"[extraction.eligibility].max-cross-track-edges must be an integer in {path}",
            "invalid",
        )

    return TrackLayerConfig(
        names=names,
        organizing_only=organizing_only,
        enforcement=str(enforcement),
        milestone_wip_cap=cap,
        wip_exempt_milestones=exempt,
        extraction_max_track_backlog=max_track_backlog,
        extraction_external_consumer_tracks=external_consumer_tracks,
        extraction_independent_release_tracks=independent_release_tracks,
        extraction_max_cross_track_edges=max_cross_track_edges,
    )
