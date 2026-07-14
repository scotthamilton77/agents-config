"""Consequence heat axis — `.critical-paths` markers + path-class heuristics (spec §6.2).

Consequence is "load-bearing by policy", 0-1 per estate file. It is seeded from the
repo's `.critical-paths` markers — compiled with the same gitignore semantics the
completion gate's triage uses, so the two share one source of truth — plus
path-class heuristics (gate-policy files, security-adjacent paths, public
contracts) that score a file high by class even absent an explicit marker. Pure
compute: the marker lines are read from the materialized snapshot by the caller
(`adapters/critical_paths.read_critical_paths`), mirroring how `complexity`
receives already-parsed `scc_records` rather than scanning itself. The
cross-axis weighted average of the three axes lives in `.2.2`, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

from pathspec import GitIgnoreSpec

from vizsuite.adapters.critical_paths import CRITICAL_PATHS_FILE

# Path-class heuristics (§6.2): a file is load-bearing by class even without an
# explicit `.critical-paths` marker. Tunable; the tested invariant is that a
# gate-policy / security / public-contract path scores above baseline, below an
# explicit marker.
_SECURITY_MARKERS = ("auth", "security", "credential", "secret", "token", "crypto", "login")
_GATE_POLICY_NAMES = (CRITICAL_PATHS_FILE, "project-config.toml")
_PUBLIC_CONTRACT_NAMES = ("__init__.py",)

CONSEQUENCE_MARKED = 1.0  # matches an explicit `.critical-paths` policy marker
CONSEQUENCE_HEURISTIC = 0.75  # matches a path-class heuristic (no explicit marker)
CONSEQUENCE_BASELINE = 0.0  # neither policy nor class → not load-bearing by policy


def _heuristic_hit(path: str) -> bool:
    """A path-class heuristic match: gate-policy, security-adjacent, or public-contract.

    Security markers match a whole path *segment* — a directory name or the
    filename stem — never an arbitrary substring, so `auth/`, `token.py`, and
    `security/` score while incidental substrings (`tokenizer.py`, `author.py`) do
    not spuriously inflate the consequence axis.
    """
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    directories = lowered.split("/")[:-1]
    stem = name.split(".", 1)[0]
    return (
        name in _GATE_POLICY_NAMES
        or name in _PUBLIC_CONTRACT_NAMES
        or stem in _SECURITY_MARKERS
        or any(directory in _SECURITY_MARKERS for directory in directories)
    )


def consequence(estate: dict[str, str], critical_paths_lines: Sequence[str]) -> dict[str, float]:
    """Per-file 0-1 consequence over the estate: `.critical-paths` markers + heuristics.

    An estate file matching a marker scores `CONSEQUENCE_MARKED` (policy is
    authoritative); a path-class heuristic match scores `CONSEQUENCE_HEURISTIC`; all
    others `CONSEQUENCE_BASELINE`. The whole estate is scored, so every scene node
    has a consequence value in `.2.2`.
    """
    spec = GitIgnoreSpec.from_lines(critical_paths_lines)
    heat: dict[str, float] = {}
    for path in estate:
        if spec.match_file(path):
            heat[path] = CONSEQUENCE_MARKED
        elif _heuristic_hit(path):
            heat[path] = CONSEQUENCE_HEURISTIC
        else:
            heat[path] = CONSEQUENCE_BASELINE
    return heat
