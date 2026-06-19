from datetime import UTC, datetime

from prgroom.lifecycle.reply import _sanitize, merge_decisions_block, reply_pr
from prgroom.prsession.enums import PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import RoutedMemory, bootstrap_state

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


class _RecordingGh:
    def __init__(self, body: str = "") -> None:
        self._body = body
        self.rest_calls: list[tuple[str, str, dict]] = []
        self.graphql_calls: list[tuple[str, dict]] = []

    def rest(self, method, path, *, fields=None):
        self.rest_calls.append((method, path, dict(fields or {})))
        if method == "GET":
            return {"body": self._body}
        return {}

    def graphql(self, query, variables):
        self.graphql_calls.append((query, dict(variables)))
        return {}


def _ref() -> PRRef:
    return PRRef(owner="o", repo="r", number=7)


def _state_with_pending(pending):
    s = bootstrap_state(_ref(), now=_NOW)
    s.phase = PRPhase.FIXES_PENDING
    s.pending_memory = pending
    return s


def test_sanitize_strips_newlines_and_comments() -> None:
    assert _sanitize("a\nb <!-- x --> c") == "a b  c"


def test_merge_appends_new_entry() -> None:
    body = merge_decisions_block(
        "intro",
        [RoutedMemory(content="decided X", round=1, source_item="c1#0", decided_by="agent")],
    )
    assert "<!-- prgroom:decisions:start -->" in body
    assert "decided X" in body
    assert "<!-- d:r1:c1#0 -->" in body


def test_merge_is_byte_identical_on_rerun() -> None:
    rm = [RoutedMemory(content="X", round=1, source_item="c1#0", decided_by="agent")]
    once = merge_decisions_block("intro", rm)
    twice = merge_decisions_block(once, rm)
    assert once == twice


def test_merge_appends_distinct_same_round_keys() -> None:
    body = merge_decisions_block(
        "",
        [
            RoutedMemory(content="A", round=1, source_item="c1#0", decided_by="a"),
            RoutedMemory(content="B", round=1, source_item="c1#1", decided_by="a"),
        ],
    )
    assert "<!-- d:r1:c1#0 -->" in body and "<!-- d:r1:c1#1 -->" in body


def test_thread_hint_routes_via_graphql_and_clears() -> None:
    gh = _RecordingGh()
    state = _state_with_pending(
        [
            RoutedMemory(
                content="why", round=1, source_item="c1#0", decided_by="a", target_hint="PRRT_abc"
            )
        ]
    )
    out = reply_pr(state, gh=gh, ref=_ref())
    assert gh.graphql_calls and gh.graphql_calls[0][1]["threadId"] == "PRRT_abc"
    assert gh.graphql_calls[0][1]["body"] == "why"
    assert out.pending_memory == []


def test_thread_less_routes_via_patch_and_clears() -> None:
    gh = _RecordingGh(body="orig body")
    state = _state_with_pending(
        [RoutedMemory(content="decision", round=1, source_item="c1#0", decided_by="a")]
    )
    out = reply_pr(state, gh=gh, ref=_ref())
    methods = [(m, p) for m, p, _ in gh.rest_calls]
    assert ("GET", "repos/o/r/pulls/7") in methods
    patch = next(f for m, p, f in gh.rest_calls if m == "PATCH")
    assert "decision" in patch["body"] and "orig body" in patch["body"]
    assert out.pending_memory == []
