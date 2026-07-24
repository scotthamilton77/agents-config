#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Validate a review verdict JSON document against the verdict schema.

Usage: uv run validate_verdict.py <verdict.json>

Prints a JSON result to stdout. Exit 0 valid, 1 invalid, 2 unreadable or unparseable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "verdict.schema.json"

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


def validate_document(document: Any) -> dict[str, Any]:
    """Validate an already-parsed document. Deterministic for identical input."""
    errors = _schema_errors(document) + _duplicate_id_errors(document)
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


def validate_path(path: Path) -> tuple[dict[str, Any], int]:
    try:
        document = read_document(path)
    except VerdictError as exc:
        return {"valid": False, "errors": [exc.as_dict()]}, EXIT_UNUSABLE
    result = validate_document(document)
    return result, EXIT_VALID if result["valid"] else EXIT_INVALID


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        result = {
            "valid": False,
            "errors": [{
                "code": "unreadable",
                "path": "",
                "message": "usage: uv run validate_verdict.py <verdict.json>",
            }],
        }
        print(json.dumps(result, sort_keys=True))
        return EXIT_UNUSABLE
    try:
        result, code = validate_path(Path(argv[0]))
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
