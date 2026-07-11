"""``push_pr`` — the lock-held ``_push`` lifecycle internal (§3.2/§3.4/§3.5).

``push_pr`` uploads the fix agent's queued commits to the PR's head branch — the
first verb that mutates the remote. It first guards the mutation: the design pins
the upload to the **local PR-branch HEAD** (§3.4), so it refuses with
``PRECONDITION_WRONG_BRANCH`` unless the worktree is actually checked out on the PR
head branch (``gh.head_ref_name``) — an ambient checkout or detached HEAD would
otherwise publish the wrong commits. Then the remote tip is the source of truth for
the commit queue (§3.4 forbids a state field for it): it reads the authoritative
remote HEAD via ``gh.head_ref_oid`` and lists local commits ahead of it with
``git.rev_list``. With ≥1 queued commit it pushes ``HEAD:<head-branch>`` to
``origin``, then counts the consumed PR-review retry (the initial observed push is
free — the counter is 0-indexed), records ``last_pushed_head_sha`` (the SHA this
CLI pushed, distinguishing CLI from external pushes for §3.4 attribution), and
flips stale required reviews to ``not_requested`` so the post-push ``_rereview``
re-asks them.

It mirrors :func:`~prgroom.lifecycle.fix.fix_pr` — works on a deepcopy, never
touches the store (the caller owns ``store.write``), and returns the mutated copy.
**Idempotent**: a no-op (state returned unchanged, nothing pushed) when no commits
are queued. This makes a state-write crash after a successful push safe — the next
invocation's ``rev_list`` finds the commits already on the remote and re-pushes
nothing, so the retry counter is never double-bumped. (The one-retry under-count
the lost write leaves behind is reconciled by the next ``_poll`` via its
external-push attribution, §3.4.) Makes **no** phase change (§3.2 push row; phase
resolution is the run aggregate's job) and sets no ``state.last_error``. A failed
``git push`` propagates its tagged error without mutating state — the counter and
the reviewer set are touched only after the push succeeds.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.client import GhNotFoundError
from prgroom.lifecycle.gh_errors import vanished_pr_terminal
from prgroom.lifecycle.predicates import flip_stale_required_reviews
from prgroom.lifecycle.warn import default_warn

if TYPE_CHECKING:
    from collections.abc import Callable

    from prgroom.config import PrgroomConfig
    from prgroom.gh.client import GhClient
    from prgroom.git.client import GitClient
    from prgroom.prsession.pr_ref import PRRef
    from prgroom.prsession.state import PRGroomingState

_REMOTE = "origin"


def has_queued_fix_commits(gh: GhClient, git: GitClient, ref: PRRef) -> bool:
    """True iff the local PR-branch HEAD has ≥1 commit not yet on the remote (§3.4).

    The remote tip is the source of truth for the commit queue (§3.4 forbids a state
    field): it reads the authoritative remote HEAD via ``gh.head_ref_oid`` and lists
    local commits ahead of it with ``git.rev_list``. Shared by :func:`push_pr` (its
    no-op guard) and the run-loop's §3.5 pre-push cap check, so the cap decision and
    the push agree on exactly what "queued" means. A 404 (vanished PR/repo) is mapped
    to a terminal :class:`~prgroom.errors.PrgroomError` here — never re-raised as a raw
    :class:`~prgroom.gh.client.GhNotFoundError` — so every caller (including the
    run-loop's ``_execute_step``, which only catches ``PrgroomError``) handles it
    through the tagged-error path rather than a stray traceback. Other gh/git failures
    already arrive as the adapter's registry-tagged ``PrgroomError``.
    """
    try:
        remote_head = gh.head_ref_oid(ref)
    except GhNotFoundError as exc:
        raise vanished_pr_terminal(ref) from exc
    return bool(git.rev_list(f"{remote_head}..HEAD"))


def push_pr(
    state: PRGroomingState,
    *,
    ref: PRRef,
    gh: GhClient,
    git: GitClient,
    config: PrgroomConfig,
    warn: Callable[[str], None] = default_warn,
) -> PRGroomingState:
    """Upload queued commits to the PR head branch, counting the consumed retry.

    Caller must hold the per-ref lock (see ``lock()``). Works on a deepcopy of
    ``state``; returns the copy for the caller to persist. A no-op when no commits
    are queued (§3.4). No phase change (§3.2 push row), no ``state.last_error``.
    """
    state = copy.deepcopy(state)
    try:
        branch = gh.head_ref_name(ref)

        # Guard the live mutation: `_push` uploads the local PR-branch HEAD (§3.4).
        # An ambient checkout on some other branch (or a detached HEAD, which reads
        # as the literal "HEAD") would publish the wrong commits, so refuse before
        # the queued-commit read and the push that could publish, rather than trust
        # the working tree.
        current = git.current_branch()
        if current != branch:
            raise PreconditionError(
                ErrorCode.PRECONDITION_WRONG_BRANCH,
                detail=f"worktree on '{current}', expected PR head branch '{branch}'",
            )

        if not has_queued_fix_commits(gh, git, ref):
            return state  # nothing queued — idempotent no-op (§3.4)

        # The initial review-eliciting push is free (§3.4: the 0-indexed counter
        # counts fix-push retries, not pushes). Evaluate before mutating the SHAs —
        # a set last_poll_sha (poll observed a HEAD) or last_pushed_head_sha (a
        # prior CLI push) means the initial push is already spent.
        is_initial_push = not state.last_poll_sha and not state.last_pushed_head_sha

        git.push(_REMOTE, f"HEAD:{branch}")

        # Mutate only after the push succeeds: a rejected push propagates its tagged
        # error (RUNTIME_PUSH_REJECTED / RUNTIME_GIT_*) with state untouched.
        state.last_pushed_head_sha = git.head_sha()
        if not is_initial_push:
            state.pr_review_retries_used += 1
        flip_stale_required_reviews(state.reviewers)
        state.last_review_invalidated_sha = state.last_pushed_head_sha

        if state.pr_review_retries_used == config.pr_review_retries:
            # Fire only on the push that lands exactly at the budget (§3.5) — not
            # with >=, which would re-warn (inaccurately) on every push past it.
            warn(
                f"the PR-review retry budget (pr_review_retries="
                f"{config.pr_review_retries}) is now exhausted; "
                "subsequent fix work will gate to human-gated"
            )
    except GhNotFoundError as exc:
        # The PR/repo vanished mid-run (404) — terminal, not a raw traceback.
        raise vanished_pr_terminal(ref) from exc
    return state
