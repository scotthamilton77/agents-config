"""Consequence heat axis (spec §6.2): `.critical-paths` markers + path-class heuristics.

An estate file matching a `.critical-paths` marker scores maximum consequence
(policy is authoritative); a file matching a path-class heuristic — gate-policy,
security-adjacent, or public-contract — scores high even without a marker; all
others baseline. `.critical-paths` is read from the materialized snapshot dir (the
same file the completion gate reads), never the live checkout. The tests pin the
*invariants* — marker beats heuristic beats baseline, everything in 0-1 — not the
tunable heuristic score.
"""

from __future__ import annotations

from pathlib import Path

from vizsuite.extract.consequence import consequence


def test_consequence_scores_markers_max_and_heuristics_high(tmp_path: Path) -> None:
    # `.critical-paths` lives in the snapshot dir (a tracked file in the archive).
    (tmp_path / ".critical-paths").write_text("packages/**\nMakefile\n", encoding="utf-8")
    estate = {
        "packages/vizsuite/cli.py": "s1",  # matches the packages/** marker → max
        "Makefile": "s2",  # matches the Makefile marker → max
        "src/auth/token.py": "s3",  # security-adjacent heuristic, no marker → high
        ".critical-paths": "s4",  # gate-policy file heuristic → high
        "docs/notes.md": "s5",  # neither marker nor heuristic → baseline
    }

    scores = consequence(estate, tmp_path)

    assert scores["packages/vizsuite/cli.py"] == 1.0  # explicit policy marker
    assert scores["Makefile"] == 1.0
    assert scores["docs/notes.md"] == 0.0  # plain file → baseline
    # heuristics score high (above baseline) without any marker, but below the
    # authoritative explicit marker.
    assert scores["docs/notes.md"] < scores["src/auth/token.py"] < 1.0
    assert scores[".critical-paths"] > 0.0
    assert all(0.0 <= value <= 1.0 for value in scores.values())  # 0-1 range


def test_consequence_without_a_critical_paths_file_uses_heuristics_only(tmp_path: Path) -> None:
    # No `.critical-paths` in the snapshot → only the path-class heuristics contribute.
    estate = {"src/security/vault.py": "s1", "lib/util.py": "s2"}

    scores = consequence(estate, tmp_path)

    assert scores["src/security/vault.py"] > 0.0  # security heuristic still fires
    assert scores["lib/util.py"] == 0.0  # nothing matches → baseline
