"""End-to-end: a single ``_run`` cycle through the REAL reply/resolve/rereview verbs.

The per-verb suites pin each lifecycle internal in isolation; ``test_lifecycle_run``
pins the loop's control flow with recorder fakes. This test closes the loop between
them: it drives ONE ``_run`` cycle through a :class:`Verbs` bundle whose
``reply``/``resolve``/``rereview`` are the production adapters (bound to a shared
call-recording gh) and whose ``push`` is a fake that stamps
``last_review_invalidated_sha`` the way ``push_pr`` does. That proves the §3.3
pipeline ordering (push → reply → resolve → rereview-last) takes effect through the
real verbs, that ``pending_memory`` drains, and that the rereview SHA stamp catches up
— behaviour no single-verb test can observe because each isolates one seam.
"""

from __future__ import annotations

from prgroom.lifecycle.reply import _ADD_THREAD_REPLY, reply_pr
from prgroom.lifecycle.rereview import rereview_pr
from prgroom.lifecycle.resolve import _RESOLVE_MUTATION, resolve_pr
from prgroom.lifecycle.run import RunContext, _run
from prgroom.prsession.enums import (
    DispositionKind,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.memory import InMemoryStore
from prgroom.prsession.state import (
    Disposition,
    Identity,
    PRGroomingState,
    ReviewerState,
    ReviewItem,
    RoutedMemory,
)

from .test_lifecycle_run import _NOW, _REF, _ctx, _quiescent_state, _verbs


class _RecordingGh:
    """Records every rest/graphql op in one ordered list so the test can assert the
    push → reply → resolve → rereview phase ordering, plus a body for the thread-less
    ``GET`` the reply path reads before its PR-body PATCH."""

    def __init__(self, body: str = "orig body") -> None:
        self._body = body
        self.ops: list[tuple[str, ...]] = []

    def rest(self, method: str, path: str, *, fields: dict | None = None) -> dict:  # noqa: ARG002
        self.ops.append(("rest", method, path))
        if method == "GET":
            return {"body": self._body}
        return {}

    def graphql(self, query: str, variables: dict) -> dict:  # noqa: ARG002
        opname = (
            "add_thread_reply"
            if query == _ADD_THREAD_REPLY
            else "resolve_thread"
            if query == _RESOLVE_MUTATION
            else "unknown"
        )
        self.ops.append(("graphql", opname))
        return {}


def _stale_required_copilot() -> dict[str, ReviewerState]:
    """A required Copilot reviewer in ``not_requested`` — satisfies the rereview guard's
    ``has_required_reviewers_to_refresh`` leg AND is in the rereview verb's refreshable set."""
    return {
        "copilot": ReviewerState(
            identity="copilot",
            kind=ReviewerKind.BOT,
            status=ReviewerStatus.NOT_REQUESTED,
            required=True,
            last_request_at=_NOW,
        )
    }


def _fixed_thread_item() -> ReviewItem:
    """A FIXED review-thread item with a thread node id — replyable AND resolvable."""
    return ReviewItem(
        kind=ItemKind.REVIEW_THREAD,
        identity=Identity(gh_id="100", thread_id="PRRT_t"),
        author="copilot",
        body_excerpt="x",
        seen_at=_NOW,
        disposition=Disposition(
            kind=DispositionKind.FIXED,
            decided_at=_NOW,
            decided_by="agent",
            commits=["abc1234"],
        ),
    )


def _seed_state() -> PRGroomingState:
    state = _quiescent_state(
        phase=PRPhase.FIXES_PENDING,
        reviewers=_stale_required_copilot(),
        items=[_fixed_thread_item()],
    )
    # _quiescent_state forwards neither pending_memory nor the rereview SHA stamps —
    # set them on the object the store and ctx both see. One thread-hint memory
    # (routes via graphql) + one thread-less (routes via the PR-body GET/PATCH).
    state.pending_memory = [
        RoutedMemory(
            content="why", retry=1, source_item="c1#0", decided_by="agent", target_hint="PRRT_t"
        ),
        RoutedMemory(content="decision", retry=1, source_item="c1#1", decided_by="agent"),
    ]
    return state


def test_run_cycle_reply_resolve_rereview_last_e2e() -> None:
    calls: list[str] = []
    gh = _RecordingGh()

    def push(ctx: RunContext) -> PRGroomingState:
        # Mirror push_pr: advance HEAD and stamp the review-invalidation SHA so the
        # post-push rereview guard arms (push.py:115). The fake skips the git upload.
        calls.append("push")
        ctx.state.last_pushed_head_sha = "newhead"
        ctx.state.last_review_invalidated_sha = "newhead"
        return ctx.state

    def wait(ctx: RunContext) -> PRGroomingState:
        # The push resolves the cycle to awaiting-review; the recorder poll keeps it
        # there, so the autonomous loop would block in `wait` forever. End the loop on
        # the first wait — the real verbs already ran (and persisted) in the prior
        # FIXES_PENDING pass, so `out` still carries their effects.
        calls.append("wait")
        ctx.state.phase = PRPhase.MERGED
        return ctx.state

    verbs = _verbs(
        calls,
        has_queued=False,
        push=push,
        wait=wait,
        reply=lambda ctx: reply_pr(ctx.state, gh=ctx.gh, ref=ctx.ref),
        resolve=lambda ctx: resolve_pr(ctx.state, gh=ctx.gh),
        rereview=lambda ctx: rereview_pr(ctx.state, ref=ctx.ref, gh=ctx.gh, deps=ctx.deps),
    )

    store = InMemoryStore()
    store.write(_REF, _seed_state())
    ctx = _ctx(_seed_state(), store=store, gh=gh)
    out = _run(ctx, verbs)

    # 1. Pipeline ordering: push → reply → resolve → rereview, observed through the
    #    REAL verbs' gh ops (push is the fake recorder; the other three are real, so
    #    they leave gh ops rather than `calls` entries). The first reply op is a POST
    #    to the per-item replies endpoint; resolve is the resolve_thread graphql; the
    #    rereview dance is DELETE+POST to requested_reviewers.
    assert "push" in calls
    reply_post = gh.ops.index(("rest", "POST", "repos/octo/demo/pulls/7/comments/100/replies"))
    resolve_op = gh.ops.index(("graphql", "resolve_thread"))
    rereview_delete = gh.ops.index(
        ("rest", "DELETE", "repos/octo/demo/pulls/7/requested_reviewers")
    )
    assert reply_post < resolve_op < rereview_delete  # reply → resolve → rereview-last

    # 2. Memory drained by the real reply verb.
    assert out.pending_memory == []

    # 3. Rereview SHA stamp caught up to the push's invalidation SHA.
    assert out.last_rereviewed_sha == out.last_review_invalidated_sha == "newhead"

    # 4. The FIXED thread item was both replied to and resolved.
    assert out.items[0].replied is True
    assert out.items[0].resolved is True
