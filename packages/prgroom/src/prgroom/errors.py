"""Failure-tier model, structured-error registry, and exit-code mapping.

Implements source spec §3.6 (failure tiers), §3.7 (error-code registry), and the
§3.3 ``exit_code_for_tier`` translation. Every error code carries a
``what`` / ``why`` / ``how`` triple per the §1 structured-stderr contract so that
both humans and agents can parse a precondition failure and act on it.

The tier determines the process exit code (a serialization contract a scheduler
reads), whether the phase transitions to ``human-gated``, and whether an
``EscalationSink`` event is filed. This module owns only the first concern; the
phase/escalation effects live in the lifecycle (later beads).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from prgroom.prsession.pr_ref import PRRef


class Tier(StrEnum):
    """Failure tier (§3.6). Drives the exit code via :func:`exit_code_for_tier`."""

    PRECONDITION_USER_ERROR = "precondition_user_error"
    PRECONDITION_NO_WORK = "precondition_no_work"
    PRECONDITION_LOCK_HELD = "precondition_lock_held"
    RUNTIME_TRANSIENT = "runtime_transient"
    RUNTIME_TERMINAL_USER = "runtime_terminal_user"
    RUNTIME_CANCELLED = "runtime_cancelled"
    CONTRACT_AUDIT_FAILED = "contract_audit_failed"
    STATE_CORRUPT = "state_corrupt"
    STATE_SCHEMA_UNKNOWN = "state_schema_unknown"
    LIFECYCLE_CAP = "lifecycle_cap"


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """The human/agent-readable description of one error code (§3.7)."""

    what: str
    why: str
    how: str


# The "no-work" tier applies ONLY to this explicitly enumerated set (§3.7) — NOT
# by NO_-prefix matching. Codes added later default to PRECONDITION_USER_ERROR
# and must be added here to gain no-work treatment.
_NO_WORK_CODES: frozenset[str] = frozenset(
    {
        "PRECONDITION_NO_ITEMS",
        "PRECONDITION_NO_CLUSTERS",
        "PRECONDITION_NO_COMMITS",
        "PRECONDITION_NO_UNREPLIED",
        "PRECONDITION_NO_UNRESOLVED",
        "PRECONDITION_NO_ESCALATIONS",
    }
)


class ErrorCode(StrEnum):
    """Stable ``<CATEGORY>_<SPECIFIC>`` identifiers (§3.7).

    The ``.value`` is the wire identifier emitted in stderr and consumed by the
    ``monitor-pr`` supervisor; adding a code is non-breaking, renaming is breaking.
    """

    # PRECONDITION_*
    PRECONDITION_NO_PR_DETECTED = "PRECONDITION_NO_PR_DETECTED"
    PRECONDITION_NO_AUTH = "PRECONDITION_NO_AUTH"
    PRECONDITION_REPO_UNREACHABLE = "PRECONDITION_REPO_UNREACHABLE"
    PRECONDITION_BAD_PR_REF = "PRECONDITION_BAD_PR_REF"
    PRECONDITION_WRONG_BRANCH = "PRECONDITION_WRONG_BRANCH"
    PRECONDITION_NO_ITEMS = "PRECONDITION_NO_ITEMS"
    PRECONDITION_NO_CLUSTERS = "PRECONDITION_NO_CLUSTERS"
    PRECONDITION_NO_COMMITS = "PRECONDITION_NO_COMMITS"
    PRECONDITION_NO_UNREPLIED = "PRECONDITION_NO_UNREPLIED"
    PRECONDITION_NO_UNRESOLVED = "PRECONDITION_NO_UNRESOLVED"
    PRECONDITION_NO_ESCALATIONS = "PRECONDITION_NO_ESCALATIONS"
    PRECONDITION_WAIT_NOT_APPLICABLE = "PRECONDITION_WAIT_NOT_APPLICABLE"
    PRECONDITION_NO_STATE = "PRECONDITION_NO_STATE"
    PRECONDITION_LOCK_HELD = "PRECONDITION_LOCK_HELD"
    PRECONDITION_STORE_UNAVAILABLE = "PRECONDITION_STORE_UNAVAILABLE"
    # RUNTIME_*
    RUNTIME_GH_TRANSIENT = "RUNTIME_GH_TRANSIENT"
    RUNTIME_GH_TERMINAL = "RUNTIME_GH_TERMINAL"
    RUNTIME_GRAPHQL_FAILED = "RUNTIME_GRAPHQL_FAILED"
    RUNTIME_PUSH_REJECTED = "RUNTIME_PUSH_REJECTED"
    RUNTIME_GIT_TRANSIENT = "RUNTIME_GIT_TRANSIENT"
    RUNTIME_GIT_TERMINAL = "RUNTIME_GIT_TERMINAL"
    RUNTIME_AGENT_UNAVAILABLE = "RUNTIME_AGENT_UNAVAILABLE"
    RUNTIME_AGENT_TIMEOUT = "RUNTIME_AGENT_TIMEOUT"
    RUNTIME_CANCELLED_SIGINT = "RUNTIME_CANCELLED_SIGINT"
    RUNTIME_CANCELLED_SIGTERM = "RUNTIME_CANCELLED_SIGTERM"
    # CONTRACT_*
    CONTRACT_CLUSTER_MALFORMED = "CONTRACT_CLUSTER_MALFORMED"
    CONTRACT_CLUSTER_COVERAGE = "CONTRACT_CLUSTER_COVERAGE"
    CONTRACT_FIX_MALFORMED = "CONTRACT_FIX_MALFORMED"
    CONTRACT_FIX_ORPHAN_COMMIT = "CONTRACT_FIX_ORPHAN_COMMIT"
    CONTRACT_FIX_UNREACHABLE_SHA = "CONTRACT_FIX_UNREACHABLE_SHA"
    CONTRACT_FIX_AUDIT_FAILED = "CONTRACT_FIX_AUDIT_FAILED"
    # STATE_*
    STATE_CORRUPT = "STATE_CORRUPT"
    STATE_SCHEMA_UNKNOWN = "STATE_SCHEMA_UNKNOWN"
    # LIFECYCLE_*
    LIFECYCLE_HARD_CAP_EXCEEDED = "LIFECYCLE_HARD_CAP_EXCEEDED"

    def registry_entry(self) -> RegistryEntry:
        """The §3.7 what/why/how triple for this code."""
        return _REGISTRY[self]

    def precondition_tier(self) -> Tier:
        """Tier for a PRECONDITION_* code (§3.7 tier-assignment rules).

        Raises :class:`ValueError` if called on a non-precondition code — only
        precondition codes have a tier resolvable from the code alone.
        """
        if not self.value.startswith("PRECONDITION_"):
            msg = f"{self.value} is not a PRECONDITION_* code"
            raise ValueError(msg)
        if self.value == "PRECONDITION_LOCK_HELD":
            return Tier.PRECONDITION_LOCK_HELD
        if self.value in _NO_WORK_CODES:
            return Tier.PRECONDITION_NO_WORK
        return Tier.PRECONDITION_USER_ERROR


_REGISTRY: dict[ErrorCode, RegistryEntry] = {
    ErrorCode.PRECONDITION_NO_PR_DETECTED: RegistryEntry(
        what="no PR found for the current branch or via positional arg",
        why="every verb requires a PR ref",
        how="pass <pr-number-or-url> or run from a branch with an open PR",
    ),
    ErrorCode.PRECONDITION_NO_AUTH: RegistryEntry(
        what="`gh auth status` failed at the startup precondition check",
        why="every verb requires gh auth",
        how="run `gh auth login`",
    ),
    ErrorCode.PRECONDITION_REPO_UNREACHABLE: RegistryEntry(
        what="gh API returned 404 for the repo",
        why="the repo must be accessible",
        how="verify the repo path and gh token scope",
    ),
    ErrorCode.PRECONDITION_BAD_PR_REF: RegistryEntry(
        what="the provided PR ref is malformed",
        why="a parseable PR ref is required",
        how="pass <number>, <owner>/<repo>#<n>, or a full URL",
    ),
    ErrorCode.PRECONDITION_WRONG_BRANCH: RegistryEntry(
        what="the worktree is not checked out on the PR's head branch",
        why="`push` uploads the local PR-branch HEAD; a stray checkout would publish wrong commits",
        how="check out the PR head branch (or run from its worktree), then re-invoke",
    ),
    ErrorCode.PRECONDITION_NO_ITEMS: RegistryEntry(
        what="the verb requires items but state has none",
        why="each verb declares its preconditions",
        how="run `poll` first",
    ),
    ErrorCode.PRECONDITION_NO_CLUSTERS: RegistryEntry(
        what="`fix` requires clustered items",
        why="clustering precedes fixing",
        how="run `cluster` first",
    ),
    ErrorCode.PRECONDITION_NO_COMMITS: RegistryEntry(
        what="`push` invoked with no local commits queued",
        why="`push` is degenerate without commits",
        how="run `fix` first OR accept the no-op",
    ),
    ErrorCode.PRECONDITION_NO_UNREPLIED: RegistryEntry(
        what="`reply` invoked with no unreplied items",
        why="nothing to do",
        how="exit-0 success-no-op (or exit 2 under --no-prework)",
    ),
    ErrorCode.PRECONDITION_NO_UNRESOLVED: RegistryEntry(
        what="`resolve` invoked with no fixed/already_addressed unresolved items",
        why="nothing to do",
        how="exit-0 success-no-op (or exit 2 under --no-prework)",
    ),
    ErrorCode.PRECONDITION_NO_ESCALATIONS: RegistryEntry(
        what="`resolve-escalated` invoked but no escalated items exist",
        why="nothing to resolve",
        how="re-check `status`; the item may have been resolved already",
    ),
    ErrorCode.PRECONDITION_WAIT_NOT_APPLICABLE: RegistryEntry(
        what="`wait` invoked while phase is fixes-pending",
        why="`wait` is for non-actionable phases; fixes-pending has work to do",
        how="invoke `run` (full cycle) or `fix`+`push` directly",
    ),
    ErrorCode.PRECONDITION_NO_STATE: RegistryEntry(
        what="no grooming state exists for this PR yet",
        why="`status` reads existing state; this PR has never been polled",
        how="run `poll` (or `run`) first to record state, then re-check `status`",
    ),
    ErrorCode.PRECONDITION_LOCK_HELD: RegistryEntry(
        what="another prgroom invocation holds the PR lock",
        why="the concurrency model is one-at-a-time per PR",
        how="wait for the other invocation; the scheduler retries on next cadence",
    ),
    ErrorCode.PRECONDITION_STORE_UNAVAILABLE: RegistryEntry(
        what="the requested store adapter is unavailable",
        why="--store/PRGROOM_STORE named an adapter not usable in this build",
        how="use --store file (the default); 'bd' is deferred to a later release",
    ),
    ErrorCode.RUNTIME_GH_TRANSIENT: RegistryEntry(
        what="gh API returned 5xx or rate-limited with Retry-After",
        why="the external service is degraded",
        how="retry on the next scheduler cadence",
    ),
    ErrorCode.RUNTIME_GH_TERMINAL: RegistryEntry(
        what="gh API returned a 4xx other than 404 or rate-limit",
        why="an auth/scope/permission issue",
        how="inspect stderr; reconfigure the gh token, then re-invoke",
    ),
    ErrorCode.RUNTIME_GRAPHQL_FAILED: RegistryEntry(
        what="the resolveReviewThread GraphQL mutation failed",
        why="the thread may have been resolved externally or the schema drifted",
        how="re-run `resolve`; if persistent, escalate via the sink",
    ),
    ErrorCode.RUNTIME_PUSH_REJECTED: RegistryEntry(
        what="`git push` was rejected (non-fast-forward, hook block, branch protection)",
        why="the local branch diverged or a rule blocks the push",
        how="reconcile manually (rebase, fix hook, adjust protection), then re-run",
    ),
    ErrorCode.RUNTIME_GIT_TRANSIENT: RegistryEntry(
        what="a git network operation timed out",
        why="an upstream connectivity blip",
        how="retry on the next cadence",
    ),
    ErrorCode.RUNTIME_GIT_TERMINAL: RegistryEntry(
        what="the `git` binary is missing or not executable",
        why="a local environment gap a retry won't fix",
        how="install git / repair PATH, then re-invoke",
    ),
    ErrorCode.RUNTIME_AGENT_UNAVAILABLE: RegistryEntry(
        what="the primary AND fallback agent CLIs both failed",
        why="the upstream model/tool is unavailable",
        how="check the claude / codex CLIs; verify quotas",
    ),
    ErrorCode.RUNTIME_AGENT_TIMEOUT: RegistryEntry(
        what="the per-contract time budget was exceeded",
        why="the agent exceeded its budget for one cluster",
        how="re-run; if persistent, raise the budget or shrink the cluster",
    ),
    ErrorCode.RUNTIME_CANCELLED_SIGINT: RegistryEntry(
        what="SIGINT received during a blocking internal (operator pressed Ctrl-C)",
        why="an operator-initiated stop; non-retryable",
        how="inspect state via `prgroom status`; re-invoke `run` when desired",
    ),
    ErrorCode.RUNTIME_CANCELLED_SIGTERM: RegistryEntry(
        what="SIGTERM received during a blocking internal (scheduler/container shutdown)",
        why="an external-initiated stop; non-retryable",
        how="inspect state via `prgroom status`; the scheduler must treat 143 as terminal",
    ),
    ErrorCode.CONTRACT_CLUSTER_MALFORMED: RegistryEntry(
        what="cluster output JSON failed schema validation",
        why="the cluster contract invariant was violated",
        how="retry once; a second failure falls back to per-item clusters",
    ),
    ErrorCode.CONTRACT_CLUSTER_COVERAGE: RegistryEntry(
        what="some input items did not appear in any cluster after fallback",
        why="the cluster contract requires every item be clustered",
        how="re-cluster; if persistent, file a `failed` disposition for orphans",
    ),
    ErrorCode.CONTRACT_FIX_MALFORMED: RegistryEntry(
        what="fix output JSON failed schema validation",
        why="the fix contract invariant was violated",
        how="the item is flipped to `failed`; escalate",
    ),
    ErrorCode.CONTRACT_FIX_ORPHAN_COMMIT: RegistryEntry(
        what="commits exist on the branch that no item claimed",
        why="the fix contract requires every commit be claimed",
        how="stash isolation is applied; affected items are flipped to `failed`; escalate",
    ),
    ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA: RegistryEntry(
        what="output claims a commit SHA that is not on the branch",
        why="the fix contract invariant was violated",
        how="the item is flipped to `failed`; escalate",
    ),
    ErrorCode.CONTRACT_FIX_AUDIT_FAILED: RegistryEntry(
        what="the disposition+evidence combination violated audit rules",
        why="the fix contract post-conditions were not met",
        how="the item is flipped to `failed`; end-of-cycle resolution may promote to human-gated",
    ),
    ErrorCode.STATE_CORRUPT: RegistryEntry(
        what="the state JSON failed to parse",
        why="the state file was written incompletely or hand-edited",
        how="move the state file aside (<file>.corrupt-YYYYMMDD); re-run to rebuild",
    ),
    ErrorCode.STATE_SCHEMA_UNKNOWN: RegistryEntry(
        what="the state schema_version is not recognized",
        why="the CLI is older than the state file (or vice versa)",
        how="upgrade/downgrade the CLI; do not run conflicting versions concurrently",
    ),
    ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED: RegistryEntry(
        what="the pre-push cap guard tripped (queued commits AND round >= max_rounds)",
        why="the hard cap was reached without quiescence",
        how="resolve escalations; raise --max-rounds and re-run, or hand off to human review",
    ),
}


# Codes that gate `resolve-escalated` re-entry (§3.2, §3.6): an operator flipping
# an escalated disposition cannot clear any of these — they require the recovery
# paths in §3.6/§3.7 (cap re-arm, state-file inspection, gh/git reconciliation).
BlockingErrorCodes: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.LIFECYCLE_HARD_CAP_EXCEEDED,
        ErrorCode.STATE_CORRUPT,
        ErrorCode.STATE_SCHEMA_UNKNOWN,
        ErrorCode.RUNTIME_GH_TERMINAL,
        ErrorCode.RUNTIME_PUSH_REJECTED,
        ErrorCode.RUNTIME_GIT_TERMINAL,
    }
)


class PrgroomError(Exception):
    """A tier-tagged runtime error. The tier drives the process exit code.

    ``signum`` is read only for the ``RUNTIME_CANCELLED`` tier (SIGINT=2 -> 130,
    SIGTERM=15 -> 143); it is ignored for every other tier.
    """

    def __init__(self, *, tier: Tier, code: ErrorCode, signum: int = 0, detail: str = "") -> None:
        self.tier = tier
        self.code = code
        self.signum = signum
        self.detail = detail
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


class PreconditionError(PrgroomError):
    """A precondition failure with a structured what/why/how stderr block (§1).

    The tier is derived from the code per the §3.7 precondition tier rules, so a
    caller need only name the code.
    """

    def __init__(self, code: ErrorCode, *, detail: str = "") -> None:
        super().__init__(tier=code.precondition_tier(), code=code, detail=detail)

    def render(self) -> str:
        """Render the canonical 4-line ``error / what / why / how`` block (§1)."""
        entry = self.code.registry_entry()
        return (
            f"error: {self.code.value}\n"
            f"  what: {entry.what}\n"
            f"  why:  {entry.why}\n"
            f"  how:  {entry.how}"
        )


def lock_held_error(ref: PRRef, *, pid: int | None = None) -> PreconditionError:
    """Build the ``PRECONDITION_LOCK_HELD`` error naming the ref and holder pid (§2).

    The detail reads ``another invocation holds the lock for <owner>/<repo>#<n> (pid
    <pid>)`` per the §2 concurrency posture. This lives in ``errors`` (not the
    lifecycle layer) because the **store adapter** raises it on contention, and the
    store cannot import the lifecycle (that would be a backward dependency); ``errors``
    is already a store-layer dependency.

    ``pid`` is the *holder's* pid: the in-memory adapter passes ``os.getpid()`` (same-
    process contention); the file adapter passes the pid it read from the lock file,
    or ``None`` when that read fails. A ``None`` pid renders ``(pid unknown)`` — a
    contention error is NEVER attributed to the contender's own process.
    """
    holder = str(pid) if pid is not None else "unknown"
    return PreconditionError(
        ErrorCode.PRECONDITION_LOCK_HELD,
        detail=f"another invocation holds the lock for {ref.display()} (pid {holder})",
    )


def exit_code_for_tier(err: PrgroomError) -> int:
    """Translate a tier-tagged error into its documented sysexits code (§3.3).

    Every case inspects ``err.tier`` only, EXCEPT ``RUNTIME_CANCELLED`` which
    reads ``err.signum`` to produce ``128 + signum``.
    """
    match err.tier:
        case Tier.PRECONDITION_USER_ERROR:
            return 2  # EX_USAGE
        case Tier.PRECONDITION_NO_WORK:
            return 0  # success-no-op
        case Tier.PRECONDITION_LOCK_HELD:
            return 75  # EX_TEMPFAIL (transient-equivalent for scheduler retry)
        case Tier.RUNTIME_TRANSIENT:
            return 75  # EX_TEMPFAIL
        case Tier.RUNTIME_TERMINAL_USER:
            return 77  # EX_NOPERM
        case Tier.RUNTIME_CANCELLED:
            return 128 + err.signum  # SIGINT(2)->130, SIGTERM(15)->143
        case Tier.CONTRACT_AUDIT_FAILED:
            return 65  # EX_DATAERR
        case Tier.STATE_CORRUPT | Tier.STATE_SCHEMA_UNKNOWN:
            return 78  # EX_CONFIG
        case Tier.LIFECYCLE_CAP:
            return 0  # graceful terminal exit
        case _:  # pragma: no cover - exhaustiveness guard for future Tier members
            # §7.6 closed-match safety: a newly added Tier with no arm above fails
            # loudly here rather than silently returning a bogus code. The match
            # is exhaustive over the current Tier set, so mypy --strict proves
            # this arm unreachable — assert_never is the documented idiom that
            # keeps the guard while satisfying warn_unreachable.
            assert_never(err.tier)
