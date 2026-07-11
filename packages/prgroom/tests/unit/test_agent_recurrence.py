"""Recurrence — the §8.2 derived per-item recurrence signal.

These tests pin the JSON wire shape the fix agent reads: the five fields §8.2
names, and the "omit ``prior_commits`` when empty" rule the spec calls out
inline. The dataclass is derived data (never persisted state), so the only
contract worth pinning is its serialization.
"""

from __future__ import annotations

from prgroom.agent.recurrence import Recurrence


def test_recurrence_serializes_all_fields_when_commits_present() -> None:
    rec = Recurrence(
        reopened=True,
        attempt_count=2,
        prior_disposition="wont_fix",
        prior_commits=("abc123", "def456"),
        first_seen_retry=1,
    )
    # prior_commits is a tuple internally (immutable value type) but serializes as a
    # JSON list for the wire shape.
    assert rec.to_dict() == {
        "reopened": True,
        "attempt_count": 2,
        "prior_disposition": "wont_fix",
        "prior_commits": ["abc123", "def456"],
        "first_seen_retry": 1,
    }
    assert isinstance(rec.to_dict()["prior_commits"], list)


def test_recurrence_is_hashable() -> None:
    # The docstring promises a hashable value type; the tuple field makes it true.
    rec = Recurrence(
        reopened=True,
        attempt_count=2,
        prior_disposition="fixed",
        prior_commits=("abc123",),
        first_seen_retry=1,
    )
    assert hash(rec) == hash(rec)  # does not raise; stable
    assert len({rec, rec}) == 1  # usable as a set member


def test_recurrence_omits_prior_commits_when_empty() -> None:
    # §8.2: prior_commits is "omitted from JSON when empty" — a wont_fix/skipped
    # prior disposition carries no SHAs, so the key must not appear at all (an empty
    # tuple is falsy, so the omit-empty rule still holds).
    rec = Recurrence(
        reopened=False,
        attempt_count=1,
        prior_disposition="skipped",
        prior_commits=(),
        first_seen_retry=3,
    )
    assert "prior_commits" not in rec.to_dict()
    assert rec.to_dict() == {
        "reopened": False,
        "attempt_count": 1,
        "prior_disposition": "skipped",
        "first_seen_retry": 3,
    }
