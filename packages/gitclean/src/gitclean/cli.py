"""Argument parsing, the JSON envelope, and the human renderer.

Cleanup re-surveys before it acts. The report the caller read may be minutes
old; a branch can gain commits or a worktree can go dirty in that window, and
acting on the stale classification is precisely the failure this tool exists
to prevent. So --cleanup runs the full survey and classification again, and
plans against what is true now.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from gitclean import get_version
from gitclean.classify import classify
from gitclean.execute import ExecutionReport, Executor, default_salvage_dir
from gitclean.model import MergeEvidence, Plan, Refusal, Survey, Target
from gitclean.plan import build_plan
from gitclean.ports import CommandPort, SubprocessCommands
from gitclean.survey import survey as run_survey

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_ANOMALY = 3

_EPILOG = """\
modes:
  --report                 survey only; emits the full measured state as JSON
  --cleanup [NAME ...]     sweep what is provably merged, or delete exactly the named targets

what a bare --cleanup takes:
  a target whose merge_evidence is pr_merged, ancestor, patch_equal or squash_equal,
  that is not the trunk or the ref merges are measured against, that is not a server
  ref, that is not the worktree this run is executing in, and -- for a worktree --
  whose working tree git reported clean. Everything else is reported with `withheld`
  saying which of those was not met.

naming a target deletes it. Nothing is re-derived, no flag is demanded, and git's
own refusals -- a checked-out branch, a dirty or locked worktree -- stand as they are.

a name that matches nothing is not an error, once nothing-matched actually means gone.
It lands in `plan.absent` with a note and the other named targets are still deleted. A
server ref the remote no longer advertises settles the same way, as `already_absent`,
without writing a salvage bundle for something that is not there to lose. Neither is
reported as work done: `deleted` stays false, because only a true there means the tool
acted.

it refuses instead where nothing-matched proves nothing -- when no ref could be read at
all, and when the name is a ref this tool does not offer as a target, such as the
server's copy of the trunk. Both of those look identical to an absent name and neither
one is, so saying "already gone" about them would be a false report.

examples:
  gitclean --report --format human
  gitclean --cleanup --dry-run
  gitclean --cleanup feat/old-thing worktree:/path/to/wt
  gitclean --cleanup origin/feat/old-thing
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitclean",
        description="Survey git worktrees and branches; clean up what is verifiably safe.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"gitclean {get_version()}")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="survey and classify; change nothing")
    mode.add_argument(
        "--cleanup",
        nargs="*",
        metavar="NAME",
        help="delete the safe subset, or exactly the named worktrees/branches",
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="resolve and report the plan without executing it"
    )
    parser.add_argument(
        "--salvage-dir",
        metavar="DIR",
        help="where a remote ref is bundled before it is deleted from the server",
    )
    parser.add_argument(
        "--format", choices=("json", "human"), default="json", help="output format (default json)"
    )
    return parser


def _envelope(
    mode: str,
    *,
    ok: bool,
    survey_data: Survey | None = None,
    targets: tuple[Target, ...] = (),
    plan: Plan | None = None,
    execution: ExecutionReport | None = None,
    refusal: Refusal | None = None,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "gitclean": get_version(),
        "ok": ok,
        "mode": mode,
        # Hoisted out of `repo` deliberately. `ok` says the run did what it was
        # asked; it does not say the survey could see everything. A reader who
        # checks one field must not have to dig for the degradations, so they
        # sit at the top level -- `repo.warnings` and `repo.gh_error` keep the
        # structured detail for anyone who needs to tell them apart.
        "warnings": list(survey_data.all_warnings()) if survey_data else [],
        "repo": survey_data.as_json() if survey_data else None,
        "summary": _summary(targets),
        "targets": [t.as_json() for t in targets],
        "plan": plan.as_json() if plan else None,
        "execution": execution.as_json() if execution else None,
        "refusal": refusal.as_json() if refusal else None,
        "error": error,
    }


def _summary(targets: tuple[Target, ...]) -> dict[str, object]:
    """Counts only. The evidence breakdown is the one distribution worth having
    at a glance: it says how much of this repository the tool can account for,
    and every tier in it is a claim a reader can go and check."""
    by_evidence: dict[str, int] = {e.value: 0 for e in MergeEvidence}
    for target in targets:
        by_evidence[target.merge_evidence.value] += 1
    return {
        "total": len(targets),
        "sweepable_now": sum(1 for t in targets if t.sweepable),
        "by_merge_evidence": by_evidence,
    }


def _planned_ids(payload: dict[str, object]) -> frozenset[str]:
    """The targets this run acts on, which is not the same set as the ones a
    bare sweep would have taken."""
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return frozenset()
    targets = plan.get("targets")
    if not isinstance(targets, list):
        return frozenset()
    return frozenset(
        str(t["id"]) for t in targets if isinstance(t, dict) and isinstance(t.get("id"), str)
    )


def _deletion_mark(entry: dict[str, object], *, dry: bool) -> str:
    """`gone` outranks `plan`: a target that is already absent is a settled
    fact rather than something a later run would still get to, and a preview
    saying `plan` for it would be promising work that does not exist."""
    if entry.get("already_absent"):
        return "gone"
    if dry:
        return "plan"
    return "ok  " if entry.get("verified") else "FAIL"


def _render_human(payload: dict[str, object], out: TextIO) -> None:
    repo = payload.get("repo")
    if isinstance(repo, dict):
        print(f"repo:  {repo.get('repo_root')}", file=out)
        print(f"base:  {repo.get('base_ref')}", file=out)

    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            print(f"WARN:  {warning}", file=out)

    # `sweepable` answers "would an unattended run take this", which stops
    # being the interesting question the moment a caller names something.
    # Rendering `not swept: no merge proof` six lines above `ok -- deleted`
    # for the same target reads as a contradiction, and the reader has to
    # know which field wins to resolve it. The plan is what was acted on, so
    # the plan is what the row reports.
    planned = _planned_ids(payload)
    targets = payload.get("targets")
    if isinstance(targets, list) and targets:
        print("", file=out)
        for entry in targets:
            if not isinstance(entry, dict):
                continue
            named = entry.get("id") in planned
            mark = "NAMED" if named else ("sweep" if entry.get("sweepable") else "hold ")
            print(
                f"  [{mark}] [{entry.get('merge_evidence'):<18}] {entry.get('id')}",
                file=out,
            )
            reasons = entry.get("reasons")
            if isinstance(reasons, list):
                for reason in reasons:
                    print(f"      - {reason}", file=out)
            if named:
                print("      named on the command line: this run acts on it", file=out)
            elif entry.get("withheld"):
                print(f"      not swept: {entry.get('withheld')}", file=out)

    summary = payload.get("summary")
    if isinstance(summary, dict):
        print("", file=out)
        print(
            f"total: {summary.get('total')}  sweepable now: {summary.get('sweepable_now')}",
            file=out,
        )

    refusal = payload.get("refusal")
    if isinstance(refusal, dict):
        print("", file=out)
        print(f"REFUSED ({refusal.get('code')}): {refusal.get('message')}", file=out)
        print(f"  remedy: {refusal.get('remedy')}", file=out)

    plan = payload.get("plan")
    # A dry run leaves every deletion unverified by construction. Rendering
    # that as FAIL would teach the reader to distrust a clean preview.
    dry = isinstance(plan, dict) and bool(plan.get("dry_run"))
    if isinstance(plan, dict):
        skipped = plan.get("skipped")
        if isinstance(skipped, list) and skipped:
            print("", file=out)
            for entry in skipped:
                if isinstance(entry, dict):
                    print(f"  SKIPPED {entry.get('name')} -- {entry.get('reason')}", file=out)
        # Printed rather than passed over in silence. The run did what was
        # asked, so it is not a failure -- but a name that matched nothing is
        # also how a typo looks, and the reader is the only one who can tell
        # the two apart.
        absent = plan.get("absent")
        if isinstance(absent, list) and absent:
            print("", file=out)
            for entry in absent:
                if isinstance(entry, dict):
                    print(f"  ABSENT  {entry.get('selector')} -- {entry.get('note')}", file=out)

    execution = payload.get("execution")
    if isinstance(execution, dict):
        print("", file=out)
        deletions = execution.get("deletions")
        if isinstance(deletions, list):
            for entry in deletions:
                if isinstance(entry, dict):
                    mark = _deletion_mark(entry, dry=dry)
                    print(f"  {mark} {entry.get('name')} -- {entry.get('detail')}", file=out)
        if execution.get("salvage_dir"):
            print(f"  salvage: {execution.get('salvage_dir')}", file=out)
        anomalies = execution.get("anomalies")
        if isinstance(anomalies, list) and anomalies:
            print("", file=out)
            for entry in anomalies:
                if isinstance(entry, dict):
                    print(f"  ANOMALY [{entry.get('stage')}] {entry.get('message')}", file=out)
                    transcript = entry.get("transcript")
                    if isinstance(transcript, list):
                        for line in transcript:
                            print(f"      {line}", file=out)


def _emit(payload: dict[str, object], fmt: str, out: TextIO) -> None:
    if fmt == "human":
        _render_human(payload, out)
    else:
        print(json.dumps(payload, indent=2, sort_keys=False), file=out)


def main(
    argv: list[str] | None = None,
    *,
    port: CommandPort | None = None,
    now: datetime | None = None,
    cwd: Path | None = None,
    out: TextIO | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout
    runner: CommandPort = port if port is not None else SubprocessCommands()
    moment = now if now is not None else datetime.now(UTC)
    mode = "report" if args.report else "cleanup"

    surveyed = run_survey(runner, cwd=cwd)
    if isinstance(surveyed, str):
        _emit(_envelope(mode, ok=False, error=surveyed), args.format, stream)
        return EXIT_USAGE

    targets = classify(surveyed)

    if args.report:
        _emit(
            _envelope(mode, ok=True, survey_data=surveyed, targets=targets),
            args.format,
            stream,
        )
        return EXIT_OK

    salvage_dir = args.salvage_dir or default_salvage_dir(surveyed, moment)
    outcome = build_plan(
        targets,
        surveyed,
        selectors=list(args.cleanup or []),
        dry_run=args.dry_run,
        salvage_dir=salvage_dir,
    )
    if isinstance(outcome, Refusal):
        _emit(
            _envelope(mode, ok=False, survey_data=surveyed, targets=targets, refusal=outcome),
            args.format,
            stream,
        )
        return EXIT_REFUSED

    execution = Executor(runner, surveyed, cwd=cwd).run(outcome)
    _emit(
        _envelope(
            mode,
            ok=execution.ok,
            survey_data=surveyed,
            targets=targets,
            plan=outcome,
            execution=execution,
        ),
        args.format,
        stream,
    )
    return EXIT_OK if execution.ok else EXIT_ANOMALY


def entry() -> None:
    sys.exit(main())
