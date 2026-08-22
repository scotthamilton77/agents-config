#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Turn a findings verdict into the fix dispatch that round owes its fixer.

Usage: uv run emit_fix_dispatch.py --verdict <verdict.json> --out <dispatch.md>
       [--schema <path>]

Stdout is JSON. Exit 0 on emission, 2 on refusal. Output is deterministic.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EMITTER_PATH = HERE / "emit_prompts.py"

# The deployed layout puts review-verdict beside this skill as a sibling. When no
# schema is found there, the verdict is checked against the structural minimum
# this script reads instead — the same fallback the prompt emitter makes.
SCHEMA_CANDIDATES = (HERE / ".." / "review-verdict" / "verdict.schema.json",)

EXIT_OK = 0
EXIT_REFUSED = 2


def _load_emitter() -> Any:
    spec = importlib.util.spec_from_file_location("review_panel_emit_prompts", EMITTER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - a broken install, not a case
        raise ImportError(f"cannot load {EMITTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The triviality boundary has one home, the prompt emitter's constant: the round that
# measures growth and the dispatch that warns about it must mean the same number, or a
# fix sized to the dispatch still triggers a full rescope nobody was told about.
TRIVIALITY_BOUNDARY: int = _load_emitter().TRIVIALITY_BOUNDARY


class Refusal(Exception):
    """A typed refusal to emit; carries a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def find_schema(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    for candidate in SCHEMA_CANDIDATES:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None


def read_verdict(path: str | None, schema: Path | None) -> dict[str, Any]:
    if not path:
        raise Refusal("bad-verdict", "no --verdict was supplied; a dispatch answers one round")
    target = Path(path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Refusal("bad-verdict", f"cannot read the verdict {target}: {exc}") from exc
    if schema is None:
        # No schema on disk: the structural minimum this script reads.
        if not isinstance(document, dict) or not isinstance(document.get("findings"), list):
            raise Refusal("bad-verdict", f"{target} is not a verdict object")
        return document
    from jsonschema import Draft202012Validator

    with schema.open(encoding="utf-8") as handle:
        validator = Draft202012Validator(json.load(handle))
    errors = sorted(validator.iter_errors(document), key=str)
    if errors:
        raise Refusal(
            "bad-verdict",
            f"{target} does not satisfy the verdict schema: {errors[0].message}. A dispatch "
            "written from an invalid verdict cites findings nothing stands behind",
        )
    return document


def partition(verdict: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Blocking findings and advisories, in the order the verdict states them."""
    findings = [item for item in verdict.get("findings", []) if isinstance(item, dict)]
    mechanical = [item for item in findings if item.get("type") == "mechanical"]
    advisory = [item for item in findings if item.get("type") != "mechanical"]
    return mechanical, advisory


def check_dispatchable(verdict: dict[str, Any], mechanical: list[dict]) -> None:
    word = verdict.get("verdict")
    if word == "clean":
        raise Refusal(
            "no-dispatch-for-clean",
            "this round is clean, and a clean round emits no fix dispatch; there is nothing to "
            "fix and a dispatch that says so is work invented under review pressure",
        )
    if word == "halted":
        raise Refusal(
            "no-dispatch-for-halted",
            "this round halted, and a halt has its own path: a transport failure is re-dispatched "
            "and an indicted upstream artifact is fixed upstream. Neither is fixer work on the "
            "artifact under review",
        )
    if not mechanical:
        raise Refusal(
            "no-blocking-findings",
            "this verdict carries no mechanical finding, so nothing in it blocks; advisories are "
            "carried to the next round as advisories, not dispatched as fixes",
        )


def _finding_block(finding: dict[str, Any]) -> str:
    """One finding, stated in full. A dispatch that maps to nothing is incomplete."""
    evidence = finding.get("evidence")
    lines = [
        f"### {finding.get('id')} — {finding.get('lens')}",
        "",
        f"- Criterion: {finding.get('ac')}",
        f"- Claim: {finding.get('claim')}",
    ]
    if isinstance(evidence, str) and evidence.strip():
        lines.append(f"- Evidence: {evidence}")
    if finding.get("downgraded_from") == "mechanical":
        lines.append(
            "- Downgraded from mechanical: the lens supplied no evidence, so there is nothing "
            "to reproduce and nothing here blocks."
        )
    return "\n".join(lines)


CLAUSES = (
    (
        "Smallest net change",
        "Make the change that closes the finding and stop there. No over-explaining, no "
        "unnecessary code, no prose that restates what the artifact already says. A fix round is "
        "where surface gets minted, and every line minted here is reviewed next round.",
    ),
    (
        "Mutation evidence for code fixes",
        "A code fix names the test that fails without it and passes with it, and says you saw "
        "both. That observation is what the disposition records: on typed code, `fixed` with no "
        "test named in its evidence is refused exactly as a bare rebuttal is. Write the test "
        "first, watch it fail, then fix.",
    ),
    (
        "Replacement-first for prose",
        "Prefer replacing incorrect text over adding text that qualifies it. Growth is paid for "
        f"with reading, not forbidden: a fix whose net growth passes {TRIVIALITY_BOUNDARY} lines "
        "states why replacement could not achieve the fix, and re-staffs a consistency read over "
        "the new text next round, scoped to the diff. Say why in the disposition, where the next "
        "reader will look for it.",
    ),
    (
        "Narration sweep",
        "Mint no transition commentary under review pressure — no \"as before\", no \"has ever "
        "claimed\", no note that a sentence used to say something else. Prose states the current "
        "decision; the history is in the commit log. Before you finish, re-read what you wrote "
        "and cut the sentences that narrate the fix rather than state the decision.",
    ),
)


def render(verdict: dict[str, Any], mechanical: list[dict], advisory: list[dict]) -> str:
    parts = [
        f"# Fix dispatch — round {verdict.get('round')}, claim {verdict.get('claim_id')}",
        "",
        f"- Artifact class: {verdict.get('artifact_class')}",
        f"- Head reviewed: {verdict.get('head_sha')}",
        f"- Base: {verdict.get('base_sha')}",
        "",
        "Every blocking finding of this round is named below in full, because a dispatch that "
        'maps to nothing — "clean up the affected section" — is incomplete by contract. Each one '
        "closes with a disposition: fixed, rebutted with evidence, or deferred as an advisory.",
        "",
        f"## Blocking findings ({len(mechanical)})",
        "",
    ]
    parts.append("\n\n".join(_finding_block(finding) for finding in mechanical))
    parts += ["", f"## Advisories ({len(advisory)}) — not blocking", ""]
    if advisory:
        parts.append(
            "These block nothing. Fix one only if it is cheaper than carrying it; otherwise "
            "defer it and say so. An advisory fixed silently is surface minted for free."
        )
        parts.append("")
        parts.append("\n\n".join(_finding_block(finding) for finding in advisory))
    else:
        parts.append("None this round.")
    parts += ["", "## How the fix is made", ""]
    for index, (title, body) in enumerate(CLAUSES, start=1):
        parts.append(f"{index}. **{title}** — {body}")
    parts.append("")
    return "\n".join(parts)


def emit(args: argparse.Namespace) -> dict[str, Any]:
    schema = find_schema(args.schema)
    verdict = read_verdict(args.verdict, schema)
    mechanical, advisory = partition(verdict)
    check_dispatchable(verdict, mechanical)
    if not args.out:
        raise Refusal("bad-verdict", "no --out was supplied; the dispatch is written to a file")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(verdict, mechanical, advisory), encoding="utf-8")
    return {
        "emitted": True,
        "out": str(out),
        "mechanical": len(mechanical),
        "advisory": len(advisory),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--verdict")
    parser.add_argument("--out")
    parser.add_argument("--schema")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = emit(args)
    except Refusal as exc:
        print(json.dumps({"emitted": False, "errors": [exc.as_dict()]}, sort_keys=True))
        return EXIT_REFUSED
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        print(json.dumps(
            {"emitted": False, "errors": [{"code": "dispatch-failure", "message": str(exc)}]},
            sort_keys=True,
        ))
        return EXIT_REFUSED
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
