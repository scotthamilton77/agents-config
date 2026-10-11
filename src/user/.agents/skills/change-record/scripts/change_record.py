#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Check a change record, the JSON document a pull request's description is written from.

Usage: uv run change_record.py lint <record.json>

``lint`` checks a record against the record schema and prints a JSON result to
stdout. Exit 0 valid, 1 invalid, 2 unreadable, unparseable or called wrongly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "record.schema.json"

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_UNUSABLE = 2


class RecordError(Exception):
    """A record that could not be read at all; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_schema() -> dict[str, Any]:
    """Read the record schema that ships beside this script."""
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_record(path: Path) -> Any:
    """Parse the record at ``path``, or raise a ``RecordError`` saying why it cannot be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError("unreadable", f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecordError("invalid-json", f"{path} is not valid JSON: {exc}") from exc


def _finding(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _schema_faults(record: Any) -> set[tuple[str, str]]:
    """Check the record's structure and return one (path, message) pair per fault.

    The validator reports a missing field and an undefined field at the object
    that should hold them, and names the field only in its message. Those two
    kinds are re-pointed at the field itself, so a reader of the path alone
    knows what to fix. The validator also raises the missing-field error once
    per missing field, which is why the faults are gathered in a set.
    """
    from jsonschema import Draft202012Validator

    faults: set[tuple[str, str]] = set()
    for err in Draft202012Validator(load_schema()).iter_errors(record):
        parent = "".join(f"/{part}" for part in err.absolute_path)
        if err.validator == "required":
            missing = [name for name in err.validator_value if name not in err.instance]
            faults |= {(f"{parent}/{name}", "this required field is missing") for name in missing}
        elif err.validator == "additionalProperties":
            extra = [name for name in err.instance if name not in err.schema.get("properties", {})]
            faults |= {(f"{parent}/{name}", "the record schema defines no such field") for name in extra}
        else:
            faults.add((parent, err.message))
    return faults


def lint_record(record: Any) -> list[dict[str, str]]:
    """Return every finding against an already-parsed record, in path order."""
    return [_finding("schema", path, message) for path, message in sorted(_schema_faults(record))]


def _lint(args: argparse.Namespace) -> int:
    """Run ``lint``: print the result as JSON and return the exit status."""
    try:
        findings = lint_record(read_record(args.record))
    except RecordError as exc:
        unreadable = [_finding(exc.code, "", exc.message)]
        print(json.dumps({"valid": False, "errors": unreadable}, sort_keys=True))
        return EXIT_UNUSABLE
    if findings:
        print(json.dumps({"valid": False, "errors": findings}, sort_keys=True))
        return EXIT_INVALID
    print(json.dumps({"valid": True}))
    return EXIT_VALID


def build_parser() -> argparse.ArgumentParser:
    """Build the command line. Each subcommand names the function that runs it as ``run``."""
    parser = argparse.ArgumentParser(
        prog="change_record.py",
        description="Work on a change record, the JSON document a pull request's description, "
        "commit message and review replies are written from.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    lint = commands.add_parser(
        "lint",
        help="check a record against the record schema",
        description="Check a record against the record schema. Prints a JSON result to stdout. "
        "Exit 0 valid, 1 invalid, 2 unreadable or unparseable.",
    )
    lint.add_argument("record", type=Path, help="path to the record's JSON file")
    lint.set_defaults(run=_lint)
    return parser


def main(argv: list[str]) -> int:
    """Run the subcommand the arguments name and return its exit status."""
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
