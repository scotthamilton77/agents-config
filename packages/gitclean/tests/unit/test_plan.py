"""Tests for selection, refusal, and ordering."""

from __future__ import annotations

from conftest import make_branch, make_survey

from gitclean.model import Disposition, Plan, Refusal, Risk, Target, TargetKind
from gitclean.plan import build_plan, resolve_selectors


def target(
    ident: str,
    *,
    kind: TargetKind = TargetKind.BRANCH,
    name: str | None = None,
    disposition: Disposition = Disposition.SAFE,
    risk: Risk = Risk.NONE,
) -> Target:
    resolved = name if name is not None else ident.split(":", 1)[1]
    return Target(
        id=ident,
        kind=kind,
        name=resolved,
        disposition=disposition,
        risk=risk,
        reasons=(),
        last_activity=None,
        salvage_needed=risk is not Risk.NONE,
    )


def plan_for(
    targets: tuple[Target, ...],
    *,
    survey=None,  # type: ignore[no-untyped-def]
    selectors: list[str] | None = None,
    clean_all: bool = False,
    force: bool = False,
    include_remote: bool = False,
) -> Plan | Refusal:
    return build_plan(
        targets,
        survey if survey is not None else make_survey(),
        selectors=selectors or [],
        clean_all=clean_all,
        force=force,
        include_remote=include_remote,
        dry_run=False,
        salvage_dir="/salvage",
    )


# -- the default sweep -------------------------------------------------------


def test_bare_cleanup_takes_only_safe_and_riskless() -> None:
    targets = (
        target("branch:merged"),
        target("branch:abandoned", disposition=Disposition.ABANDONED, risk=Risk.RECOVERABLE),
        target("branch:active", disposition=Disposition.ACTIVE),
        target("branch:safe-but-risky", risk=Risk.RECOVERABLE),
    )
    result = plan_for(targets)
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["merged"]


def test_remote_branches_need_include_remote() -> None:
    targets = (target("remote:origin/merged", kind=TargetKind.REMOTE_BRANCH),)
    assert not plan_for(targets).targets  # type: ignore[union-attr]
    widened = plan_for(targets, include_remote=True)
    assert isinstance(widened, Plan)
    assert [t.name for t in widened.targets] == ["origin/merged"]


def test_naming_a_remote_branch_without_include_remote_is_refused_not_ignored() -> None:
    """Dropping it silently returns a successful, empty plan. The caller reads
    that as "the ref is gone" and moves on; the server still has it."""
    targets = (target("remote:origin/merged", kind=TargetKind.REMOTE_BRANCH),)

    result = plan_for(targets, selectors=["origin/merged"])

    assert isinstance(result, Refusal)
    assert result.code == "E_REMOTE_NOT_ENABLED"
    assert [t.name for t in result.blocked] == ["origin/merged"]
    assert "--include-remote" in result.remedy


def test_an_automatic_sweep_still_passes_over_remote_branches_quietly() -> None:
    """Nobody asked for them, so there is nothing to refuse -- the refusal is
    for a caller who named one and would otherwise be misled."""
    targets = (
        target("remote:origin/merged", kind=TargetKind.REMOTE_BRANCH),
        target("branch:local"),
    )

    result = plan_for(targets)

    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["local"]


# -- --clean-all -------------------------------------------------------------


def test_clean_all_without_force_is_refused() -> None:
    result = plan_for((target("branch:x"),), clean_all=True)
    assert isinstance(result, Refusal)
    assert result.code == "E_CLEAN_ALL_REQUIRES_FORCE"


def test_clean_all_with_force_takes_everything_unprotected() -> None:
    targets = (
        target("branch:merged"),
        target("branch:abandoned", disposition=Disposition.ABANDONED, risk=Risk.RECOVERABLE),
        target("branch:main", disposition=Disposition.PROTECTED),
    )
    result = plan_for(targets, clean_all=True, force=True)
    assert isinstance(result, Plan)
    assert sorted(t.name for t in result.targets) == ["abandoned", "merged"]


# -- protection is not overridable -------------------------------------------


def test_force_does_not_override_protected() -> None:
    targets = (target("branch:main", disposition=Disposition.PROTECTED),)
    result = plan_for(targets, selectors=["main"], force=True)
    assert isinstance(result, Refusal)
    assert result.code == "E_PROTECTED"


# -- data loss ---------------------------------------------------------------


def test_named_risky_target_is_refused_without_force() -> None:
    targets = (target("branch:wip", risk=Risk.RECOVERABLE),)
    result = plan_for(targets, selectors=["wip"])
    assert isinstance(result, Refusal)
    assert result.code == "E_DATA_LOSS"
    assert [t.name for t in result.blocked] == ["wip"]


def test_refusal_names_the_blocked_targets_not_just_the_flag() -> None:
    """A refusal that only says 'pass --force' teaches the reader to pass
    --force. Listing the blockers lets them drop those instead."""
    targets = (
        target("branch:wip-a", risk=Risk.RECOVERABLE),
        target("branch:wip-b", risk=Risk.DATA_LOSS),
    )
    result = plan_for(targets, selectors=["wip-a", "wip-b"])
    assert isinstance(result, Refusal)
    assert {t.name for t in result.blocked} == {"wip-a", "wip-b"}


def test_force_admits_risky_targets_and_sets_a_salvage_dir() -> None:
    targets = (target("branch:wip", risk=Risk.RECOVERABLE),)
    result = plan_for(targets, selectors=["wip"], force=True)
    assert isinstance(result, Plan)
    assert result.salvage_dir == "/salvage"


def test_no_salvage_dir_when_nothing_needs_salvaging() -> None:
    result = plan_for((target("branch:merged"),))
    assert isinstance(result, Plan)
    assert result.salvage_dir is None


# -- selector resolution -----------------------------------------------------


def test_unknown_selector_is_refused() -> None:
    result = plan_for((target("branch:x"),), selectors=["nope"])
    assert isinstance(result, Refusal)
    assert result.code == "E_UNKNOWN_TARGET"


def test_ambiguous_bare_name_is_refused_with_the_candidates() -> None:
    """`feat/x` names both the local branch and origin's copy. Guessing which
    one the caller meant is how the wrong ref gets deleted."""
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
    )
    result = plan_for(targets, selectors=["feat/x"], include_remote=True)
    assert isinstance(result, Refusal)
    assert result.code == "E_AMBIGUOUS_TARGET"
    assert len(result.blocked) == 2


def test_exact_id_disambiguates() -> None:
    targets = (
        target("branch:feat/x"),
        target("remote:origin/feat/x", kind=TargetKind.REMOTE_BRANCH),
    )
    result = plan_for(targets, selectors=["branch:feat/x"], include_remote=True)
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["branch:feat/x"]


def test_worktree_selectable_by_basename() -> None:
    targets = (target("worktree:/repo/wt/feature", kind=TargetKind.WORKTREE),)
    result = plan_for(targets, selectors=["feature"])
    assert isinstance(result, Plan)
    assert [t.id for t in result.targets] == ["worktree:/repo/wt/feature"]


def test_repeated_selector_is_not_planned_twice() -> None:
    targets = (target("branch:x"),)
    result = plan_for(targets, selectors=["x", "branch:x"])
    assert isinstance(result, Plan)
    assert len(result.targets) == 1


def test_resolve_selectors_returns_targets_in_request_order() -> None:
    targets = (target("branch:a"), target("branch:b"))
    resolved, refusal = resolve_selectors(["b", "a"], targets)
    assert refusal is None
    assert [t.name for t in resolved] == ["b", "a"]


# -- worktree occupancy ------------------------------------------------------


def _occupied_survey():  # type: ignore[no-untyped-def]
    return make_survey(branches=(make_branch("held", checked_out_at="/repo/wt"),))


def test_named_occupied_branch_is_refused() -> None:
    result = plan_for((target("branch:held"),), survey=_occupied_survey(), selectors=["held"])
    assert isinstance(result, Refusal)
    assert result.code == "E_BRANCH_IN_USE"


def test_automatic_sweep_skips_an_occupied_branch_instead_of_refusing() -> None:
    """One occupied branch must not block cleaning everything else."""
    targets = (target("branch:held"), target("branch:free"))
    result = plan_for(targets, survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["free"]


def test_a_skipped_target_is_reported_never_silently_dropped() -> None:
    result = plan_for((target("branch:held"),), survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [s.name for s in result.skipped] == ["held"]
    assert "/repo/wt" in result.skipped[0].reason


def test_occupancy_resolves_when_the_worktree_is_also_being_removed() -> None:
    targets = (
        target("worktree:/repo/wt", kind=TargetKind.WORKTREE),
        target("branch:held"),
    )
    result = plan_for(targets, survey=_occupied_survey())
    assert isinstance(result, Plan)
    assert [t.name for t in result.targets] == ["/repo/wt", "held"]


# -- ordering ----------------------------------------------------------------


def test_plan_orders_worktrees_then_local_then_remote() -> None:
    targets = (
        target("remote:origin/z", kind=TargetKind.REMOTE_BRANCH),
        target("branch:b"),
        target("worktree:/repo/w", kind=TargetKind.WORKTREE),
    )
    result = plan_for(targets, clean_all=True, force=True, include_remote=True)
    assert isinstance(result, Plan)
    assert [t.kind.value for t in result.targets] == ["worktree", "branch", "remote_branch"]
