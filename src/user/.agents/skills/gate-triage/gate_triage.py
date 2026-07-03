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


def _rel_to_marker(marker_folder: str, path: str) -> str | None:
    """Path relative to the marker's folder, or None if outside its subtree."""
    if marker_folder == "":
        return path
    prefix = marker_folder + "/"
    return path[len(prefix):] if path.startswith(prefix) else None


def _match_markers(candidate: str, markers: tuple[CriticalMarker, ...]) -> tuple[str, str] | None:
    """Return (marker_label, matched_pattern) for the first matching marker, else None."""
    for m in markers:
        rel = _rel_to_marker(m.folder, candidate)
        if rel is None:
            continue
        if m.spec.match_file(rel):
            label = (m.folder + "/.critical-paths").lstrip("/") or ".critical-paths"
            matched = next((p.pattern for p in m.spec.patterns
                            if p.include and p.match_file(rel)), "*")
            return (label, matched)
    return None


def critical_hits(files: tuple[ChangedFile, ...],
                  markers: tuple[CriticalMarker, ...]) -> tuple[CriticalHit, ...]:
    hits: list[CriticalHit] = []
    for f in files:
        candidates = [f.path] + ([f.old_path] if f.status == "R" and f.old_path else [])
        for cand in candidates:
            if Path(cand).name in POLICY_INPUT_BASENAMES:  # §5 hardcoded policy inputs
                hits.append(CriticalHit(path=cand, marker=Path(cand).name, pattern="<policy-input>"))
                break
            found = _match_markers(cand, markers)
            if found:
                hits.append(CriticalHit(path=f.path, marker=found[0], pattern=found[1]))
                break
    return tuple(hits)


def _subsystems(files: tuple[ChangedFile, ...]) -> int:
    """Distinct top-level dir touched; repo-root files and dotfile dirs each count once."""
    tops = set()
    for f in files:
        parts = Path(f.path).parts
        tops.add(parts[0] if len(parts) > 1 else "<root>")
    return len(tops)


def compute_tier(facts: DiffFacts, hits: tuple[CriticalHit, ...], config: TriageConfig) -> Tier:
    if hits:
        return Tier.HEAVY  # critical hit — unconditional, overrides SKIP
    files = facts.files
    loc = sum(f.loc_changed for f in files)
    if (len(files) >= config.heavy_min_files
            or loc >= config.heavy_min_loc
            or _subsystems(files) >= config.heavy_min_subsystems
            or facts.new_deps):
        return Tier.HEAVY
    if len(files) == 1 and loc <= config.trivial_max_loc:
        return Tier.SKIP
    return Tier.SERIAL


_SCALE_BUCKETS = {
    "small": ScaleHint(finder_dimensions=3, refuters=2, synthesis_effort="high"),
    "medium": ScaleHint(finder_dimensions=4, refuters=2, synthesis_effort="high"),
    "large": ScaleHint(finder_dimensions=6, refuters=3, synthesis_effort="xhigh"),
}


def compute_scale_hint(facts: DiffFacts) -> ScaleHint:
    """Size the HEAVY fleet from the diff. Bucket = count of HEAVY quant thresholds
    crossed — {files ≥ heavy_min_files, loc ≥ heavy_min_loc,
    subsystems ≥ heavy_min_subsystems} — evaluated against default thresholds, with
    new_deps forcing 'large':

        0 crossed              → small  → (3, 2, "high")
        exactly 1 crossed      → medium → (4, 2, "high")
        2+ crossed OR new_deps → large  → (6, 3, "xhigh")

    Monotone by construction (spec §9.17): each threshold is a ≥ step function, so
    growing any dimension can only cross MORE thresholds, never fewer, and new_deps
    only ever escalates; the bucket→fleet map is non-decreasing field-by-field
    (small ≤ medium ≤ large). Hence a strictly larger diff never yields a smaller
    fleet. Uses default thresholds, not loaded config — scale is a coarse advisory
    for the workflow, deliberately independent of per-repo tier tuning."""
    config = TriageConfig()
    loc = sum(f.loc_changed for f in facts.files)
    crossed = sum((
        len(facts.files) >= config.heavy_min_files,
        loc >= config.heavy_min_loc,
        _subsystems(facts.files) >= config.heavy_min_subsystems,
    ))
    if facts.new_deps or crossed >= 2:
        return _SCALE_BUCKETS["large"]
    if crossed == 1:
        return _SCALE_BUCKETS["medium"]
    return _SCALE_BUCKETS["small"]


def triage(facts: DiffFacts, markers: tuple[CriticalMarker, ...],
           config: TriageConfig) -> TriageResult:
    """Pure composition: critical_hits → compute_tier → compute_scale_hint → assemble."""
    hits = critical_hits(facts.files, markers)
    tier = compute_tier(facts, hits, config)
    scale = compute_scale_hint(facts)
    hit_strings = tuple(f"{h.path} ← {h.marker}:{h.pattern}" for h in hits)
    file_classes = tuple(sorted({classify_file(f.path).value for f in facts.files}))
    return TriageResult(
        tier_floor=tier,
        files=len(facts.files),
        loc_changed=sum(f.loc_changed for f in facts.files),
        subsystems=_subsystems(facts.files),
        new_deps=facts.new_deps,
        file_classes=file_classes,
        critical_path_hits=hit_strings,
        scale_hint=scale,
    )


def _result_to_json(result: TriageResult) -> str:
    """Serialize a TriageResult to the spec §4.2 JSON payload."""
    payload = {
        "tier_floor": result.tier_floor.value,
        "files": result.files,
        "loc_changed": result.loc_changed,
        "subsystems": result.subsystems,
        "new_deps": result.new_deps,
        "file_classes": list(result.file_classes),
        "critical_path_hits": list(result.critical_path_hits),
        "scale_hint": {
            "finder_dimensions": result.scale_hint.finder_dimensions,
            "refuters": result.scale_hint.refuters,
            "synthesis_effort": result.scale_hint.synthesis_effort,
        },
    }
    return json.dumps(payload, indent=2)


def _default_base_ref(repo_root: Path) -> str:
    """Boundary: the repo's default branch (origin/HEAD target), or 'main' on failure."""
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_root, capture_output=True, text=True, check=True)
        return out.stdout.strip().removeprefix("origin/") or "main"
    except (subprocess.CalledProcessError, OSError):
        return "main"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute the completion-gate tier floor.")
    parser.add_argument("--repo-root", default=".", help="repo root (default: cwd)")
    parser.add_argument("--base-ref", default=None,
                        help="base ref for the diff (default: repo default branch)")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    base_ref = args.base_ref or _default_base_ref(repo_root)
    config = load_config(repo_root)
    facts = collect_diff(repo_root, base_ref)
    markers = load_markers(repo_root)
    print(_result_to_json(triage(facts, markers, config)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
