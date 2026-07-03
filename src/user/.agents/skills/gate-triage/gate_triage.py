# /// script
# requires-python = ">=3.11"
# dependencies = ["pathspec>=0.12"]
# ///
"""gate-triage: compute the completion-gate tier floor (SKIP/SERIAL/HEAVY).

Pure core over value types; git + filesystem confined to boundary functions
(collect_diff, load_markers, load_config). Invoked by the completion-gate rule:
  uv run gate_triage.py --repo-root <root> --base-ref <default-branch>
Emits a JSON triage payload on stdout (spec §4.2)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pathspec

DEPENDENCY_FILES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "requirements.txt", "poetry.lock",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
})

# Gate policy inputs — always HEAVY, independent of any marker pattern (spec §5).
# A change to the gate's own policy is never evaluated under the policy it carries.
POLICY_INPUT_BASENAMES = frozenset({"project-config.toml", ".critical-paths"})


class Tier(str, Enum):
    SKIP = "SKIP"
    SERIAL = "SERIAL"
    HEAVY = "HEAVY"


class FileClass(str, Enum):
    DOCS = "docs"
    CONFIG = "config"
    CODE = "code"


@dataclass(frozen=True)
class ChangedFile:
    path: str
    old_path: str | None
    loc_changed: int
    status: str  # A/M/D/R; untracked (??) → "A"


@dataclass(frozen=True)
class DiffFacts:
    files: tuple[ChangedFile, ...]
    new_deps: bool
    base_ref: str


@dataclass(frozen=True)
class TriageConfig:
    heavy_min_files: int = 8
    heavy_min_loc: int = 400
    heavy_min_subsystems: int = 3
    trivial_max_loc: int = 3  # SKIP ceiling; hard-capped at 20 on load


@dataclass(frozen=True)
class CriticalMarker:
    folder: str  # repo-relative POSIX dir the marker lives in ("" == repo root)
    spec: pathspec.PathSpec


@dataclass(frozen=True)
class CriticalHit:
    path: str
    marker: str   # "<folder>/.critical-paths" or "<policy-input>"
    pattern: str


@dataclass(frozen=True)
class ScaleHint:
    finder_dimensions: int
    refuters: int
    synthesis_effort: str


@dataclass(frozen=True)
class TriageResult:
    tier_floor: Tier
    files: int
    loc_changed: int
    subsystems: int
    new_deps: bool
    file_classes: tuple[str, ...]
    critical_path_hits: tuple[str, ...]
    scale_hint: ScaleHint


def load_config(repo_root: Path) -> TriageConfig:
    """Boundary: read [completion-gate] from project-config.toml. Config decides
    whether review runs, so it is validated, not merely parsed. ANY failure,
    absent section, or absent file → defaults. Never fails open to 'no gate'."""
    default = TriageConfig()
    path = repo_root / "project-config.toml"
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return default
    section = data.get("completion-gate")
    if not isinstance(section, dict):
        return default
    fields = {f: getattr(default, f) for f in
              ("heavy_min_files", "heavy_min_loc", "heavy_min_subsystems", "trivial_max_loc")}
    for key, val in section.items():
        if key not in fields:
            continue  # unknown keys ignored
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            return default  # bad type/negative → fail closed
        fields[key] = val
    fields["trivial_max_loc"] = min(fields["trivial_max_loc"], 20)  # hard cap
    if fields["heavy_min_loc"] < fields["trivial_max_loc"]:
        return default  # nonsensical ordering → fail closed
    return TriageConfig(**fields)


_DOCS_EXT = {".md", ".rst", ".txt", ".adoc"}
_CONFIG_EXT = {".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg"}


def classify_file(path: str) -> FileClass:
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    if suffix in _DOCS_EXT:
        return FileClass.DOCS
    if suffix in _CONFIG_EXT:
        return FileClass.CONFIG
    if suffix == "" and name.startswith("."):
        return FileClass.CONFIG  # extensionless dotfile
    return FileClass.CODE  # unknown/missing ext → CODE
