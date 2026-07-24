from datetime import UTC, datetime

from prgroom.lifecycle.poll import _apply_sha_attribution
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


def _state():
    return bootstrap_state(PRRef(owner="o", repo="r", number=1), now=_NOW)


# _apply_sha_attribution now owns only the SHA bookkeeping (retry count, last_poll_sha,
# invalidated-sha). The reviewer-invalidation flip and its `now` boundary stamp moved
# earlier in poll_pr (before reconciliation), so this helper no longer takes `now`.


def test_external_push_stamps_review_invalidated_sha() -> None:
    s = _state()
    s.last_poll_sha = "old"
    s.last_pushed_head_sha = "mine"  # not the new head -> external
    external = _apply_sha_attribution(s, "external-head")
    assert external is True
    assert s.last_review_invalidated_sha == "external-head"


def test_own_push_recognized_does_not_stamp_invalidated() -> None:
    s = _state()
    s.last_poll_sha = "old"
    s.last_pushed_head_sha = "mine"
    external = _apply_sha_attribution(s, "mine")  # CLI's own push, _push already stamped
    assert external is False
    assert s.last_review_invalidated_sha == ""


def test_bootstrap_does_not_stamp() -> None:
    s = _state()  # last_poll_sha == ""
    _apply_sha_attribution(s, "first-head")
    assert s.last_review_invalidated_sha == ""
