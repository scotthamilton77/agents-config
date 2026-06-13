"""Pure fix-output validator (§5 fix audit guards).

These functions are pure: the caller (:mod:`prgroom.agent.fix`) computes the two
git-derived commit sets and passes them in, so the audit is unit-testable
without a repository. Reachability is **set membership only** — the caller
derives the sets from ``git rev_list``.

The two sets:

* ``ancestors_of_pre`` — commits reachable from the pre-cluster baseline
  (``rev-list <pre>``). A commit here predates the fix work.
* ``new_in_cluster`` — commits introduced by the fix work
  (``rev-list <pre>..<post>``). A commit here is brand-new on the branch.

§5 fix audit guards:

* ``fixed`` → ≥1 claimed sha, and every claimed sha is a NEW commit
  (``∈ new_in_cluster``). No commits → ``CONTRACT_FIX_AUDIT_FAILED``; a sha in
  neither set → ``CONTRACT_FIX_UNREACHABLE_SHA``; a sha that is a pre-baseline
  ancestor → ``CONTRACT_FIX_AUDIT_FAILED`` (a ``fixed`` must be new work).
* ``already_addressed`` → every claimed sha predates the baseline
  (``∈ ancestors_of_pre``). A sha in neither set → ``CONTRACT_FIX_UNREACHABLE_SHA``;
  a brand-new sha → ``CONTRACT_FIX_AUDIT_FAILED`` (claims pre-existing but isn't).
* ``skipped | deferred | wont_fix | escalated | failed`` → non-empty rationale,
  else ``CONTRACT_FIX_AUDIT_FAILED``.
* Orphan check: every sha in ``new_in_cluster`` must be claimed by some item;
  any unclaimed → one structural ``CONTRACT_FIX_ORPHAN_COMMIT`` (``gh_id=None``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prgroom.agent.errors import AuditViolation
from prgroom.errors import ErrorCode
from prgroom.prsession.enums import DispositionKind

if TYPE_CHECKING:
    from prgroom.agent.contracts import FixInput, FixItemResult, FixOutput

_RATIONALE_REQUIRED = frozenset(
    {
        DispositionKind.SKIPPED,
        DispositionKind.DEFERRED,
        DispositionKind.WONT_FIX,
        DispositionKind.ESCALATED,
        DispositionKind.FAILED,
    }
)


def audit_fix_items(
    req: FixInput,
    out: FixOutput,
    *,
    ancestors_of_pre: set[str],
    new_in_cluster: set[str],
) -> dict[str, AuditViolation]:
    """Validate each fix item's disposition+evidence. Pure; keyed by gh_id."""
    del req  # the items carry their own gh_id; req is part of the uniform signature
    violations: dict[str, AuditViolation] = {}
    for row in out.items:
        violation = _audit_one(
            row, ancestors_of_pre=ancestors_of_pre, new_in_cluster=new_in_cluster
        )
        if violation is not None:
            violations[row.gh_id] = violation
    return violations


def _audit_one(
    row: FixItemResult, *, ancestors_of_pre: set[str], new_in_cluster: set[str]
) -> AuditViolation | None:
    if row.disposition is DispositionKind.FIXED:
        return _audit_fixed(row, ancestors_of_pre=ancestors_of_pre, new_in_cluster=new_in_cluster)
    if row.disposition is DispositionKind.ALREADY_ADDRESSED:
        return _audit_already_addressed(
            row, ancestors_of_pre=ancestors_of_pre, new_in_cluster=new_in_cluster
        )
    if row.disposition in _RATIONALE_REQUIRED:
        return _audit_rationale(row)
    return None  # pragma: no cover  # exhaustive over DispositionKind; defensive guard


def _fail(row: FixItemResult, detail: str) -> AuditViolation:
    return AuditViolation(code=ErrorCode.CONTRACT_FIX_AUDIT_FAILED, detail=detail, gh_id=row.gh_id)


def _unreachable(row: FixItemResult, sha: str) -> AuditViolation:
    return AuditViolation(
        code=ErrorCode.CONTRACT_FIX_UNREACHABLE_SHA,
        detail=f"item {row.gh_id!r} claims unreachable sha {sha!r}",
        gh_id=row.gh_id,
    )


def _audit_fixed(
    row: FixItemResult, *, ancestors_of_pre: set[str], new_in_cluster: set[str]
) -> AuditViolation | None:
    # First offending sha wins: the item fails as a whole regardless of which sha
    # tripped it (the contract is one violation per item, keyed by gh_id), so there
    # is no value in collecting every bad sha.
    if not row.commit_shas:
        return _fail(row, f"item {row.gh_id!r} is 'fixed' but claims no commits")
    for sha in row.commit_shas:
        if sha in new_in_cluster:
            continue
        if sha in ancestors_of_pre:
            return _fail(row, f"item {row.gh_id!r} 'fixed' claims pre-baseline commit {sha!r}")
        return _unreachable(row, sha)
    return None


def _audit_already_addressed(
    row: FixItemResult, *, ancestors_of_pre: set[str], new_in_cluster: set[str]
) -> AuditViolation | None:
    # commit_shas is REQUIRED for already_addressed (§5, same as fixed): the
    # disposition asserts a prior commit handles the item, so it must name one.
    if not row.commit_shas:
        return _fail(row, f"item {row.gh_id!r} is 'already_addressed' but claims no commits")
    # First offending sha wins (see _audit_fixed): one violation per item.
    for sha in row.commit_shas:
        if sha in ancestors_of_pre:
            continue
        if sha in new_in_cluster:
            return _fail(
                row, f"item {row.gh_id!r} 'already_addressed' claims brand-new commit {sha!r}"
            )
        return _unreachable(row, sha)
    return None


def _audit_rationale(row: FixItemResult) -> AuditViolation | None:
    if not row.rationale.strip():
        return _fail(row, f"item {row.gh_id!r} '{row.disposition.value}' has an empty rationale")
    return None


def audit_orphans(out: FixOutput, *, new_in_cluster: set[str]) -> AuditViolation | None:
    """Every new commit must be claimed by some item; else one structural orphan."""
    claimed = {sha for row in out.items for sha in row.commit_shas}
    orphans = sorted(new_in_cluster - claimed)
    if not orphans:
        return None
    return AuditViolation(
        code=ErrorCode.CONTRACT_FIX_ORPHAN_COMMIT,
        detail=f"unclaimed commits on the branch: {orphans}",
        gh_id=None,
    )
