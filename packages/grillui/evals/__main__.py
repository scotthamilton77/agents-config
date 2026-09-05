"""Replay recorded turns against the seats a session would use, and check them.

This spends real tokens on real models and takes minutes, which is why it is
run on purpose. What it proves is the half the unit suite cannot: that the
prompt those tests render is a prompt the seated models answer the way the
board needs.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.cases import Case, load_cases
from evals.checks import (
    a_revise_supplies_what_it_revises,
    added_nodes_carry_short_and_body,
    option_references_name_their_decision,
    the_reply_is_the_map_document,
    the_rulings_are_the_ones_owed,
    the_stop_verdict_is_expected,
    the_turn_speaks_once,
)
from grillui.drivers import read_cli_reply, read_codex_reply, read_document, seat_driver
from grillui.lane import AgentUnreachableError, DocumentRefusedError
from grillui.schemas import HEAVY_TIER
from grillui.session import open_session
from grillui.tiers import (
    CLAUDE_TRANSPORT,
    CODEX_TRANSPORT,
    OPENROUTER_TRANSPORT,
    TRANSPORTS,
    Seat,
    TierConfig,
    UnknownTransportError,
    compose,
)

REPORTS = Path.home() / ".grillui-evals"
TOLERANCE = 0.1
BASELINE = "prompt_tokens_near_baseline"

# The checks a reply can only be held to once it is a document. A reply that is
# not one fails all of them for that reason, rather than leaving cells nobody
# can tell apart from checks that were never run.
DEPENDENT = (
    the_rulings_are_the_ones_owed,
    added_nodes_carry_short_and_body,
    the_turn_speaks_once,
    option_references_name_their_decision,
    the_stop_verdict_is_expected,
    a_revise_supplies_what_it_revises,
)


def _codex_output(raw: str) -> int | None:
    """What the Codex turn said it wrote, off the stream it printed."""
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            counted = event.get("usage", {}).get("output_tokens")
            return counted if isinstance(counted, int) else None
    return None


def _cli_output(raw: str) -> int | None:
    """What the CLI turn said it wrote, off the object it printed."""
    try:
        counted = json.loads(raw).get("usage", {}).get("output_tokens")
    except (ValueError, AttributeError):
        return None
    return counted if isinstance(counted, int) else None


# What each transport hands back: the reply read with the same function the
# driver reads it with, so an eval never disagrees with a session about what a
# seat said, and the two counts beside it. The hosted completion reports its
# prompt count through the driver's own seam and nothing about its output, so
# that count is absent rather than invented.
REPLIES: dict[str, Callable[[Any], tuple[str | None, int | None, int | None]]] = {
    OPENROUTER_TRANSPORT: lambda raw: (raw[0], raw[1], None),
    CLAUDE_TRANSPORT: lambda raw: (
        read_cli_reply(raw)[0],
        read_cli_reply(raw)[2],
        _cli_output(raw),
    ),
    CODEX_TRANSPORT: lambda raw: (
        read_codex_reply(raw)[0],
        read_codex_reply(raw)[2],
        _codex_output(raw),
    ),
}


class SampleCountRefusedError(argparse.ArgumentTypeError):
    """A sample count that would take no turn."""

    def __init__(self, counted: int) -> None:
        super().__init__(f"a run takes at least one sample, not {counted}")


class SeatRefusedError(ValueError):
    """A --seat that does not read as a seat."""

    def __init__(self, stated: str) -> None:
        super().__init__(f"a seat reads transport:model[:effort], not {stated!r}")


class ReplayRefusedError(RuntimeError):
    """A case that cannot be replayed as the session would have taken it."""

    def __init__(self, case: str, why: str) -> None:
        super().__init__(f"{case}: {why}")


def seat_of(case: Case, config: TierConfig) -> Seat:
    """The seat this case's turn is taken on when nothing narrows it."""
    if case.tier == HEAVY_TIER:
        return config.expert_seat
    return config.seat_for(case.channel)


def named(seat: Seat) -> str:
    return ":".join(one for one in (seat.transport, seat.model, seat.effort) if one)


def read_seat(stated: str) -> Seat:
    transport, _, rest = stated.partition(":")
    model, _, effort = rest.partition(":")
    if not transport or not model:
        raise SeatRefusedError(stated)
    if transport not in TRANSPORTS:
        raise UnknownTransportError(transport)
    return Seat(transport, model, effort or None)


class Tap:
    """The seam a driver sends through, with what came back kept.

    The driver is the one the session builds and it sends the turn itself; this
    only keeps the bytes and the clock, so what is checked is what a session
    would have received rather than a second composition of it.
    """

    def __init__(self, seam: Callable[..., Any]) -> None:
        self._seam = seam
        self.raw: Any = None
        self.seconds = 0.0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        self.raw = self._seam(*args, **kwargs)
        self.seconds += time.monotonic() - started
        return self.raw


def replay(
    case: Case, seat: Seat, config: TierConfig
) -> tuple[str, int | None, int | None, float, str | None]:
    """One sample: the reply, what it counted at either end, how long it took, and
    the reason the turn was refused, or nothing where it was not.

    A refusal is caught here because this is where what the seat returned is
    held: the turn happened and was paid for, and a row reporting nothing about
    it is the only record of a turn nobody can account for.
    """
    driver = seat_driver(config, seat, tier=case.tier)
    seam = "transport" if seat.transport == OPENROUTER_TRANSPORT else "cli"
    tap = Tap(getattr(driver, seam))
    setattr(driver, seam, tap)
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        (directory / "log.jsonl").write_text(
            "".join(one.model_dump_json() + "\n" for one in case.entries), encoding="utf-8"
        )
        log = open_session(directory)
        if compose(case.recorded, case.context, log.entries()) != compose(
            case.recorded, case.context, list(case.entries)
        ):
            raise ReplayRefusedError(case.name, "the session renders a prompt it does not pin")
        dispatch = directory / "dispatch.json"
        dispatch.write_text(case.recorded, encoding="utf-8")
        refused: str | None = None
        try:
            driver.run(log, dispatch)
        except (DocumentRefusedError, AgentUnreachableError) as why:
            refused = str(why)
    if tap.raw is None:
        raise ReplayRefusedError(case.name, "the seat was never reached")
    try:
        reply, prompt_tokens, output_tokens = REPLIES[seat.transport](tap.raw)
    except AgentUnreachableError:
        reply, prompt_tokens, output_tokens = "", None, None
    return reply or "", prompt_tokens, output_tokens, tap.seconds, refused


def check(
    case: Case,
    reply: str,
    tokens: int | None,
    *,
    baseline: bool,
    refused: str | None = None,
) -> dict[str, str | None]:
    """Every check this reply is held to, by name.

    `refused` is the reason a seat produced no reply to check, and it fails the
    same checks the reply's own shape failure would: a turn nobody could read is
    the turn that happened, and the record says so rather than saying nothing.

    `baseline` is whether this seat is the one the case's token count was
    measured on. Held to another seat's count, a model that was never measured
    fails a check about a number nobody claimed for it.
    """
    shape = refused or the_reply_is_the_map_document(reply)
    results: dict[str, str | None] = {the_reply_is_the_map_document.__name__: shape}
    if shape is not None:
        results |= {one.__name__: shape for one in DEPENDENT}
    else:
        document = read_document(reply)
        results |= {
            the_rulings_are_the_ones_owed.__name__: the_rulings_are_the_ones_owed(
                document, case.owed_rulings
            ),
            added_nodes_carry_short_and_body.__name__: added_nodes_carry_short_and_body(document),
            the_turn_speaks_once.__name__: the_turn_speaks_once(document, case.speech_limit),
            option_references_name_their_decision.__name__: (
                option_references_name_their_decision(document)
            ),
            the_stop_verdict_is_expected.__name__: the_stop_verdict_is_expected(
                document, case.stop
            ),
            a_revise_supplies_what_it_revises.__name__: a_revise_supplies_what_it_revises(document),
        }
    if baseline and case.prompt_tokens is not None:
        results[BASELINE] = _near(tokens, case.prompt_tokens)
    return results


def _near(counted: int | None, baseline: int) -> str | None:
    if counted is None:
        return "the seat reported no prompt token count"
    if abs(counted - baseline) <= baseline * TOLERANCE:
        return None
    return f"{counted} prompt tokens, baseline {baseline}"


def matrix_of(runs: list[dict[str, Any]]) -> str:
    """The matrix, as a table anyone can paste."""
    names = sorted({one for run in runs for one in run["checks"]})
    lines = ["| case | seat | sample | " + " | ".join(names) + " |"]
    lines.append("|" + "---|" * (len(names) + 3))
    # A dash is a check that does not apply to this run. Everything else is a
    # verdict, so a blank never stands for a check nobody got round to.
    for run in runs:
        cells = [
            "-" if one not in run["checks"] else ("pass" if run["checks"][one] is None else "FAIL")
            for one in names
        ]
        lines.append(
            f"| {run['case']} | {run['seat']} | {run['sample']} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines)


def _samples(stated: str) -> int:
    """A sample count that samples something.

    Nothing is not a smaller run, it is a run that took no turn and reported no
    failure, which reads exactly like a suite that passed.
    """
    counted = int(stated)
    if counted < 1:
        raise SampleCountRefusedError(counted)
    return counted


def _dated() -> Path:
    """A report directory of this run's own, named for when it started.

    Made rather than named, because two runs starting inside the same second
    would otherwise write one another's replies and counts into one directory
    and leave a report of two turns nobody can separate.
    """
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ-")
    return Path(tempfile.mkdtemp(prefix=stamp, dir=REPORTS))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="grillui-evals",
        description="Replay recorded turns against real seats and check the replies.",
    )
    parser.add_argument(
        "--case", action="append", default=[], help="run only this case, repeatable"
    )
    parser.add_argument(
        "--seat", action="append", default=[], help="add transport:model[:effort], repeatable"
    )
    parser.add_argument(
        "-n", type=_samples, default=None, help="samples per case, default the case's"
    )
    parser.add_argument("--report", type=Path, default=None, help="where the report is written")
    args = parser.parse_args(argv)

    config = TierConfig.from_env()
    cases = [one for one in load_cases() if not args.case or one.name in args.case]
    if not cases:
        parser.error(f"no case named {', '.join(args.case)}")
    added = [read_seat(one) for one in args.seat]
    where = args.report or _dated()
    where.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    for case in cases:
        measured = seat_of(case, config)
        # Keyed by name, because two runs under one name write over each other's
        # reply and counts and the report reads as one run.
        for seat in {named(one): one for one in [measured, *added]}.values():
            for sample in range(1, (args.n or case.samples) + 1):
                reply, prompt_tokens, output_tokens, seconds = "", None, None, 0.0
                try:
                    reply, prompt_tokens, output_tokens, seconds, refused = replay(
                        case, seat, config
                    )
                except ReplayRefusedError as why:
                    refused = str(why)
                results = check(
                    case, reply, prompt_tokens, baseline=seat == measured, refused=refused
                )
                run = {
                    "case": case.name,
                    "seat": named(seat),
                    "sample": sample,
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "output_bytes": len(reply.encode()),
                    "wall_seconds": round(seconds, 1),
                    "checks": results,
                }
                runs.append(run)
                kept = where / case.name / named(seat).replace(":", "-")
                kept.mkdir(parents=True, exist_ok=True)
                (kept / f"{sample}.txt").write_text(reply, encoding="utf-8")
                (kept / f"{sample}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
                failed = [one for one, why in results.items() if why is not None]
                said = "FAIL " + ", ".join(failed) if failed else "pass"
                print(f"{case.name} {named(seat)} #{sample}: {said}")

    matrix = matrix_of(runs)
    (where / "matrix.json").write_text(json.dumps(runs, indent=2), encoding="utf-8")
    (where / "matrix.md").write_text(matrix + "\n", encoding="utf-8")
    print(f"\n{matrix}\n\nreport: {where}")
    return 1 if any(why is not None for run in runs for why in run["checks"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
