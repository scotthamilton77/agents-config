#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Validate a review verdict JSON document against the verdict schema.

Usage: uv run validate_verdict.py <verdict.json> [--staffing <staffing.json>]

Given a staffing record, also checks the verdict against it: the digest the verdict
names must be that file's, and the lenses it reports must be exactly the staffed set.

Prints a JSON result to stdout. Exit 0 valid, 1 invalid, 2 unreadable or unparseable.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

SCHEMA_PATH = Path(__file__).resolve().parent / "verdict.schema.json"

USAGE = "usage: uv run validate_verdict.py <verdict.json> [--staffing <staffing.json>]"

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_UNUSABLE = 2


class VerdictError(Exception):
    """A typed validation failure; carries a stable machine-readable code."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _pointer(parts: Any) -> str:
    return "/" + "/".join(str(part) for part in parts) if parts else ""


def _schema_errors(document: Any) -> list[dict[str, str]]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(load_schema())
    return [
        {"code": "schema", "path": _pointer(err.absolute_path), "message": err.message}
        for err in validator.iter_errors(document)
    ]


def _duplicate_id_errors(document: Any) -> list[dict[str, str]]:
    if not isinstance(document, dict):
        return []
    findings = document.get("findings")
    if not isinstance(findings, list):
        return []
    seen: set[str] = set()
    errors: list[dict[str, str]] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        finding_id = finding.get("id")
        if not isinstance(finding_id, str):
            continue
        if finding_id in seen:
            errors.append({
                "code": "duplicate-finding-id",
                "path": f"/findings/{index}/id",
                "message": f"finding id {finding_id!r} is not unique within the artifact",
            })
        seen.add(finding_id)
    return errors


def _duplicate_lens_errors(document: Any) -> list[dict[str, str]]:
    """One entry per lens, always. A re-dispatched lens reports once, not once per attempt."""
    if not isinstance(document, dict):
        return []
    lenses = document.get("lenses")
    if not isinstance(lenses, list):
        return []
    seen: set[str] = set()
    errors: list[dict[str, str]] = []
    for index, entry in enumerate(lenses):
        if not isinstance(entry, dict):
            continue
        name = entry.get("lens")
        if not isinstance(name, str):
            continue
        if name in seen:
            errors.append({
                "code": "duplicate-lens",
                "path": f"/lenses/{index}/lens",
                "message": f"lens {name!r} reports more than once; a lens has exactly one entry",
            })
        seen.add(name)
    return errors


class Staffing(NamedTuple):
    """A staffing record reduced to the two things a verdict is answerable to."""

    digest: str
    lenses: frozenset[str]


def _staffing_errors(document: Any, staffing: Staffing) -> list[dict[str, str]]:
    """Check the verdict against the record it was dispatched from.

    Skips whatever the document states malformedly: the schema errors already name it,
    and a second complaint about the same field is noise.
    """
    if not isinstance(document, dict):
        return []
    errors: list[dict[str, str]] = []

    record = document.get("staffing_record")
    claimed = record.get("digest") if isinstance(record, dict) else None
    if isinstance(claimed, str) and claimed != staffing.digest:
        errors.append({
            "code": "staffing-digest-mismatch",
            "path": "/staffing_record/digest",
            "message": (f"verdict names staffing record {claimed}, "
                        f"but the supplied file is {staffing.digest}"),
        })

    lenses = document.get("lenses")
    if not isinstance(lenses, list):
        return errors
    reported: set[str] = set()
    for index, entry in enumerate(lenses):
        if not isinstance(entry, dict):
            continue
        name = entry.get("lens")
        if not isinstance(name, str):
            continue
        reported.add(name)
        if name not in staffing.lenses:
            errors.append({
                "code": "lens-not-staffed",
                "path": f"/lenses/{index}/lens",
                "message": f"lens {name!r} reports but the staffing record does not staff it",
            })
    for name in sorted(staffing.lenses - reported):
        errors.append({
            "code": "staffing-coverage-gap",
            "path": "/lenses",
            "message": f"staffed lens {name!r} is not reported; silence is not a clean lens",
        })
    return errors


def validate_document(document: Any, staffing: Staffing | None = None) -> dict[str, Any]:
    """Validate an already-parsed document. Deterministic for identical input."""
    errors = (_schema_errors(document) + _duplicate_id_errors(document)
              + _duplicate_lens_errors(document))
    if staffing is not None:
        errors += _staffing_errors(document, staffing)
    if not errors:
        return {"valid": True}
    errors.sort(key=lambda err: (err["path"], err["code"], err["message"]))
    return {"valid": False, "errors": errors}


def read_document(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerdictError("unreadable", "", f"cannot read {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise VerdictError("unreadable", "", f"cannot decode {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerdictError("invalid-json", "", f"{path} is not valid JSON: {exc}") from exc


def read_staffing(path: Path) -> Staffing:
    """Read a staffing record: the digest of its bytes, and the lens set it staffs.

    Only the ``lenses`` key is read — the rest of the record's shape is owned elsewhere.
    A record that does not carry that key as a list of strings cannot answer the coverage
    question at all, so it is refused rather than read as staffing nothing.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise VerdictError("unreadable", "", f"cannot read staffing record {path}: {exc}") from exc
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerdictError(
            "unreadable", "", f"staffing record {path} is not readable JSON: {exc}"
        ) from exc
    lenses = record.get("lenses") if isinstance(record, dict) else None
    if not isinstance(lenses, list) or not all(isinstance(name, str) for name in lenses):
        raise VerdictError(
            "unreadable", "", f"staffing record {path} has no 'lenses' list of lens names"
        )
    return Staffing(digest=digest, lenses=frozenset(lenses))


def validate_path(path: Path, staffing_path: Path | None = None) -> tuple[dict[str, Any], int]:
    try:
        document = read_document(path)
        staffing = read_staffing(staffing_path) if staffing_path is not None else None
    except VerdictError as exc:
        return {"valid": False, "errors": [exc.as_dict()]}, EXIT_UNUSABLE
    result = validate_document(document, staffing)
    return result, EXIT_VALID if result["valid"] else EXIT_INVALID


def parse_args(argv: list[str]) -> tuple[Path, Path | None]:
    """Read the verdict path and the optional staffing path, given either spelling.

    The staffing record is a second positional or the value of ``--staffing``.
    """
    positional: list[str] = []
    staffing: str | None = None
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--staffing":
            if not rest or staffing is not None:
                raise VerdictError("unreadable", "", USAGE)
            staffing = rest.pop(0)
        else:
            positional.append(arg)
    if not positional or len(positional) > 2 or (len(positional) == 2 and staffing is not None):
        raise VerdictError("unreadable", "", USAGE)
    if len(positional) == 2:
        staffing = positional[1]
    return Path(positional[0]), Path(staffing) if staffing is not None else None


def main(argv: list[str]) -> int:
    try:
        verdict_path, staffing_path = parse_args(argv)
        result, code = validate_path(verdict_path, staffing_path)
    except VerdictError as exc:
        print(json.dumps({"valid": False, "errors": [exc.as_dict()]}, sort_keys=True))
        return EXIT_UNUSABLE
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        result = {
            "valid": False,
            "errors": [{"code": "unreadable", "path": "", "message": str(exc)}],
        }
        code = EXIT_UNUSABLE
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
