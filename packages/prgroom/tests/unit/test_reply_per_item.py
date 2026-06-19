from datetime import UTC, datetime

from prgroom.lifecycle.reply import reply_pr
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Disposition, Identity, ReviewItem, bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


class _RecordingGh:
    def __init__(self) -> None:
        self.rest_calls: list[tuple[str, str, dict]] = []
        self.graphql_calls: list[tuple[str, dict]] = []

    def rest(self, method: str, path: str, *, fields=None):
        self.rest_calls.append((method, path, dict(fields or {})))
        return {}

    def graphql(self, query: str, variables: dict):
        self.graphql_calls.append((query, dict(variables)))
        return {}


def _ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=7)


def _item(kind, gh_id, disp, *, reply_to=0, rationale="", commits=None) -> ReviewItem:
    return ReviewItem(
        kind=kind,
        identity=Identity(gh_id=gh_id, reply_to_comment_id=reply_to),
        author="rev",
        body_excerpt="b",
        seen_at=_NOW,
        disposition=Disposition(
            kind=disp,
            decided_at=_NOW,
            decided_by="agent",
            rationale=rationale,
            commits=commits or [],
        ),
    )


def _state(items):
    s = bootstrap_state(_ref(), now=_NOW)
    s.phase = PRPhase.FIXES_PENDING
    s.items = items
    return s


def test_fixed_top_level_review_thread_reply() -> None:
    gh = _RecordingGh()
    state = _state(
        [_item(ItemKind.REVIEW_THREAD, "555", DispositionKind.FIXED, commits=["abc1234"])]
    )
    out = reply_pr(state, gh=gh, ref=_ref())
    method, path, fields = gh.rest_calls[0]
    assert method == "POST"
    assert path == "repos/o/r/pulls/7/comments/555/replies"
    assert fields["body"].startswith("Fixed in abc1234.")
    assert out.items[0].replied is True


def test_nested_reply_uses_reply_to_comment_id() -> None:
    gh = _RecordingGh()
    state = _state(
        [
            _item(
                ItemKind.REVIEW_THREAD,
                "999",
                DispositionKind.SKIPPED,
                reply_to=555,
                rationale="out of scope",
            )
        ]
    )
    reply_pr(state, gh=gh, ref=_ref())
    _, path, fields = gh.rest_calls[0]
    assert path == "repos/o/r/pulls/7/comments/555/replies"
    assert fields["body"] == "out of scope"


def test_issue_comment_endpoint() -> None:
    gh = _RecordingGh()
    state = _state(
        [
            _item(
                ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED, commits=["def5678"]
            )
        ]
    )
    reply_pr(state, gh=gh, ref=_ref())
    _, path, fields = gh.rest_calls[0]
    assert path == "repos/o/r/issues/7/comments"
    assert fields["body"] == "Already addressed in def5678."


def test_failed_item_gets_no_reply() -> None:
    gh = _RecordingGh()
    state = _state([_item(ItemKind.REVIEW_THREAD, "1", DispositionKind.FAILED)])
    reply_pr(state, gh=gh, ref=_ref())
    assert gh.rest_calls == []
    assert state.items[0].replied is False


def test_escalated_replied_regardless_of_escalation_filed() -> None:
    gh = _RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "2", DispositionKind.ESCALATED)
    item.disposition = Disposition(
        kind=DispositionKind.ESCALATED, decided_at=_NOW, decided_by="a", escalation_filed=True
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert "Captured for follow-up" in gh.rest_calls[0][2]["body"]


def test_idempotent_skips_already_replied() -> None:
    gh = _RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "3", DispositionKind.FIXED, commits=["a"])
    item.replied = True
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert gh.rest_calls == []
