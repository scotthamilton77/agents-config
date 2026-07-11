"""Tests for §8.1 snapshot assembly + §8.2 recurrence derivation.

The snapshot module does the gh/git legwork the fix agent must NOT do (§8.1):
it reads the PR resource (base ref, body's ``## Decisions`` block, labels), the
review threads with full reply-chains, and the git branch state (recent commits +
diff-since-base), then dumps everything to two files passed to the fix contract.

The single mocked seam is the subprocess boundary: ``GhCli`` is driven by a
``RecordedRunner`` and ``GitClient`` is a small fake. ``derive_recurrence`` is a
pure function over a ``ReviewItem`` + state, tested without any boundary.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prgroom.errors import ErrorCode, PrgroomError, Tier
from prgroom.gh import GhCli
from prgroom.lifecycle.snapshot import (
    DECISIONS_END,
    DECISIONS_START,
    assemble_snapshot,
    derive_recurrence,
    extract_decisions_block,
)
from prgroom.proc import CommandResult
from prgroom.prsession.enums import DispositionKind, ItemKind, PRPhase
from prgroom.prsession.pr_ref import PRRef
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    QuiescenceState,
    ReviewItem,
)
from tests.fakes import RecordedRunner

_REF = PRRef(owner="octo", repo="demo", number=7)
_T0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)


def _ok(payload: object) -> CommandResult:
    return CommandResult(returncode=0, stdout=json.dumps(payload), stderr="")


def _thread_map_ok(nodes: list[dict[str, object]]) -> CommandResult:
    """A gh-api-graphql reviewThreads success envelope (the thread-id map read)."""
    return _ok({"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": nodes}}}}})


def _item(
    gh_id: str,
    *,
    thread_id: str = "",
    disposition: Disposition | None = None,
    cluster_id: str = "c-1",
    seen_at: datetime = _T0,
) -> ReviewItem:
    kind = ItemKind.REVIEW_THREAD if thread_id else ItemKind.ISSUE_COMMENT
    return ReviewItem(
        kind=kind,
        identity=Identity(gh_id=gh_id, thread_id=thread_id),
        author="copilot",
        body_excerpt="please fix",
        seen_at=seen_at,
        cluster_id=cluster_id,
        disposition=disposition,
    )


def _state(*items: ReviewItem, retries_: int = 2) -> PRGroomingState:
    return PRGroomingState(
        pr=_REF,
        phase=PRPhase.FIXES_PENDING,
        pr_review_retries_used=retries_,
        last_polled_at=_T0,
        last_activity_at=_T0,
        quiescence=QuiescenceState(ci_state="success"),
        items=list(items),
    )


class FakeGit:
    """A minimal ``GitClient`` fake scripting the §8.1 branch-state reads."""

    def __init__(self, *, log: str = "log-text", diff_stat: str = "diff-text") -> None:
        self._log = log
        self._diff_stat = diff_stat
        self.log_calls: list[str] = []
        self.diff_calls: list[str] = []

    def head_sha(self) -> str:  # pragma: no cover - unused by snapshot
        return "head"

    def rev_list(self, range_: str) -> list[str]:  # pragma: no cover - unused
        del range_
        return []

    def log(self, range_: str) -> str:
        self.log_calls.append(range_)
        return self._log

    def diff_stat(self, range_: str) -> str:
        self.diff_calls.append(range_)
        return self._diff_stat

    def push(self, remote: str, branch: str) -> None:  # pragma: no cover - unused
        del remote, branch

    def stash(self) -> None:  # pragma: no cover - unused
        return None


def _gh(
    *,
    base_ref: str = "main",
    body: str = "PR body",
    labels: list[str] | None = None,
    review_comments: list[dict[str, object]] | None = None,
    thread_nodes: list[dict[str, object]] | None = None,
) -> GhCli:
    """Queue the snapshot's gh reads: PR resource, review comments, thread-id map.

    When ``review_comments`` is non-empty, ``_fetch_review_threads`` issues an extra
    GraphQL ``reviewThreads`` read after the REST comments read; ``thread_nodes``
    supplies that envelope's nodes (default empty → threads degrade to their REST
    root-comment id key).
    """
    pr_resource = {
        "body": body,
        "base": {"ref": base_ref},
        "labels": [{"name": n} for n in (labels or [])],
    }
    results = [
        _ok(pr_resource),
        _ok(review_comments or []),
    ]
    if review_comments:
        results.append(_thread_map_ok(thread_nodes or []))
    return GhCli(RecordedRunner(results))


# ───────────────────────── derive_recurrence ─────────────────────────


def test_derive_recurrence_none_when_no_prior_disposition() -> None:
    item = _item("a", thread_id="PRT_a")
    state = _state(item)
    assert derive_recurrence(item, state, threads={}) is None


def test_derive_recurrence_carries_prior_disposition_and_commits() -> None:
    disp = Disposition(
        kind=DispositionKind.WONT_FIX,
        decided_at=_T0,
        decided_by="claude opus[1m]",
        rationale="suffix denotes pipeline",
        commits=["c1", "c2"],
    )
    item = _item("a", thread_id="PRT_a", disposition=disp)
    rec = derive_recurrence(item, _state(item), threads={})
    assert rec is not None
    assert rec.prior_disposition == "wont_fix"
    assert rec.prior_commits == ("c1", "c2")
    assert rec.attempt_count == 1  # MVP floor: schema retains one disposition
    assert rec.first_seen_retry == 2  # MVP proxy: current retry counter (schema has no first-seen)
    assert rec.reopened is False  # no newer reply than decided_at


def test_derive_recurrence_reopened_when_newer_reply_on_thread() -> None:
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    item = _item("a", thread_id="PRT_a", disposition=disp)
    # A reply on the same thread arrived AFTER the disposition was decided.
    threads = {"PRT_a": [{"created_at": _T1.isoformat()}]}
    rec = derive_recurrence(item, _state(item), threads=threads)
    assert rec is not None
    assert rec.reopened is True


def test_derive_recurrence_not_reopened_when_reply_predates_disposition() -> None:
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T1, decided_by="x")
    item = _item("a", thread_id="PRT_a", disposition=disp)
    threads = {"PRT_a": [{"created_at": _T0.isoformat()}]}  # older than decided_at
    rec = derive_recurrence(item, _state(item), threads=threads)
    assert rec is not None
    assert rec.reopened is False


def test_derive_recurrence_omits_prior_commits_when_empty() -> None:
    disp = Disposition(kind=DispositionKind.SKIPPED, decided_at=_T0, decided_by="x")
    item = _item("a", thread_id="PRT_a", disposition=disp)
    rec = derive_recurrence(item, _state(item), threads={})
    assert rec is not None
    assert rec.prior_commits == ()
    assert "prior_commits" not in rec.to_dict()


# ───────────────────────── extract_decisions_block ─────────────────────────


def test_extract_decisions_block_present() -> None:
    body = f"intro\n\n{DECISIONS_START}\n## Decisions\n- a decision\n{DECISIONS_END}\ntail"
    extracted = extract_decisions_block(body)
    assert "## Decisions" in extracted
    assert "a decision" in extracted


def test_extract_decisions_block_absent_returns_empty() -> None:
    assert extract_decisions_block("a PR body with no decisions section") == ""


def test_extract_decisions_block_start_without_end_returns_empty() -> None:
    # A start sentinel with no matching end has no parseable boundary → empty,
    # rather than guessing where the block ends.
    body = f"intro\n{DECISIONS_START}\n## Decisions\n- dangling"
    assert extract_decisions_block(body) == ""


def test_derive_recurrence_no_thread_id_is_not_reopened() -> None:
    # An item with no thread_id (e.g. an issue_comment) cannot be "reopened" by a
    # thread reply — the reopened signal degrades to False.
    disp = Disposition(kind=DispositionKind.SKIPPED, decided_at=_T0, decided_by="x")
    item = _item("a", disposition=disp)  # no thread_id → issue_comment kind
    rec = derive_recurrence(
        item, _state(item), threads={"PRT_a": [{"created_at": _T1.isoformat()}]}
    )
    assert rec is not None
    assert rec.reopened is False


def test_derive_recurrence_ignores_malformed_reply_timestamp() -> None:
    # A reply with a blank/missing created_at OR a truly malformed (non-ISO) string
    # cannot prove a reopen — each is skipped, not crashed (a non-ISO value would
    # otherwise raise ValueError out of datetime.fromisoformat and abort `fix`).
    # With no other newer reply the item is not reopened.
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    item = _item("a", thread_id="PRT_a", disposition=disp)
    threads = {
        "PRT_a": [
            {"created_at": ""},
            {"body": "no timestamp at all"},
            {"created_at": "not-a-real-timestamp"},  # non-ISO → must be skipped, not crash
        ]
    }
    rec = derive_recurrence(item, _state(item), threads=threads)
    assert rec is not None
    assert rec.reopened is False


def test_derive_recurrence_naive_reply_timestamp_does_not_crash() -> None:
    # A present-but-naive (offsetless) timestamp can't be compared to the tz-aware
    # decided_at; it is skipped (can't prove a reopen) rather than raising TypeError.
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    item = _item("a", thread_id="PRT_a", disposition=disp)
    threads = {"PRT_a": [{"created_at": "2026-06-10T12:00:00"}]}  # no offset → naive
    rec = derive_recurrence(item, _state(item), threads=threads)
    assert rec is not None
    assert rec.reopened is False


# ───────────────────────── assemble_snapshot ─────────────────────────


def test_assemble_snapshot_writes_both_files(tmp_path: Path) -> None:
    item = _item("11", thread_id="PRT_11")
    state = _state(item)
    gh = _gh(base_ref="main", body="body", labels=["bug", "needs-fix"])
    git = FakeGit(log="commit log here", diff_stat="2 files changed")
    snap = assemble_snapshot(state, [item], ref=_REF, gh=gh, git=git, scratch_dir=tmp_path)
    assert Path(snap.pr_detail_path).is_file()
    assert Path(snap.branch_state_path).is_file()
    # The branch-state file carries the git log + diff-stat dump verbatim.
    branch_text = Path(snap.branch_state_path).read_text(encoding="utf-8")
    assert "commit log here" in branch_text
    assert "2 files changed" in branch_text
    # git reads are scoped to base..HEAD (base ref from the gh PR resource).
    assert git.log_calls == ["origin/main..HEAD"]
    assert git.diff_calls == ["origin/main..HEAD"]


def test_assemble_snapshot_detail_carries_labels_and_decisions(tmp_path: Path) -> None:
    body = f"intro\n{DECISIONS_START}\n## Decisions\n- adopted Result<T>\n{DECISIONS_END}"
    item = _item("11", thread_id="PRT_11")
    gh = _gh(base_ref="main", body=body, labels=["human-review-required"])
    snap = assemble_snapshot(
        _state(item), [item], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path
    )
    detail = json.loads(Path(snap.pr_detail_path).read_text(encoding="utf-8"))
    assert detail["labels"] == ["human-review-required"]
    assert "adopted Result<T>" in detail["decisions"]
    assert detail["description"] == body


def test_assemble_snapshot_detail_carries_prior_dispositions(tmp_path: Path) -> None:
    disp = Disposition(
        kind=DispositionKind.FIXED,
        decided_at=_T0,
        decided_by="claude opus[1m]",
        commits=["c1"],
    )
    done = _item("done", thread_id="PRT_done", disposition=disp)
    todo = _item("todo", thread_id="PRT_todo")
    state = _state(done, todo)
    gh = _gh()
    snap = assemble_snapshot(state, [todo], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path)
    detail = json.loads(Path(snap.pr_detail_path).read_text(encoding="utf-8"))
    prior = detail["prior_dispositions"]
    assert len(prior) == 1
    assert prior[0]["gh_id"] == "done"
    assert prior[0]["kind"] == "fixed"
    assert prior[0]["commits"] == ["c1"]
    assert prior[0]["decided_by"] == "claude opus[1m]"


def test_assemble_snapshot_threads_carry_full_reply_chain(tmp_path: Path) -> None:
    review_comments = [
        {"id": 1, "in_reply_to_id": None, "body": "top", "created_at": _T0.isoformat()},
        {"id": 2, "in_reply_to_id": 1, "body": "reply", "created_at": _T1.isoformat()},
    ]
    item = _item("11", thread_id="PRT_11")
    gh = _gh(review_comments=review_comments)
    snap = assemble_snapshot(
        _state(item), [item], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path
    )
    detail = json.loads(Path(snap.pr_detail_path).read_text(encoding="utf-8"))
    chains = detail["review_threads"]
    # Both the top comment and its reply are present (full reply-chain, §8.1).
    bodies = [c["body"] for thread in chains for c in thread["comments"]]
    assert "top" in bodies
    assert "reply" in bodies


def test_assemble_snapshot_keys_threads_by_graphql_node_id(tmp_path: Path) -> None:
    # The snapshot keys each thread by its GraphQL PRRT_* node id (the key-space
    # Identity.thread_id and resolveReviewThread use) — NOT the REST root-comment id.
    review_comments = [
        {"id": 11, "in_reply_to_id": None, "body": "top", "created_at": _T0.isoformat()},
    ]
    thread_nodes = [{"id": "PRRT_x", "comments": {"nodes": [{"databaseId": 11}]}}]
    item = _item("11", thread_id="PRRT_x")
    gh = _gh(review_comments=review_comments, thread_nodes=thread_nodes)
    snap = assemble_snapshot(
        _state(item), [item], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path
    )
    detail = json.loads(Path(snap.pr_detail_path).read_text(encoding="utf-8"))
    assert [t["thread_id"] for t in detail["review_threads"]] == ["PRRT_x"]


def test_assemble_snapshot_recurrence_reopened_via_graphql_keyed_threads(tmp_path: Path) -> None:
    # The payoff: an item carrying its GraphQL node id (set by a prior poll) is
    # flagged reopened when a newer reply lands — because the snapshot now keys
    # threads by that same PRRT_* node id, so _thread_reopened's lookup hits.
    disp = Disposition(kind=DispositionKind.FIXED, decided_at=_T0, decided_by="x")
    item = _item("11", thread_id="PRRT_x", disposition=disp)
    review_comments = [
        {"id": 11, "in_reply_to_id": None, "body": "top", "created_at": _T0.isoformat()},
        {"id": 12, "in_reply_to_id": 11, "body": "ping", "created_at": _T1.isoformat()},
    ]
    thread_nodes = [
        {"id": "PRRT_x", "comments": {"nodes": [{"databaseId": 11}, {"databaseId": 12}]}}
    ]
    gh = _gh(review_comments=review_comments, thread_nodes=thread_nodes)
    snap = assemble_snapshot(
        _state(item), [item], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path
    )
    assert snap.recurrence["11"].reopened is True


def test_assemble_snapshot_returns_ephemeral_dirs(tmp_path: Path) -> None:
    item = _item("11", thread_id="PRT_11")
    snap = assemble_snapshot(
        _state(item), [item], ref=_REF, gh=_gh(), git=FakeGit(), scratch_dir=tmp_path
    )
    assert Path(snap.memory_dir).is_dir()
    assert Path(snap.response_outbox_dir).is_dir()


def test_assemble_snapshot_404_on_pr_resource_is_terminal(tmp_path: Path) -> None:
    # A mid-run 404 on the PR resource means the PR/repo vanished → terminal
    # RUNTIME_GH_TERMINAL (mirrors poll.py), never a crash or a blind retry.
    item = _item("11", thread_id="PRT_11")
    not_found = CommandResult(returncode=1, stdout="{}", stderr="gh: Not Found (HTTP 404)")
    gh = GhCli(RecordedRunner([not_found]))
    with pytest.raises(PrgroomError) as exc:
        assemble_snapshot(
            _state(item), [item], ref=_REF, gh=gh, git=FakeGit(), scratch_dir=tmp_path
        )
    assert exc.value.code is ErrorCode.RUNTIME_GH_TERMINAL
    assert exc.value.tier is Tier.RUNTIME_TERMINAL_USER


def test_assemble_snapshot_embeds_recurrence_for_prior_disposition_items(
    tmp_path: Path,
) -> None:
    disp = Disposition(kind=DispositionKind.WONT_FIX, decided_at=_T0, decided_by="x")
    # An item being re-fixed that still carries its prior disposition gets a
    # recurrence object in the per-item recurrence map (forward-compat seam).
    reopened = _item("a", thread_id="PRT_a", disposition=disp)
    snap = assemble_snapshot(
        _state(reopened), [reopened], ref=_REF, gh=_gh(), git=FakeGit(), scratch_dir=tmp_path
    )
    assert "a" in snap.recurrence
    assert snap.recurrence["a"].prior_disposition == "wont_fix"


def test_assemble_snapshot_no_recurrence_for_fresh_items(tmp_path: Path) -> None:
    fresh = _item("a", thread_id="PRT_a")
    snap = assemble_snapshot(
        _state(fresh), [fresh], ref=_REF, gh=_gh(), git=FakeGit(), scratch_dir=tmp_path
    )
    assert snap.recurrence == {}
