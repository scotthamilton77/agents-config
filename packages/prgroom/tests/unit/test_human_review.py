"""Tests for the §4.4/§4.6 human-review merge-constraint derivation.

The precedence (label > approval > None) and the load-bearing bot-filter are pinned
here against the pure :func:`derive_human_review`. The thin gh fetch is exercised
through a tiny structural ``GhClient`` fake (the two REST GETs), so the derivation
logic stays free of any subprocess.
"""

from __future__ import annotations

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.human_review import (
    derive_human_review,
    fetch_human_review_inputs,
)
from prgroom.prsession.pr_ref import PRRef


def _review(login: str, state: str = "APPROVED", *, type_: str = "User") -> dict:
    return {"state": state, "user": {"login": login, "type": type_}}


def test_unconstrained_pr_is_satisfied_with_no_label() -> None:
    hr = derive_human_review(labels=[], reviews=[])
    assert hr.required is False
    assert hr.satisfied_by is None
    assert hr.satisfied is True  # not required -> satisfied


def test_required_label_unsatisfied_without_approval() -> None:
    hr = derive_human_review(labels=["human-review-required"], reviews=[])
    assert hr.required is True
    assert hr.satisfied_by is None
    assert hr.satisfied is False


def test_label_satisfaction_takes_precedence_over_approval() -> None:
    hr = derive_human_review(
        labels=["human-review-required", "human-approved"],
        reviews=[_review("alice")],
    )
    assert hr.satisfied_by == "label"


def test_label_match_is_case_insensitive() -> None:
    hr = derive_human_review(labels=["Human-Review-Required", "HUMAN-APPROVED"], reviews=[])
    assert hr.required is True
    assert hr.satisfied_by == "label"


def test_first_non_bot_approval_satisfies() -> None:
    hr = derive_human_review(labels=["human-review-required"], reviews=[_review("alice")])
    assert hr.satisfied_by == "approval:alice"
    assert hr.satisfied is True


def test_bot_approval_does_not_satisfy() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot")],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].counted is False
    assert hr.candidates_seen[0].reason == "bot"


def test_bot_detected_by_login_suffix_when_type_absent() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[{"state": "APPROVED", "user": {"login": "dependabot[bot]"}}],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].reason == "bot"


def test_empty_login_approval_does_not_satisfy() -> None:
    # An anonymous/loginless APPROVED review cannot satisfy human review — it must
    # NOT yield satisfied_by="approval:" (an empty login). It is recorded as a
    # non-counted candidate with reason "no-login" for operator debuggability.
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("", type_="User")],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].login == ""
    assert hr.candidates_seen[0].counted is False
    assert hr.candidates_seen[0].reason == "no-login"


def test_missing_user_approval_does_not_satisfy() -> None:
    # No `user` object at all → no login → not a valid approver.
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[{"state": "APPROVED"}],
    )
    assert hr.satisfied_by is None
    assert hr.candidates_seen[0].counted is False
    assert hr.candidates_seen[0].reason == "no-login"


def test_loginless_then_human_skips_loginless_picks_human() -> None:
    # A loginless approval is skipped; the first VALID human approval still wins.
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("", type_="User"), _review("carol")],
    )
    assert hr.satisfied_by == "approval:carol"
    assert hr.candidates_seen[0].reason == "no-login"
    assert hr.candidates_seen[1].counted is True


def test_bot_then_human_skips_bot_picks_human() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot"), _review("bob")],
    )
    assert hr.satisfied_by == "approval:bob"
    assert [c.login for c in hr.candidates_seen] == ["github-copilot[bot]", "bob"]
    assert hr.candidates_seen[1].counted is True
    assert hr.candidates_seen[1].reason == ""


def test_first_of_two_humans_wins() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("alice"), _review("bob")],
    )
    assert hr.satisfied_by == "approval:alice"


def test_non_approved_reviews_are_not_candidates() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[
            _review("alice", state="CHANGES_REQUESTED"),
            _review("bob", state="COMMENTED"),
        ],
    )
    assert hr.candidates_seen == []
    assert hr.satisfied_by is None


def test_to_dict_shape() -> None:
    hr = derive_human_review(
        labels=["human-review-required"],
        reviews=[_review("github-copilot[bot]", type_="Bot")],
    )
    assert hr.to_dict() == {
        "required": True,
        "satisfied_by": None,
        "candidates_seen": [
            {
                "login": "github-copilot[bot]",
                "approved": True,
                "counted": False,
                "reason": "bot",
            }
        ],
    }


class _FakeGh:
    """A minimal structural ``GhClient`` returning canned label/review payloads."""

    def __init__(self, labels: object, reviews: object) -> None:
        self._labels = labels
        self._reviews = reviews

    def rest(
        self,
        method: str,
        path: str,
        *,
        fields: object = None,  # noqa: ARG002  # part of the GhClient.rest signature; unused here
    ) -> object:
        assert method == "GET"
        return self._labels if path.endswith("/labels") else self._reviews


def test_fetch_maps_payloads_to_inputs() -> None:
    gh = _FakeGh(
        labels=[{"name": "human-review-required"}, {"name": "bug"}],
        reviews=[_review("alice")],
    )
    ref = PRRef(owner="octo", repo="demo", number=7)
    labels, reviews = fetch_human_review_inputs(gh, ref)  # type: ignore[arg-type]
    assert labels == ["human-review-required", "bug"]
    assert reviews == [_review("alice")]


class _NotFoundGh:
    """A structural ``GhClient`` whose every REST GET raises a 404."""

    def rest(
        self,
        method: str,  # noqa: ARG002  # part of the GhClient.rest signature; unused here
        path: str,  # noqa: ARG002  # part of the GhClient.rest signature; unused here
        *,
        fields: object = None,  # noqa: ARG002  # part of the GhClient.rest signature; unused here
    ) -> object:
        raise GhNotFoundError


def test_fetch_404_maps_to_terminal_prgroom_error() -> None:
    # A 404 during enrichment (PR vanished / access lost) is a terminal PrgroomError,
    # NOT a raw GhNotFoundError — mirroring poll.py's _vanished_pr_terminal convention.
    ref = PRRef(owner="octo", repo="demo", number=7)
    with pytest.raises(PrgroomError) as excinfo:
        fetch_human_review_inputs(_NotFoundGh(), ref)  # type: ignore[arg-type]
    assert excinfo.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert excinfo.value.tier is Tier.RUNTIME_TERMINAL_USER
