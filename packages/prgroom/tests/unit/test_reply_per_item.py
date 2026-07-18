from datetime import UTC, datetime

from prgroom.lifecycle.idempotency import reply_marker, with_marker
from prgroom.lifecycle.reply import reply_pr
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Disposition, Identity, ReviewItem, bootstrap_state
from tests.fakes import RecordingGh

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


def _first_post(gh: RecordingGh) -> tuple[str, str, dict]:
    """The first POST call — the pre-flight GET occupies index 0 whenever a
    surface is needed, so positional ``rest_calls[0]`` reads select the scan."""
    return next((m, p, f) for m, p, f in gh.rest_calls if m == "POST")


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
    gh = RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "555", DispositionKind.FIXED, commits=["abc1234"])
    out = reply_pr(_state([item]), gh=gh, ref=_ref())
    method, path, fields = _first_post(gh)
    assert method == "POST"
    assert path == "repos/o/r/pulls/7/comments/555/replies"
    assert fields["body"].startswith("Fixed in abc1234.")
    assert out.items[0].replied is True


def test_fixed_with_rationale_appends_it() -> None:
    gh = RecordingGh()
    item = _item(
        ItemKind.REVIEW_THREAD,
        "555",
        DispositionKind.FIXED,
        commits=["abc1234"],
        rationale="tightened the bound",
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"] == with_marker(
        "Fixed in abc1234. tightened the bound", reply_marker(item)
    )


def test_fixed_empty_commits_renders_grammatical() -> None:
    # A FIXED disposition with no commits (reachable via `resolve-escalated --as fixed`
    # with no --commits) must not post the broken "Fixed in ." — it drops the sha clause.
    gh = RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "1", DispositionKind.FIXED)
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"] == with_marker("Fixed.", reply_marker(item))


def test_fixed_empty_commits_with_rationale() -> None:
    gh = RecordingGh()
    item = _item(
        ItemKind.REVIEW_THREAD,
        "1",
        DispositionKind.FIXED,
        rationale="manual human resolution",
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"] == with_marker(
        "Fixed. manual human resolution", reply_marker(item)
    )


def test_already_addressed_empty_commits_renders_grammatical() -> None:
    # Same defect class as FIXED: no commits must not post "Already addressed in .".
    gh = RecordingGh()
    item = _item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED)
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"] == with_marker("Already addressed.", reply_marker(item))


def test_escalated_cap_variant_when_rationale_names_cap() -> None:
    gh = RecordingGh()
    item = _item(
        ItemKind.REVIEW_THREAD,
        "7",
        DispositionKind.ESCALATED,
        rationale="PR-review retry budget exhausted",
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"] == with_marker(
        "Round limit reached on this PR; deferring further iterations to a human reviewer.",
        reply_marker(item),
    )


def test_escalated_substring_cap_does_not_trigger_cap_variant() -> None:
    # "captured" contains "cap" as a substring but NOT as a standalone word — it must
    # render the normal escalated body, not the cap variant (word-boundary match).
    gh = RecordingGh()
    item = _item(
        ItemKind.REVIEW_THREAD,
        "8",
        DispositionKind.ESCALATED,
        rationale="captured the edge case for a human",
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert _first_post(gh)[2]["body"].startswith("Captured for follow-up")


def test_empty_rendered_body_skips_post_and_keeps_replied_false() -> None:
    # SKIPPED/DEFERRED/WONT_FIX render from rationale; an empty rationale (reachable via
    # `resolve-escalated --as skipped` with no --rationale) renders "". Posting "" fails the
    # GitHub API — skip the POST and leave replied False so a later rationale can still reply.
    # The pre-flight surface GET still fires (tolerated over-fetch, §11 ledger).
    gh = RecordingGh()
    out = reply_pr(
        _state([_item(ItemKind.REVIEW_THREAD, "9", DispositionKind.SKIPPED, rationale="")]),
        gh=gh,
        ref=_ref(),
    )
    assert [m for m, _, _ in gh.rest_calls if m == "POST"] == []
    assert out.items[0].replied is False


def test_nested_reply_uses_reply_to_comment_id() -> None:
    gh = RecordingGh()
    item = _item(
        ItemKind.REVIEW_THREAD,
        "999",
        DispositionKind.SKIPPED,
        reply_to=555,
        rationale="out of scope",
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    _, path, fields = _first_post(gh)
    assert path == "repos/o/r/pulls/7/comments/555/replies"
    assert fields["body"] == with_marker("out of scope", reply_marker(item))


def test_issue_comment_endpoint() -> None:
    gh = RecordingGh()
    item = _item(
        ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED, commits=["def5678"]
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    _, path, fields = _first_post(gh)
    assert path == "repos/o/r/issues/7/comments"
    assert fields["body"] == with_marker("Already addressed in def5678.", reply_marker(item))


def test_failed_item_gets_no_reply() -> None:
    # FAILED is not replyable → no surface is needed → no scan GET either (this
    # doubles as the §5 no-surface/no-GET pin).
    gh = RecordingGh()
    state = _state([_item(ItemKind.REVIEW_THREAD, "1", DispositionKind.FAILED)])
    reply_pr(state, gh=gh, ref=_ref())
    assert gh.rest_calls == []
    assert state.items[0].replied is False


def test_escalated_replied_regardless_of_escalation_filed() -> None:
    gh = RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "2", DispositionKind.ESCALATED)
    item.disposition = Disposition(
        kind=DispositionKind.ESCALATED, decided_at=_NOW, decided_by="a", escalation_filed=True
    )
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert "Captured for follow-up" in _first_post(gh)[2]["body"]


def test_reply_captures_own_reply_id_from_post_response() -> None:
    # The POST response carries the new comment's numeric id; reply_pr records it on
    # own_reply_id so a later poll can drop our own reply (recursive-self-reply fix).
    gh = RecordingGh(post_reply_id=424242)
    state = _state([_item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED)])
    out = reply_pr(state, gh=gh, ref=_ref())
    assert out.items[0].replied is True
    assert out.items[0].own_reply_id == 424242


def test_reply_own_reply_id_stays_zero_when_response_lacks_id() -> None:
    # Defensive: a POST response with no usable "id" leaves own_reply_id at 0.
    gh = RecordingGh(post_reply_id=None)
    state = _state([_item(ItemKind.ISSUE_COMMENT, "12", DispositionKind.ALREADY_ADDRESSED)])
    out = reply_pr(state, gh=gh, ref=_ref())
    assert out.items[0].replied is True
    assert out.items[0].own_reply_id == 0


def test_idempotent_skips_already_replied() -> None:
    # Already replied → no surface is needed → zero gh calls (no-surface/no-GET pin).
    gh = RecordingGh()
    item = _item(ItemKind.REVIEW_THREAD, "3", DispositionKind.FIXED, commits=["a"])
    item.replied = True
    reply_pr(_state([item]), gh=gh, ref=_ref())
    assert gh.rest_calls == []
