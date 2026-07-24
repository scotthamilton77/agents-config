"""The deploy-time conflict audit (S3-D, charter D16 / AC2)."""

from __future__ import annotations

from installer.core.conflict_audit import conflict_violations


def test_no_claimants_is_green() -> None:
    assert conflict_violations([]) == []


def test_same_key_distinct_values_conflicts_and_names_both() -> None:
    violations = conflict_violations(
        [
            ("rules/a.md", {"pr-review-medium": "comments"}),
            ("rules/b.md", {"pr-review-medium": "verdict-artifact"}),
        ]
    )
    assert len(violations) == 1
    msg = violations[0]
    assert "pr-review-medium" in msg
    assert "comments" in msg and "verdict-artifact" in msg
    assert "rules/a.md" in msg and "rules/b.md" in msg


def test_same_key_same_value_does_not_conflict() -> None:
    violations = conflict_violations(
        [
            ("rules/a.md", {"k": "v"}),
            ("rules/b.md", {"k": "v"}),
        ]
    )
    assert violations == []


def test_artifact_without_claims_contributes_nothing() -> None:
    violations = conflict_violations(
        [
            ("rules/a.md", {"k": "v"}),
            ("rules/b.md", {}),
        ]
    )
    assert violations == []


def test_distinct_keys_never_conflict() -> None:
    violations = conflict_violations(
        [
            ("rules/a.md", {"k1": "v1"}),
            ("rules/b.md", {"k2": "v2"}),
        ]
    )
    assert violations == []


def test_message_is_deterministic_across_ordering() -> None:
    forward = conflict_violations(
        [("a", {"k": "x"}), ("b", {"k": "y"})],
    )
    reverse = conflict_violations(
        [("b", {"k": "y"}), ("a", {"k": "x"})],
    )
    assert forward == reverse
