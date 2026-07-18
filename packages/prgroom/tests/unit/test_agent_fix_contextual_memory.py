from datetime import UTC, datetime

from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput, MemoryEntry
from prgroom.agent.dispatcher import Dispatched
from prgroom.agent.fix import run_fix
from prgroom.agent.subprocess_runner import AgentSpec
from prgroom.prsession.enums import DispositionKind, ItemKind
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import Identity, ReviewItem

_NOW = datetime(2026, 6, 19, tzinfo=UTC)


class _FakeGit:
    def head_sha(self) -> str:
        return "h"

    def rev_list(self, range_: str) -> list[str]:
        del range_  # mirrors the GitClient Protocol signature; no commits in these tests
        return []

    def stash(self) -> None:
        pass


class _Dispatcher:
    def __init__(self, out: FixOutput) -> None:
        self._out = out

    def fix(self, request: FixInput) -> FixOutput:
        del request  # canned outcome; mirrors the FixContract Protocol signature
        return Dispatched(output=self._out, winner=AgentSpec(cli="claude", model="opus[1m]"))


def _item(gh_id: str, thread_id: str = "") -> ReviewItem:
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id=gh_id, thread_id=thread_id),
        author="rev",
        body_excerpt="b",
        seen_at=_NOW,
    )


def _req(items: list[ReviewItem]) -> FixInput:
    return FixInput(
        pr=PRRef(owner="o", repo="r", number=1),
        cluster_id="c1",
        item_gh_ids=[i.identity.gh_id for i in items],
        items=items,
        pr_detail_path="/d",
        branch_state_path="/b",
        memory_dir="/m",
        response_outbox_dir="/out",
    )


def test_contextual_memory_carried_for_cluster_thread() -> None:
    item = _item("100", thread_id="PRRT_a")
    out = FixOutput(
        items=[FixItemResult(gh_id="100", disposition=DispositionKind.FIXED, commit_shas=["s1"])],
        memory=[MemoryEntry(classification="CONTEXTUAL", content="why", target_hint="PRRT_a")],
    )
    res = run_fix(_req([item]), _Dispatcher(out), _FakeGit(), now=_NOW)
    assert [e.content for e in res.contextual_memory] == ["why"]


def test_non_cluster_target_hint_not_routed() -> None:
    item = _item("100", thread_id="PRRT_a")
    out = FixOutput(
        items=[FixItemResult(gh_id="100", disposition=DispositionKind.FIXED, commit_shas=["s1"])],
        memory=[MemoryEntry(classification="CONTEXTUAL", content="x", target_hint="PRRT_other")],
    )
    res = run_fix(_req([item]), _Dispatcher(out), _FakeGit(), now=_NOW)
    assert res.contextual_memory == []  # unknown-thread hint -> audit violation, not routed
