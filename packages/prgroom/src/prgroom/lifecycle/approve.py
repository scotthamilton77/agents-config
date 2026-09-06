"""The ``approve`` verb — an App-authored approving review pinned to a head SHA.

The approval is a mechanical attestation, never an authorization: it satisfies a
branch ruleset's approving-review requirement for a merge decided elsewhere, and
it asserts no outcome of its own. It refuses when the PR's live head has moved
off the SHA the caller named, is a no-op when the App has already approved that
exact head, and never retries — every failure hands back to a human with its own
error code.

It stands outside the grooming loop: no grooming state is read or written, and
no PR lock is taken.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from prgroom.config import ApproverConfig
from prgroom.errors import ErrorCode, PreconditionError
from prgroom.gh.app import (
    HttpTransport,
    MintedApp,
    build_jwt,
    iter_reviews,
    mint_installation_token,
    openssl_signer,
    read_head_sha,
    submit_review,
)
from prgroom.proc import CommandRunner
from prgroom.prsession.pr_ref import PRRef

APPROVE_EVENT = "APPROVE"

_APPROVED_STATE = "APPROVED"


def resolve_key_path(approver: ApproverConfig, env: Mapping[str, str]) -> Path:
    """Resolve the App key's path from the environment variable the config names.

    Opening it here rather than leaving it to the signer turns two very different
    failures — a key that is not there and a key openssl would not accept — into
    two distinguishable errors.
    """
    raw = env.get(approver.key_path_env, "").strip()
    if not raw:
        raise PreconditionError(
            ErrorCode.PRECONDITION_APPROVER_KEY_ENV_UNSET,
            detail=f"{approver.key_path_env} is unset or empty",
        )
    path = Path(raw)
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise PreconditionError(
            ErrorCode.PRECONDITION_APPROVER_KEY_UNREADABLE,
            detail=f"{path}: {exc}",
        ) from exc
    return path


def attestation_body(login: str, head_sha: str, facts: str) -> str:
    """The review body: who submitted it, that it is not human, and the caller's facts.

    It claims no rule-specific outcome — which checks a merge requires is a
    property of the merge policy, and this review re-verifies none of them — so
    the caller's facts are recorded verbatim instead of prose asserting results
    nobody here checked.
    """
    return (
        f"Automated attestation by `{login}` — **not a human review**.\n\n"
        f"This approving review is machine-submitted and pinned to `{head_sha}`. It "
        "attests only that an approval was requested for that exact commit; merge "
        "authorization is decided outside this review.\n\n"
        f"Authorizing facts: `{facts}`"
    )


def approve_pr(
    *,
    http: HttpTransport,
    runner: CommandRunner,
    ref: PRRef,
    head_sha: str,
    facts: str,
    app_id: int,
    key_path: Path,
    now: int,
) -> str:
    """Submit (or recognize) the App's approving review; return the line to print.

    The head is re-read live and compared before anything is posted, so an
    approval can never land on a commit the caller did not decide on.
    """
    signer = openssl_signer(runner, key_path)
    minted = mint_installation_token(http, build_jwt(app_id, now, signer), ref)

    live_head = read_head_sha(http, minted.token, ref)
    if live_head != head_sha:
        raise PreconditionError(
            ErrorCode.PRECONDITION_APPROVER_HEAD_MOVED,
            detail=f"{ref.display()} now heads at {live_head}, not the named {head_sha}",
        )

    existing = _existing_approval_id(http, minted, ref, head_sha)
    if existing is not None:
        return (
            f"already approved by {minted.login} at {head_sha} (review {existing}) — nothing posted"
        )

    review_id = submit_review(
        http,
        minted.token,
        ref,
        event=APPROVE_EVENT,
        body=attestation_body(minted.login, head_sha, facts),
        commit_id=head_sha,
    )
    return f"approved: review {review_id} by {minted.login} pinned to {head_sha}"


def _existing_approval_id(
    http: HttpTransport, minted: MintedApp, ref: PRRef, head_sha: str
) -> int | None:
    """The id of this App's own APPROVED review at ``head_sha``, if one is there.

    All three conditions matter: another actor's approval does not license this
    one, a comment-only review by the App is not an approval, and an approval of
    an earlier head does not attest the current one.
    """
    for review in iter_reviews(http, minted.token, ref):
        if (
            (review.get("user") or {}).get("login") == minted.login
            and review.get("state") == _APPROVED_STATE
            and review.get("commit_id") == head_sha
        ):
            return int(review["id"])
    return None
