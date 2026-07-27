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
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "attack-record.schema.json"
LENSES_PATH = HERE / "lenses.json"
REQUIRED_KEYS = ("lens", "mandate", "tier", "transport")

# What the record wears once the document's own extension is dropped.
RECORD_SUFFIX = "-ac-attack.json"

# The emitter's untrusted-content markers, held again here because the two scripts deploy
# separately and neither can import the other. Two copies of a constant drift, so a test runs both
# scripts over one document and holds the verdicts together rather than trusting the copy.
FENCE_OPEN = "<<<BEGIN UNTRUSTED CONTENT>>>"
FENCE_CLOSE = "<<<END UNTRUSTED CONTENT>>>"

# A byte-order mark at the head of a document and a zero-width no-break space anywhere else, and
# `strip` removes neither. Escaped rather than written out, since no reader sees one on the page.
BOM = "\ufeff"

EXIT_COMPLETE = 0
EXIT_INCOMPLETE = 1
EXIT_UNUSABLE = 2

DECLARATION = "--implementation-started"
# What an agent writes to say the work has not started, in either spelling a valued option takes.
# The flag takes no value, so a command line writing one refuses either way — as unparseable, or
# for want of the record the denial was read as; what is at stake is only what the answer says back.
NEGATIONS = frozenset({"false", "0", "no", "off"})

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


def fold(name: str) -> str:
    """A lens name as the filesystem holding its prompt matches it — the emitter's comparison.

    The volumes this runs on match without regard to case or to which Unicode form composed a
    character, so two names held apart by anything less are one prompt file once a round lands.
    """
    return unicodedata.normalize("NFC", name).casefold()


def usable(value: Any) -> bool:
    """Whether a registry field carries something an attacker can be built from — the emitter's.

    Present is not usable. An entry carrying `"mandate": ""` is one the emitter refuses outright,
    so a registry holding it dispatched nothing; and a lens named with only whitespace passes for
    a name to demand a report for, while the record schema forbids any record from carrying it —
    the round is then unclosable by any record, and no error names the entry that made it so.
    """
    return isinstance(value, str) and bool(value.strip())


@lru_cache(maxsize=1)
def declared_lenses() -> tuple[str, ...]:
    """The declared lens set, refused unless the emitter would emit a round from it.

    Cached: the file is static for the life of a run. Coverage is read off this set, so it has to
    be the set the round was dispatched from — a registry the emitter refuses could not have
    produced the round in hand, and a name declared twice would demand the same lens twice here.

    Every key an entry owes is held to the same test, though only the name is read here: the
    question this answers is whether a round could have come from this registry at all, and an
    entry without a usable mandate, tier or transport is one the emitter refuses to emit from —
    leaving a lens that no round could dispatch counted here as an attacker that ran.
    """
    with LENSES_PATH.open(encoding="utf-8") as handle:
        lenses = json.load(handle)["lenses"]
    names = [entry["lens"] for entry in lenses if usable(entry.get("lens"))]
    labels = [entry["lens"] if usable(entry.get("lens")) else f"the entry at position {position}"
              for position, entry in enumerate(lenses)]
    unusable = [f"{labels[position]} without a usable {key}"
                for position, entry in enumerate(lenses)
                for key in REQUIRED_KEYS if not usable(entry.get(key))]
    if not lenses:
        problem = "declares no lens"
    elif unusable:
        problem = f"declares {', '.join(unusable)}"
    elif len({fold(name) for name in names}) != len(names):
        problem = "names one lens twice, matching names the way the filesystem does"
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


def one_value_per_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Refuse an object writing one key twice, which JSON otherwise resolves to the last one.

    The record a reader reviews and the record the round is decided from are two documents then:
    a record carrying `"dispositions"` twice is adjudicated on the second alone while the first is
    what stands in the text above it, and nothing reports the difference. The schema cannot see it
    either — the repeat is gone before validation, so the forbidding of unknown properties has
    nothing left to refuse.
    """
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"the key {key!r} is written twice in one object")
        seen.add(key)
    return dict(pairs)


def read_record(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError("unreadable", f"cannot read the record {path}: {exc}") from exc
    try:
        return json.loads(text, object_pairs_hook=one_value_per_key)
    except ValueError as exc:  # malformed JSON, or one key written twice in an object
        raise RecordError("invalid-json", f"{path} is not valid JSON: {exc}") from exc


def require_record_binds_its_document(path: Path, record: dict) -> None:
    """Refuse a record that does not name, and is not named for, one document beside it.

    The record is committed beside the document it attacked and named for it without the
    document's extension, and that pair of names is the whole of what binds the two. A `spec_path`
    leading out of the record's own directory names a document this record was not committed
    beside and no attacker in the round read. A record standing under another document's name is
    the same loss from the other end: the document is found beside the record, so a copy of one
    round's record under a second document's name reads as a closed round over a document no
    attacker ever saw, and clears work to start against it.

    Both are decided on the record's own basename, since a copy is what changes it, and on
    `spec_path` whatever document the run is told to read: naming a document to check against moves
    where the round is read from, never which document this record is a round over.

    The pair is matched the way the filesystem matched it when the two were committed, as every
    other name in this round is: on the volumes this runs on a record and a document held apart by
    case or Unicode form alone are one pair, and a round that genuinely closed would be refused
    over a difference the message cannot show the reader. On a volume that does hold them apart
    this admits a pair it need not, which is the cheaper error — the two names still have to
    correspond, so a record copied under another document's name is refused as before.
    """
    name = record["spec_path"]
    if name != Path(name).name or name in ("", ".", ".."):
        raise RecordError(
            "spec-not-a-bare-filename",
            f"the record names its document {name!r}, which is not a bare filename; the record is "
            "committed beside the document it attacked, so name that document's basename — a "
            "path leading out of the record's own directory names a document no attacker in this "
            "round read",
        )
    expected = Path(name).stem + RECORD_SUFFIX
    if fold(path.name) != fold(expected):
        raise RecordError(
            "record-name-mismatch",
            f"this record is named {path.name!r} while the round in it is over {name!r}, whose "
            f"record is named {expected!r}; a record standing under another document's name closes "
            "a round over a document no attacker in that round read — rename it, or name in "
            "it the document it actually attacked",
        )


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
    attacked document, and reading it would check the round against unrelated text. --spec is read
    for presence, not content — a wrapper passing an unset variable is refused rather than falling
    back to the document the record names.
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
        path = record_path.parent / record["spec_path"]
    try:
        return path, path.read_bytes()
    except OSError as exc:
        raise RecordError(
            "spec-unreadable",
            f"cannot read the attacked document {path}: {exc}; the record names it relative to "
            "its own directory, and --spec overrides that when the document has moved",
        ) from exc


def require_attackable_document(path: Path, document: bytes) -> None:
    """Refuse a document the emitter would not have emitted a round over.

    Every refusal here is one of the emitter's, and the emitter's is where a document like this one
    is kept out of a round: it is what never dispatches an attacker. This mirrors that refusal
    where the document on disk is the revision the round attacked — a round that accepted nothing
    — and there it says no attacker read this text, so a record closing a round over it was written
    by hand and closing it clears work to start against criteria nobody attacked. A round claiming
    an acceptance edited the document afterwards by construction, so what is read here is the
    post-edit content rather than what any attacker saw; the revision attacked is a hash, and the
    content it names cannot be recovered from it to be held to the same test.

    Bytes that do not decode are refused rather than repaired, because the emitter hands an
    attacker the document as text and a document that has none is not what any attacker read.
    Emptiness is decided over that text for the same reason: a document of nothing but a
    non-breaking space is whitespace to the emitter, and a comparison of bytes would pass it. A
    byte-order mark comes out before that test, since `strip` leaves it standing and a document of
    nothing else states nothing. A document carrying an untrusted-content marker of its own cannot
    be fenced without being altered, so the emitter refuses it rather than attack text the recorded
    revision does not name.
    """
    try:
        text = document.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordError(
            "no-spec",
            f"the attacked document {path} is not text: {exc}; the emitter reads the document it "
            "fences as text and refuses one it cannot, so no attacker in any round read these "
            "bytes — write the document as UTF-8 and attack it",
        ) from exc
    if not text.replace(BOM, "").strip():
        raise RecordError(
            "no-spec",
            f"the attacked document {path} is empty; the emitter refuses to emit a round over a "
            "document like this one, so no round in hand read it, and an empty round proves "
            "nothing — attack the document once it states the criteria it is meant to state",
        )
    if FENCE_OPEN in text or FENCE_CLOSE in text:
        raise RecordError(
            "spec-contains-marker",
            f"the attacked document {path} carries an untrusted-content marker of its own; the "
            "emitter refuses it rather than rewrite what it hashed, so no round in hand attacked "
            "this text — take the marker out of the document and attack the revision that leaves",
        )


def revisions_of(data: bytes) -> dict[str, str]:
    """This content's revision written in each notation; both name these exact bytes.

    The object id is the one a git blob of these bytes wears, taken over the bytes as they stand
    and through no clean filter a repository configures: a revision names the document an attacker
    read, and what an attacker read is what is on disk. So the object id a record is written from
    has to be taken the same way, which is what the staleness message says where it is reached.
    """
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

    Only the revisions the adjudication reads are checked: one left behind on a disposition flipped
    to rejected, one on a disposition naming a proposal the round does not hold, and one on a
    second disposition for a proposal already adjudicated are all read by nothing. Refusing the
    whole record over how any of them is written would send the reader to debug a field that
    decides no part of the round — and it refuses fatally, hiding the error that names the
    disposition itself.
    """
    held = {proposal["id"] for proposal in record["proposals"]}
    adjudicating: dict[str, dict[str, Any]] = {}
    for entry in record["dispositions"]:
        if entry["id"] in held:
            adjudicating.setdefault(entry["id"], entry)
    revisions = [record["spec_revision"]] + [
        entry["revision"] for entry in adjudicating.values()
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
    """Hold the lenses the record reports against the ones the registry declares.

    Coverage is containment: every declared lens owes a report, and a report beyond them is a lens
    since retired or renamed — coverage this round obtained and the registry no longer asks for,
    which is surplus rather than a defect. Refusing it would leave every committed record naming a
    retired lens permanently unclosable over an attack that did run. A name misspelled is caught
    all the same, since the lens it was meant to be then has no report of its own.

    Names are matched the way the filesystem matched them when the prompts landed: a name differing
    only in case or in Unicode form was one prompt file and so one attacker, and holding the two
    apart here would report a lens missing over a difference the message cannot show the reader.
    """
    counted: dict[str, int] = {}
    spelling: dict[str, str] = {}
    for entry in record["lenses"]:
        key = fold(entry["lens"])
        counted[key] = counted.get(key, 0) + 1
        spelling.setdefault(key, entry["lens"])
    errors = [
        {"code": "duplicate-lens",
         "message": f"the {spelling[key]} lens reports {count} times; coverage is read off one "
                    "entry per lens"}
        for key, count in counted.items() if count > 1
    ]
    errors += [
        {"code": "lens-missing",
         "message": f"the {name} lens has no report; a lens that errored or returned unreadable "
                    "output leaves the round unfinished, and an empty proposal list never stands "
                    "in for a report"}
        for name in declared_lenses() if fold(name) not in counted
    ]
    return errors


def _report_errors(record: dict) -> list[dict[str, Any]]:
    """Hold each lens's report against the proposals attributed to it.

    A report and the proposal list are two accounts of the same round, and a record where they
    disagree describes no round at all: it either credits a lens with work it did not report or
    loses the work it did. Attribution is matched as coverage is, the way the filesystem matched
    the prompt names, so a lens and the proposals it produced are held together by whichever of the
    two spellings each was written in.

    Three ways they disagree, and none of the three implies another: a proposal attributed to a
    lens the record files no report for traces to no attacker at all; a lens reporting proposals
    with none attributed to it has lost the ones it made; a lens reporting empty with proposals
    attributed to it never made them. The first is what catches a misspelled attribution on a lens
    that produced more than one proposal — the lens keeps the others, so nothing about its report
    contradicts anything, and the misattributed proposal would otherwise close the round traceable
    to nothing.

    Attribution is read against the lenses this record reports, never against the registry. A lens
    since retired reports in the record that ran it and no longer stands in the registry, so
    reading attribution off the registry would refuse every record holding that attacker's
    findings — which is the loss coverage is containment to avoid.
    """
    reported = {fold(entry["lens"]) for entry in record["lenses"]}
    attributed = {fold(proposal["lens"]) for proposal in record["proposals"]}
    errors: list[dict[str, Any]] = [
        {"code": "unreported-proposal-lens", "id": proposal["id"],
         "message": f"proposal {proposal['id']!r} is attributed to {proposal['lens']!r}, which "
                    "files no report in this round; a lens that produced a proposal reported, so "
                    "this one traces to no attacker the record names — correct the attribution, "
                    "or record the report the lens that made it owes"}
        for proposal in record["proposals"]
        if fold(proposal["lens"]) not in reported
    ]
    for entry in record["lenses"]:
        name, report = entry["lens"], entry["report"]
        if report == "empty" and fold(name) in attributed:
            errors.append({
                "code": "contradicted-empty-report",
                "message": f"the {name} lens reports empty, yet proposals in this round are "
                           "attributed to it; a report and the proposal list are one account",
            })
        elif report == "proposals" and fold(name) not in attributed:
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


def check(record: dict, revisions: dict[str, str]) -> list[dict[str, Any]]:
    """Everything wrong with this round, as a pure function of the record and the document.

    The document arrives as the revisions its bytes hash to, since a revision is the whole of what
    the round is decided against and the run has them in hand already.
    """
    present = set(revisions.values())
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
                       "document as it now stands and re-adjudicate against that. The revision "
                       "names the document's bytes as they stand on disk: `git hash-object "
                       "--no-filters` prints the object id this check computes, where the same "
                       "command without that option runs whatever clean filter the repository "
                       "configures and prints a different id for a document nothing is wrong with",
        })
    return errors


def report(errors: list[dict[str, Any]], started: bool, code: int, clean: bool = False,
           read: dict[str, str] | None = None) -> int:
    """Print the result; `read` names the document the verdict was decided against.

    A round checked against a copy handed to --spec answers a different question from one checked
    against the live document, and that substitution is invisible unless the answer says which
    file it read. A run that opened none omits both keys rather than naming a document it never
    read.

    One finding is printed once. A record repeating a lens entry contradicts its proposal list
    once per copy, and byte-identical errors distinguish nothing for a reader while inviting them
    to count two defects where the record holds one.
    """
    if errors and started:
        errors = [*errors, {"code": "ordering-violation", "message": ORDERING_MESSAGE}]
    distinct = {tuple(sorted(error.items())): error for error in errors}
    result = {
        "clean": clean,
        "complete": code == EXIT_COMPLETE,
        "errors": sorted(distinct.values(),
                         key=lambda err: (err["code"], err.get("id", ""), err["message"])),
        **(read or {}),
    }
    print(json.dumps(result, sort_keys=True))
    return code


def declared(argv: list[str]) -> bool:
    """Whether this command line claims the implementation has started.

    Read off the argument list, which every run has, rather than off the parse, which a malformed
    command line does not survive: work claimed against a round the check could not even read is
    still work claimed, and the same reading then decides both paths.

    Matched by option name, not by the whole argument: `--implementation-started=true` is what an
    agent writes for a flag it thinks takes a value, argparse rejects it outright because the flag
    takes none, and reading the argument whole would drop the declaration along with the parse —
    reporting the malformed command line while the work claimed against the round goes unanswered.

    The value written there is read, though, since `--implementation-started=false` declares that
    the work has not started, and answering it with an ordering violation would tell the operator
    the opposite of what they wrote. A denial written after a space is the same denial in the
    spelling every valued option also takes, and is read the same way; anything else following the
    flag is left alone, the record's own path above all, so a command line naming the record after
    the flag still declares. A value that is not a recognisable denial reads as a declaration,
    which is the direction that fails closed.
    """
    for position, arg in enumerate(argv):
        name, valued, value = arg.partition("=")
        if name != DECLARATION:
            continue
        if not valued:
            value = argv[position + 1] if position + 1 < len(argv) else ""
        if value.strip().lower() not in NEGATIONS:
            return True
    return False


def build_parser() -> argparse.ArgumentParser:
    # No abbreviating an option name: argparse otherwise takes any unambiguous prefix of one, while
    # the declaration is read by its full name — so a short spelling would parse as a claim that
    # the reading above cannot see, and the answer would report a round with the claim dropped.
    # Refusing the short spelling outright leaves the parse and that reading one vocabulary.
    parser = argparse.ArgumentParser(add_help=True, allow_abbrev=False)
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
    # The denial is read wherever the declaration is, not only where the parse rejected it: the
    # record is optional, so `--implementation-started false` parses — argparse binds the denial
    # to the record and leaves the flag standing — and reading the flag alone would answer an
    # operator who denied the claim with the very violation they denied. Argparse is the authority on
    # what the arguments are, since normalising the denial away before the parse would hand the run
    # a command line nobody wrote; what is decided here is only what the answer says about them.
    started = args.implementation_started and declared(argv)
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
        require_record_binds_its_document(record_path, record)
        require_comparable_revisions(record)
        path, document = read_document(record_path, record, args.spec)
        revisions = revisions_of(document)
        # The revision goes out in the record's own notation: the reader holds it against
        # spec_revision as a string, and the other notation for it would read as another document.
        read = {"document": str(path), "revision": revisions[notation_of(record["spec_revision"])]}
        require_attackable_document(path, document)  # after `read`, so the refusal names the file
        errors = check(record, revisions)
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
