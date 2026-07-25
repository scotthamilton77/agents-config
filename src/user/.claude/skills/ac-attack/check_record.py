#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Check whether an attack record closes its round over the document it attacked.

Usage: uv run check_record.py <record.json> [--spec <path>] [--implementation-started]

Prints a JSON result to stdout. Exit 0 complete, 1 not complete, 2 unusable input.
Read-only and deterministic: the same inputs always produce byte-identical output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "attack-record.schema.json"
LENSES_PATH = HERE / "lenses.json"

EXIT_COMPLETE = 0
EXIT_INCOMPLETE = 1
EXIT_UNUSABLE = 2

ORDERING_MESSAGE = (
    "this round is unfinished and a work item that changes the system the document describes has "
    "already been claimed; the attack runs before that work, never alongside it"
)


class RecordError(Exception):
    """A typed failure to read the round's inputs; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


def declared_lenses() -> list[str]:
    with LENSES_PATH.open(encoding="utf-8") as handle:
        return [lens["lens"] for lens in json.load(handle)["lenses"]]


def read_record(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError("unreadable", f"cannot read the record {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecordError("invalid-json", f"{path} is not valid JSON: {exc}") from exc


def schema_errors(record: Any) -> list[dict[str, Any]]:
    from jsonschema import Draft202012Validator

    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        validator = Draft202012Validator(json.load(handle))
    return [
        {"code": "schema",
         "message": ("/" + "/".join(str(part) for part in err.absolute_path) + ": "
                     if err.absolute_path else "") + err.message}
        for err in validator.iter_errors(record)
    ]


def read_document(record_path: Path, record: dict, override: str | None) -> bytes:
    """Find the attacked document: --spec if given, else spec_path as written or beside the record."""
    raw = override or record.get("spec_path", "")
    candidates = [Path(raw)] if override else [Path(raw), record_path.parent / raw]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return candidate.read_bytes()
            except OSError as exc:
                raise RecordError(
                    "spec-unreadable", f"cannot read the attacked document {candidate}: {exc}"
                ) from exc
    raise RecordError(
        "spec-unreadable",
        f"cannot find the attacked document {raw!r}; the record names it relative to the working "
        "directory or to its own directory, and --spec overrides both",
    )


def revisions_of(data: bytes) -> set[str]:
    """Every revision string that names this exact content."""
    blob = b"blob %d\0" % len(data) + data
    return {
        "sha256:" + hashlib.sha256(data).hexdigest(),
        hashlib.sha1(blob, usedforsecurity=False).hexdigest(),
    }


def _lens_errors(record: dict) -> list[dict[str, Any]]:
    reported = [entry["lens"] for entry in record["lenses"]]
    errors = []
    for name in declared_lenses():
        count = reported.count(name)
        if count == 0:
            errors.append({
                "code": "lens-missing",
                "message": f"the {name} lens has no report; a lens that errored or returned "
                           "unreadable output leaves the round unfinished, and an empty proposal "
                           "list never stands in for a report",
            })
        elif count > 1:
            errors.append({
                "code": "duplicate-lens",
                "message": f"the {name} lens reports {count} times; coverage is read off one "
                           "entry per lens",
            })
    for name in sorted(set(reported) - set(declared_lenses())):
        errors.append({
            "code": "unknown-lens",
            "message": f"{name!r} reported, but it is not one of the declared attack lenses",
        })
    return errors


def _disposition_errors(record: dict, present: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """Adjudication of every proposal, plus the revisions the acceptances account for.

    `present` is every revision naming the document's current content, which is what lets an
    acceptance that renames the attacked revision in the other notation be caught as a rename.
    """
    proposals, attacked = record["proposals"], record["spec_revision"]
    errors: list[dict[str, Any]] = []
    accounted: set[str] = set()
    seen: set[int] = set()
    for entry in record["dispositions"]:
        index = entry["index"]
        if index >= len(proposals):
            errors.append({
                "code": "unknown-proposal-index", "index": index,
                "message": f"there is no proposal {index}; the round holds {len(proposals)}",
            })
            continue
        if index in seen:
            errors.append({
                "code": "duplicate-disposition", "index": index,
                "message": f"proposal {index} is adjudicated more than once; each proposal gets "
                           "exactly one disposition",
            })
            continue
        seen.add(index)
        if entry["disposition"] == "accepted":
            revision, covering = entry.get("revision", ""), entry.get("covering_ac", "").strip()
            if not revision or not covering:
                errors.append({
                    "code": "unincorporated-acceptance", "index": index,
                    "message": f"proposal {index} was accepted without naming both the revision "
                               "of the document that now carries it and the criterion that does",
                })
            elif revision == attacked or {revision, attacked} <= present:
                errors.append({
                    "code": "unincorporated-acceptance", "index": index,
                    "message": f"proposal {index} was accepted against the revision it attacked; "
                               "accepting a proposal without changing the document leaves it "
                               "unadjudicated",
                })
            else:
                accounted.add(revision)
        elif not entry.get("rationale", "").strip():
            errors.append({
                "code": "missing-rationale", "index": index,
                "message": f"proposal {index} was rejected with no reason stated; out of scope is "
                           "a judgement, and a judgement is written down",
            })
    for index in range(len(proposals)):
        if index not in seen:
            errors.append({
                "code": "unadjudicated-proposal", "index": index,
                "message": f"proposal {index} has no disposition; the round closes only once "
                           "every proposal is accepted or rejected",
            })
    return errors, accounted


def check(record: dict, document: bytes) -> list[dict[str, Any]]:
    """Everything wrong with this round, as a pure function of the record and the document."""
    present = revisions_of(document)
    errors = _lens_errors(record)
    disposition_errors, accounted = _disposition_errors(record, present)
    errors += disposition_errors
    if not present & (accounted | {record["spec_revision"]}):
        errors.append({
            "code": "stale-revision",
            "message": "the document has changed since the round, into a revision no acceptance "
                       "accounts for; attack the new revision or re-adjudicate the proposals "
                       "against it",
        })
    return errors


def report(errors: list[dict[str, Any]], started: bool, code: int, clean: bool = False) -> int:
    if errors and started:
        errors = [*errors, {"code": "ordering-violation", "message": ORDERING_MESSAGE}]
    result = {
        "clean": clean,
        "complete": code == EXIT_COMPLETE,
        "errors": sorted(errors, key=lambda err: (err["code"], err.get("index", -1),
                                                  err["message"])),
    }
    print(json.dumps(result, sort_keys=True))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("record")
    parser.add_argument("--spec")
    parser.add_argument("--implementation-started", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    started = args.implementation_started
    try:
        record_path = Path(args.record)
        record = read_record(record_path)
        invalid = schema_errors(record)
        if invalid:
            return report(invalid, started, EXIT_UNUSABLE)
        document = read_document(record_path, record, args.spec)
    except RecordError as exc:
        return report([exc.as_dict()], started, EXIT_UNUSABLE)
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        return report([{"code": "unreadable", "message": str(exc)}], started, EXIT_UNUSABLE)
    errors = check(record, document)
    if errors:
        return report(errors, started, EXIT_INCOMPLETE)
    return report([], started, EXIT_COMPLETE, clean=not record["proposals"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
