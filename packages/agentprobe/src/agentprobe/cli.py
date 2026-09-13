"""Command line: drive scenarios against a live Claude Code, and report on what was recorded."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import report, session
from .events import load_runs


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _next_run_dir(out: Path, scenario: str) -> Path:
    """Return a fresh run directory, numbered after the highest one already there."""
    existing = [p.name for p in out.glob(f"{scenario}-*") if p.is_dir()]
    numbers = [int(name.rsplit("-", 1)[-1]) for name in existing if name.rsplit("-", 1)[-1].isdigit()]
    return out / f"{scenario}-{max(numbers, default=0) + 1:03d}"


def run_command(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    for _ in range(args.runs):
        run_dir = _next_run_dir(out, args.scenario)
        launch = session.prepare(run_dir, args.scenario, dict(os.environ), args.model)
        if args.dry_run:
            print(launch.describe())
            return 0
        started = _timestamp()
        version = session.claude_version()
        outcome = session.run_session(launch, quiet_seconds=args.quiet, max_seconds=args.max_seconds)
        meta = {
            "claude_version": version,
            "scenario": args.scenario,
            "outcome": outcome,
            "session_id": session.session_id_of(launch.events_path),
            "started_at": started,
            "ended_at": _timestamp(),
        }
        _collect_gate_decisions(run_dir, str(meta["session_id"]))
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"{run_dir}: {outcome}, session {meta['session_id'] or 'not recorded'}")
    return 0


def _collect_gate_decisions(run_dir: Path, session_id: str) -> None:
    """Copy the report gate's record of this session into the run directory.

    The gate writes outside the run directory, and the report reads nothing else, so a run
    that does not collect this loses the evidence one detector depends on.
    """
    if not session_id:
        return
    source = session.gate_decisions_path(run_dir.resolve(), session_id)
    if source.exists():
        (run_dir / "decisions.jsonl").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def report_command(args: argparse.Namespace) -> int:
    roots = [Path(d).expanduser().resolve() for d in args.directories]
    runs = load_runs([root for root in roots if root.exists()])
    print(report.render(report.aggregate(runs), report.invalid_runs(runs)))
    # Reporting measures; it does not judge, so a behaviour that was observed is not a
    # failure and never changes the exit status.
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentprobe",
        description=(
            "Drive scripted Claude Code sessions under a hook that records every payload, "
            "then report how often each known behaviour appears, per Claude Code version."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    runner = subparsers.add_parser("run", help="drive one or more live sessions through a scenario")
    runner.add_argument("scenario", choices=session.scenario_names(), help="which scenario to drive")
    runner.add_argument("--out", required=True, help="directory to create run directories under")
    runner.add_argument("--runs", type=int, default=1, help="how many sessions to drive, one after another")
    runner.add_argument("--model", default="haiku", help="model the probed session runs on")
    runner.add_argument(
        "--quiet",
        type=float,
        default=session.DEFAULT_QUIET_SECONDS,
        help="seconds the event log must go untouched before the run counts as finished",
    )
    runner.add_argument(
        "--max-seconds",
        type=float,
        default=session.DEFAULT_MAX_SECONDS,
        help="hard limit on one session",
    )
    runner.add_argument(
        "--dry-run",
        action="store_true",
        help="write the run directory, print the command and the scrubbed environment, and stop",
    )
    runner.set_defaults(func=run_command)

    reporter = subparsers.add_parser("report", help="read run directories and print the behaviour table")
    reporter.add_argument("directories", nargs="+", help="run directories, or a directory holding them")
    reporter.set_defaults(func=report_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


def entry() -> None:
    raise SystemExit(main())
