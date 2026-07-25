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
from gitclean.classify import DEFAULT_IDLE_DAYS, classify
from gitclean.execute import ExecutionReport, Executor, default_salvage_dir
from gitclean.model import Disposition, Plan, Refusal, Risk, Survey, Target
from gitclean.plan import build_plan
from gitclean.ports import CommandPort, SubprocessCommands
from gitclean.survey import survey as run_survey

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_ANOMALY = 3

_EPILOG = """\
modes:
  --report                 survey only; emits the full classified state as JSON
  --cleanup [NAME ...]     delete the safe subset, or exactly the named targets
  --clean-all              delete everything not protected (requires --force)

verdicts:
  disposition  protected | safe | active | abandoned   -- is this still live work?
  risk         none | recoverable | data_loss          -- would deleting destroy the only copy?

  A bare --cleanup takes only disposition=safe AND risk=none. --force overrides
  risk (salvaging first); it never overrides protected.

examples:
  gitclean --report --format human
  gitclean --cleanup --dry-run
  gitclean --cleanup feat/old-thing worktree:/path/to/wt
  gitclean --cleanup --include-remote
  gitclean --clean-all --force --dry-run
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
    mode.add_argument(
        "--clean-all",
        action="store_true",
        help="delete every non-protected target; requires --force",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="accept data loss: salvage to a bundle first, then delete. Never overrides protected.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="resolve and report the plan without executing it"
    )
    parser.add_argument(
        "--include-remote",
        action="store_true",
        help="allow deleting remote branches (off by default: remote deletions affect others)",
    )
    parser.add_argument(
        "--idle-days",
        type=int,
        default=DEFAULT_IDLE_DAYS,
        metavar="N",
        help="idle window before an unmerged branch counts as abandoned "
        f"(default {DEFAULT_IDLE_DAYS})",
    )
    parser.add_argument(
        "--base", metavar="REF", help="branch to measure merges against (default: origin's HEAD)"
    )
    parser.add_argument("--salvage-dir", metavar="DIR", help="where --force writes bundles")
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
    by_disposition: dict[str, int] = {d.value: 0 for d in Disposition}
    by_risk: dict[str, int] = {r.value: 0 for r in Risk}
    for target in targets:
        by_disposition[target.disposition.value] += 1
        by_risk[target.risk.value] += 1
    return {
        "total": len(targets),
        "by_disposition": by_disposition,
        "by_risk": by_risk,
        "sweepable_now": sum(
            1 for t in targets if t.disposition is Disposition.SAFE and t.risk is Risk.NONE
        ),
    }


def _render_human(payload: dict[str, object], out: TextIO) -> None:
    repo = payload.get("repo")
    if isinstance(repo, dict):
        print(f"repo:  {repo.get('repo_root')}", file=out)
        print(f"base:  {repo.get('base_ref')}", file=out)

    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            print(f"WARN:  {warning}", file=out)

    targets = payload.get("targets")
    if isinstance(targets, list) and targets:
        print("", file=out)
        for entry in targets:
            if not isinstance(entry, dict):
                continue
            print(
                f"  [{entry.get('disposition'):<9}] [{entry.get('risk'):<11}] {entry.get('id')}",
                file=out,
            )
            reasons = entry.get("reasons")
            if isinstance(reasons, list):
                for reason in reasons:
                    print(f"      - {reason}", file=out)

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

    execution = payload.get("execution")
    if isinstance(execution, dict):
        print("", file=out)
        deletions = execution.get("deletions")
        if isinstance(deletions, list):
            for entry in deletions:
                if isinstance(entry, dict):
                    mark = "plan" if dry else ("ok  " if entry.get("verified") else "FAIL")
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
    mode = "report" if args.report else ("clean-all" if args.clean_all else "cleanup")

    surveyed = run_survey(runner, cwd=cwd, base_override=args.base)
    if isinstance(surveyed, str):
        _emit(_envelope(mode, ok=False, error=surveyed), args.format, stream)
        return EXIT_USAGE

    targets = classify(surveyed, now=moment, idle_days=args.idle_days)

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
        clean_all=args.clean_all,
        force=args.force,
        include_remote=args.include_remote,
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
