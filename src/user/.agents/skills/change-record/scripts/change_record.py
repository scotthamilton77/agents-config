#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Check a change record, the JSON document a pull request's description is written from.

Usage: uv run change_record.py lint <record.json>

``lint`` checks a record against the record schema, then against the writing
rules a program can decide, and prints a JSON result to stdout. Exit 0 valid,
1 invalid, 2 unreadable, unparseable or called wrongly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

REFERENCES = Path(__file__).resolve().parent.parent / "references"
SCHEMA_PATH = REFERENCES / "record.schema.json"
PHRASES_PATH = REFERENCES / "lint-phrases.json"

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_UNUSABLE = 2

# The entry a list holds to say that it has nothing in it.
NONE = "None."

# The commit types whose pull request body carries a criteria table.
CRITERIA_TABLE_TYPES = frozenset({"feat", "fix", "refactor", "perf", "test"})

# The five shapes of id that a stranger cannot read without a gloss. A tracker
# id is read only with its dotted suffix, because without one it looks like any
# hyphenated word. The part before the first dot must hold a letter and a
# digit, which keeps a decimal out, and must not be a version such as v1.2.
ID = re.compile(
    r"""(?<![\w.\#&-])
    (?:
        (?:[a-z][a-z0-9]*-)*(?!v\d+\.)(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]+(?:\.\d+)+  # a tracker id
      | [A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[A-Z]+\d+                 # a hyphenated id, the shape of many criterion ids
      | [A-Z]{1,3}\d+                                           # a short id, the shape of many decision ids
      | \#\d+                                                   # a pull request number
      | (?:[Ss]ections?\s+|§\s*)(?P<section>\d+(?:\.\d+)*)      # a section of a spec
    )
    (?![\w-]|\.\d)""",
    re.VERBOSE,
)

# A line end as Markdown reads one. Any other separator, such as U+2028, is a
# character within a line.
LINE_END = re.compile(r"\r\n|\r|\n")

# A code span opens with a run of backticks and closes with a run of the same
# length on the same line. A span that wraps across a line end is not read as
# one. A fold or a fence that starts a line inside such a span is a real one,
# because Markdown reads the start of a line before it reads the span. A
# backtick after a backslash is an escaped character and opens nothing.
CODE_SPAN = re.compile(r"(?<![`\\])(`+)(?!`)[^\r\n]+?(?<!`)\1(?!`)")

SENTENCE_END = re.compile(r"""[.!?]+["')\]]*(?:\s+|$)""")

# Neither of these ends a sentence, and their full stops would otherwise be read as ends.
MID_SENTENCE = re.compile(r"\b(?:e\.g|i\.e)\.", re.IGNORECASE)

# The two fields that close with the work item's id in brackets.
CLOSED_BY_AN_ID = frozenset({"/pr/title", "/commit/subject"})

# Constructs that belong in an artifact a machine reads, by the name a finding
# gives them. A fenced block is read apart from these, a line at a time.
MACHINE_CONTENT = {
    "a `<details>` fold": re.compile(r"<details[\s>]", re.IGNORECASE),
    "an HTML comment": re.compile(r"<!--"),
}

# A whole line that opens a fenced block whose language is JSON. The fence may
# sit at any depth of a quote or a list. A run of backticks with another
# backtick later on the line is a code span that starts the line, so it opens
# nothing.
JSON_FENCE = re.compile(
    r"(?:[ \t]*(?:>|[-*+][ \t]|\d{1,9}[.)][ \t]))*[ \t]*(?:`{3,}[ \t]*json\b[^`]*|~{3,}[ \t]*json\b.*)",
    re.IGNORECASE,
)


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


def load_phrases() -> dict[str, list[str]]:
    """Read the phrase lists that ship beside this script, which an author reads too."""
    with PHRASES_PATH.open(encoding="utf-8") as handle:
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


def is_none(entry: Any) -> bool:
    """Say whether a list entry is the one that states its list is empty.

    Space around the entry is ignored, because a reader sees the same entry
    with or without it.
    """
    return isinstance(entry, str) and entry.strip() == NONE


def _discovered_work(record: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield the index and the row of each piece of discovered work.

    A row is an object, and the entry that states the list is empty is a
    string. The schema promises nothing more about the string than its
    pattern, so the two are told apart by type and never by the string's text.
    """
    for index, row in enumerate(record["discovered"]["rows"]):
        if isinstance(row, dict):
            yield index, row


def outside_code(text: str) -> str:
    """Return ``text`` with each code span replaced by a placeholder.

    A code span quotes a literal, so nothing in it is the author's own wording.
    The placeholder holds a word, so a sentence that is only a code span still
    counts as one, and it holds angle brackets, so it completes no phrase.
    """
    return CODE_SPAN.sub("<code>", text)


def holds_json_fence(text: str) -> bool:
    """Say whether any line of ``text`` opens a fenced block whose language is JSON.

    Each line is judged alone. Keeping track of which block is open would let
    a line that only looks like a fence hide a real block below it.
    """
    return any(JSON_FENCE.fullmatch(line) for line in LINE_END.split(text))


def count_sentences(text: str) -> int:
    """Count the sentences in ``text``.

    A sentence ends at a full stop, a question mark or an exclamation mark that
    is followed by a space or by the end of the text. A full stop inside a
    number, a file name or a code span therefore ends nothing. An abbreviation
    other than "e.g." and "i.e." does end a sentence when a space follows it,
    so a text that leans on abbreviations counts long.
    """
    plain = MID_SENTENCE.sub("", outside_code(text))
    return sum(1 for part in SENTENCE_END.split(plain) if re.search(r"\w", part))


def _strings(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Yield the path and value of every string under ``node``."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for name, child in node.items():
            yield from _strings(child, f"{path}/{name}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _strings(child, f"{path}/{index}")


def _body_scope(record: dict[str, Any]) -> Iterator[tuple[str | None, str]]:
    """Yield the pull request body's text in the order a reader meets it, as (path, text) pairs.

    A pair with no path is a cell that sets an id beside its own gloss, such as
    a line of the tracker tree or the id column of a table. It introduces the
    id for the text below it and is never itself at fault. A filed row of
    discovered work is the tracker's text, so only its id is read. A gate's
    command and a diagram's source are not read, because neither can take a
    gloss and stay what it is.
    """
    fits = record.get("where_this_fits", {})
    yield "/pr/title", record["pr"]["title"]
    yield "/summary", record["summary"]
    for index, entry in enumerate(record["heads_up"]):
        yield f"/heads_up/{index}", entry
    for item in fits.get("ancestry", []):
        yield None, item["id"]
    yield "/work_item/slice", record["work_item"]["slice"]
    for reference in fits.get("builds_on", []) + fits.get("concurrent", []):
        yield None, f"#{reference['pr']}"
    for part in fits.get("scope", []):
        yield None, part["slice"]
        if "pr" in part:
            yield None, f"#{part['pr']}"
    for index, row in enumerate(record["risk"]["rows"]):
        for cell in ("failure", "exposed", "evidence", "recovery"):
            yield f"/risk/rows/{index}/{cell}", row[cell]
    for index, change in enumerate(record["changes"]):
        yield f"/changes/{index}/topic", change["topic"]
        yield f"/changes/{index}/text", change["text"]
    if "design_notes" in record:
        yield "/design_notes", record["design_notes"]
    for index, row in _discovered_work(record):
        yield None, row.get("item", "")
        if "pr" in row:
            yield None, f"#{row['pr']}"
        if row["status"] != "filed":
            yield f"/discovered/rows/{index}/what", row["what"]
            yield f"/discovered/rows/{index}/reason", row["reason"]
    for index, gate in enumerate(record["verification"]["gates"]):
        yield f"/verification/gates/{index}/location", gate["location"]
    for index, entry in enumerate(record["verification"]["not_run"]):
        yield f"/verification/not_run/{index}", entry
    criteria = record.get("criteria", [])
    if isinstance(criteria, str):
        yield "/criteria", criteria
    else:
        for index, row in enumerate(criteria):
            yield None, row["id"]
            yield f"/criteria/{index}/promise", row["promise"]
            yield f"/criteria/{index}/evidence", row["evidence"]


def _commit_scope(record: dict[str, Any]) -> Iterator[tuple[str | None, str]]:
    """Yield the commit message's text in the order a reader meets it, as (path, text) pairs.

    The message's first body line sets the work item's id beside its gloss, so
    that id is introduced for the sections below the line.
    """
    commit = record["commit"]
    yield "/commit/subject", commit["subject"]
    yield None, record["work_item"]["id"]
    yield "/work_item/gloss", record["work_item"]["gloss"]
    for name in ("why", "change", "verification", "trivial"):
        if name in commit:
            yield f"/commit/{name}", commit[name]


def _gloss_scopes(record: dict[str, Any]) -> Iterator[Iterable[tuple[str | None, str]]]:
    """Yield each stretch of text that is read on its own.

    The body is one. The commit message is another, because it is read alone
    in the log. Each reply is another, because it is read alone on its thread.
    """
    yield _body_scope(record)
    yield _commit_scope(record)
    for index, reply in enumerate(record.get("replies", [])):
        yield [
            (f"/replies/{index}/change", reply["change"]),
            (f"/replies/{index}/verification", reply["verification"]),
        ]


def _author_text(record: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield the path and text of every text field the author wrote.

    These are the fields the gloss scopes read, without the cells that only
    introduce an id. Generated parts and the text of a filed row of discovered
    work are left out there, so they are left out here.
    """
    for scope in _gloss_scopes(record):
        for path, text in scope:
            if path is not None:
                yield path, text


def _glossed(text: str, match: re.Match[str]) -> bool:
    """Say whether the id at ``match`` carries a gloss.

    A gloss is a parenthetical. One opens straight after the id and holds at
    least one word that is not itself an id, or the id sits inside one and the
    words around it say what it is. Backticks or emphasis around the id do not
    come between it and its gloss.
    """
    depth = 0
    for char in text[: match.start()]:
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
    following = re.match(r"[`*_]*\s*\(([^()]*)", text[match.end():])
    return depth > 0 or bool(following and re.search(r"[^\W\d_]", ID.sub("", following.group(1))))


def _closes_the_text(text: str, match: re.Match[str]) -> bool:
    """Say whether the id at ``match`` stands alone in the brackets that close ``text``."""
    return text[: match.start()].rstrip().endswith("[") and text[match.end():].strip() == "]"


def _bare_ids(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each id whose first use, in a stretch of text read on its own, has no gloss.

    A title and a commit subject close with the work item's id in brackets.
    That id is part of the form and takes no gloss, so it is passed over when
    it stands alone there. An id among other words in those brackets is read.
    """
    for scope in _gloss_scopes(record):
        seen: set[str] = set()
        for path, text in scope:
            for match in ID.finditer(text):
                if path in CLOSED_BY_AN_ID and _closes_the_text(text, match):
                    continue
                name = " ".join(match.group().split())
                key = f"section {match['section']}" if match["section"] else name
                if key in seen:
                    continue
                seen.add(key)
                if path is not None and not _glossed(text, match):
                    message = f"{name} is first named here and has no gloss; follow it with what it is, in parentheses"
                    yield _finding("bare-id", path, message)


def _unstated_emptiness(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each part of the record that is empty and does not say so."""
    verification = record["verification"]
    needs_table = record["pr"]["type"] in CRITERIA_TABLE_TYPES
    stated = f'write the single entry "{NONE}" when there is nothing to say'
    checks = [
        ("/heads_up", not record["heads_up"], f"this list is empty; {stated}"),
        ("/discovered/rows", not record["discovered"]["rows"], f"this list is empty; {stated}"),
        ("/risk/rows", not record["risk"]["rows"], "the risk table has no row"),
        ("/criteria", needs_table and record.get("criteria") == [], "the criteria table has no row"),
        (
            "/verification",
            not verification["gates"] and not verification["not_run"],
            "this group lists no gate and nothing that was not run",
        ),
    ]
    for path, empty, message in checks:
        if empty:
            yield _finding("unstated-empty", path, message)


def _none_beside_entries(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each list that says it is empty and holds another entry as well."""
    lists = {
        "/heads_up": record["heads_up"],
        "/discovered/rows": record["discovered"]["rows"],
        "/verification/not_run": record["verification"]["not_run"],
    }
    for path, entries in lists.items():
        if any(is_none(entry) for entry in entries) and len(entries) > 1:
            message = f'"{NONE}" says this list is empty, so no other entry sits beside it'
            yield _finding("none-beside-entry", path, message)


def _discovered_rows(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each row of discovered work that leaves out what its status calls for."""
    for index, row in _discovered_work(record):
        path = f"/discovered/rows/{index}"
        if row["status"] == "filed" and not row.get("item", "").strip():
            yield _finding("discovered-row", f"{path}/item", "a filed row names its tracker item")
        if row["status"] == "in flight" and "pr" not in row:
            yield _finding("discovered-row", f"{path}/pr", "an in-flight row names the pull request it belongs to")
        if not row["reason"].strip():
            yield _finding("discovered-row", f"{path}/reason", "a row says why the work is not in this pull request")


def _summary_length(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report a summary that is shorter or longer than its template allows."""
    count = count_sentences(record["summary"])
    if not 3 <= count <= 5:
        yield _finding("summary-length", "/summary", f"the summary has {count} sentences, and it takes three to five")


def _commentary(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each listed phrase of commentary about the document, in any text the author wrote."""
    patterns = {
        phrase: re.compile(r"(?<!\w)" + r"\s+".join(map(re.escape, phrase.split())) + r"(?!\w)", re.IGNORECASE)
        for phrase in load_phrases()["document_commentary"]
    }
    for path, text in _author_text(record):
        plain = outside_code(text)
        for phrase, pattern in patterns.items():
            if pattern.search(plain):
                yield _finding("commentary", path, f'"{phrase}" talks about the document; say the thing itself')


def _machine_content(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each construct, anywhere in the record, that belongs in an artifact a machine reads."""
    for path, text in _strings(record):
        plain = outside_code(text)
        found = [name for name, pattern in MACHINE_CONTENT.items() if pattern.search(plain)]
        if holds_json_fence(text):
            found.append("a fenced `json` block")
        for name in found:
            message = f"this field holds {name}, which belongs in an artifact a machine reads"
            yield _finding("machine-content", path, message)


# The rules beyond the schema. Each takes a record whose structure is valid and yields its findings.
RULES = (
    _bare_ids,
    _unstated_emptiness,
    _none_beside_entries,
    _discovered_rows,
    _summary_length,
    _commentary,
    _machine_content,
)


def lint_record(record: Any) -> list[dict[str, str]]:
    """Return every finding against an already-parsed record, in path order.

    The rules beyond the schema read fields by name, so they run only on a
    record whose structure the schema accepts.
    """
    findings = [_finding("schema", path, message) for path, message in sorted(_schema_faults(record))]
    if not findings:
        findings = [finding for rule in RULES for finding in rule(record)]
        findings.sort(key=lambda finding: (finding["path"], finding["code"], finding["message"]))
    return findings


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
        help="check a record against the record schema and the writing rules",
        description="Check a record against the record schema, then against the writing rules a program "
        "can decide. Prints a JSON result to stdout. Exit 0 valid, 1 invalid, 2 unreadable or unparseable.",
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
