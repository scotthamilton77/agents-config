from datetime import UTC, datetime

from prgroom.lifecycle.predicates import push_awaiting_rereview
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


def _state():
    return bootstrap_state(PRRef(owner="o", repo="r", number=1), now=_NOW)


def test_false_when_both_shas_empty_bootstrap() -> None:
    assert push_awaiting_rereview(_state()) is False


def test_true_after_invalidation_not_yet_rereviewed() -> None:
    s = _state()
    s.last_review_invalidated_sha = "sha1"
    assert push_awaiting_rereview(s) is True


def test_false_after_rereview_caught_up() -> None:
    s = _state()
    s.last_review_invalidated_sha = "sha1"
    s.last_rereviewed_sha = "sha1"
    assert push_awaiting_rereview(s) is False
