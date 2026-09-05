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
from grillui.schemas import HEAVY_TIER
from grillui.session import open_session
from grillui.tiers import (
    CLAUDE_TRANSPORT,
    CODEX_TRANSPORT,
    OPENROUTER_TRANSPORT,
    Seat,
    TierConfig,
    compose,
)

REPORTS = Path.home() / ".grillui-evals"
TOLERANCE = 0.1
BASELINE = "prompt_tokens_near_baseline"

# What each transport hands back, read with the same functions the driver reads
# it with, so an eval never disagrees with a session about what a seat said.
REPLIES = {
    OPENROUTER_TRANSPORT: lambda raw: (raw[0], raw[1]),
    CLAUDE_TRANSPORT: lambda raw: (read_cli_reply(raw)[0], read_cli_reply(raw)[2]),
    CODEX_TRANSPORT: lambda raw: (read_codex_reply(raw)[0], read_codex_reply(raw)[2]),
}


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
    return Seat(transport, model, effort or None)


class Tap:
    """The seam a driver sends through, with what came back kept.

    The driver is the one the session builds and it sends the turn itself; this
    only keeps the bytes and the clock, so what is checked is what a session
    would have received rather than a second composition of it.
    """

    def __init__(self, seam: Any) -> None:
        self._seam = seam
        self.raw: Any = None
        self.seconds = 0.0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        self.raw = self._seam(*args, **kwargs)
        self.seconds += time.monotonic() - started
        return self.raw


def replay(case: Case, seat: Seat, config: TierConfig) -> tuple[str, int | None, float]:
    """One sample: the reply, what its prompt counted at, and how long it took."""
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
        driver.run(log, dispatch)
    if tap.raw is None:
        raise ReplayRefusedError(case.name, "the seat was never reached")
    reply, tokens = REPLIES[seat.transport](tap.raw)
    return reply or "", tokens, tap.seconds


def check(case: Case, reply: str, tokens: int | None) -> dict[str, str | None]:
    """Every check this reply is held to, by name."""
    shape = the_reply_is_the_map_document(reply)
    results: dict[str, str | None] = {the_reply_is_the_map_document.__name__: shape}
    if shape is None:
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
    if case.prompt_tokens is not None:
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
    for run in runs:
        cells = [
            "-" if one not in run["checks"] else ("pass" if run["checks"][one] is None else "FAIL")
            for one in names
        ]
        lines.append(
            f"| {run['case']} | {run['seat']} | {run['sample']} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines)


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
    parser.add_argument("-n", type=int, default=None, help="samples per case, default the case's")
    parser.add_argument("--report", type=Path, default=None, help="where the report is written")
    args = parser.parse_args(argv)

    config = TierConfig.from_env()
    cases = [one for one in load_cases() if not args.case or one.name in args.case]
    if not cases:
        parser.error(f"no case named {', '.join(args.case)}")
    added = [read_seat(one) for one in args.seat]
    where = args.report or REPORTS / datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    where.mkdir(parents=True, exist_ok=True)

    runs: list[dict[str, Any]] = []
    for case in cases:
        for seat in [seat_of(case, config), *added]:
            for sample in range(1, (args.n or case.samples) + 1):
                reply, tokens, seconds = replay(case, seat, config)
                results = check(case, reply, tokens)
                run = {
                    "case": case.name,
                    "seat": named(seat),
                    "sample": sample,
                    "prompt_tokens": tokens,
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
