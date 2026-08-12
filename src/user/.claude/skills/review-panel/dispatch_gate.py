#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Authorize every lens dispatch of a round, and parse what comes back.

Usage: uv run dispatch_gate.py claim --lens <name> --transport <name> --model <name>
           --reason initial|transport-error|unusable-output [--evidence <verbatim>]
           [--out-dir <dir>]
       uv run dispatch_gate.py ingest --output <path> [--out-dir <dir>]

Stdout is JSON. Exit 0 on authorization or ingestion, 2 on refusal. Every
authorized attempt is appended to the round's ledger before it runs, so a lens
that has spent its dispatches cannot spend another by asking again.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_REFUSED = 2

# The ledger holds one JSON record per line, appended and never rewritten. The
# bound is only as trustworthy as the history it counts, and a read-modify-write
# ledger loses an attempt whenever two dispatches of one round overlap — which is
# the normal shape of a panel, not an edge case.
LEDGER_NAME = "attempts.json"
ROUND_META_NAME = "round.json"

# Three dispatches per lens per round, at most one of them recovering a reviewer
# that produced unusable output. Recovery is a chain of attempts that each
# declare transport AND model, because a model can sit at capacity for the length
# of a round while another model of the same vendor answers: a single transport
# flip abandons a live vendor on one saturated model's say-so. A chain with no
# end is the opposite failure — one lens spending the whole round's budget.
MAX_ATTEMPTS = 3
MAX_UNUSABLE_RECOVERIES = 1

# Seconds to wait before a recovery dispatch, indexed by how many recoveries
# precede it. A route that has failed twice is likelier saturated than flaking,
# so the second wait is the longer one.
BACKOFF_SECONDS = (15, 30)

INITIAL = "initial"
TRANSPORT_ERROR = "transport-error"
UNUSABLE_OUTPUT = "unusable-output"
REASONS = (INITIAL, TRANSPORT_ERROR, UNUSABLE_OUTPUT)

# A lens name becomes a filename under the round directory, so it carries no
# separator and no traversal.
LENS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# A body that is nothing but one fenced block, language tag optional.
FENCED_RE = re.compile(
    r"\A\s*```[A-Za-z0-9_+-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?```\s*\Z", re.DOTALL
)

HALT_GUIDANCE = (
    "Every route this lens ran on died in transport. The round is over: abandon every dispatch "
    "not yet made, write the verdict halted with these routes and their errors verbatim in the "
    "halt block, and lead the operator report with them, ahead of any finding."
)


class Refusal(Exception):
    """A typed refusal to authorize or to ingest; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str, halt: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.halt = halt

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ledger_path(out_dir: str) -> Path:
    return Path(out_dir) / LEDGER_NAME


def read_ledger(path: Path) -> list[dict]:
    """Every record appended to this round's ledger, oldest first."""
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal(
            "unreadable-ledger", f"cannot read the attempt ledger {path}: {exc}"
        ) from exc
    records = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Refusal(
                "unreadable-ledger",
                f"line {number} of the attempt ledger {path} is not a record: {exc}; a bound "
                "cannot be enforced against a history that does not parse",
            ) from exc
        if not isinstance(record, dict):
            raise Refusal(
                "unreadable-ledger",
                f"line {number} of the attempt ledger {path} is not a record object",
            )
        records.append(record)
    return records


def append_record(path: Path, record: dict[str, Any]) -> None:
    """Append one record. The ledger is only ever opened for append, so no
    invocation can rewrite what an earlier one wrote."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def claims_for(records: list[dict], lens: str) -> list[dict]:
    return [r for r in records if r.get("kind") == "claim" and r.get("lens") == lens]


def output_path_for(out_dir: str, lens: str, attempt: int) -> Path:
    """Where this attempt writes its raw output — one path per (lens, attempt).

    A fresh path per attempt is what makes an absent file mean something. A
    transport that writes its output file only on success leaves the previous
    attempt's file untouched when it fails, so a reused path hands the harvester
    a stale report that reads as this attempt's.
    """
    return Path(out_dir).resolve() / f"{lens}.attempt-{attempt}.out"


def backoff_for(attempt: int) -> int:
    return BACKOFF_SECONDS[min(attempt - 2, len(BACKOFF_SECONDS) - 1)]


def check_lens(raw: str | None) -> str:
    if not (raw or "").strip():
        raise Refusal("no-lens", "no --lens was named; this gate bounds dispatches per lens")
    lens = (raw or "").strip()
    if not LENS_RE.match(lens):
        raise Refusal(
            "no-lens",
            f"lens name {lens!r} is not a plain name; a lens names its own output file, so it may "
            "hold only letters, digits, dot, dash and underscore",
        )
    return lens


def check_route(transport: str | None, model: str | None) -> tuple[str, str]:
    """Both halves, on every attempt. An attempt recorded without its model cannot
    say which route is exhausted, and a dead vendor and a saturated model recover
    in opposite directions."""
    declared_transport, declared_model = (transport or "").strip(), (model or "").strip()
    if not declared_transport or not declared_model:
        raise Refusal(
            "no-route-declaration",
            "every dispatch declares both --transport and --model; a route recorded without its "
            "model leaves the next attempt no way to say what was already exhausted",
        )
    return declared_transport, declared_model


def check_reason(raw: str | None, attempt: int) -> str:
    if raw not in REASONS:
        raise Refusal(
            "unknown-reason",
            f"reason {raw!r} is outside the closed set; a dispatch declares one of: "
            + ", ".join(REASONS),
        )
    if attempt == 1 and raw != INITIAL:
        raise Refusal(
            "unknown-reason",
            f"this is the first dispatch of the lens, so its reason is {INITIAL!r}; {raw!r} "
            "describes a failure no attempt has recorded",
        )
    if attempt > 1 and raw == INITIAL:
        raise Refusal(
            "unknown-reason",
            f"the lens has already been dispatched, so this attempt declares what failed: "
            f"{TRANSPORT_ERROR!r} when the route died and the reviewer never ran, "
            f"{UNUSABLE_OUTPUT!r} when the route worked and the body is unusable",
        )
    return raw


def check_evidence(raw: str | None, reason: str) -> str:
    if reason == INITIAL:
        return ""
    if not (raw or "").strip():
        raise Refusal(
            "no-failure-evidence",
            "a recovery dispatch carries --evidence: the failed attempt's error or output, "
            "verbatim. 'the route was unavailable' and '402 Insufficient credits' ask different "
            "things of whoever reads the round, and only one of them can be acted on",
        )
    return raw or ""


def declared_lenses(out_dir: str) -> frozenset[str] | None:
    """The lens names this round's metadata declares, or None when it declares none.

    A misspelled lens would otherwise open a second attempt chain under a name no
    lens holds, spending dispatches against a bound that then guards nothing.
    """
    try:
        meta = json.loads((Path(out_dir) / ROUND_META_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    entries = meta.get("lenses") if isinstance(meta, dict) else None
    if not isinstance(entries, list):
        return None
    names = {
        entry["lens"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("lens"), str)
    }
    return frozenset(names) or None


def failed_routes(prior: list[dict], reason: str, evidence: str) -> list[dict[str, Any]]:
    """Every dispatched attempt paired with the failure the next claim reported for it.

    A claim describes the attempt before it, so the refused claim closes the
    record: without it the failure that ran the lens out — the most recent one —
    would be the one missing.
    """
    reported = [(r.get("reason"), r.get("evidence", "")) for r in prior[1:]] + [(reason, evidence)]
    return [
        {
            "attempt": record.get("attempt"),
            "transport": record.get("transport"),
            "model": record.get("model"),
            "reason": failure,
            "error": error,
        }
        for record, (failure, error) in zip(prior, reported)
    ]


def exhausted(lens: str, why: str, routes: list[dict[str, Any]]) -> Refusal:
    """The refusal for a dispatch past the bound, carrying halt guidance when every
    recorded failure was transport-class.

    A lens that ran out of routes and a lens whose reviewer kept producing garbage
    end identically — no entry, an incomplete round — but only the first says
    anything about the dispatches the round has not made yet.
    """
    transport_only = bool(routes) and all(route["reason"] == TRANSPORT_ERROR for route in routes)
    if not transport_only:
        return Refusal("attempts-exhausted", f"{lens}: {why}")
    rendered = "; ".join(f"{r['transport']}/{r['model']}: {r['error']}" for r in routes)
    return Refusal(
        "attempts-exhausted",
        f"{lens}: {why} Every route it ran on died in transport — {rendered}",
        halt={"guidance": HALT_GUIDANCE, "exhausted_routes": routes},
    )


def claim(args: argparse.Namespace) -> dict[str, Any]:
    """Authorize one dispatch of one lens, or refuse and say what closes the lens."""
    lens = check_lens(args.lens)
    transport, model = check_route(args.transport, args.model)
    declared = declared_lenses(args.out_dir)
    if declared is not None and lens not in declared:
        raise Refusal(
            "unknown-lens",
            f"this round declares no lens {lens!r}; its lenses are " + ", ".join(sorted(declared)),
        )
    path = ledger_path(args.out_dir)
    prior = claims_for(read_ledger(path), lens)
    attempt = len(prior) + 1
    reason = check_reason(args.reason, attempt)
    evidence = check_evidence(args.evidence, reason)

    refusal = None
    if len(prior) >= MAX_ATTEMPTS:
        refusal = exhausted(
            lens,
            f"{len(prior)} dispatches is the bound for one lens in one round.",
            failed_routes(prior, reason, evidence),
        )
    elif (
        reason == UNUSABLE_OUTPUT
        and sum(1 for r in prior if r.get("reason") == UNUSABLE_OUTPUT) >= MAX_UNUSABLE_RECOVERIES
    ):
        refusal = exhausted(
            lens,
            "a reviewer that returns unusable output is re-dispatched once, then the lens fails "
            "closed.",
            failed_routes(prior, reason, evidence),
        )
    if refusal is not None:
        # The refused claim carries the last failure's evidence, which exists
        # nowhere else once this process exits.
        append_record(
            path,
            {
                "kind": "refusal",
                "lens": lens,
                "attempt": attempt,
                "code": refusal.code,
                "reason": reason,
                "evidence": evidence,
                "timestamp": now(),
            },
        )
        raise refusal

    record = {
        "kind": "claim",
        "lens": lens,
        "attempt": attempt,
        "transport": transport,
        "model": model,
        "cwd": str(Path.cwd()),
        "reason": reason,
        "output_path": str(output_path_for(args.out_dir, lens, attempt)),
        "timestamp": now(),
    }
    if evidence:
        record["evidence"] = evidence
    if attempt > 1:
        record["backoff_seconds"] = backoff_for(attempt)
    append_record(path, record)
    return {"authorized": True, **{k: v for k, v in record.items() if k != "kind"}}


def _as_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def parse_report(body: str) -> tuple[dict, str]:
    """The tolerance ladder, in order; the first step that yields an object wins.

    Models violate an exact-output contract in predictable, harmless ways: a
    fence around the object, a sentence of preamble in front of it. Tolerance
    stops at the end of this ladder on purpose — reconstructing a report from
    prose makes the harvester the reviewer, and nothing downstream can tell the
    difference.
    """
    document = _as_object(body)
    if document is not None:
        return document, "whole-body"
    fenced = FENCED_RE.match(body)
    if fenced is not None:
        document = _as_object(fenced.group("body"))
        if document is not None:
            return document, "fenced-block"
    start = body.find("{")
    if start != -1:
        try:
            decoded, _ = json.JSONDecoder().raw_decode(body[start:])
        except (json.JSONDecodeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            return decoded, "first-object"
    raise Refusal(
        "unparseable-output",
        "the body is not a lens report: it is not JSON, not a single fenced object, and holds no "
        "object to decode from its first brace. The lens has no entry and the round is incomplete "
        "unless it is re-dispatched; a report assembled from the prose by hand is not a review",
    )


def _resolved(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:  # pragma: no cover - resolution of a plain path does not fail here
        return str(path)


def match_claim(records: list[dict], output: Path) -> dict | None:
    """The claim that assigned this output path, or None if no claim did."""
    target = _resolved(output)
    for record in reversed(records):
        if record.get("kind") != "claim":
            continue
        assigned = record.get("output_path")
        if isinstance(assigned, str) and _resolved(Path(assigned)) == target:
            return record
    return None


def outcome_record(claimed: dict, outcome: str, output: Path, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "outcome",
        "lens": claimed.get("lens"),
        "attempt": claimed.get("attempt"),
        "outcome": outcome,
        "output_path": str(output),
        "timestamp": now(),
        **extra,
    }


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    """Read one lens's raw output through the tolerance ladder, and record what it was."""
    if not (args.output or "").strip():
        raise Refusal(
            "no-output-path",
            "no --output was supplied; ingest reads the file the claim assigned to this attempt",
        )
    output = Path((args.output or "").strip()).expanduser()
    path = ledger_path(args.out_dir)
    records = read_ledger(path)
    claimed = match_claim(records, output)
    if claimed is None:
        append_record(
            path,
            {
                "kind": "refusal",
                "code": "unclaimed-attempt",
                "output_path": str(output),
                "timestamp": now(),
            },
        )
        raise Refusal(
            "unclaimed-attempt",
            f"no claim in this round assigned the output path {output}; a dispatch made without "
            "one leaves a hole in the ledger, and an unbounded lens is what the hole hides",
        )
    if not output.is_file():
        append_record(path, outcome_record(claimed, "no-output", output))
        raise Refusal(
            "no-output",
            f"the claimed output path {output} holds no file. Each attempt writes its own path, "
            "so nothing there means the route wrote nothing and the reviewer never ran: claim "
            f"again with reason {TRANSPORT_ERROR!r}, carrying the route's error as the evidence",
        )
    try:
        body = output.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        append_record(path, outcome_record(claimed, "unparseable", output))
        raise Refusal(
            "unparseable-output", f"cannot read the claimed output {output} as text: {exc}"
        ) from exc
    try:
        report, recovery = parse_report(body)
    except Refusal:
        append_record(path, outcome_record(claimed, "unparseable", output))
        raise
    append_record(path, outcome_record(claimed, "parsed", output, recovery=recovery))
    return {
        "ingested": True,
        "lens": claimed.get("lens"),
        "attempt": claimed.get("attempt"),
        "recovery": recovery,
        "report": report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    verbs = parser.add_subparsers(dest="verb", required=True)

    claim_parser = verbs.add_parser("claim", help="authorize one dispatch of one lens")
    claim_parser.add_argument("--out-dir", default=".")
    claim_parser.add_argument("--lens")
    claim_parser.add_argument("--transport")
    claim_parser.add_argument("--model")
    claim_parser.add_argument("--reason")
    claim_parser.add_argument("--evidence")
    claim_parser.set_defaults(run=claim)

    ingest_parser = verbs.add_parser("ingest", help="read one lens's raw output")
    ingest_parser.add_argument("--out-dir", default=".")
    ingest_parser.add_argument("--output")
    ingest_parser.set_defaults(run=ingest)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    verb = "authorized" if args.verb == "claim" else "ingested"
    try:
        result = args.run(args)
    except Refusal as exc:
        answer: dict[str, Any] = {verb: False, "errors": [exc.as_dict()]}
        if exc.halt is not None:
            answer["halt"] = exc.halt
        print(json.dumps(answer, sort_keys=True))
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        print(json.dumps(
            {verb: False, "errors": [{"code": "gate-failure", "message": str(exc)}]},
            sort_keys=True,
        ))
        return EXIT_REFUSED
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
