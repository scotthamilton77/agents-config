"""Lifecycle and item enums for the PR-grooming state schema (§2).

Every value here is part of the on-disk serialization contract (it is written
verbatim into the state JSON), so the canonical strings are pinned at the
serialization boundary by the state round-trip tests, not by literal-equality
assertions at the definition.
"""

from __future__ import annotations

from enum import StrEnum


class PRPhase(StrEnum):
    """What the PR is *waiting on* — not what the CLI is doing (§2)."""

    IDLE = "idle"
    AWAITING_REVIEW = "awaiting-review"
    FIXES_PENDING = "fixes-pending"
    QUIESCED = "quiesced"
    HUMAN_GATED = "human-gated"
    MERGED = "merged"


class ItemKind(StrEnum):
    """The kind of reviewer-produced item (§2)."""

    REVIEW_THREAD = "review_thread"
    REVIEW_SUMMARY = "review_summary"
    ISSUE_COMMENT = "issue_comment"


class DispositionKind(StrEnum):
    """The fix agent's per-item outcome (§2, §5)."""

    FIXED = "fixed"
    ALREADY_ADDRESSED = "already_addressed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"
    WONT_FIX = "wont_fix"
    ESCALATED = "escalated"
    FAILED = "failed"


class GateStrength(StrEnum):
    """The verify tier a fix recommends for its item (fix-verify spec §6.1)."""

    FULL = "full"
    LITE = "lite"

    @classmethod
    def parse(cls, raw: object) -> GateStrength | None:
        """None for anything that is not a canonical gate value (lenient boundary parse).

        ``raw`` is typed ``object`` because this is a contract-boundary parse: the
        value flows from ``FixOutput.from_dict`` (``recommended_gate``), which passes
        through whatever a provider emitted for that JSON field — a canonical string,
        but also ``null`` (Python ``None``), a number, a bool, a list, or a dict. The
        non-str guard makes that leniency explicit: any non-str value returns ``None``,
        so a malformed gate becomes a ``CONTRACT_FIX_AUDIT_FAILED`` violation downstream
        rather than an exception.
        """
        if not isinstance(raw, str):
            return None
        try:
            return cls(raw)
        except ValueError:
            return None


class ReviewerKind(StrEnum):
    """Whether a reviewer is a human or a bot (§2)."""

    HUMAN = "human"
    BOT = "bot"


class ReviewerStatus(StrEnum):
    """A reviewer's engagement status; gates quiescence when required (§2, §4)."""

    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    REVIEW_FOUND = "review_found"
    DECLINED = "declined"
