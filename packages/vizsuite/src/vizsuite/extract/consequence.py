"""Consequence heat axis — `.critical-paths` markers + path-class heuristics (spec §6.2).

Consequence is "load-bearing by policy", 0-1 per estate file. It is seeded from the
repo's `.critical-paths` markers — read from the *materialized snapshot* with the
same gitignore semantics the completion gate's triage uses, so the two share one
source of truth — plus path-class heuristics (gate-policy files, security-adjacent
paths, public contracts) that score a file high by class even absent an explicit
marker. The cross-axis weighted average of the three axes lives in `.2.2`, not here.
"""

from __future__ import annotations

from pathlib import Path

from pathspec import GitIgnoreSpec

_CRITICAL_PATHS_FILE = ".critical-paths"

# Path-class heuristics (§6.2): a file is load-bearing by class even without an
# explicit `.critical-paths` marker. Tunable; the tested invariant is that a
# gate-policy / security / public-contract path scores above baseline, below an
# explicit marker.
_SECURITY_MARKERS = ("auth", "security", "credential", "secret", "token", "crypto", "login")
_GATE_POLICY_NAMES = (".critical-paths", "project-config.toml")
_PUBLIC_CONTRACT_NAMES = ("__init__.py",)

CONSEQUENCE_MARKED = 1.0  # matches an explicit `.critical-paths` policy marker
CONSEQUENCE_HEURISTIC = 0.75  # matches a path-class heuristic (no explicit marker)
CONSEQUENCE_BASELINE = 0.0  # neither policy nor class → not load-bearing by policy


def _load_critical_paths(snapshot_dir: Path) -> GitIgnoreSpec:
    """Compile the snapshot's `.critical-paths` into a gitignore spec (empty if absent).

    Uses the same gitignore semantics the completion gate's triage applies to this
    very file, so consequence and the gate agree on what is load-bearing by policy.
    """
    marker_file = snapshot_dir / _CRITICAL_PATHS_FILE
    lines = marker_file.read_text(encoding="utf-8").splitlines() if marker_file.is_file() else []
    return GitIgnoreSpec.from_lines(lines)


def _heuristic_hit(path: str) -> bool:
    """A path-class heuristic match: gate-policy, security-adjacent, or public-contract."""
    name = path.rsplit("/", 1)[-1]
    lowered = path.lower()
    return (
        name in _GATE_POLICY_NAMES
        or name in _PUBLIC_CONTRACT_NAMES
        or any(marker in lowered for marker in _SECURITY_MARKERS)
    )


def consequence(estate: dict[str, str], snapshot_dir: Path) -> dict[str, float]:
    """Per-file 0-1 consequence over the estate: `.critical-paths` markers + heuristics.

    An estate file matching a marker scores `CONSEQUENCE_MARKED` (policy is
    authoritative); a path-class heuristic match scores `CONSEQUENCE_HEURISTIC`; all
    others `CONSEQUENCE_BASELINE`. The whole estate is scored, so every scene node
    has a consequence value in `.2.2`.
    """
    spec = _load_critical_paths(snapshot_dir)
    heat: dict[str, float] = {}
    for path in estate:
        if spec.match_file(path):
            heat[path] = CONSEQUENCE_MARKED
        elif _heuristic_hit(path):
            heat[path] = CONSEQUENCE_HEURISTIC
        else:
            heat[path] = CONSEQUENCE_BASELINE
    return heat
