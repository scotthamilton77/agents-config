#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Authorize every lens dispatch of a round, and parse what comes back.

Usage: uv run dispatch_gate.py preflight --out-dir <dir>
       uv run dispatch_gate.py claim --lens <name> --transport <name> --model <name>
           --reason initial|transport-error|unusable-output [--evidence <verbatim>]
           [--out-dir <dir>]
       uv run dispatch_gate.py ingest --output <path> [--out-dir <dir>]

Stdout is JSON. Exit 0 on authorization, ingestion, or an affordable or
unanswerable preflight; 2 on refusal. Every authorized attempt is appended to
the round's ledger before it runs, so a lens that has spent its dispatches
cannot spend another by asking again. Run preflight once, before the round's
first claim: it checks whether the openrouter dispatches round.json plans can
be afforded, and refuses loudly on a shortfall instead of a lens dying
mid-round.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_REFUSED = 2

# The ledger holds one JSON record per line, appended and never rewritten. The
# bound is only as trustworthy as the history it counts, and a read-modify-write
# ledger loses an attempt whenever two dispatches of one round overlap — which is
# the normal shape of a panel, not an edge case.
LEDGER_NAME = "attempts.jsonl"

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
    """Append one record.

    The ledger is opened in binary append mode and written as a single byte string so concurrent
    processes don't risk interleaving partial JSON fragments.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
    with path.open("ab", buffering=0) as handle:
        handle.write(line)

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


ROUND_META_NAME = "round.json"
OPENROUTER_TRANSPORT = "openrouter"

# The floor for one openrouter dispatch: a frontier model reserves its full
# max_tokens against the key's balance up front, whatever it actually returns.
# 32,768 max_tokens at ~$15 per million output tokens (frontier-tier pricing)
# prices that reservation at ~$0.49; rounded up to the cent to keep the floor
# conservative. Flat across lenses and models on purpose — this gate carries no
# per-model pricing table and does not judge which model a lens deserves.
RESERVATION_USD = 0.50

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
KEY_MANAGEMENT_URL = "https://openrouter.ai/settings/keys"


def round_meta_path(out_dir: str) -> Path:
    return Path(out_dir) / ROUND_META_NAME


def read_round_meta(out_dir: str) -> dict[str, Any]:
    """This round's plan, as emit_prompts.py wrote it: which lenses, on which transports.

    Preflight runs after the round is planned and before its first dispatch, so
    round.json already exists; one missing or unparseable means the round was
    never emitted and there is nothing to check the budget of.
    """
    path = round_meta_path(out_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("no-round-meta", f"cannot read round metadata {path}: {exc}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refusal("no-round-meta", f"round metadata {path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("lenses"), list):
        raise Refusal("no-round-meta", f"round metadata {path} carries no lens list")
    return document


def count_openrouter_lenses(round_meta: dict[str, Any]) -> int:
    return sum(
        1
        for lens in round_meta["lenses"]
        if isinstance(lens, dict) and lens.get("transport") == OPENROUTER_TRANSPORT
    )


def urllib_fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    """One live HTTP GET, returning its status and raw body.

    An HTTPError still carries a status and a body — OpenRouter's 402/403
    replies are JSON — so it is read rather than raised; only a request that
    never reached a server (DNS, connection, timeout) surfaces as an OSError.
    """
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _probe_endpoint(url: str, api_key: str) -> tuple[dict[str, Any] | None, str | None]:
    """This endpoint's ``data`` object, or the reason it could not be read."""
    try:
        status, body = urllib_fetch(url, {"Authorization": f"Bearer {api_key}"})
    except OSError as exc:
        return None, str(exc)
    if not 200 <= status < 300:
        return None, f"HTTP {status}"
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None, "response body is not JSON"
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None, "response carries no data object"
    return data, None


def probe_remaining_credit(api_key: str) -> tuple[float | None, list[str]]:
    """The tightest of every credit bound the key answers, or none if neither did.

    ``/key`` bounds what this specific key may still spend (null when the key
    is uncapped); ``/credits`` bounds the account's whole balance but requires
    a management key, so a regular key sees it answer 403 — that is one
    endpoint failing to answer, not a shortfall. Either bound can be the
    binding one, so the effective remaining credit is the smaller of whichever
    endpoint actually answers.
    """
    bounds: list[float] = []
    warnings: list[str] = []

    key_data, key_error = _probe_endpoint(KEY_URL, api_key)
    if key_error is not None:
        warnings.append(f"{KEY_URL}: {key_error}")
    else:
        limit_remaining = key_data.get("limit_remaining")
        if isinstance(limit_remaining, (int, float)):
            bounds.append(float(limit_remaining))

    credits_data, credits_error = _probe_endpoint(CREDITS_URL, api_key)
    if credits_error is not None:
        warnings.append(f"{CREDITS_URL}: {credits_error}")
    else:
        total, used = credits_data.get("total_credits"), credits_data.get("total_usage")
        if isinstance(total, (int, float)) and isinstance(used, (int, float)):
            bounds.append(float(total) - float(used))

    if not bounds:
        return None, warnings
    return min(bounds), warnings


def _preflight_record(outcome: str, count: int, demand: float, **extra: Any) -> dict[str, Any]:
    return {
        "kind": "preflight", "outcome": outcome, "openrouter_lenses": count,
        "demand_usd": demand, "timestamp": now(), **extra,
    }


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    """Verify the round's planned openrouter dispatches can be afforded before the first claim."""
    path = ledger_path(args.out_dir)
    count = count_openrouter_lenses(read_round_meta(args.out_dir))
    demand = round(count * RESERVATION_USD, 2)

    if count == 0:
        record = _preflight_record("pass", 0, 0.0)
        append_record(path, record)
        return {"preflight": True, **{k: v for k, v in record.items() if k != "kind"}}

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        refusal = Refusal(
            "no-openrouter-key",
            f"round.json plans {count} openrouter lens dispatch(es), demanding ${demand:.2f} in "
            "reservation, but OPENROUTER_API_KEY is not set — those dispatches could not run "
            f"without a key. Manage keys at {KEY_MANAGEMENT_URL}",
        )
        append_record(path, _preflight_record("refusal", count, demand, code=refusal.code))
        raise refusal

    remaining, warnings = probe_remaining_credit(api_key)
    if remaining is None:
        warning = "; ".join(warnings) if warnings else "the credit probe could not be answered"
        record = _preflight_record("warn", count, demand, warning=warning)
        append_record(path, record)
        return {"preflight": True, **{k: v for k, v in record.items() if k != "kind"}}

    if remaining < demand:
        refusal = Refusal(
            "insufficient-openrouter-credit",
            f"round.json plans {count} openrouter lens dispatch(es), demanding ${demand:.2f} in "
            f"reservation, but only ${remaining:.2f} remains on OPENROUTER_API_KEY — a lens would "
            f"die mid-round. Manage keys at {KEY_MANAGEMENT_URL}",
        )
        append_record(
            path,
            _preflight_record("refusal", count, demand, remaining_usd=remaining, code=refusal.code),
        )
        raise refusal

    record = _preflight_record("pass", count, demand, remaining_usd=remaining)
    append_record(path, record)
    return {"preflight": True, **{k: v for k, v in record.items() if k != "kind"}}


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
    """Both halves, on every attempt, recorded exactly as declared.

    An attempt recorded without its model cannot say which route is exhausted, and
    a dead vendor and a saturated model recover in opposite directions. Which
    route a lens deserves is not this gate's question: it counts attempts and
    records what ran them, so a route it refused to record would be a dispatch it
    could not bound.
    """
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
    body = ""
    if output.is_file():
        try:
            body = output.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            append_record(path, outcome_record(claimed, "unparseable", output))
            raise Refusal(
                "unparseable-output", f"cannot read the claimed output {output} as text: {exc}"
            ) from exc
    if not body.strip():
        append_record(path, outcome_record(claimed, "no-output", output))
        raise Refusal(
            "no-output",
            f"the claimed output path {output} holds nothing. Each attempt writes its own path, "
            "so nothing there means the route wrote nothing and the reviewer never ran: claim "
            f"again with reason {TRANSPORT_ERROR!r}, carrying the route's error as the evidence",
        )
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

    preflight_parser = verbs.add_parser(
        "preflight", help="verify the round's planned openrouter dispatches can be afforded"
    )
    preflight_parser.add_argument("--out-dir", default=".")
    preflight_parser.set_defaults(run=preflight)

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


VERB_KEYS = {"claim": "authorized", "ingest": "ingested", "preflight": "preflight"}


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    verb = VERB_KEYS[args.verb]
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
