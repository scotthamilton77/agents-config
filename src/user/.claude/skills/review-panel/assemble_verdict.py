#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Assemble one round's verdict envelope from the lens reports it recovered.

Usage: uv run assemble_verdict.py --round-dir <dir> --report <lens>=<path> ...
       --routes <path> --out <verdict.json> [--schema <path>] [--repo-root <path>]
       [--indict <finding-id>=<artifact-path>]

The round directory is the one the prompts were emitted into: it holds the round
metadata the emitter wrote and the attempt ledger the dispatch gate appended to.
Coverage is fail-closed in both directions — every staffed lens reports exactly
once, and nothing else reports at all.

Stdout is JSON. Exit 0 on assembly, 2 on refusal. Output is deterministic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# The deployed layout puts review-verdict beside this skill as a sibling.
SCHEMA_CANDIDATES = (HERE / ".." / "review-verdict" / "verdict.schema.json",)

EXIT_OK = 0
EXIT_REFUSED = 2

ROUND_NAME = "round.json"
LEDGER_NAME = "attempts.jsonl"
SUPPRESSIONS_NAME = "suppressions.json"

ROUTE_FIELDS = ("lens", "vendor", "transport", "model")
ROUTE_KEYS = frozenset({*ROUTE_FIELDS, "substitution"})

# The ledger the emitter writes carries the lens that raised each settled item, which is
# what suppression matches on. The envelope's disposition entries are a closed shape that
# has no room for it, so it is matched on here and dropped on the way in.
LEDGER_ONLY_FIELDS = ("lens",)

COPIED_FROM_ROUND = (
    "artifact_class", "round", "base_sha", "head_sha", "claim_id",
    "retained_categories", "staffing_record",
)


class Refusal(Exception):
    """A typed refusal to assemble; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def blank(value: Any) -> bool:
    """True when this is not a string with something in it."""
    return not isinstance(value, str) or not value.strip()


def find_schema(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    for candidate in SCHEMA_CANDIDATES:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def read_round(round_dir: str | None) -> tuple[Path, dict[str, Any]]:
    if not round_dir:
        raise Refusal("bad-round", "no --round-dir was supplied; a verdict answers one round")
    directory = Path(round_dir)
    path = directory / ROUND_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("bad-round", f"cannot read {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise Refusal("bad-round", f"{path} is not a round record")
    entries = document.get("lenses")
    if not isinstance(entries, list) or not entries:
        raise Refusal(
            "bad-round",
            f"{path} staffs no lens; a round with nothing dispatched has no verdict to assemble",
        )
    for entry in entries:
        if not isinstance(entry, dict) or blank(entry.get("lens")):
            raise Refusal("bad-round", f"{path} carries a lens entry with no lens name")
    return directory, document


def staffed_lenses(round_meta: dict[str, Any]) -> list[str]:
    """The lenses this round dispatched, in the round's own order.

    A lens the emitter dropped for an empty delta is recorded separately and was never
    dispatched, so it owes no report.
    """
    return [entry["lens"] for entry in round_meta["lenses"]]


def parse_pairs(values: list[str], flag: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw in values:
        name, sep, value = raw.partition("=")
        if not sep or blank(name) or blank(value):
            raise Refusal(
                "bad-report", f"{flag} takes <lens>=<path>; {raw!r} is not that shape"
            )
        if name in pairs:
            raise Refusal(
                "duplicate-report",
                f"lens {name!r} is named twice by {flag}; a lens reports exactly once, and two "
                "reports for one lens double-count its coverage",
            )
        pairs[name] = value
    return pairs


def read_routes(path: str | None) -> dict[str, dict[str, Any]]:
    """What actually produced each report, as the invoker declares it."""
    if not path:
        raise Refusal(
            "bad-routes",
            "no --routes was supplied; the envelope records what actually ran each lens, which "
            "the round metadata cannot know",
        )
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("bad-routes", f"cannot read the routes file {path}: {exc}") from exc
    if not isinstance(document, list):
        raise Refusal("bad-routes", f"{path} must be a JSON array of route declarations")
    routes: dict[str, dict[str, Any]] = {}
    for entry in document:
        if not isinstance(entry, dict):
            raise Refusal("bad-routes", f"{path} holds a route entry that is not an object")
        unknown = sorted(set(entry) - ROUTE_KEYS)
        if unknown:
            raise Refusal(
                "bad-routes",
                f"route entry {entry.get('lens')!r} carries unknown key(s) "
                f"{', '.join(unknown)}; a declared route names " + ", ".join(ROUTE_FIELDS)
                + " and, when the lens ran off its declared entry, substitution",
            )
        for field in ROUTE_FIELDS:
            if blank(entry.get(field)):
                raise Refusal(
                    "bad-routes",
                    f"a route entry has no {field}; every reported lens names the vendor, "
                    "transport, and model that actually produced it",
                )
        lens = entry["lens"]
        if lens in routes:
            raise Refusal(
                "duplicate-report",
                f"lens {lens!r} is declared twice in --routes; a lens has exactly one route",
            )
        routes[lens] = entry
    return routes


def check_coverage(staffed: list[str], reports: dict[str, str], routes: dict[str, Any]) -> None:
    """Fail closed both ways: nothing unstaffed reports, and nothing staffed is silent."""
    known = set(staffed)
    for lens in sorted(set(reports) | set(routes)):
        if lens not in known:
            raise Refusal(
                "unstaffed-report",
                f"lens {lens!r} reports but this round did not staff it; output from a lens the "
                "round never dispatched is not coverage of it",
            )
    for lens in staffed:
        if lens not in reports:
            raise Refusal(
                "incomplete-round",
                f"staffed lens {lens!r} has no --report; silence is incompleteness, not a clean "
                "lens, and a round missing a lens is not written as a verdict",
            )
        if lens not in routes:
            raise Refusal(
                "incomplete-round",
                f"staffed lens {lens!r} has no entry in --routes; a report whose route is "
                "undeclared cannot be checked against what the gate authorized",
            )


def read_claims(directory: Path) -> list[dict[str, Any]]:
    """The dispatches the gate authorized this round, oldest first."""
    path = directory / LEDGER_NAME
    if not path.is_file():
        raise Refusal(
            "unauthorized-dispatch",
            f"the round directory holds no {LEDGER_NAME}, so no dispatch in it was authorized; a "
            "round assembled without the gate's ledger is a round nobody bounded",
        )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise Refusal("unreadable-ledger", f"cannot read the attempt ledger {path}: {exc}") from exc
    records = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Refusal(
                "unreadable-ledger",
                f"line {number} of the attempt ledger {path} is not a record: {exc}; "
                "authorization cannot be checked against a history that does not parse",
            ) from exc
        if not isinstance(record, dict):
            raise Refusal(
                "unreadable-ledger",
                f"line {number} of the attempt ledger {path} is not a record object",
            )
        if record.get("kind") == "claim":
            records.append(record)
    return records


def check_authorized(staffed: list[str], routes: dict[str, dict], claims: list[dict]) -> None:
    """Every reported route was claimed at the gate before it ran."""
    for lens in staffed:
        route = routes[lens]
        mine = [record for record in claims if record.get("lens") == lens]
        if any(
            record.get("transport") == route["transport"] and record.get("model") == route["model"]
            for record in mine
        ):
            continue
        recorded = ", ".join(
            sorted({f"{record.get('transport')}/{record.get('model')}" for record in mine})
        )
        raise Refusal(
            "unauthorized-dispatch",
            f"lens {lens!r} reports from {route['transport']}/{route['model']}, which the gate "
            f"never authorized this round; it claimed {recorded or 'nothing'}. Output from a "
            "dispatch that went around the gate is refused rather than read",
        )


def settled_index(round_meta: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Settled items keyed by the lens and id that would re-cite them.

    Matching is exact re-citation and nothing else: a fuzzy match would suppress a live
    finding on a resemblance no one can audit.
    """
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in round_meta.get("prior_dispositions", []):
        if not isinstance(entry, dict):
            continue
        lens, item = entry.get("lens"), entry.get("id")
        if blank(lens) or blank(item):
            continue
        index[(lens, item)] = entry
    return index


def envelope_dispositions(round_meta: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in entry.items() if key not in LEDGER_ONLY_FIELDS}
        for entry in round_meta.get("prior_dispositions", [])
        if isinstance(entry, dict)
    ]


def read_report(lens: str, path: str) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("bad-report", f"cannot read the {lens} report {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise Refusal("bad-report", f"the {lens} report {path} is not a report object")
    stated = document.get("lens")
    if not blank(stated) and stated != lens:
        raise Refusal(
            "lens-mismatch",
            f"the report at {path} is filed under lens {lens!r} but reports as {stated!r}; a "
            "report attributed to the wrong lens misstates which mandate found the defect",
        )
    findings = document.get("findings", [])
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise Refusal("bad-report", f"the {lens} report {path} has no list of finding objects")
    return document


def collect(
    staffed: list[str], reports: dict[str, str], settled: dict[tuple[str, str], dict]
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Findings, suppressions, and each lens's own verdict, in the round's lens order."""
    findings: list[dict[str, Any]] = []
    suppressions: list[dict[str, Any]] = []
    lens_verdicts: dict[str, str] = {}
    seen: dict[str, str] = {}
    for lens in staffed:
        path = reports[lens]
        report = read_report(lens, path)
        raised = report.get("findings", [])
        # A lens's verdict is its findings; a declared word that disagrees with its own
        # list is not a second fact about the round.
        lens_verdicts[lens] = "findings" if raised else "clean"
        for raw in raised:
            finding = dict(raw)
            finding["lens"] = lens
            item = finding.get("id")
            if blank(item):
                raise Refusal(
                    "bad-report",
                    f"the {lens} report {path} carries a finding with no id; an unidentified "
                    "finding can be neither dispositioned nor suppressed later",
                )
            if finding.get("type") == "mechanical" and blank(finding.get("evidence")):
                # Never dropped and never left blocking: an unevidenced mechanical claim
                # cannot be acted on, and the marker keeps the demotion countable.
                finding["type"] = "advisory"
                finding["downgraded_from"] = "mechanical"
            match = settled.get((lens, item))
            if match is not None:
                suppressions.append({
                    "lens": lens,
                    "finding_id": item,
                    "settled_id": match.get("id"),
                    "settled_round": match.get("round"),
                    "disposition": match.get("disposition"),
                })
                continue
            if item in seen:
                raise Refusal(
                    "duplicate-finding-id",
                    f"finding id {item!r} is raised by both {seen[item]!r} and {lens!r}; two "
                    "findings sharing an id cannot be dispositioned apart",
                )
            seen[item] = lens
            findings.append(finding)
    suppressions.sort(key=lambda entry: (entry["lens"], entry["finding_id"]))
    return findings, suppressions, lens_verdicts


def build_halt(
    indict: str, findings: list[dict], repo_root: str | None
) -> dict[str, Any]:
    """The upstream-defect halt: the round measured against a ruler it now says is bent."""
    item, sep, target = indict.partition("=")
    if not sep or blank(item) or blank(target):
        raise Refusal(
            "bad-indictment", f"--indict takes <finding-id>=<artifact-path>; {indict!r} is not that"
        )
    if not any(finding.get("id") == item for finding in findings):
        raise Refusal(
            "bad-indictment",
            f"finding {item!r} indicts an upstream artifact but is not in this round's findings; "
            "a halt names a finding the verdict itself carries",
        )
    if not repo_root:
        raise Refusal(
            "bad-indictment",
            "--repo-root is required with --indict: the indicted artifact is recorded relative to "
            "the repository, because the resume check re-reads it from there",
        )
    root = Path(repo_root).resolve()
    resolved = Path(target) if Path(target).is_absolute() else root / target
    try:
        payload = resolved.read_bytes()
    except OSError as exc:
        raise Refusal(
            "bad-indictment", f"cannot read the indicted artifact {resolved}: {exc}"
        ) from exc
    try:
        relative = resolved.resolve().relative_to(root)
    except ValueError as exc:
        raise Refusal(
            "bad-indictment",
            f"the indicted artifact {resolved} is outside the repository root {root}; the resume "
            "check resolves the recorded path against that root and would never find it",
        ) from exc
    return {
        "reason": "upstream-defect",
        "indicted_finding": item,
        "indicted_artifact": str(relative),
        "artifact_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        # Every staffed lens reported: the round stopped on its own finding, not on a
        # route that died with dispatches still to make.
        "abandoned_lenses": [],
    }


def staffing_check(envelope: dict[str, Any], directory: Path) -> tuple[list[str], list[str]]:
    """The verdict against the record it was dispatched from: same bytes, same lens set.

    The digest recorded at emission is what identifies the record, so a record that has
    moved since costs the path half of the check and nothing more.
    """
    record = envelope["staffing_record"]
    if not isinstance(record, dict):
        # The schema errors already name a malformed record; a second complaint is noise.
        return [], []
    stated = record.get("path")
    if blank(stated):
        return [], [
            "the round names no staffing record path, so the record cannot be re-read; the "
            "verdict is checked against the schema only, and the digest it carries governs"
        ]
    path = Path(stated)
    if not path.is_file() and not path.is_absolute():
        path = directory / stated
    try:
        payload = path.read_bytes()
        staffing = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [
            f"the staffing record {stated} is not readable now ({exc}); the verdict is checked "
            "against the schema only, and the digest recorded at emission governs"
        ]
    errors = []
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    if digest != record.get("digest"):
        errors.append(
            f"the staffing record {stated} is {digest} now, but the round was dispatched from "
            f"{record.get('digest')}; a record edited after the round is not what it answers to"
        )
    lenses = staffing.get("lenses") if isinstance(staffing, dict) else None
    if isinstance(lenses, list):
        reported = {entry["lens"] for entry in envelope["lenses"]}
        missing = sorted(set(lenses) - reported)
        extra = sorted(reported - set(lenses))
        if missing:
            errors.append(f"staffed lens(es) {', '.join(missing)} report nothing")
        if extra:
            errors.append(f"lens(es) {', '.join(extra)} report but are not staffed")
    return errors, []


def validate(envelope: dict[str, Any], schema: Path | None, directory: Path) -> list[str]:
    if schema is None:
        raise Refusal(
            "no-schema",
            "no verdict schema was found beside this skill and none was passed with --schema; an "
            "envelope nothing validated is not a verdict",
        )
    from jsonschema import Draft202012Validator

    with schema.open(encoding="utf-8") as handle:
        validator = Draft202012Validator(json.load(handle))
    problems = [error.message for error in sorted(validator.iter_errors(envelope), key=str)]
    staffing_errors, warnings = staffing_check(envelope, directory)
    problems += staffing_errors
    if problems:
        raise Refusal(
            "invalid-envelope",
            "the assembled verdict does not satisfy the verdict contract, so nothing was "
            f"written: {problems[0]}",
        )
    return warnings


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    directory, round_meta = read_round(args.round_dir)
    staffed = staffed_lenses(round_meta)
    reports = parse_pairs(args.report, "--report")
    routes = read_routes(args.routes)
    check_coverage(staffed, reports, routes)
    check_authorized(staffed, routes, read_claims(directory))

    findings, suppressions, lens_verdicts = collect(staffed, reports, settled_index(round_meta))
    envelope: dict[str, Any] = {
        "schema_version": "3",
        **{key: round_meta.get(key) for key in COPIED_FROM_ROUND},
        "lenses": [
            {
                "lens": lens,
                "verdict": lens_verdicts[lens],
                **{field: routes[lens][field] for field in ("vendor", "transport", "model")},
                **({"substitution": routes[lens]["substitution"]}
                   if "substitution" in routes[lens] else {}),
            }
            for lens in staffed
        ],
        "prior_dispositions": envelope_dispositions(round_meta),
        "verdict": "findings" if findings else "clean",
        "findings": findings,
    }
    if args.indict:
        envelope["halt"] = build_halt(args.indict, findings, args.repo_root)
        envelope["verdict"] = "halted"

    if not args.out:
        raise Refusal("bad-round", "no --out was supplied; the verdict is written to a file")
    warnings = validate(envelope, find_schema(args.schema), directory)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out.parent / SUPPRESSIONS_NAME).write_text(
        json.dumps(suppressions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    answer = {
        "assembled": True,
        "out": str(out),
        "verdict": envelope["verdict"],
        "mechanical": sum(1 for item in findings if item.get("type") == "mechanical"),
        "advisory": sum(1 for item in findings if item.get("type") != "mechanical"),
        "suppressed": len(suppressions),
        # One distinct vendor means the panel collapsed onto it, and blind spots
        # correlate inside a vendor. The count is reported wherever the round is.
        "distinct_vendors": len({routes[lens]["vendor"] for lens in staffed}),
    }
    if warnings:
        answer["warnings"] = warnings
    return answer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--round-dir")
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--routes")
    parser.add_argument("--out")
    parser.add_argument("--schema")
    parser.add_argument("--repo-root")
    parser.add_argument("--indict")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = assemble(args)
    except Refusal as exc:
        print(json.dumps({"assembled": False, "errors": [exc.as_dict()]}, sort_keys=True))
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        print(json.dumps(
            {"assembled": False, "errors": [{"code": "assembler-failure", "message": str(exc)}]},
            sort_keys=True,
        ))
        return EXIT_REFUSED
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
