"""The published shape of the report, pinned field by field.

Every other test in this suite reads model objects through their Python
attributes, so the serialization is exercised on the way past and asserted
nowhere: dropping the `kind` line out of ``Target.as_json`` left all 328 of them
green. What ships is the JSON, and a consumer that switched on a field it no
longer receives finds out in production.

So this asserts the envelope's key set *exactly* -- not a sample -- and the type
behind each key. Exact means a field added here without a line below fails too,
which is the point: this file is the contract, and widening it is a decision
somebody makes on purpose rather than a diff that slips through.

Each type is asserted twice, and the second run is not redundant. A row where
every optional is populated pins the types; a row where every optional is empty
pins that the keys are still all there, holding null -- because `as_json` is
free to build a dict conditionally, and a field that disappears when its value
is None is a field a consumer cannot read without guessing.
"""

from __future__ import annotations

import io
import json
from typing import Any

from conftest import make_branch, make_pr, make_survey, make_worktree
from test_survey import make_port, ref_line

from gitclean.cli import main
from gitclean.execute import ExecutionReport
from gitclean.model import (
    Absent,
    Anomaly,
    Counterpart,
    Deletion,
    MergeEvidence,
    NotOffered,
    Plan,
    Refusal,
    SalvageRecord,
    Skipped,
    Target,
    TargetKind,
)

NONE = type(None)

# -- the spec language -------------------------------------------------------
#
# A spec is a type (exact match), a tuple of specs (any of them), a one-element
# list (a JSON array whose every element matches), or a one-entry dict keyed by
# `*` (a JSON object of unknown keys whose every value matches). A nested object
# with a known key set is spelled `dict` here and asserted against its own spec
# by the test that reaches it -- one level per assertion, so a failure names the
# row it came from.
#
# Types are matched exactly rather than with isinstance, because `isinstance(
# True, int)` is true: a field that silently changed from a count to a flag
# would otherwise still satisfy an `int` spec.


def _matches(value: object, spec: Any) -> bool:
    if isinstance(spec, tuple):
        return any(_matches(value, option) for option in spec)
    if isinstance(spec, list):
        return isinstance(value, list) and all(_matches(item, spec[0]) for item in value)
    if isinstance(spec, dict):
        return isinstance(value, dict) and all(
            type(key) is str and _matches(item, spec["*"]) for key, item in value.items()
        )
    return type(value) is spec


def assert_shape(payload: dict[str, object], spec: dict[str, Any], label: str) -> None:
    assert set(payload) == set(spec), (
        f"{label}: the serialized key set changed -- "
        f"missing {sorted(set(spec) - set(payload))}, "
        f"unexpected {sorted(set(payload) - set(spec))}"
    )
    for key, field_spec in spec.items():
        assert _matches(payload[key], field_spec), (
            f"{label}.{key}: {payload[key]!r} does not match the published type"
        )


# -- the rows ----------------------------------------------------------------

PULL_REQUEST = {
    "number": int,
    "state": str,
    "url": str,
    "updated_at": str,
    "head_oid": str,
}

WORKTREE = {
    "path": str,
    "branch": (str, NONE),
    "head": str,
    "is_main": bool,
    "locked": bool,
    "prunable": bool,
    "dirty": (bool, NONE),
    "dirty_file_count": (int, NONE),
    "untracked_file_count": (int, NONE),
    "ignored_file_count": (int, NONE),
    "last_activity": (str, NONE),
}

BRANCH = {
    "name": str,
    "is_remote": bool,
    "remote": (str, NONE),
    "head": str,
    "last_activity": (str, NONE),
    "upstream": (str, NONE),
    "upstream_ref": (str, NONE),
    "is_default": bool,
    "is_current": bool,
    "checked_out_at": (str, NONE),
    "unpushed_commits": (int, NONE),
    "unmerged_commits": (int, NONE),
    "merged": bool,
    "merge_evidence": str,
    "pr": (dict, NONE),
    "pr_covers_tip": (bool, NONE),
    "probe_failures": [str],
}

COUNTERPART = {"name": (str, NONE), "id": (str, NONE), "known": bool}
"""No `relation` key: it is the object key the counterpart hangs under in
`pairing`, and carrying it twice would let the two disagree."""

TARGET = {
    "id": str,
    "kind": str,
    "name": str,
    "pairing": {"*": dict},
    "merge_evidence": str,
    "merge_proven": bool,
    "sweepable": bool,
    "withheld": (str, NONE),
    "reasons": [str],
    "last_activity": (str, NONE),
}

NOT_OFFERED = {"name": str, "reason": str}

SURVEY = {
    "repo_root": str,
    "git_common_dir": str,
    "base_ref": str,
    "default_branch": str,
    "default_branch_known": bool,
    "current_branch": (str, NONE),
    "gh_available": bool,
    "gh_error": (str, NONE),
    "pr_evidence_gap": (str, NONE),
    "warnings": [str],
    "worktrees": [dict],
    "branches": [dict],
    "branches_known": bool,
    "worktrees_known": bool,
    "dropped_refs": int,
    "dropped_worktrees": int,
    "not_offered": [dict],
}

ANOMALY = {"stage": str, "target_id": (str, NONE), "message": str, "transcript": [str]}

SALVAGE = {"target_id": str, "kind": str, "path": str, "verified": bool, "detail": str}

DELETION = {
    "target_id": str,
    "kind": str,
    "name": str,
    "deleted": bool,
    "verified": bool,
    "detail": str,
    "already_absent": bool,
}

SKIPPED = {"target_id": str, "name": str, "reason": str}

ABSENT = {"selector": str, "note": str}

PLAN = {
    "targets": [dict],
    "salvage_dir": (str, NONE),
    "dry_run": bool,
    "skipped": [dict],
    "absent": [dict],
}

EXECUTION = {
    "deletions": [dict],
    "salvages": [dict],
    "anomalies": [dict],
    "salvage_dir": (str, NONE),
}

REFUSAL = {"code": str, "message": str, "blocked": [dict], "remedy": str}

SUMMARY = {"total": int, "sweepable_now": int, "by_merge_evidence": {"*": int}}

ENVELOPE = {
    "gitclean": str,
    "ok": bool,
    "mode": str,
    "warnings": [str],
    "repo": (dict, NONE),
    "summary": dict,
    "targets": [dict],
    "plan": (dict, NONE),
    "execution": (dict, NONE),
    "refusal": (dict, NONE),
    "error": (str, NONE),
}


def _target(**kwargs: object) -> Target:
    fields: dict[str, object] = {
        "id": "branch:feat/thing",
        "kind": TargetKind.BRANCH,
        "name": "feat/thing",
        "merge_evidence": MergeEvidence.SQUASH_EQUAL,
        "merge_proven": True,
        "sweepable": False,
        "withheld": "a reason",
        "reasons": ("a measurement",),
        "last_activity": "2026-07-24T00:00:00+00:00",
        "pairing": (
            Counterpart(relation="worktree", name="/repo/wt", id="worktree:/repo/wt", known=True),
            Counterpart(relation="upstream", name=None, id=None, known=True),
        ),
    }
    fields.update(kwargs)
    return Target(**fields)  # type: ignore[arg-type]


# -- every row, populated and empty ------------------------------------------


def test_a_pull_request_row_holds_exactly_its_published_fields() -> None:
    assert_shape(make_pr().as_json(), PULL_REQUEST, "pr")


def test_a_worktree_row_holds_exactly_its_published_fields() -> None:
    assert_shape(make_worktree().as_json(), WORKTREE, "worktree")
    unread = make_worktree(branch=None, dirty_file_count=None, last_activity=None)
    assert_shape(unread.as_json(), WORKTREE, "worktree (nothing answered)")


def test_a_branch_row_holds_exactly_its_published_fields() -> None:
    full = make_branch(pr=make_pr(), checked_out_at="/repo/wt", probe_failures=("a probe",))
    assert_shape(full.as_json(), BRANCH, "branch")
    pr = full.as_json()["pr"]
    assert isinstance(pr, dict)
    assert_shape(pr, PULL_REQUEST, "branch.pr")

    bare = make_branch(
        upstream=None,
        last_activity=None,
        unpushed_commits=None,
        unmerged_commits=None,
        pr=None,
    )
    assert_shape(bare.as_json(), BRANCH, "branch (nothing answered)")


def test_a_target_row_holds_exactly_its_published_fields() -> None:
    payload = _target().as_json()
    assert_shape(payload, TARGET, "target")
    assert_shape(_target(withheld=None, last_activity=None, pairing=()).as_json(), TARGET, "target")

    # The pairing is an object keyed by relation, and each entry is a
    # counterpart row: this is the structure a reader groups the table by, so
    # both halves of it are pinned rather than the outer dict alone.
    pairing = payload["pairing"]
    assert isinstance(pairing, dict)
    assert set(pairing) == {"worktree", "upstream"}
    for relation, entry in pairing.items():
        assert isinstance(entry, dict)
        assert_shape(entry, COUNTERPART, f"target.pairing.{relation}")


def test_a_survey_holds_exactly_its_published_fields() -> None:
    full = make_survey(
        branches=(make_branch(),),
        worktrees=(make_worktree(),),
        not_offered=(NotOffered(name="origin/main", reason="the trunk"),),
        warnings=("a probe did not answer",),
        gh_error="gh failed",
        pr_evidence_gap="the list was truncated",
    )
    payload = full.as_json()
    assert_shape(payload, SURVEY, "repo")
    for key, spec in (
        ("branches", BRANCH),
        ("worktrees", WORKTREE),
        ("not_offered", NOT_OFFERED),
    ):
        rows = payload[key]
        assert isinstance(rows, list)
        assert_shape(rows[0], spec, f"repo.{key}[0]")

    assert_shape(make_survey(current_branch=None).as_json(), SURVEY, "repo (empty)")


def test_the_execution_rows_hold_exactly_their_published_fields() -> None:
    report = ExecutionReport(
        deletions=(
            Deletion(
                target_id="branch:feat/thing",
                kind=TargetKind.BRANCH,
                name="feat/thing",
                deleted=True,
                verified=True,
                detail="deleted",
            ),
        ),
        salvages=(
            SalvageRecord(
                target_id="remote:origin/feat/thing",
                kind="bundle",
                path="/repo/.gitclean-salvage/feat-thing.bundle",
                verified=True,
                detail="restored",
            ),
        ),
        anomalies=(
            Anomaly(
                stage="delete",
                target_id="branch:feat/thing",
                message="git refused",
                transcript=("git branch -D -- feat/thing", "exit 1"),
            ),
        ),
        salvage_dir="/repo/.gitclean-salvage",
    )
    payload = report.as_json()
    assert_shape(payload, EXECUTION, "execution")
    for key, spec in (("deletions", DELETION), ("salvages", SALVAGE), ("anomalies", ANOMALY)):
        rows = payload[key]
        assert isinstance(rows, list)
        assert_shape(rows[0], spec, f"execution.{key}[0]")

    empty = ExecutionReport(deletions=(), salvages=(), anomalies=(), salvage_dir=None)
    assert_shape(empty.as_json(), EXECUTION, "execution (nothing done)")
    assert_shape(
        Anomaly(stage="survey", target_id=None, message="m", transcript=()).as_json(),
        ANOMALY,
        "anomaly (no target)",
    )


def test_a_plan_holds_exactly_its_published_fields() -> None:
    full = Plan(
        targets=(_target(),),
        salvage_dir="/repo/.gitclean-salvage",
        dry_run=True,
        skipped=(Skipped(target_id="branch:feat/thing", name="feat/thing", reason="held"),),
        absent=(Absent(selector="feat/gone", note="nothing matched"),),
    )
    payload = full.as_json()
    assert_shape(payload, PLAN, "plan")
    for key, spec in (("targets", TARGET), ("skipped", SKIPPED), ("absent", ABSENT)):
        rows = payload[key]
        assert isinstance(rows, list)
        assert_shape(rows[0], spec, f"plan.{key}[0]")

    assert_shape(
        Plan(targets=(), salvage_dir=None, dry_run=False).as_json(), PLAN, "plan (do nothing)"
    )


def test_a_refusal_holds_exactly_its_published_fields() -> None:
    refusal = Refusal(
        code="E_AMBIGUOUS", message="two things match", blocked=(_target(),), remedy="name one"
    )
    payload = refusal.as_json()
    assert_shape(payload, REFUSAL, "refusal")
    blocked = payload["blocked"]
    assert isinstance(blocked, list)
    assert_shape(blocked[0], TARGET, "refusal.blocked[0]")

    assert_shape(Refusal(code="E_X", message="m").as_json(), REFUSAL, "refusal (bare)")


# -- the wire vocabulary -----------------------------------------------------


def test_the_evidence_tiers_are_spelled_the_way_the_report_publishes_them() -> None:
    """Written out rather than derived from the enum, which would only assert
    that the enum equals itself. These strings are what a consumer switches on,
    and renaming a member is a change to the report even when nothing in Python
    notices."""
    assert {e.value for e in MergeEvidence} == {
        "pr_merged",
        "pr_closed_unmerged",
        "ancestor",
        "patch_equal",
        "squash_equal",
        "none",
    }
    assert {k.value for k in TargetKind} == {"worktree", "branch", "remote_branch"}


# -- the envelope the CLI actually emits -------------------------------------


def test_the_report_envelope_holds_exactly_its_published_fields() -> None:
    """Assembled by the CLI rather than by hand, because the envelope is the
    only one of these a caller receives whole. The repository behind it is the
    smallest the survey will describe -- a trunk, its worktree -- since what is
    under test is the shape, not the survey's content."""
    port = make_port(
        refs=[ref_line("refs/heads/main", "main", upstream="origin/main", head="*")],
        has_gh=False,
    )
    buffer = io.StringIO()
    assert main(["--report"], port=port, out=buffer) == 0
    payload = json.loads(buffer.getvalue())

    assert_shape(payload, ENVELOPE, "envelope")
    assert_shape(payload["repo"], SURVEY, "envelope.repo")
    assert_shape(payload["summary"], SUMMARY, "envelope.summary")
    assert_shape(payload["targets"][0], TARGET, "envelope.targets[0]")
    branches = payload["repo"]["branches"]
    assert_shape(branches[0], BRANCH, "envelope.repo.branches[0]")
    assert_shape(payload["repo"]["worktrees"][0], WORKTREE, "envelope.repo.worktrees[0]")

    # A report builds no plan and deletes nothing, and says so with the keys
    # present and null rather than by leaving them out.
    assert payload["plan"] is None
    assert payload["execution"] is None
    assert payload["refusal"] is None

    # Every tier is a key in the breakdown whether or not anything landed in it,
    # so a caller can read a zero instead of a KeyError.
    assert set(payload["summary"]["by_merge_evidence"]) == {e.value for e in MergeEvidence}
