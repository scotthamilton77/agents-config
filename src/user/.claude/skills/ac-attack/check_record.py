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
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "attack-record.schema.json"
LENSES_PATH = HERE / "lenses.json"

EXIT_COMPLETE = 0
EXIT_INCOMPLETE = 1
EXIT_UNUSABLE = 2

DECLARATION = "--implementation-started"

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


@lru_cache(maxsize=1)
def declared_lenses() -> tuple[str, ...]:
    """The declared lens set, refused unless the emitter would emit a round from it.

    Cached: the file is static for the life of a run. Coverage is read off this set, so it has to
    be the set the round was dispatched from — a registry the emitter refuses could not have
    produced the round in hand, and a name declared twice would demand the same lens twice here.
    Names are compared case-insensitively because a lens's name is its prompt's filename, and two
    names differing only in case are one file on a case-insensitive volume.
    """
    with LENSES_PATH.open(encoding="utf-8") as handle:
        lenses = json.load(handle)["lenses"]
    names = [entry["lens"] for entry in lenses if isinstance(entry.get("lens"), str)]
    folded = [name.lower() for name in names]
    if not lenses:
        problem = "declares no lens"
    elif len(names) != len(lenses):
        problem = "declares an entry without its lens name"
    elif len(set(folded)) != len(folded):
        problem = "names one lens twice"
    elif any(name != Path(name).name or name in ("", ".", "..") for name in names):
        problem = "names a lens that is not a bare filename"
    else:
        return tuple(names)
    raise RecordError(
        "no-lenses",
        f"the lens registry {problem}; the emitter refuses to emit a round from a registry like "
        "this one, so no round in hand came from it, and coverage read off it credits the record "
        "with attackers that never ran — repair the registry both scripts read",
    )


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


def read_document(record_path: Path, record: dict, override: str | None) -> tuple[Path, bytes]:
    """Find the attacked document: --spec if given, else spec_path relative to the record.

    The record is committed beside the document it names, so that directory is the only one
    searched: a same-named file in whatever directory the check happens to run from is not the
    attacked document, and reading it would check the round against unrelated text. A spec_path
    that is not a bare filename leads back out of that directory and is refused for the same
    reason. --spec is read for presence, not content — a wrapper passing an unset variable is
    refused rather than falling back to the document the record names.
    """
    if override is not None and not override.strip():
        raise RecordError(
            "no-spec",
            "--spec was given without a document; name the document to check the round against, "
            "or drop the option to read the one the record names",
        )
    if override is not None:
        path = Path(override)
    else:
        name = record["spec_path"]
        if name != Path(name).name or name in ("", ".", ".."):
            raise RecordError(
                "spec-not-a-bare-filename",
                f"the record names its document {name!r}, which is not a bare filename; the "
                "record is committed beside the document it attacked, so name that document's "
                "basename — a path leading out of the record's own directory names a document no "
                "attacker in this round read",
            )
        path = record_path.parent / name
    try:
        return path, path.read_bytes()
    except OSError as exc:
        raise RecordError(
            "spec-unreadable",
            f"cannot read the attacked document {path}: {exc}; the record names it relative to "
            "its own directory, and --spec overrides that when the document has moved",
        ) from exc


def revisions_of(data: bytes) -> dict[str, str]:
    """This content's revision written in each notation; both name these exact bytes."""
    blob = b"blob %d\0" % len(data) + data
    return {
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
        "object id": hashlib.sha1(blob, usedforsecurity=False).hexdigest(),
    }


def notation_of(revision: str) -> str:
    """Which of the two ways of writing a revision this one is written in."""
    return "digest" if revision.startswith("sha256:") else "object id"


def require_comparable_revisions(record: dict) -> None:
    """Refuse a record that writes one content as two revision strings.

    Revisions are compared as strings, and the checker cannot reconcile two that differ: a revision
    is a hash, and the content it names is not recoverable from it. So one content written two ways
    — in both notations, which share no characters, or with the whitespace a tool left on it —
    reads as two revisions, and an acceptance naming the very revision it attacked passes as an
    incorporation. Held to one spelling, string equality decides revision identity soundly.

    Only the revisions the adjudication reads are checked. A `revision` left behind on a
    disposition flipped to rejected decides nothing, and refusing the whole record over it would
    send the reader to debug a field that does not matter.
    """
    revisions = [record["spec_revision"]] + [
        entry["revision"] for entry in record["dispositions"]
        if entry["disposition"] == "accepted"
    ]
    for revision in revisions:
        if revision != revision.strip():
            raise RecordError(
                "untrimmed-revision",
                f"the revision {revision!r} carries surrounding whitespace; strip it — "
                "git hash-object ends its output with a newline, and a revision carrying that "
                "newline compares unequal to the same revision written without it, so an "
                "acceptance that changed nothing could pass as an incorporation",
            )
    if len({notation_of(revision) for revision in revisions}) > 1:
        raise RecordError(
            "mixed-revision-notation",
            "this record writes revisions in both notations, as a digest and as an object id; "
            "revisions are compared as strings, so one content written both ways would read as "
            "two revisions and an acceptance that changed nothing could pass as an incorporation",
        )


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


def _report_errors(record: dict) -> list[dict[str, Any]]:
    """Hold each lens's report against the proposals attributed to it.

    A report and the proposal list are two accounts of the same round, and a record where they
    disagree describes no round at all: it either credits a lens with work it did not report or
    loses the work it did.
    """
    declared = set(declared_lenses())
    attributed = {proposal["lens"] for proposal in record["proposals"]}
    errors = [
        {"code": "unknown-proposal-lens", "id": proposal["id"],
         "message": f"proposal {proposal['id']!r} is attributed to {proposal['lens']!r}, which is "
                    "not one of the declared attack lenses; every proposal carries the lens that "
                    "produced it"}
        for proposal in record["proposals"]
        if proposal["lens"] not in declared
    ]
    for entry in record["lenses"]:
        name, report = entry["lens"], entry["report"]
        if report == "empty" and name in attributed:
            errors.append({
                "code": "contradicted-empty-report",
                "message": f"the {name} lens reports empty, yet proposals in this round are "
                           "attributed to it; a report and the proposal list are one account",
            })
        elif report == "proposals" and name not in attributed:
            errors.append({
                "code": "contradicted-proposals-report",
                "message": f"the {name} lens reports proposals, yet none in this round are "
                           "attributed to it; a proposal it made and the record lost is a hole "
                           "nobody adjudicates",
            })
    return errors


def _disposition_errors(record: dict) -> tuple[list[dict[str, Any]], set[str]]:
    """Adjudication of every proposal, plus the revisions the acceptances account for.

    A disposition names its proposal by id, not by position: dropping a malformed proposal
    renumbers every position after it, and a disposition keyed on position would then adjudicate a
    proposal nobody wrote it against. Two proposals sharing an id leave the same doubt, so the
    round is refused rather than resolved either way.

    An acceptance names a revision other than the one attacked, decided by string comparison: the
    record is refused upstream unless every revision in it is written in one notation, so two
    revision strings differ exactly when the content they name does.
    """
    ids = [proposal["id"] for proposal in record["proposals"]]
    attacked = record["spec_revision"]
    errors: list[dict[str, Any]] = [
        {"code": "duplicate-proposal-id", "id": name,
         "message": f"two proposals in this round carry the id {name!r}; a disposition naming it "
                    "adjudicates neither of them, so give each proposal an id of its own"}
        for name in dict.fromkeys(ids)
        if ids.count(name) > 1
    ]
    accounted: set[str] = set()
    seen: set[str] = set()
    for entry in record["dispositions"]:
        name = entry["id"]
        if name not in ids:
            errors.append({
                "code": "unknown-proposal-id", "id": name,
                "message": f"there is no proposal {name!r} in this round; every disposition "
                           "adjudicates a proposal the round holds",
            })
            continue
        if name in seen:
            errors.append({
                "code": "duplicate-disposition", "id": name,
                "message": f"proposal {name!r} is adjudicated more than once; each proposal gets "
                           "exactly one disposition",
            })
            continue
        seen.add(name)
        if entry["disposition"] == "accepted":
            if entry["revision"] == attacked:
                errors.append({
                    "code": "unincorporated-acceptance", "id": name,
                    "message": f"proposal {name!r} was accepted against the revision it attacked; "
                               "accepting a proposal without changing the document leaves it "
                               "unadjudicated",
                })
            else:
                accounted.add(entry["revision"])
    for name in dict.fromkeys(ids):
        if name not in seen:
            errors.append({
                "code": "unadjudicated-proposal", "id": name,
                "message": f"proposal {name!r} has no disposition; the round closes only once "
                           "every proposal is accepted or rejected",
            })
    return errors, accounted


def check(record: dict, document: bytes) -> list[dict[str, Any]]:
    """Everything wrong with this round, as a pure function of the record and the document."""
    present = set(revisions_of(document).values())
    errors = _lens_errors(record) + _report_errors(record)
    disposition_errors, accounted = _disposition_errors(record)
    errors += disposition_errors
    # An acceptance says the document was edited to carry the proposal, so the revision attacked
    # accounts for the document only in a round that accepted nothing. Unioning it in regardless
    # would close a round whose edit was reverted, lost in a rebase, or never made — clearing work
    # to start against criteria every accepted proposal is absent from. Containment rather than
    # intersection for the same reason: the document hashes to one content, so matching just one of
    # several accepted revisions lets a reverted final edit, or an acceptance carrying a fabricated
    # revision, ride in on whichever acceptance does match.
    required = accounted or {record["spec_revision"]}
    if not required <= present:  # every accepted revision, not merely one
        errors.append({
            "code": "stale-revision",
            "message": "the document does not hash to every revision this round accounts for — "
                       "each acceptance names the revision that carries it, and the document is "
                       "one content, so a record whose acceptances name several different "
                       "revisions asks it to be in two states at once; name in every acceptance "
                       "the revision the document reached once every accepted proposal was in it, "
                       "and in a round that accepted nothing the revision attacked, or attack the "
                       "document as it now stands and re-adjudicate against that",
        })
    return errors


def report(errors: list[dict[str, Any]], started: bool, code: int, clean: bool = False,
           read: dict[str, str] | None = None) -> int:
    """Print the result; `read` names the document the verdict was decided against.

    A round checked against a copy handed to --spec answers a different question from one checked
    against the live document, and that substitution is invisible unless the answer says which
    file it read. A run that opened none omits both keys rather than naming a document it never
    read.
    """
    if errors and started:
        errors = [*errors, {"code": "ordering-violation", "message": ORDERING_MESSAGE}]
    result = {
        "clean": clean,
        "complete": code == EXIT_COMPLETE,
        "errors": sorted(errors, key=lambda err: (err["code"], err.get("id", ""), err["message"])),
        **(read or {}),
    }
    print(json.dumps(result, sort_keys=True))
    return code


def declared(argv: list[str]) -> bool:
    """Whether the ordering declaration is on a command line the parse rejected.

    Matched by option name, not by the whole argument: `--implementation-started=true` is what an
    agent writes for a flag it thinks takes a value, argparse rejects it outright because the flag
    takes none, and reading the argument whole would drop the declaration along with the parse —
    reporting the malformed command line while the work claimed against the round goes unanswered.
    """
    return any(arg.split("=", 1)[0] == DECLARATION for arg in argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    # Optional so that naming no record answers in the JSON contract like every other failure,
    # rather than in argparse's usage text on stderr.
    parser.add_argument("record", nargs="?")
    parser.add_argument("--spec")
    parser.add_argument(DECLARATION, action="store_true")
    return parser


def parse_or_report(argv: list[str]) -> argparse.Namespace | int:
    """Parse, or return the exit status after reporting on stdout.

    Argparse exits on its own for a malformed command line, which would end the run without the
    JSON stdout every other failure produces. A caller parsing stdout must not have to special-case
    the one failure that predates the parse.
    """
    try:
        return build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:  # --help asked for and given
            raise
        return report(
            [{"code": "bad-arguments",
              "message": "the command line could not be parsed; an option was given without its "
                         "value, or an unknown option was passed (argparse wrote the detail to "
                         "stderr)"}],
            declared(argv), EXIT_UNUSABLE,
        )


def main(argv: list[str]) -> int:
    args = parse_or_report(argv)
    if isinstance(args, int):
        return args
    started = args.implementation_started
    # What the run knows about the document, filled in the moment one is opened, so a failure after
    # that point still answers which file the verdict was reached over — the reading a caller needs
    # most when the check itself is what broke.
    read: dict[str, str] | None = None
    try:
        if not args.record:
            raise RecordError(
                "no-record",
                "no attack record was named; the check reads the record committed beside the "
                "attacked document, and an unnamed record is not an unattacked one",
            )
        record_path = Path(args.record)
        record = read_record(record_path)
        invalid = schema_errors(record)
        if invalid:
            return report(invalid, started, EXIT_UNUSABLE)
        require_comparable_revisions(record)
        path, document = read_document(record_path, record, args.spec)
        # The revision goes out in the record's own notation: the reader holds it against
        # spec_revision as a string, and the other notation for it would read as another document.
        read = {"document": str(path),
                "revision": revisions_of(document)[notation_of(record["spec_revision"])]}
        errors = check(record, document)
    except RecordError as exc:
        return report([exc.as_dict()], started, EXIT_UNUSABLE, read=read)
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        return report([{"code": "checker-failure", "message": str(exc)}], started, EXIT_UNUSABLE,
                      read=read)
    if errors:
        return report(errors, started, EXIT_INCOMPLETE, read=read)
    return report([], started, EXIT_COMPLETE, clean=not record["proposals"], read=read)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
