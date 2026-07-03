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
