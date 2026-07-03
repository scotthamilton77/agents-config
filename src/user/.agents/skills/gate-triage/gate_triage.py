# /// script
# requires-python = ">=3.11"
# dependencies = ["pathspec>=0.12"]
# ///
"""gate-triage: compute the completion-gate tier floor (SKIP/SERIAL/HEAVY).

Pure core over value types; git + filesystem confined to boundary functions
(collect_diff, load_markers, load_config). Invoked by the completion-gate rule:
  uv run gate_triage.py --repo-root <root> --base-ref <default-branch>
Emits a JSON triage payload on stdout."""
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

# Gate policy inputs — always HEAVY, independent of any marker pattern.
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
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
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
        # Rename (R) and copy (C) both carry an old_path; evaluate both endpoints
        # so a critical-path source is never missed. Adding old_path only ever
        # adds hits (more HEAVY) — the fail-closed-safe direction.
        candidates = [f.path] + ([f.old_path] if f.status in ("R", "C") and f.old_path else [])
        for cand in candidates:
            if Path(cand).name in POLICY_INPUT_BASENAMES:  # hardcoded policy inputs
                # Record the current path (f.path), consistent with the marker
                # branch — when matched via old_path (rename/copy) that old path
                # may no longer exist. The matched policy-input name stays in
                # `marker` for provenance.
                hits.append(CriticalHit(path=f.path, marker=Path(cand).name, pattern="<policy-input>"))
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

    Monotone by construction: each threshold is a ≥ step function, so
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
    """Serialize a TriageResult to the JSON payload."""
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
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _run_git(repo_root: Path, *args: str) -> str:
    """Boundary: run a git command in repo_root and return stdout (raises on error)."""
    return subprocess.run(["git", *args], cwd=repo_root,
                          capture_output=True, text=True, check=True).stdout


def _default_base_ref(repo_root: Path) -> str:
    """Boundary: the repo's default branch (origin/HEAD target), or 'main' on failure."""
    try:
        ref = _run_git(repo_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        return ref or "main"
    except (subprocess.CalledProcessError, OSError):
        return "main"


def _merge_base(repo_root: Path, base_ref: str) -> str:
    """merge-base of base_ref and HEAD; falls back to base_ref if there is none."""
    try:
        return _run_git(repo_root, "merge-base", base_ref, "HEAD").strip()
    except subprocess.CalledProcessError:
        return base_ref


def _parse_name_status_z(text: str) -> dict[str, tuple[str, str | None]]:
    """Parse `git diff --name-status -z` → {new_path: (status_letter, old_path)}.
    Layout: 'M\\0path\\0' for A/M/D; 'R066\\0old\\0new\\0' for R/C (rename/copy)."""
    tokens = text.split("\0")
    out: dict[str, tuple[str, str | None]] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "":
            i += 1
            continue
        letter = tok[0]
        if letter in ("R", "C"):
            out[tokens[i + 2]] = (letter, tokens[i + 1])
            i += 3
        else:
            out[tokens[i + 1]] = (letter, None)
            i += 2
    return out


def _parse_numstat_z(text: str) -> dict[str, int]:
    """Parse `git diff --numstat -z` → {new_path: added + deleted}. Binary '-' → 0.
    Layout: '1\\t0\\tpath\\0'; renames: '1\\t0\\t\\0old\\0new\\0'."""
    tokens = text.split("\0")
    out: dict[str, int] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "":
            i += 1
            continue
        added_s, deleted_s, rest = tok.split("\t", 2)
        loc = (0 if added_s == "-" else int(added_s)) + (0 if deleted_s == "-" else int(deleted_s))
        if rest == "":  # rename: next two tokens are old, new
            out[tokens[i + 2]] = loc
            i += 3
        else:
            out[rest] = loc
            i += 1
    return out


def _line_count(path: Path) -> int:
    try:
        return len(path.read_bytes().splitlines())  # bytes: never decodes, binary-safe
    except OSError:
        return 0


def _untracked_files(repo_root: Path) -> list[tuple[str, int]]:
    """(path, full line count) for every untracked file (git status '?? ' entries)."""
    out = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    result: list[tuple[str, int]] = []
    for record in out.split("\0"):
        if record.startswith("?? "):
            path = record[3:]
            result.append((path, _line_count(repo_root / path)))
    return result


def collect_diff(repo_root: Path, base_ref: str) -> DiffFacts:
    """Boundary: the candidate change at gate time — the net diff from the
    merge-base of base_ref..HEAD to the working tree (committed + staged +
    unstaged), plus untracked files. A single `git diff <merge-base>` yields the
    net state deduped by path with rename provenance computed across the whole
    span, so a committed rename followed by an unstaged edit keeps its old_path
    without manual evidence-merging."""
    merge_base = _merge_base(repo_root, base_ref)
    statuses = _parse_name_status_z(
        _run_git(repo_root, "diff", "-M", "--name-status", "-z", merge_base))
    locs = _parse_numstat_z(
        _run_git(repo_root, "diff", "-M", "--numstat", "-z", merge_base))
    files: list[ChangedFile] = [
        ChangedFile(path=path, old_path=old_path, loc_changed=locs.get(path, 0), status=letter)
        for path, (letter, old_path) in statuses.items()
    ]
    for path, loc in _untracked_files(repo_root):
        if path not in statuses:  # untracked can't overlap tracked; guard anyway
            files.append(ChangedFile(path=path, old_path=None, loc_changed=loc, status="A"))
    new_deps = any(Path(f.path).name in DEPENDENCY_FILES for f in files)
    return DiffFacts(files=tuple(files), new_deps=new_deps, base_ref=base_ref)


def load_markers(repo_root: Path) -> tuple[CriticalMarker, ...]:
    """Boundary: discover every .critical-paths file; anchor its patterns to its
    own folder (repo-root marker → folder "")."""
    markers: list[CriticalMarker] = []
    for path in sorted(repo_root.rglob(".critical-paths")):
        if ".git" in path.parts:
            continue
        rel_dir = path.parent.relative_to(repo_root).as_posix()
        folder = "" if rel_dir == "." else rel_dir
        spec = pathspec.PathSpec.from_lines("gitignore", path.read_text(errors="replace").splitlines())
        markers.append(CriticalMarker(folder=folder, spec=spec))
    return tuple(markers)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute the completion-gate tier floor.")
    parser.add_argument("--repo-root", default=".", help="repo root (default: cwd)")
    parser.add_argument("--base-ref", default=None,
                        help="base ref for the diff (default: repo default branch)")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    base_ref = args.base_ref or _default_base_ref(repo_root)
    try:
        config = load_config(repo_root)
        facts = collect_diff(repo_root, base_ref)
        markers = load_markers(repo_root)
        print(_result_to_json(triage(facts, markers, config)))
    except Exception as exc:
        # Fail closed on ANY unexpected error, not just the git boundary: an
        # unresolvable --base-ref or missing git (CalledProcessError/OSError),
        # malformed git output (ValueError/IndexError from the -z parsers), or a
        # bad marker pattern (pathspec error). The documented contract is a
        # non-zero exit with a one-line diagnostic, never a traceback; a non-zero
        # exit routes the caller to SERIAL — never SKIP (see this skill's
        # SKILL.md exit-code table). KeyboardInterrupt/SystemExit are
        # BaseException and still propagate, so argparse's bad-arg exit is
        # unaffected.
        detail = getattr(exc, "stderr", None) or str(exc)
        print(f"gate-triage: failed to compute tier floor (base-ref {base_ref!r}): "
              f"{detail.strip()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
