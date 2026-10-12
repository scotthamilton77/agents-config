#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Start, fill and check a change record, and render a pull request's three artifacts from it.

A change record is the JSON document a pull request's description, commit
message and review replies are written from.

Usage: uv run change_record.py init --type TYPE --component NAME --work-item ID <record.json>
       uv run change_record.py lint [--pr NUMBER] <record.json>
       uv run change_record.py context <record.json>
       uv run change_record.py discovered <record.json>
       uv run change_record.py campaign [--pr NUMBER] [--app LOGIN] <record.json>
       uv run change_record.py render body <record.json> [--existing-body FILE] [--comment-url URL]
       uv run change_record.py render commit <record.json>
       uv run change_record.py render reply <record.json> --finding ID
       uv run change_record.py publish [--dry-run] <record.json>

``init`` writes a new record with every field the author fills left empty.
It never replaces a file. Exit 0 written, 1 a file is already there, 2 the
file cannot be written or the call is wrong.

``lint`` checks a record against the record schema, then against the writing
rules a program can decide, and prints a JSON result to stdout. With ``--pr``
it also reads that pull request's changed paths through ``gh`` and checks the
record against them. Exit 0 valid, 1 invalid, 2 unreadable, unparseable,
called wrongly, or ``gh`` failed.

``context`` and ``discovered`` fill the parts of a record that are copied
from the tracker and from GitHub, which they read through ``work`` and ``gh``
in the working directory's repository. Each takes the work item and the pull
request from the record, and writes the file once, after every call has
succeeded. Exit 0 the record holds the part, 2 anything failed.

``campaign`` fills the record's review campaign the same way, from the review
verdicts posted on its pull request, which it reads through ``gh``. It checks
each verdict with the ``review-verdict`` skill's validator and names each
review it skips on stderr.

``render`` fills one of the three template files from a record and writes the
result to stdout, or to the file ``--output`` names. It lints first. A record
it refuses gets the JSON result on stderr and nothing written. ``render body``
warns on stderr when the body shows more words above its horizontal rule than
a one-pager takes, and writes the body all the same. Exit 0 rendered, 1
refused, 2 unreadable, unparseable or called wrongly.

``publish`` posts a record on its pull request, which it reads and writes
through ``gh``. It lints first. It then posts the record as a new comment and
sets the pull request body to the render that points at that comment. It never
edits a comment. With ``--dry-run`` it prints the comment and the body to
stdout and writes nothing. A record it refuses gets the JSON result on stderr.
Exit 0 published, 1 refused, 2 unreadable or unparseable, or a call failed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import itertools
import json
import re
import secrets
import string
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
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

# The commit types whose pull request body carries a risk table of one row.
ONE_RISK_ROW_TYPES = frozenset({"docs", "chore", "build", "ci", "style", "revert"})

# What opens a commit subject: the type, the component in parentheses, and the
# colon and space that set them off from the wording. Each part may be missing,
# so the pattern matches any subject and a rule can say which part is.
SUBJECT_OPENING = re.compile(r"(?P<type>[^\s(:]*)(?:\((?P<component>[^)]*)\))?(?P<separator>: )?")

# The most characters a commit subject takes.
SUBJECT_LIMIT = 100

# The sections of a commit body, each with the fewest and the most sentences it takes.
# The verification takes any number, because one decisive check can be one sentence.
BODY_SECTIONS = {"why": (2, 3), "change": (3, 4), "verification": (1, None)}
BODY_WORDS = (80, 150)

# The fewest and the most words that the two prose lines of a reply hold between them.
REPLY_WORDS = (40, 90)

# The fields a new record leaves empty that no rule about their content reads.
# Each is a string, except the list of changes.
AUTHOR_FILLS = (
    "/pr/title",
    "/pr/head_sha",
    "/work_item/gloss",
    "/work_item/slice",
    "/changes",
    "/commit/attribution/tool",
    "/commit/attribution/co_author",
    "/commit/attribution/session_key",
    "/commit/attribution/session_url",
)

# The fields an artifact sets on one line, where a line break would change what
# the artifact is. A break in the work item's id or gloss, or in an attribution
# value, moves the lines git reads the commit message's trailers from. The
# commit subject is one line too, and the rule on its form says so, which is
# why it is left out here and one fault draws one finding.
ONE_LINE_FIELDS = (
    "/pr/title",
    "/work_item/id",
    "/work_item/gloss",
    "/work_item/slice",
    "/commit/attribution/tool",
    "/commit/attribution/co_author",
    "/commit/attribution/session_key",
    "/commit/attribution/session_url",
)

# The characters git reads a trailer's key from. A last paragraph with a line
# git cannot read as a trailer loses every trailer it holds.
TRAILER_KEY = re.compile(r"[A-Za-z0-9-]+")

# The form of a link to a comment: a host, then a path that names something on
# it. A query or a fragment may follow. No host is named here, because a
# comment lives wherever the repository is hosted.
URL = re.compile(r"https?://[^\s/?#]+/[^\s?#]+(?:[?#]\S*)?")

# The five shapes of id that a stranger cannot read without a gloss. A tracker
# id is read only with its dotted suffix, because without one it looks like any
# hyphenated word. The part before the first dot must hold a letter and a
# digit, which keeps a decimal out, and must not be a version such as v1.2.
ID = re.compile(
    r"""(?<![\w.\#&-])
    (?:
        (?P<tracker>(?:[a-z][a-z0-9]*-)*(?!v\d+\.)(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]+(?:\.\d+)+)  # a tracker id
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

# A whole line that opens a fenced block, and what the line says after the
# fence, which starts with the block's language. The fence may sit at any depth
# of a quote or a list. A run of backticks with another backtick later on the
# line is a code span that starts the line, so it opens nothing.
FENCE = re.compile(
    r"(?:[ \t]*(?:>|[-*+][ \t]|\d{1,9}[.)][ \t]))*[ \t]*(?:`{3,}(?=[^`]*\Z)|~{3,})(?P<after>.*)"
)

# What follows the fence on a line that opens a block whose language is JSON.
JSON_LANGUAGE = re.compile(r"[ \t]*json\b", re.IGNORECASE)


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
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecordError("invalid-json", f"{path} is not valid JSON: {exc}") from exc
    # JSON can escape half of a surrogate pair, which is a text no file and no
    # digest can take. Refusing it here keeps it from every rule and every writer.
    where = next(_not_utf8(record), None)
    if where is not None:
        message = f"{path} holds text that UTF-8 cannot hold, at {where or 'its root'}; half of a surrogate pair is such text"
        raise RecordError("not-utf-8", message)
    return record


def _not_utf8(node: Any, path: str = "") -> Iterator[str]:
    """Yield the path of each text under ``node`` that UTF-8 cannot hold, be it a value or a field's name."""
    if isinstance(node, str):
        try:
            node.encode("utf-8")
        except UnicodeEncodeError:
            yield path
    elif isinstance(node, dict):
        for name, child in node.items():
            yield from _not_utf8(name, f"{path}/{name}")
            yield from _not_utf8(child, f"{path}/{name}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _not_utf8(child, f"{path}/{index}")


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


def fence_openings(text: str) -> Iterator[str]:
    """Yield, for each line of ``text`` that opens a fenced block, what the line says after the fence.

    Each line is judged alone. Keeping track of which block is open would let
    a line that only looks like a fence hide a real block below it.
    """
    for line in LINE_END.split(text):
        match = FENCE.fullmatch(line)
        if match:
            yield match["after"]


def holds_json_fence(text: str) -> bool:
    """Say whether any line of ``text`` opens a fenced block whose language is JSON."""
    return any(JSON_LANGUAGE.match(after) for after in fence_openings(text))


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


def count_words(text: str) -> int:
    """Count the words in ``text``, a word being a run of characters with no space in it.

    A number, a file name and a hyphenated compound each count as one word, as
    they do for a word counter in a shell.
    """
    return len(text.split())


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
    gloss and stay what it is. An item a spec mints sets its id beside what
    the item is, which the author words.
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
    # A short body carries no blast radius, so an item named there introduces no id.
    shown = record["pr"]["type"] not in ONE_RISK_ROW_TYPES
    for index, item in enumerate(record.get("blast_radius", {}).get("mints", []) if shown else []):
        yield None, item.get("id", "")
        yield f"/blast_radius/mints/{index}/what", item["what"]
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


def _closing_brackets(text: str) -> int | None:
    """Return where the brackets that close ``text`` open, or None when no brackets close it."""
    body = text.rstrip()
    opening = body.rfind("[")
    return opening if opening >= 0 and body.endswith("]") else None


def closing_id(text: str) -> str | None:
    """Return what stands in the brackets that close ``text``, or None when no brackets close it.

    A title and a commit subject close with the work item's short id in
    brackets. Space inside the brackets and after them is no part of what
    they hold.
    """
    opening = _closing_brackets(text)
    return None if opening is None else text.rstrip()[opening + 1 : -1].strip()


def _closes_the_text(text: str, match: re.Match[str]) -> bool:
    """Say whether the id at ``match`` stands alone in the brackets that close ``text``."""
    return closing_id(text) == match.group() and text[match.end():].strip() == "]"


def _bare_ids(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each id whose first use, in a stretch of text read on its own, has no gloss.

    A title and a commit subject close with the work item's short id in
    brackets. That id is part of the form and takes no gloss, so it is passed
    over when it stands alone there. The form puts no other id in that place,
    so any other id in those brackets is read, and so is an id among other
    words there.
    """
    own = short_id(record["work_item"]["id"])
    for scope in _gloss_scopes(record):
        seen: set[str] = set()
        for path, text in scope:
            for match in ID.finditer(text):
                if path in CLOSED_BY_AN_ID and match.group() == own and _closes_the_text(text, match):
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


def short_id(work_item_id: str) -> str:
    """Return a work item's short id, which is its full id without the project prefix.

    The prefix is everything up to and including the last hyphen, so a project
    name that holds a hyphen of its own goes with it. An id with no hyphen is
    already short.
    """
    return work_item_id.rsplit("-", 1)[-1]


def _commit_subject(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each way the commit subject departs from its form.

    The form is one line: a type, a component in parentheses, a colon and a
    space, at least one word of wording, a space, and the work item's short id
    in brackets at the end. The type and the component are the record's own,
    so the subject and the pull request cannot name different ones. Each part
    is checked on its own, so a finding names the part that is missing.
    """
    subject = record["commit"]["subject"]
    kind, component = record["pr"]["type"], record["pr"]["component"]
    short = short_id(record["work_item"]["id"])

    def broken(message: str) -> dict[str, str]:
        return _finding("commit-subject", "/commit/subject", message)

    if not subject.strip():
        yield broken(f"the subject is empty; write `{kind}({component}): what is true after this merges [{short}]`")
        return
    if len(subject) > SUBJECT_LIMIT:
        yield broken(f"the subject is {len(subject)} characters long, and it takes at most {SUBJECT_LIMIT}")
    if LINE_END.search(subject):
        yield broken("the subject holds a line break, and a subject is one line")
    opening = SUBJECT_OPENING.match(subject)
    types = load_schema()["properties"]["pr"]["properties"]["type"]["enum"]
    if opening["type"] not in types:
        yield broken(f"`{opening['type']}` is not a commit type; the types are {', '.join(types)}")
    elif opening["type"] != kind:
        yield broken(f"the subject's type is `{opening['type']}`, and the record's `pr.type` is `{kind}`")
    named = (opening["component"] or "").strip()
    tracker = ID.fullmatch(named)
    if not named:
        yield broken("the subject names no component; write one in parentheses after the type")
    elif tracker and tracker["tracker"]:
        yield broken(f"the subject's component `{named}` is a tracker id; name the thing a reader would search for")
    elif named != component:
        yield broken(f"the subject's component is `{named}`, and the record's `pr.component` is `{component}`")
    if not opening["separator"]:
        yield broken("the subject has no colon and space after its type and component")
    brackets = _closing_brackets(subject)
    wording = subject[opening.end() : brackets]
    if not re.search(r"\w", wording):
        yield broken("the subject says nothing between its component and its closing id; say what is true now")
    elif brackets is not None and not wording[-1].isspace():
        yield broken("the subject has no space before its closing brackets")
    closing = closing_id(subject)
    if closing is None:
        yield broken(f"the subject does not end with the work item's short id in brackets, `[{short}]`")
    elif closing != short:
        yield broken(f"the subject ends with `[{closing}]`, and the work item's short id is `{short}`")


def _commit_body(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report a commit body that is incomplete or out of range, and a missing body with no reason given.

    The words of a body are counted only when all three sections are there,
    because the total of an incomplete body says nothing about the finished one.
    """
    commit = record["commit"]
    present = [name for name in BODY_SECTIONS if name in commit]

    def broken(field: str, message: str) -> dict[str, str]:
        return _finding("commit-body", f"/commit{field}", message)

    if not present:
        if "trivial" not in commit:
            yield broken("", "the message has no body, and `trivial` gives no reason for leaving it out")
        elif not commit["trivial"].strip():
            yield broken("/trivial", "this reason is empty; say why the change needs no body")
        return
    if "trivial" in commit:
        yield broken("/trivial", "`trivial` stands in place of a body, and this message has a body as well")
    for name, (fewest, most) in BODY_SECTIONS.items():
        if name not in commit:
            yield broken(f"/{name}", "a body holds all three sections, and this one is missing")
            continue
        count = count_sentences(commit[name])
        if count < fewest or (most is not None and count > most):
            takes = "at least one" if most is None else f"{fewest} to {most}"
            yield broken(f"/{name}", f"this section has {count} sentences, and it takes {takes}")
    words = sum(count_words(commit[name]) for name in present)
    low, high = BODY_WORDS
    if len(present) == len(BODY_SECTIONS) and not low <= words <= high:
        yield broken("", f"the three sections total {words} words, and a body takes {low} to {high}")


def _groups_by_type(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each group the record's type or its reach calls for and the record does not hold in that form.

    A risk table with no row at all is left to the rule on stated emptiness,
    so one empty table is reported once.
    """
    kind = record["pr"]["type"]
    criteria = record.get("criteria")
    if kind in CRITERIA_TABLE_TYPES and not isinstance(criteria, list):
        yield _finding("required-group", "/criteria", f"a `{kind}` pull request carries its criteria as a table")
    if kind == "spec":
        one_line = isinstance(criteria, str) and criteria.strip() and not LINE_END.search(criteria.strip())
        if not one_line:
            message = "a `spec` pull request's criteria is one line, saying whether they were attacked and where the record is"
            yield _finding("required-group", "/criteria", message)
        elif "attacked" not in outside_code(criteria).lower():
            # The word is all a program can hold the line to. Where the record
            # is cannot be asked for, because criteria that were not attacked
            # have no record.
            message = (
                "a `spec` pull request's criteria says whether the criteria were attacked, "
                "in that word, as in \"were attacked\" or \"were not attacked\""
            )
            yield _finding("required-group", "/criteria", message)
    rows = len(record["risk"]["rows"])
    if kind in ONE_RISK_ROW_TYPES and rows > 1:
        message = f"a `{kind}` pull request takes one risk row, and this table has {rows}"
        yield _finding("required-group", "/risk/rows", message)
    if record["risk"]["reaches_outside_package"]:
        radius = record.get("blast_radius", {})
        if kind == "spec":
            # A spec changes no package. What it reaches is the tracker, through
            # the items it mints, so those stand where the diagrams would.
            if not any(item["what"].strip() for item in radius.get("mints", [])):
                message = (
                    "a `spec` pull request reaches outside its package through the items it mints, "
                    "so the record names each one and says what it is"
                )
                yield _finding("required-group", "/blast_radius/mints", message)
        else:
            for name in ("reach_graph", "task_flow"):
                if not radius.get(name, "").strip():
                    message = "the change reaches outside its package, so the record holds this diagram"
                    yield _finding("required-group", f"/blast_radius/{name}", message)


def pr_changed_paths(number: int) -> list[str]:
    """Return every path pull request ``number`` changes, read from GitHub's list of its files through ``gh``.

    The pull request is looked up in the repository of the working directory.
    A renamed file counts under its old path and its new one, because a
    change to either meets the rename. The list is read in pages, since
    GitHub refuses to give the whole diff of a large pull request in one
    answer. A ``gh`` that cannot be run, or that fails, raises a
    ``RecordError``, because a check that could not read the paths has
    decided nothing.
    """
    file = holding({"filename": NAME}, {"previous_filename": TEXT_OR_NONE})
    files = gh_pages(f"repos/{{owner}}/{{repo}}/pulls/{number}/files?per_page=100", file)
    return sorted({file[name] for file in files for name in ("filename", "previous_filename") if file.get(name)})


def _reach(record: dict[str, Any], changed: list[str]) -> Iterator[dict[str, str]]:
    """Report a record that says the change stays inside its package when ``changed`` says otherwise.

    A path's top-level component is its first segment: the directory at the
    root that the path sits under, or the file itself when it sits at the root.
    A path under a ``docs`` directory at the root counts toward no component,
    because documentation describes a component and is not one. Without that,
    a change that updates its own documentation would always span two.
    The check is coarse on purpose, because it knows no repository's layout.
    Two packages under one top-level directory count as one component, so a
    pass here does not prove the flag.
    """
    components = sorted({path.split("/", 1)[0] for path in changed if not path.startswith("docs/")})
    if not record["risk"]["reaches_outside_package"] and len(components) > 1:
        message = (
            "the flag says the change stays inside its package, and the pull request changes paths under "
            f"{len(components)} top-level components: {', '.join(components)}"
        )
        yield _finding("reach", "/risk/reaches_outside_package", message)


def stamp(content: Any) -> str:
    """Return the stamp over ``content``, as sixty-four hex characters.

    The stamp is the SHA-256 digest of these bytes: ``content`` written as
    JSON with the keys of every object sorted, with no space after a comma or
    a colon, and with each character outside ASCII written as itself, then
    encoded as UTF-8. The order of an object's keys and the layout of the file
    the content was read from therefore change nothing. Any change to a
    value, or to the order of a list, changes the stamp.

    Half of a surrogate pair is a text UTF-8 cannot hold. It is encoded as the
    three bytes its code point would take, so every content has a stamp and
    this function never raises on one. A record read from a file never holds
    such text, because reading refuses it.

    ``content`` is a generated part as ``generated_parts`` gives it: a group
    without its own stamp field, or the list of filed rows.
    """
    written = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(written.encode("utf-8", "surrogatepass")).hexdigest()


def generated_parts(record: dict[str, Any]) -> Iterator[tuple[str, str, Any]]:
    """Yield each generated part that ``record`` holds, as (group, key, content).

    The part's stamp belongs at ``record[group][key]`` and covers ``content``.
    For ``where_this_fits`` and for ``campaign`` the content is the whole
    group without its ``digest``. For ``discovered`` it is the list of filed
    rows in the order the record holds them, and the stamp is ``filed_digest``.
    A group the record does not hold is not a part. Neither are the filed
    rows when the record has none and carries no stamp for them.
    """
    for group in ("where_this_fits", "campaign"):
        if group in record:
            yield group, "digest", {name: value for name, value in record[group].items() if name != "digest"}
    discovered = record["discovered"]
    filed = [row for _, row in _discovered_work(record) if row["status"] == "filed"]
    if filed or "filed_digest" in discovered:
        yield "discovered", "filed_digest", filed


def stamp_generated(record: dict[str, Any]) -> dict[str, Any]:
    """Set the stamp of every generated part ``record`` holds, and return the record.

    This is for a record whose generated parts were all copied by hand from
    the tracker's and GitHub's output. A generator stamps only the part it
    wrote, with ``stamp``, so it never vouches for a part it did not write.
    """
    for group, key, content in generated_parts(record):
        record[group][key] = stamp(content)
    return record


def _line_breaks(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each field an artifact sets on one line that holds a line break.

    These fields are facts, or are one line by their form, so no artifact can
    set a break in one and stay what it is. Prose that an artifact sets on one
    line may hold a break, and ``render`` reads it as a space.
    """
    for path in ONE_LINE_FIELDS:
        value: Any = record
        for name in path.split("/")[1:]:
            value = value[name]
        if LINE_END.search(value):
            yield _finding("line-break", path, "this field is set on one line, and it holds a line break")


def _session_key(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report a session trailer key that git would not read as a trailer's key.

    An empty key is left to the rule on unfilled fields.
    """
    key = record["commit"]["attribution"]["session_key"]
    if key.strip() and not TRAILER_KEY.fullmatch(key):
        message = "git reads a trailer's key from letters, digits and hyphens alone, and this key holds something else"
        yield _finding("session-key", "/commit/attribution/session_key", message)


def _unfilled(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each field the author fills that is still empty.

    The schema lets these fields be empty so that a new record is valid
    before anyone has written in it. A rule about a field's content, such as
    the summary's length, reports its own field when that field is empty.
    """
    for path in AUTHOR_FILLS:
        value: Any = record
        for name in path.split("/")[1:]:
            value = value[name]
        if not (value.strip() if isinstance(value, str) else value):
            yield _finding("unfilled", path, "this field is empty, and the author fills it")


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Compile a listed phrase into a pattern that matches it whole, in any letter case.

    The word ``<number>`` in a phrase stands for any run of digits.
    """
    words = (r"\d+" if word == "<number>" else re.escape(word) for word in phrase.split())
    return re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", re.IGNORECASE)


def _identity(entry: dict[str, Any], id_key: str) -> tuple[str | None, str | None, str]:
    """Return what tells one review finding from every other: its claim id, artifact class and finding id.

    Finding ids start again with each claim and each artifact class, so the id
    alone can name two findings. ``id_key`` is the field that holds the
    finding id, which a campaign finding and a reply name differently.
    """
    return entry.get("claim_id"), entry.get("artifact_class"), entry[id_key]


def _names_item(text: str, item: str) -> bool:
    """Say whether ``text`` names the tracker item ``item`` itself, and not a longer id that opens with it."""
    return bool(re.search(r"(?<![\w.-])" + re.escape(item) + r"(?![\w-]|\.\d)", text))


def _names_some_item(text: str, work_item_id: str) -> bool:
    """Say whether ``text`` names any tracker item.

    An id with a dotted suffix has the shape of one. An id with no suffix
    looks like any hyphenated word, so it counts only when it opens with the
    project prefix of the record's own work item.
    """
    prefix = work_item_id.removesuffix(short_id(work_item_id))
    of_project = prefix and re.search(r"(?<![\w.-])" + re.escape(prefix) + r"\w", text)
    return bool(of_project) or any(match["tracker"] for match in ID.finditer(text))


def _replies(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each reply that is out of range, that lacks what its outcome calls for, or that carries campaign status.

    A reply's words are those of its Change and Verification lines. The
    labels, the outcome and the commit are not counted, because the author
    does not write them.
    """
    findings = {_identity(entry, "id"): entry for entry in record.get("campaign", {}).get("findings", [])}
    patterns = [_phrase_pattern(phrase) for phrase in load_phrases()["campaign_status"]]
    low, high = REPLY_WORDS
    for index, reply in enumerate(record.get("replies", [])):
        path = f"/replies/{index}"
        text = f"{reply['change']} {reply['verification']}"
        words = count_words(text)
        if not low <= words <= high:
            message = f"the Change and Verification lines hold {words} words between them, and a reply takes {low} to {high}"
            yield _finding("reply", path, message)
        sentences = count_sentences(reply["change"])
        if sentences == 0:
            yield _finding("reply", f"{path}/change", "the Change line is empty; say what is different now")
        elif sentences > 2:
            message = f"the Change line has {sentences} sentences, and it takes one or two"
            yield _finding("reply", f"{path}/change", message)
        if reply["outcome"] == "Deferred":
            item = findings.get(_identity(reply, "finding_id"), {}).get("work_item")
            if item and not _names_item(text, item):
                message = f"a deferral names the item that inherits the finding, and this reply does not name {item}"
                yield _finding("reply", path, message)
            elif not item and not _names_some_item(text, record["work_item"]["id"]):
                message = "a deferral names the item that inherits the finding, and this reply names no tracker item"
                yield _finding("reply", path, message)
        if reply["outcome"] == "Rejected" and not URL.fullmatch(reply.get("request_url", "")):
            message = (
                "a rejection gets a reply only when a reviewer asks; "
                "give the URL of the comment that asked for it, with its host and its path"
            )
            yield _finding("reply", f"{path}/request_url", message)
        for name in ("change", "verification"):
            plain = outside_code(reply[name])
            for found in filter(None, (pattern.search(plain) for pattern in patterns)):
                message = f'"{found.group()}" is campaign status, which the pull request body states once'
                yield _finding("reply", f"{path}/{name}", message)


def _reply_counts(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each finding the campaign marks fixed that has no reply, or more than one.

    A fixed finding changed code or prose, so it gets a reply. A finding with
    any other disposition, or with none yet, needs no reply.
    """
    replied = [_identity(reply, "finding_id") for reply in record.get("replies", [])]
    for entry in record.get("campaign", {}).get("findings", []):
        count = replied.count(_identity(entry, "id"))
        if entry.get("disposition") != "fixed" or count == 1:
            continue
        name = f"{entry['id']} (claim {entry['claim_id']}, {entry['artifact_class']})"
        if count:
            message = f"the fixed finding {name} has {count} replies, and it takes one"
        else:
            message = (
                f"the fixed finding {name} has no reply; "
                "a reply answers a finding by giving its claim id, artifact class and finding id"
            )
        yield _finding("reply-count", "/replies", message)


# The words a finding names each generated part with, by the group that holds it.
GENERATED_PARTS = {
    "where_this_fits": "`where_this_fits`",
    "campaign": "`campaign`",
    "discovered": "the filed rows of `discovered`",
}


def _stale_stamps(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each generated part whose content its stamp does not cover, or that has no stamp."""
    for group, key, content in generated_parts(record):
        found = record[group].get(key)
        name = GENERATED_PARTS[group]
        if found is None:
            message = f"there is no stamp over {name}; a generated part is stamped when it is written"
            yield _finding("stale-stamp", f"/{group}/{key}", message)
        elif found != stamp(content):
            message = f"the stamp over {name} no longer matches the content; a generated part is never edited by hand"
            yield _finding("stale-stamp", f"/{group}/{key}", message)


def _summary_length(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report a summary that is shorter or longer than its template allows."""
    count = count_sentences(record["summary"])
    if not 3 <= count <= 5:
        yield _finding("summary-length", "/summary", f"the summary has {count} sentences, and it takes three to five")


def _commentary(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each listed phrase of commentary about the document, in any text the author wrote."""
    patterns = {phrase: _phrase_pattern(phrase) for phrase in load_phrases()["document_commentary"]}
    for path, text in _author_text(record):
        plain = outside_code(text)
        for phrase, pattern in patterns.items():
            if pattern.search(plain):
                yield _finding("commentary", path, f'"{phrase}" talks about the document; say the thing itself')


def machine_constructs(text: str) -> list[str]:
    """Name each construct in ``text`` that belongs in an artifact a machine reads."""
    plain = outside_code(text)
    found = [name for name, pattern in MACHINE_CONTENT.items() if pattern.search(plain)]
    if holds_json_fence(text):
        found.append("a fenced `json` block")
    return found


def _machine_content(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each construct, anywhere in the record, that belongs in an artifact a machine reads."""
    for path, text in _strings(record):
        for name in machine_constructs(text):
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
    _commit_subject,
    _commit_body,
    _groups_by_type,
    _stale_stamps,
    _replies,
    _reply_counts,
    _unfilled,
    _line_breaks,
    _session_key,
)


def lint_record(record: Any, changed: list[str] | None = None) -> list[dict[str, str]]:
    """Return every finding against an already-parsed record, in path order.

    The rules beyond the schema read fields by name, so they run only on a
    record whose structure the schema accepts. ``changed`` is the list of
    paths the record's pull request changes. When it is given, the record's
    reach flag is checked against it.
    """
    findings = [_finding("schema", path, message) for path, message in sorted(_schema_faults(record))]
    if not findings:
        findings = [finding for rule in RULES for finding in rule(record)]
        if changed is not None:
            findings += _reach(record, changed)
        findings.sort(key=lambda finding: (finding["path"], finding["code"], finding["message"]))
    return findings


def _lint(args: argparse.Namespace) -> int:
    """Run ``lint``: print the result as JSON and return the exit status."""
    try:
        record = read_record(args.record)
        findings = lint_record(record, None if args.pr is None else pr_changed_paths(args.pr))
    except RecordError as exc:
        unreadable = [_finding(exc.code, "", exc.message)]
        print(json.dumps({"valid": False, "errors": unreadable}, sort_keys=True))
        return EXIT_UNUSABLE
    if findings:
        print(json.dumps({"valid": False, "errors": findings}, sort_keys=True))
        return EXIT_INVALID
    print(json.dumps({"valid": True}))
    return EXIT_VALID


def new_record(kind: str, component: str, work_item_id: str) -> dict[str, Any]:
    """Return a new record for a pull request of type ``kind``, with every field the author fills left empty.

    The record is valid against the schema. It holds no generated part and no
    reply, because those come later. The reach flag starts false, since a
    flag has no empty value, so the author sets it when the change reaches
    outside its package.
    """
    criteria: dict[str, Any] = {}
    if kind in CRITERIA_TABLE_TYPES:
        criteria["criteria"] = []
    elif kind == "spec":
        criteria["criteria"] = ""
    return {
        "pr": {"number": None, "title": "", "type": kind, "component": component, "head_sha": ""},
        "work_item": {"id": work_item_id, "gloss": "", "slice": ""},
        "summary": "",
        "heads_up": [],
        "risk": {"reaches_outside_package": False, "rows": []},
        "changes": [],
        "discovered": {"rows": []},
        "verification": {"gates": [], "not_run": []},
        **criteria,
        "commit": {
            "subject": "",
            "attribution": {"tool": "", "co_author": "", "session_key": "", "session_url": ""},
        },
        "record": {"schema_version": 1, "revision": 0},
    }


def _init(args: argparse.Namespace) -> int:
    """Run ``init``: write a new record, and refuse to replace a file that is already there."""
    record = new_record(args.type, args.component, args.work_item)
    try:
        # Opening for exclusive creation makes the check and the write one step,
        # so a file that appears between them is never replaced.
        with args.record.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    except FileExistsError:
        print(f"{args.record} already exists, and init never replaces a file", file=sys.stderr)
        return EXIT_INVALID
    except OSError as exc:
        print(f"cannot write {args.record}: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    # A path may hold bytes that are no text, which standard output refuses as they are.
    print(f"wrote {args.record}".encode("utf-8", "backslashreplace").decode("utf-8"))
    return EXIT_VALID


# What every generator shares: running an executable, writing the record once,
# and keeping its own heads-up rows.


def run_tool(command: list[str], sent: str | None = None) -> str:
    """Run ``command``, a call to the ``gh`` or the ``work`` executable, and return what it printed.

    A command that cannot be run, or that exits with an error, raises a
    ``RecordError`` whose message quotes the whole command, so the message
    names the call and every id the call was given. The error's code is the
    executable's name followed by ``-failed``. The reason is the message of
    the error the tracker printed, or else what the command wrote to stderr.
    ``sent`` is text the command reads from its standard input.
    """
    quoted = f"`{' '.join(command)}`"
    try:
        # What an executable prints is bytes, and bytes that are no UTF-8 must not stop the read.
        proc = subprocess.run(command, input=sent, capture_output=True, encoding="utf-8", errors="replace", check=False)
    except OSError as exc:
        raise RecordError(f"{command[0]}-failed", f"cannot run {quoted}: {exc}") from exc
    if proc.returncode != 0:
        try:
            reason = json.loads(proc.stdout)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            reason = proc.stderr.strip() or proc.stdout.strip() or "it printed no reason"
        raise RecordError(f"{command[0]}-failed", f"{quoted} exited {proc.returncode}: {reason}")
    return proc.stdout


# The shape of an answer says what the answer must hold before anything reads
# it. A shape is a JSON Schema. An answer that fits no shape can be read as
# something it is not: an object where a list belongs reads as an empty list,
# and an entry with no name reads as no entry. Each read therefore states its
# answer's shape, and these are the pieces the shapes are made of.
TEXT = {"type": "string"}
NAME = {"type": "string", "minLength": 1}
TEXT_OR_NONE = {"type": ["string", "null"]}
COUNT = {"type": "integer", "minimum": 1}


def holding(needs: dict[str, Any], may_hold: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the shape of an object that holds every field of ``needs``, each in the shape given for it.

    The object may hold other fields too. A field of ``may_hold`` need not be
    there, and has its shape when it is.
    """
    return {"type": "object", "required": sorted(needs), "properties": {**needs, **(may_hold or {})}}


def listing(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the shape of a list whose every entry has the shape ``entry``."""
    return {"type": "array", "items": entry}


def unusable(command: list[str], why: str) -> RecordError:
    """Return the error for an answer to ``command`` that cannot be used, which names the call and says why."""
    return RecordError(f"{command[0]}-failed", f"`{' '.join(command)}` gave an answer that cannot be used: {why}")


def tool_json(command: list[str], shape: dict[str, Any] | None = None, sent: str | None = None) -> Any:
    """Run ``command`` as ``run_tool`` does, and return what it printed, parsed as JSON.

    ``shape`` is the shape the answer must have. An answer that does not fit
    it raises a ``RecordError`` that names the call and the place where the
    answer departs from the shape, so no caller goes on with it. A call that
    gives no shape takes whatever JSON came back.
    """
    printed = run_tool(command, sent)
    try:
        answer = json.loads(printed)
    except ValueError as exc:
        # Text that is no JSON fails to load, and so does JSON that holds a number thousands of digits long.
        raise unusable(command, f"it cannot be loaded as JSON: {exc}") from exc
    if shape is not None:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import best_match

        fault = best_match(Draft202012Validator(shape).iter_errors(answer))
        if fault is not None:
            where = "".join(f"/{part}" for part in fault.absolute_path) or "its root"
            why = fault.message
            if fault.validator == "type":
                # The validator's own message for a wrong type quotes the whole value, which can run to pages.
                kinds = fault.validator_value
                why = f"the value is not of type {kinds if isinstance(kinds, str) else ' or '.join(kinds)}"
            raise unusable(command, f"at {where}, {why}")
    return answer


def gh_pages(endpoint: str, entry: dict[str, Any] | None = None) -> list[Any]:
    """Return every entry of a list the GitHub API serves in pages, read through ``gh api``.

    The pages are asked for one at a time, and the reading stops at the first
    page that comes back empty. ``endpoint`` is the path of the list, with or
    without a query of its own. ``entry`` is the shape every entry must have.
    Every page must be a list, whatever its entries.
    """
    entries: list[Any] = []
    page = 1
    while True:
        command = ["gh", "api", f"{endpoint}{'&' if '?' in endpoint else '?'}page={page}"]
        batch = tool_json(command, listing(entry or {}))
        if not batch:
            return entries
        entries += batch
        page += 1


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Replace the record file at ``path`` with ``record``, in one step.

    The text is written beside the file and then moved over it, so a reader
    never finds half a record. Each write has a file of its own there, so two
    writers at once never write through one file, and the record is whichever
    of their two records was moved last. The groups are written in the order
    the schema lists them, so the file reads the same whichever generator ran
    first. A record that holds text UTF-8 cannot hold is refused before
    anything is written, because no file can take it and no later read would
    accept it.
    """
    where = next(_not_utf8(record), None)
    if where is not None:
        message = f"cannot write {path}: the record would hold text that UTF-8 cannot hold, at {where or 'its root'}"
        raise RecordError("not-utf-8", message)
    ordered = {name: record[name] for name in load_schema()["properties"] if name in record}
    beside = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        # Creating the file fails where one of that name exists, so no writer ever opens another's.
        with beside.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n")
        beside.replace(path)
    except OSError as exc:
        # A failed run leaves nothing behind, and that includes the text written beside the record.
        beside.unlink(missing_ok=True)
        raise RecordError("unwritable", f"cannot write {path}: {exc}") from exc


def set_generator_rows(record: dict[str, Any], generator: str, rows: list[str]) -> None:
    """Make ``rows`` the heads-up rows that ``generator`` holds in ``record``.

    A generator's row opens with its name and a colon, which is how the next
    run finds the rows to replace. A row takes the place of a ``None.`` entry.
    When the generator's last row goes and no other entry is left, the list
    holds ``None.``. That is so even where the list was empty before the
    generator wrote into it, because the record keeps no trace of that. A
    list the generator has no row in, and gives none to, is left as it is.
    """
    opening = f"{generator}: "
    entries = record["heads_up"]
    others = [entry for entry in entries if not entry.startswith(opening) and not (rows and is_none(entry))]
    took_one_out = len(others) < len(entries)
    record["heads_up"] = others + [opening + row for row in rows] or ([NONE] if took_one_out else [])


# What ``inert`` quotes where it finds one outside a code span: the opening of
# a fold with the rest of its tag, or the opening of an HTML comment with the
# rest of the comment, as far as either runs before a backtick or the line's end.
QUOTABLE = re.compile(r"<details\b[^>`\r\n]*>?|<!--(?:[^`\r\n]*?-->)?", re.IGNORECASE)


def _inert_line(line: str, ending: str) -> str:
    """Return one line of text with every construct a machine reads quoted as a code span.

    ``ending`` is the line end that follows the line, or nothing after the
    last line. The line is read with it, because a fold's tag may break
    straight after its name, and the line end is then what makes it a fold.
    """
    if not machine_constructs(line + ending):
        return line
    parts, at = [], 0
    for span in [*CODE_SPAN.finditer(line), None]:
        between = line[at : span.start() if span else len(line)]
        parts.append(QUOTABLE.sub(lambda found: f"`{found[0]}`", between))
        if span:
            parts.append(span[0])
            at = span.end()
    quoted = "".join(parts)
    if not machine_constructs(quoted + ending):
        return quoted
    # A span cannot quote the construct where it stands. That is so for a line
    # that opens a fence, and for a construct beside a backtick or a backslash.
    # A span around the whole line, longer than any run of backticks in it,
    # always can.
    longest = max((len(run) for run in re.findall("`+", line)), default=0)
    fence = "`" * (longest + 1)
    return f"{fence} {line} {fence}"


def inert(text: str) -> str:
    """Return ``text`` with every construct a machine reads quoted as a code span, so that it stays a literal.

    A generator copies titles and reasons that other people wrote. A fold, an
    HTML comment or a line that opens a ``json`` fence would act as markup in
    the pull request body, and the lint refuses each of them in any field. A
    code span shows the same characters and does nothing. Text that holds no
    such construct comes back as it was, so quoting twice changes nothing.
    A code span stays on one line, so each line is quoted on its own, and it
    is read together with the line end after it.
    """
    lines = re.split(f"({LINE_END.pattern})", text) + [""]
    return "".join(_inert_line(line, ending) + ending for line, ending in zip(lines[::2], lines[1::2]))


def regenerated(record: dict[str, Any], fill: Callable[..., None], **options: Any) -> dict[str, Any]:
    """Return a copy of ``record`` in which ``fill`` has set afresh every part its generator owns.

    ``record`` itself is left as it was, so the two can be compared.
    """
    filled = copy.deepcopy(record)
    try:
        fill(filled, **options)
    except (KeyError, IndexError, TypeError) as exc:
        # Each read states the shape of its answer, and a wrong shape fails
        # there, naming the call. This catches a read whose stated shape
        # asks for less than the generator goes on to use.
        message = f"an answer from the tracker or from GitHub lacks what the generator reads: {exc!r}"
        raise RecordError("answer-shape", message) from exc
    return filled


def run_generator(args: argparse.Namespace, fill: Callable[..., None]) -> int:
    """Run one generator over the record file ``args.record`` names, and return the exit status.

    ``fill`` computes every part its generator owns and sets them in the
    record it is given. Each option the subcommand takes besides the record's
    path reaches ``fill`` as a keyword argument of the option's name. The file
    is written once, after ``fill`` returns, and only when the record changed.
    A failure of any kind therefore leaves the file as it was, and a second
    run over unchanged sources writes nothing.
    """
    options = {name: value for name, value in vars(args).items() if name not in ("command", "record", "run")}
    try:
        record = read_record(args.record)
        faults = sorted(_schema_faults(record))
        if faults:
            where, fault = faults[0]
            message = f"{args.record} does not fit the record schema at {where or 'its root'}: {fault}"
            raise RecordError("schema", message)
        filled = regenerated(record, fill, **options)
        if filled != record:
            write_record(args.record, filled)
    except RecordError as exc:
        print(exc.message, file=sys.stderr)
        return EXIT_UNUSABLE
    said = f"wrote {args.record}" if filled != record else f"{args.record} is already current"
    # A path may hold bytes that are no text, which standard output refuses as they are.
    print(said.encode("utf-8", "backslashreplace").decode("utf-8"))
    return EXIT_VALID


def add_generator(commands: Any, name: str, fill: Callable[..., None], does: str) -> argparse.ArgumentParser:
    """Add the subcommand ``name`` to ``commands``: a generator that takes a record file and runs ``fill``.

    ``does`` says what the generator does, as the words that follow "to" in a
    sentence. The subcommand's parser is returned, so a generator that takes
    options adds them to it.
    """
    generator = commands.add_parser(
        name,
        help=does,
        description=f"Read a record to {does}. The record names the work item and the pull request to read about. "
        "The file is written once, after every call has succeeded, so a failure leaves it as it was. "
        "Exit 0 the record holds the part, 2 anything failed.",
    )
    generator.add_argument("record", type=Path, help="path to the record's JSON file")
    generator.set_defaults(run=lambda args: run_generator(args, fill))
    return generator


# The two generators that read the tracker: `context` and `discovered`.

# The list of a repository's open pull requests. The `gh` executable fills in
# the owner and the name of the repository the working directory belongs to.
OPEN_PULLS = "repos/{owner}/{repo}/pulls?state=open&per_page=100"

# What `context` says in the heads-up list when it could not compare paths with the other open pull requests.
NO_NUMBER = "The record names no pull request yet, so the other open pull requests were not checked for shared paths."

# The line the tracker adds to an item's notes when the item is delivered, and
# the evidence it was given. The tracker writes the evidence as the caller
# gave it and checks nothing.
DELIVERED = re.compile(r"\[work\] delivered:[ \t]*(?P<evidence>.*)")

# Evidence that names a pull request: a number alone, a number after a `#`, or
# a pull request's URL. The URL names a repository, and so does a `#` with an
# owner and a name before it. Evidence of any other kind names no pull request.
PULL_EVIDENCE = re.compile(r"(?:(?:.*[ \t])?(?:(?P<url>\S+)/pull/|(?P<before>[^\s#]*)#))?(?P<number>\d+)(?:[/#?]\S*)?")

# The heading of the triage record the tracker writes at the end of a
# discovered item's description, and the scope line under it with the reason
# the line gives. The tracker writes a dash between the scope call and its
# reason. A call that defers work names the route it took before that dash,
# so the reason is what follows it.
TRIAGE_HEADING = re.compile(r"## Triage[ \t]*")
TRIAGE_SCOPE = re.compile(r"- Scope: (?:out-of-scope|in-scope — deferred: .+?) — (?P<reason>.+?)[ \t]*")


def unfenced_lines(text: str) -> Iterator[str | None]:
    """Yield each line of ``text``, with None in place of a line that belongs to a fenced block.

    A fenced block quotes its content, so nothing in it says anything about
    the text around it. A block runs from the line that opens it to a line
    that holds only a fence of the same character and at least the same
    length, or to the end of the text when no such line follows.
    """
    opener = ""
    for line in LINE_END.split(text):
        fence = FENCE.fullmatch(line)
        run = re.search("(?:`+|~+)$", line[: fence.start("after")])[0] if fence else ""
        if not opener and not run:
            yield line
            continue
        if not opener:
            opener = run
        elif run[:1] == opener[0] and len(run) >= len(opener) and not fence["after"].strip():
            opener = ""
        yield None


def triage_reason(description: str) -> str | None:
    """Return the reason the triage record in ``description`` gives for its scope call, or None when it holds none.

    The record is a heading with the scope line straight under it. The last
    one in the description counts, because the tracker writes the record at
    the end. A record quoted inside a fenced block is an example and does not
    count.
    """
    reason = None
    for heading, scope in itertools.pairwise(unfenced_lines(description)):
        if heading is None or scope is None or not TRIAGE_HEADING.fullmatch(heading):
            continue
        found = TRIAGE_SCOPE.fullmatch(scope)
        if found:
            reason = found["reason"]
    return reason


def work_call(*arguments: str) -> list[str]:
    """Return the command that makes a read of the tracker through the ``work`` executable."""
    return ["work", "--format", "json", *arguments]


def tracker(*arguments: str, shape: dict[str, Any] | None = None) -> Any:
    """Return the data of the tracker's answer to a read, which must have the shape ``shape``."""
    return tool_json(work_call(*arguments), holding({"data": shape or {}}))["data"]


def tracked_items(ids: list[str], fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the tracker items ``ids`` in the order given, each holding ``fields`` in the shapes given.

    The answer must hold each item asked for once, and no other. An answer
    with an item missing would otherwise read as that item not existing, and
    an answer with a stranger in it would put the stranger in the record.
    """
    item = holding({"id": NAME, **fields})
    items = tracker("show", *ids, shape=holding({"items": listing(item)}))["items"]
    found = [item["id"] for item in items]
    if sorted(found) != sorted(ids):
        why = f"it holds {', '.join(found) or 'no item'}, which is not each item asked for once"
        raise unusable(work_call("show", *ids), why)
    return sorted(items, key=lambda item: ids.index(item["id"]))


def _children(owner_id: str) -> list[dict[str, Any]]:
    """Return the tracker's children of ``owner_id`` in id order, each with its title, status, notes and parent."""
    child = holding({"id": NAME, "title": TEXT, "status": TEXT, "notes": TEXT_OR_NONE, "parent": TEXT_OR_NONE})
    children = tracker("list", "--parent", owner_id, shape=holding({"items": listing(child)}))["items"]
    ids = [child["id"] for child in children]
    strangers = [child["id"] for child in children if child["parent"] != owner_id]
    if strangers or len(set(ids)) < len(ids):
        why = f"{strangers[0]} is no child of {owner_id}" if strangers else "it lists an item twice"
        raise unusable(work_call("list", "--parent", owner_id), why)
    return sorted(children, key=lambda child: _in_id_order(child["id"]))


def _ancestors(item_id: str) -> list[dict[str, Any]]:
    """Return the tracker item ``item_id`` and every item above it, outermost first.

    Each step reads the parent field of the item below. An id that looks like
    a path says nothing about where its item sits now, so no step reads one.
    """
    chain: list[dict[str, Any]] = []
    following: str | None = item_id
    while following is not None:
        if any(item["id"] == following for item in chain):
            raise RecordError("work-failed", f"the tracker's parent fields lead from {following} back to itself")
        chain.insert(0, tracked_items([following], {"title": TEXT, "type": TEXT, "parent": TEXT_OR_NONE})[0])
        following = chain[0]["parent"]
    return chain


def _in_id_order(item_id: str) -> list[Any]:
    """Return a sort key that puts tracker ids in the order a reader counts them, so .10 follows .9."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item_id)]


def _scope(
    work_item: dict[str, Any], children: list[dict[str, Any]], pulls: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return the scope table: one row per child of the owning item, with its title and its status.

    The record's own work item is this pull request, whatever else is true of
    it. A closed child is done. A child is in flight when an open pull request
    names it, which a title does by closing with the child's id in brackets,
    short or full. The lowest-numbered such pull request is the one shown,
    whichever form of the id it uses.
    Every other child is open. An owning item with no child has one part, which
    is this pull request.
    """
    naming: dict[str, int] = {}
    for pull in pulls:
        naming.setdefault(closing_id(pull["title"]), pull["number"])
    rows: list[dict[str, Any]] = []
    for child in children:
        row = {"slice": child["id"], "covers": inert(child["title"])}
        carriers = [naming[name] for name in (child["id"], short_id(child["id"])) if name in naming]
        if child["id"] == work_item["id"]:
            row["status"] = "this PR"
        elif child["status"] == "closed":
            row["status"] = "done"
        elif carriers:
            row.update(status="in flight", pr=min(carriers))
        else:
            row["status"] = "open"
        rows.append(row)
    return rows or [{"slice": work_item["id"], "covers": inert(work_item["title"]), "status": "this PR"}]


def _delivering_pulls(children: list[dict[str, Any]]) -> set[int]:
    """Return the numbers of this repository's pull requests that the deliveries of closed ``children`` name.

    A delivery that names no repository is a pull request of this one. A
    delivery that names a repository counts only when it names the working
    directory's own, by its URL or by its owner and name. The same number in
    another repository is another pull request, so it is neither listed nor
    looked up here. GitHub is asked which repository this is once, and only
    when a delivery names one.
    """
    numbers: set[int] = set()
    this: dict[str, str] = {}
    for child in children:
        if child["status"] != "closed":
            continue
        for line in LINE_END.split(child["notes"] or ""):
            marker = DELIVERED.fullmatch(line.strip())
            evidence = marker and PULL_EVIDENCE.fullmatch(marker["evidence"])
            if not evidence:
                continue
            named = evidence["url"] or ("/" in (evidence["before"] or "") and evidence["before"])
            if named:
                asked = ["gh", "repo", "view", "--json", "nameWithOwner,url"]
                this = this or tool_json(asked, holding({"nameWithOwner": NAME, "url": NAME}))
                own = this["url"].rstrip("/") if evidence["url"] else this["nameWithOwner"]
                if named.rstrip("/").casefold() != own.casefold():
                    continue
            numbers.add(int(evidence["number"]))
    return numbers


def _builds_on(children: list[dict[str, Any]], apart_from: int | None) -> list[dict[str, Any]]:
    """Return the merged pull requests that delivered ``children``, lowest number first, each with its title.

    The number comes from the delivery the tracker recorded on a closed child.
    The tracker records it as the caller gave it and checks nothing, so GitHub
    is asked whether each one merged, and one that closed without merging is
    left out. ``apart_from`` is the record's own pull request, which is never
    something it builds on.
    """
    numbers = _delivering_pulls(children)
    merged = []
    for number in sorted(numbers - {apart_from}):
        asked_for = holding({"number": {"const": number}, "state": TEXT, "title": TEXT})
        pull = tool_json(["gh", "pr", "view", str(number), "--json", "number,state,title"], asked_for)
        if pull["state"] == "MERGED":
            merged.append({"pr": number, "gloss": inert(pull["title"])})
    return merged


def _concurrent(number: int, others: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return each of the open pull requests ``others`` that changes a path pull request ``number`` changes.

    Each entry carries the pull request's title. The paths of ``number`` are
    read only when there is another open pull request to compare them with.
    Every open pull request costs two calls or more, so a repository with
    hundreds open makes this slow.
    """
    own = set(pr_changed_paths(number)) if others else set()
    return [
        {"pr": pull["number"], "gloss": inert(pull["title"])}
        for pull in others
        if own.intersection(pr_changed_paths(pull["number"]))
    ]


def fill_context(record: dict[str, Any]) -> None:
    """Set ``where_this_fits`` in ``record`` from the tracker and from GitHub, with its stamp.

    The owning item is the work item's parent. A work item at the root of its
    tree, or directly under the root, is its own owning item, because the
    children of a root are every piece of work in the project.
    """
    number = record["pr"]["number"]
    chain = _ancestors(record["work_item"]["id"])
    owner = chain[-1] if len(chain) <= 2 else chain[-2]
    children = _children(owner["id"])
    # A pull request that opens or closes while the pages are read moves the
    # ones after it, so one can come back on two pages. It is kept once.
    open_pulls = {pull["number"]: pull for pull in gh_pages(OPEN_PULLS, holding({"number": COUNT, "title": TEXT}))}
    others = [open_pulls[other] for other in sorted(open_pulls) if other != number]
    fits = {
        "ancestry": [{"id": item["id"], "title": inert(item["title"]), "type": inert(item["type"])} for item in chain],
        "builds_on": _builds_on([child for child in children if child["id"] != chain[-1]["id"]], number),
        "concurrent": [] if number is None else _concurrent(number, others),
        "scope": _scope(chain[-1], children, others),
    }
    record["where_this_fits"] = {**fits, "digest": stamp(fits)}
    # A pull request's paths are GitHub's to give, so a record with no number
    # cannot be compared with the other open ones. The list then says so, and
    # it says nothing when no other pull request is open.
    set_generator_rows(record, "context", [NO_NUMBER] if number is None and others else [])


def fill_discovered(record: dict[str, Any]) -> None:
    """Set the filed rows of ``discovered`` in ``record`` from the tracker, with their stamp.

    An item gets a row when its discovered-from edge points at the record's
    work item. The row holds the item's id, its title, and the reason its
    triage record gives for the scope call. The filed rows come first, in id
    order, and every other row stays where the author put it. The ``None.``
    entry goes when a filed row arrives. It never comes from here, because
    only the author can say that the pull request found nothing.
    """
    work_item_id = record["work_item"]["id"]
    edge = holding({"id": NAME, "type": TEXT})
    edges = tracker("dep", "list", work_item_id, shape=holding({"dependents": listing(edge)}))["dependents"]
    found = sorted({edge["id"] for edge in edges if edge["type"] == "discovered-from"}, key=_in_id_order)
    items = tracked_items(found, {"title": TEXT, "description": TEXT_OR_NONE}) if found else []
    filed = []
    for item in items:
        reason = triage_reason(item["description"] or "")
        if reason is None:
            message = (
                f"{item['id']} was discovered from {work_item_id}, and its description holds no triage record "
                "to take the reason from"
            )
            raise RecordError("no-triage", message)
        filed.append({"status": "filed", "item": item["id"], "what": inert(item["title"]), "reason": inert(reason)})
    rest = [row for row in record["discovered"]["rows"] if not (isinstance(row, dict) and row["status"] == "filed")]
    if filed:
        rest = [row for row in rest if isinstance(row, dict)]
    record["discovered"]["rows"] = filed + rest
    record["discovered"]["filed_digest"] = stamp(filed)


# The generator that reads the review verdicts posted on a pull request: `campaign`.

# The skill that defines a review verdict. Every skill sits beside the others in
# one skills directory, in a source tree and wherever the skills are installed.
VERDICT_SKILL = Path(__file__).resolve().parent.parent.parent / "review-verdict"

# The column of a reviewer's row that counts a finding, by the finding's disposition.
DISPOSITION_COLUMNS = {
    "fixed": "fixed",
    "rebutted": "rejected",
    "advisory-deferred": "deferred",
    "transferred": "deferred",
}

# The two places a reply names its commit: in parentheses at the end of its
# Change line, which is matched whole, and straight after the word "commit".
CLOSING_COMMIT = re.compile(r"Change:.*\(([0-9a-f]{7,40})\)[ \t]*")
NAMED_COMMIT = re.compile(r"\bcommits?\b[\s:`]*\b([0-9a-f]{7,40})\b", re.IGNORECASE)

# The states GitHub gives a review that was submitted and still stands. A
# review in any other state is no round: it is a draft that was never
# submitted, or it was dismissed.
SUBMITTED = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})


def or_none(shape: dict[str, Any]) -> dict[str, Any]:
    """Return ``shape`` widened to take null too, which GitHub gives where an account or a review is gone."""
    return {**shape, "type": [shape["type"], "null"]}


# The shape of each answer `campaign` reads from GitHub, which holds what
# `campaign` reads from that answer and nothing else: the pull request, an
# entry of its reviews, an entry of its review comments, and the comparison of
# its base branch with its head.
PULL = holding({
    "user": or_none(holding({"login": NAME})),
    "head": holding({"sha": NAME}),
    "base": holding({"ref": NAME}),
})
REVIEW = holding({
    "id": COUNT,
    "body": TEXT_OR_NONE,
    "state": TEXT,
    "user": or_none(holding({"login": NAME, "type": TEXT})),
})
REVIEW_COMMENT = holding(
    {"id": COUNT, "pull_request_review_id": or_none(COUNT), "body": TEXT, "user": or_none(holding({"login": NAME}))},
    {"in_reply_to_id": or_none(COUNT)},
)
COMPARISON = holding({"merge_base_commit": holding({"sha": NAME})})

# The heads-up row for a campaign whose latest round did not end it clean.
NOT_TERMINAL_CLEAN = "The latest review round is not terminal-clean, so no commit is recorded as cleared by review."


def _verdict_skill(name: str) -> Callable[..., dict[str, Any]]:
    """Return the function ``name`` of the ``review-verdict`` skill, loaded from the skill directory beside this one.

    It is that skill's own function. This script holds no copy of the
    verdict's rules, so the two cannot come to disagree.
    """
    path = VERDICT_SKILL / "validate_verdict.py"
    try:
        spec = importlib.util.spec_from_file_location("validate_verdict", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, name)
    except (OSError, ImportError, SyntaxError, AttributeError) as exc:
        message = f"`campaign` reads verdicts with the `review-verdict` skill's `{name}`, and {path} does not give it: {exc}"
        raise RecordError("no-verdict-skill", message) from exc


def load_verdict_validator() -> Callable[[Any], dict[str, Any]]:
    """Return the validator that the ``review-verdict`` skill ships.

    The validator takes a parsed verdict and returns ``{"valid": True}``, or
    ``{"valid": False, "errors": [...]}`` with a message in each error.
    """
    return _verdict_skill("validate_document")


def load_round_status() -> Callable[..., dict[str, Any]]:
    """Return the rule that the ``review-verdict`` skill ships for whether a review round is terminal-clean.

    The rule takes one verdict, with the pull request's current head, its
    merge base and its other verdicts as keyword arguments. It returns a
    result whose ``terminal_clean`` is the decision.
    """
    return _verdict_skill("round_status")


def fenced_json(body: str) -> str | None:
    """Return the text of the last fenced ``json`` block in ``body``, or ``None`` when it ends with no such block.

    The reviewing App posts a verdict, and the record of one finding, as the
    last fenced block of a comment. The last line that is only backticks
    closes that block. The last line above it that is the same run of
    backticks and then ``json`` opens it. That run is longer than any run of
    backticks inside the block, so no line of the block's own text closes it.
    """
    lines = LINE_END.split(body)
    close = next((at for at in reversed(range(len(lines))) if len(lines[at]) >= 3 and set(lines[at]) == {"`"}), None)
    if close is None:
        return None
    opener = lines[close] + "json"
    start = next((at for at in reversed(range(close)) if lines[at] == opener), None)
    return None if start is None else "\n".join(lines[start + 1 : close])


def reply_commit(body: str) -> str:
    """Return the commit that the reply ``body`` names, or an empty string when it names none.

    The commit is the one in parentheses that ends the reply's Change line.
    A reply with no such line names the first commit that comes straight
    after the word "commit". A commit id anywhere else in a reply is not
    read, because a reply also names commits that fixed nothing. The reply's
    lines end wherever ``LINE_END`` says a line ends.
    """
    closing = filter(None, map(CLOSING_COMMIT.fullmatch, LINE_END.split(body)))
    named = next(closing, None) or NAMED_COMMIT.search(body)
    return named.group(1) if named else ""


def _thread_finding(body: str) -> str | None:
    """Return the finding id that the record ending the comment ``body`` gives, or ``None`` when it gives none.

    The record is whatever the comment's last fenced ``json`` block holds, so
    it can hold anything. Only a record that is an object with a text ``id``
    names a finding. Any other opens no thread.
    """
    try:
        finding_id = json.loads(fenced_json(body) or "")["id"]
    except (ValueError, KeyError, TypeError):
        return None
    return finding_id if isinstance(finding_id, str) else None


def _reply_commits(
    comments: list[Any], author: str | None, posted: list[tuple[int, dict[str, Any]]]
) -> dict[tuple[str, str, str], str]:
    """Return the commit the pull request's author names in reply to each finding, by the finding.

    The reviewing App opens a thread for a finding with a comment that ends
    in the finding's record, and that comment belongs to the review whose
    verdict raised the finding. The verdict gives the claim id and the
    artifact class, and the record gives the finding id. The author's reply
    on that thread is the one read, and a later reply that names a commit
    replaces an earlier one. A finding with no thread has no entry. A pull
    request whose author's account is gone has no author, so no reply on it
    is the author's, and that includes a reply from an account that is gone.
    """
    verdicts = dict(posted)
    threads: dict[int, tuple[str, str, str]] = {}
    for comment in comments:
        verdict = verdicts.get(comment["pull_request_review_id"])
        finding_id = _thread_finding(comment["body"])
        if verdict is not None and finding_id is not None and comment.get("in_reply_to_id") is None:
            threads[comment["id"]] = (verdict["claim_id"], verdict["artifact_class"], finding_id)
    commits: dict[tuple[str, str, str], str] = {}
    for comment in comments:
        finding = threads.get(comment.get("in_reply_to_id"))
        commit = reply_commit(comment["body"])
        if finding and commit and author is not None and (comment["user"] or {}).get("login") == author:
            commits[finding] = commit
    return commits


def _taken_as_written(verdict: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield each identifier of ``verdict`` that a record takes as it is written, with its place in the verdict.

    These are the claim id, the artifact class, each reviewer's name, each
    finding's id, and the work item a disposition names. A reply is matched
    to its finding by the first, the second and the fourth, so none of them
    can be quoted the way a claim is.
    """
    yield "/claim_id", verdict["claim_id"]
    yield "/artifact_class", verdict["artifact_class"]
    for index, entry in enumerate(verdict["lenses"]):
        yield f"/lenses/{index}/lens", entry["lens"]
    for index, finding in enumerate(verdict["findings"]):
        yield f"/findings/{index}/id", finding["id"]
        yield f"/findings/{index}/lens", finding["lens"]
    for index, prior in enumerate(verdict["prior_dispositions"]):
        if "work_item" in prior:
            yield f"/prior_dispositions/{index}/work_item", prior["work_item"]


def _read_verdict(text: str, validate: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
    """Return the verdict that ``text`` holds, or raise a ``ValueError`` that says why it cannot be read.

    Four kinds of verdict are refused here, where the review that carries
    one can be named. One cannot be loaded as JSON. One escapes half of a
    surrogate pair, which is text no record can take. One the validator
    rejects. One holds, in an identifier the record takes as it is written,
    a construct the lint refuses in every field.
    """
    try:
        verdict = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"it cannot be loaded as JSON: {exc}") from exc
    where = next(_not_utf8(verdict), None)
    if where is not None:
        raise ValueError(f"it holds text that UTF-8 cannot hold, at {where or 'its root'}")
    result = validate(verdict)
    if not result["valid"]:
        faults = "; ".join(str(error.get("message")) for error in result.get("errors", []))
        raise ValueError(f"the verdict validator rejects it: {faults}")
    for where, identifier in _taken_as_written(verdict):
        held = machine_constructs(identifier)
        if held:
            raise ValueError(f"at {where}, an identifier holds {held[0]}, and the record takes it as it is written")
    return verdict


def _posted_verdicts(
    reviews: list[Any], app: str | None, validate: Callable[[Any], dict[str, Any]]
) -> tuple[list[tuple[int, dict[str, Any]]], int]:
    """Return the verdicts the reviewing App posted, each with its review's id, and the count that could not be read.

    Only a review whose body ends in a fenced ``json`` block carries a
    verdict, and every other review is passed over without a word. A review
    counts as the reviewing App's when a bot account posted it, and ``app``
    narrows that to one login. A review by anyone else is skipped. So is a
    review in a state outside ``SUBMITTED``, which is a draft or a review
    that was dismissed. A verdict of the App's own that ``_read_verdict``
    refuses is skipped and counted as unreadable. Each review that is skipped
    is named on stderr, so no verdict goes uncounted without a word.
    """
    posted: list[tuple[int, dict[str, Any]]] = []
    unreadable = 0
    for review in reviews:
        text = fenced_json(review["body"] or "")
        if text is None:
            continue
        author = review["user"] or {}
        if author.get("type") != "Bot" or app not in (None, author.get("login")):
            reason = f"its author, {author.get('login')}, is not the reviewing App"
        elif review["state"] not in SUBMITTED:
            reason = f"its state is {review['state']}, and only a submitted review that stands is a round"
        else:
            try:
                posted.append((review["id"], _read_verdict(text, validate)))
                continue
            except ValueError as exc:
                unreadable += 1
                reason = f"its verdict cannot be read: {exc}"
        print(f"campaign: review {review['id']} is skipped, because {reason}", file=sys.stderr)
    return posted, unreadable


def _empty_campaign_rows(counted: int, unreadable: int) -> list[str]:
    """Return the heads-up rows that say why a campaign is empty, which is none when a verdict was counted."""
    if counted:
        return []
    if not unreadable:
        return ["No review round has run on this pull request."]
    carried = "review carries a verdict" if unreadable == 1 else "reviews carry verdicts"
    return [f"{unreadable} {carried} that could not be read, so no review round is counted."]


def _terminal_sha(verdicts: list[dict[str, Any]], pull: dict[str, Any], judge: Callable[..., dict[str, Any]]) -> str:
    """Return the head commit of the latest round in ``verdicts`` when it is terminal-clean, and an empty string otherwise.

    ``verdicts`` is in the order the reviews were posted, so the latest round
    is the last of them. An earlier round never names the commit. ``judge`` is
    the ``review-verdict`` skill's rule for a round, and it alone decides.
    This script hands it the facts it asks for and repeats none of its checks.

    The facts are the head commit that ``pull`` gives, the merge base of that
    head and the base branch, and every other verdict. GitHub's comparison of
    the two gives the merge base. The base branch is compared by its name,
    because the commit GitHub gives for a pull request's base can be behind
    that branch. No staffing record is handed over, so the rule does not
    compare the reviewers that ran with the ones that were staffed. A
    campaign with no verdict has no round to judge, and nothing is compared
    for it.
    """
    if not verdicts:
        return ""
    *others, latest = verdicts
    head = pull["head"]["sha"]
    comparison = ["gh", "api", f"repos/{{owner}}/{{repo}}/compare/{pull['base']['ref']}...{head}"]
    merge_base = tool_json(comparison, COMPARISON)["merge_base_commit"]["sha"]
    status = judge(latest, head_sha=head, merge_base=merge_base, other_envelopes=others)
    return latest["head_sha"] if status["terminal_clean"] else ""


def campaign_part(
    verdicts: list[dict[str, Any]], commits: dict[tuple[str, str, str], str], terminal_sha: str = ""
) -> dict[str, Any]:
    """Return the campaign part of a record, built from review verdicts in the order they were posted.

    ``commits`` gives the commit the author's reply names, by the finding.
    ``terminal_sha`` is the commit the campaign ended clean at, or an empty
    string when it has not ended clean.

    A finding is named by its verdict's claim id and artifact class together
    with its own id, because finding ids start again with each claim and each
    class. A reviewer's row gives the lowest and the highest round the
    reviewer ran in, across every claim and class. It counts each finding the
    reviewer raised once, and counts it again under the column of the
    finding's latest disposition. A finding with no disposition is in none of
    those columns, so the columns can total less than the findings.

    A finding's entry gives the round it first appeared in and the claim as
    that round worded it. Its disposition is the latest one a verdict gives
    it, with that disposition's evidence as the reason. A disposition for a
    finding that none of ``verdicts`` raised is passed over.
    """
    rounds: dict[str, list[int]] = {}
    findings: dict[tuple[str, str, str], dict[str, Any]] = {}
    raised_by: dict[tuple[str, str, str], str] = {}
    settled: dict[tuple[str, str, str], dict[str, Any]] = {}
    for verdict in verdicts:
        claim, kind = verdict["claim_id"], verdict["artifact_class"]
        for name in [entry["lens"] for entry in verdict["lenses"] + verdict["findings"]]:
            rounds.setdefault(name, []).append(verdict["round"])
        for finding in verdict["findings"]:
            key = (claim, kind, finding["id"])
            if key not in findings:
                raised_by[key] = finding["lens"]
                findings[key] = {
                    "claim_id": claim,
                    "artifact_class": kind,
                    "round": verdict["round"],
                    "id": finding["id"],
                    "claim": inert(finding["claim"]),
                }
        for prior in verdict["prior_dispositions"]:
            settled[(claim, kind, prior["id"])] = prior
    reviewers = []
    for name, ran in rounds.items():
        raised = [key for key in findings if raised_by[key] == name]
        row = {
            "reviewer": name,
            "rounds": str(min(ran)) if min(ran) == max(ran) else f"{min(ran)} to {max(ran)}",
            "findings": len(raised),
            "fixed": 0,
            "rejected": 0,
            "deferred": 0,
        }
        for key in raised:
            if key in settled:
                row[DISPOSITION_COLUMNS[settled[key]["disposition"]]] += 1
        reviewers.append(row)
    for key, entry in findings.items():
        if key in settled:
            entry["disposition"] = settled[key]["disposition"]
            entry["reason"] = inert(settled[key].get("evidence", ""))
            if "work_item" in settled[key]:
                entry["work_item"] = settled[key]["work_item"]
        entry["commit"] = commits.get(key, "")
    part = {"reviewers": reviewers, "terminal_sha": terminal_sha, "findings": list(findings.values())}
    return {**part, "digest": stamp(part)}


def fill_campaign(record: dict[str, Any], pr: int | None = None, app: str | None = None) -> None:
    """Set ``campaign`` in ``record`` from the review verdicts posted on its pull request, with its stamp.

    The pull request is ``pr``, or else the one the record names, and a
    ``pr`` that is not the record's own is refused. The validator and the
    rule for a round are loaded before the first call, so a missing skill
    costs no call. The pull request is read for its author, whose replies
    name the commits, and for its head and its base branch. A campaign that
    comes out empty gets a heads-up row that says why, and that row goes when
    a later run counts a verdict. A campaign whose latest round is not
    terminal-clean gets a row that says so, and that row goes when a later
    run names the terminal commit.
    """
    held = record["pr"]["number"]
    number = held if pr is None else pr
    if number is None:
        raise RecordError("no-pull-request", "the record names no pull request yet; give its number with --pr")
    if held not in (None, number):
        message = f"the record is for pull request {held}, and --pr names pull request {number}"
        raise RecordError("other-pull-request", message)
    validate, judge = load_verdict_validator(), load_round_status()
    pull = f"repos/{{owner}}/{{repo}}/pulls/{number}"
    answer = tool_json(["gh", "api", pull], PULL)
    author = (answer["user"] or {}).get("login")
    reviews = gh_pages(f"{pull}/reviews?per_page=100", REVIEW)
    comments = gh_pages(f"{pull}/comments?per_page=100", REVIEW_COMMENT)
    posted, unreadable = _posted_verdicts(reviews, app, validate)
    verdicts = [verdict for _, verdict in posted]
    terminal = _terminal_sha(verdicts, answer, judge)
    record["campaign"] = campaign_part(verdicts, _reply_commits(comments, author, posted), terminal)
    rows = _empty_campaign_rows(len(verdicts), unreadable)
    if verdicts and not terminal:
        rows.append(NOT_TERMINAL_CLEAN)
    set_generator_rows(record, "campaign", rows)


def _filled(text: str) -> str:
    """Return ``text`` as a command-line argument's value, and refuse it when it is blank or is no text.

    A byte on the command line that is no UTF-8 arrives as half of a surrogate
    pair. The record is written as UTF-8, so such a value cannot go into it.
    """
    if not text.strip():
        raise argparse.ArgumentTypeError("the value is blank")
    if next(_not_utf8(text), None) is not None:
        raise argparse.ArgumentTypeError("the value holds a byte that is not UTF-8 text")
    return text


# Rendering. Each artifact is one template file, read when the artifact is
# rendered, so every heading, label and column title a reader sees comes from
# that file and none from this script.

# Another tool keeps a decisions block in the pull request body, between these
# two markers. A render carries the block over and never writes one.
DECISIONS_OPENING = "<!-- prgroom:decisions:start -->"
DECISIONS_CLOSING = "<!-- prgroom:decisions:end -->"

# A review round records a disposition in its own vocabulary. A reader sees
# the word here in its place.
OUTCOME_OF = {
    "fixed": "Fixed",
    "rebutted": "Rejected",
    "advisory-deferred": "Deferred",
    "transferred": "Deferred",
}

# A whole line that is the row under a table's header, which is what makes the
# lines around it a table.
TABLE_RULE = re.compile(r"(?=.*\|)(?=.*-)[ \t|:-]+")

# A whole line that git reads as the end of a commit message. The trailers
# below such a line are no longer read.
DIVIDER = re.compile(r"---(?:\s.*)?")

# A word of prose for the wrap: a run with no space in it, with any code span
# it touches taken whole, spaces and all.
WORD = re.compile(r"(?:" + CODE_SPAN.pattern + r"|\S)+")

# The most columns a line of commit prose takes, which is the width a log is read at.
WRAP_COLUMN = 72

# The most words that the part of a body above its horizontal rule shows a reader.
ONE_PAGER_WORDS = 400

# A fold, from its opening tag to its closing one, and the horizontal rule that ends the one-pager.
# A tag straight after a backtick is quoted in a code span, so it opens no fold.
FOLD = re.compile(r"(?<!`)<details[\s>].*?</details>", re.DOTALL)
ONE_PAGER_END = re.compile(r"^---$", re.MULTILINE)

# A line that opens or closes a block of a template. An opening line may name
# the values its path takes, after an equals sign and with commas between them.
_SECTION = re.compile(r"\{\{([#/])([a-z_.]+)(?:=([a-z,]+))?\}\}")
_PARENTHESIS = re.compile(r" \((?:[^()$]*\$\{[^}]+\})+[^()$]*\)")


class Refusal(Exception):
    """A render that must not be written; carries the findings that say why."""

    def __init__(self, findings: list[dict[str, str]]) -> None:
        super().__init__(findings)
        self.findings = findings


class _Slots(string.Template):
    """Template text whose ``${a.b}`` slots name record fields by their path."""

    braceidpattern = r"[a-z_.\[\]]+"


def _look(record: dict[str, Any], path: str, bound: dict[str, Any]) -> Any:
    """Return what the record holds at a slot's path, or None when it holds nothing there.

    A path through ``[]`` is read from the one list entry bound for the line
    being filled. Every other path is read from the record's root.
    """
    head, each, rest = path.partition("[]")
    node = bound.get(head) if each else record
    for name in filter(None, (rest if each else head).split(".")):
        node = node.get(name) if isinstance(node, dict) else None
    return node


def _holds_something(value: Any) -> bool:
    """Say whether a value has anything in it for a reader.

    Text that is only space, a list of nothing and a group whose every value
    is empty all render as a group the record does not hold.
    """
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(map(_holds_something, value.values()))
    if isinstance(value, list):
        return any(map(_holds_something, value))
    return value is not None


def _one_line(text: str) -> str:
    """Return prose as one line, in which each line break and the space around it read as one space."""
    if not LINE_END.search(text):
        return text
    return " ".join(filter(None, (part.strip() for part in LINE_END.split(text))))


def _shown(value: Any) -> str:
    """Return a field's value as a reader sees it.

    A list reaches here only from a slot that names it whole, which the
    templates do for references to other pull requests.
    """
    if isinstance(value, list):
        return ", ".join(f"#{ref['pr']} ({ref['gloss']})" for ref in value) or "none"
    return "" if value is None else str(value)


def _fill_line(line: str, record: dict[str, Any], bound: dict[str, Any]) -> str:
    """Fill one template line.

    A slot that stands alone on its line is a block, and its value keeps its
    own lines. Any other slot is set on the template's line. A table row keeps
    a line break as ``<br>`` and escapes a pipe, so the value stays in its
    cell. Elsewhere a line break reads as a space. Text in parentheses goes,
    parentheses and all, when the record holds a value for none of the slots
    inside them.
    """
    in_table = line.startswith("|")
    is_block = bool(_Slots.pattern.fullmatch(line))

    def shown(path: str) -> str:
        text = _shown(_look(record, path, bound))
        if in_table:
            return LINE_END.sub("<br>", text.replace("|", "\\|"))
        return text if is_block else _one_line(text)

    def kept(found: re.Match[str]) -> str:
        return found[0] if any(shown(path) for path in _Slots(found[0]).get_identifiers()) else ""

    line = _PARENTHESIS.sub(kept, line)
    return _Slots(line).substitute({path: shown(path) for path in _Slots(line).get_identifiers()})


def _fill(template: str, record: dict[str, Any], bound: dict[str, Any] | None = None) -> str:
    """Fill a template from a record and return the artifact.

    A line whose slot passes through a list appears once per entry, unless the
    caller bound that list to one entry. The lines between ``{{#a.b}}`` and
    ``{{/a.b}}`` appear only when the record holds a value at that path. The
    lines between ``{{#a.b=x,y}}`` and ``{{/a.b}}`` appear only when the value
    at that path is one of those named, which is how a template says which
    commit types carry a block. A record that holds a group its type does not
    carry therefore renders without it. A blank line of the template is left
    out where the line before it is blank, so the lines that vanish between
    two blank lines leave one behind.
    """
    bound = bound or {}
    lines: list[str] = []
    open_sections: list[bool] = []
    for line in template.splitlines():
        section = _SECTION.fullmatch(line)
        if section and section[1] == "#":
            held = _look(record, section[2], bound)
            open_sections.append(held in section[3].split(",") if section[3] else _holds_something(held))
        elif section:
            open_sections.pop()
        elif not line and lines and not lines[-1]:
            continue
        elif all(open_sections):
            repeated = [
                path for path in _Slots(line).get_identifiers()
                if "[]" in path and path.partition("[]")[0] not in bound
            ]
            if not repeated:
                lines.append(_fill_line(line, record, bound))
                continue
            head, _, field = repeated[0].partition("[]")
            first = field.lstrip(".")
            for entry in _look(record, head, bound) or []:
                # The entry that states its list is empty stands in the line's first place.
                if is_none(entry) and first:
                    entry = {first: NONE}
                lines.append(_fill_line(line, record, {**bound, head: entry}))
    return "\n".join(lines) + "\n"


def _template(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def _wrapped(text: str) -> str:
    """Set prose as one paragraph, in lines of at most ``WRAP_COLUMN`` columns.

    A line break in the text reads as a space. A code span is never split,
    because a construct it quotes would stop being a literal at the start of
    a line. A word or a span longer than a line takes a line of its own.
    """
    lines: list[str] = []
    for found in WORD.finditer(_one_line(text)):
        word = found.group()
        if lines and len(lines[-1]) + 1 + len(word) <= WRAP_COLUMN:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return "\n".join(lines)


def commit_markup(written: str, laid_out: str) -> Iterator[str]:
    """Name each construct in one field of a commit message that the message cannot hold.

    A commit message is read as plain text in a log, where a table, a fold, a
    fenced block and an HTML comment do not render. ``written`` is the field as
    the record holds it, and ``laid_out`` is the same text as the message shows
    it. The message is what a reader gets, so every construct is read from
    ``laid_out``, with the readers ``lint`` uses. A table and a fenced block
    are made of whole lines, which the wrap takes apart, so those two are read
    from ``written`` as well.
    """
    plain = outside_code(laid_out)
    yield from (name for name, pattern in MACHINE_CONTENT.items() if pattern.search(plain))
    shown = LINE_END.split(laid_out)
    if any(TABLE_RULE.fullmatch(line) for line in [*LINE_END.split(written), *shown]):
        yield "a Markdown table"
    if any(True for text in (written, laid_out) for _ in fence_openings(text)):
        yield "a fenced block"
    if any(DIVIDER.fullmatch(line) for line in shown):
        yield "a line that opens with `---`, which git reads as the end of the message"


def render_commit_message(record: dict[str, Any]) -> str:
    """Return the commit message for a record, or raise ``Refusal`` when a field carries markup."""
    commit = dict(record["commit"])
    for section in BODY_SECTIONS:
        if section in commit:
            commit[section] = _wrapped(commit[section])
    view = {**record, "commit": commit}
    template = _template("commit-message.txt")
    faults = [
        _finding("commit-markup", "/" + path.replace(".", "/"), f"a commit message cannot hold {kind}")
        for path in _Slots(template).get_identifiers()
        for kind in commit_markup(_shown(_look(record, path, {})), _shown(_look(view, path, {})))
    ]
    if faults:
        raise Refusal(faults)
    return _fill(template, view)


def render_reply(record: dict[str, Any], entry: dict[str, Any]) -> str:
    """Return the reply to one review finding, given that finding's entry in the record's replies."""
    return _fill(_template("review-reply.txt"), record, {"replies": entry})


def _decisions_block(body: str) -> str:
    """Return the decisions block an existing body holds, markers included, or "" when it holds none.

    A body with one marker, a repeated marker or the two out of order has no
    block that can be told apart from the text around it. Rendering such a body
    as if it had none would drop what the other tool wrote, so it is refused.
    """
    counts = {marker: body.count(marker) for marker in (DECISIONS_OPENING, DECISIONS_CLOSING)}
    if not any(counts.values()):
        return ""
    for marker, count in counts.items():
        if count != 1:
            message = f"the existing body holds {marker} {count} times, and a decisions block has it once"
            raise Refusal([_finding("decisions-block", "", message)])
    start, end = body.index(DECISIONS_OPENING), body.index(DECISIONS_CLOSING)
    if end < start:
        message = f"the existing body holds {DECISIONS_CLOSING} before {DECISIONS_OPENING}"
        raise Refusal([_finding("decisions-block", "", message)])
    return body[start : end + len(DECISIONS_CLOSING)]


def _outcome(finding: dict[str, Any], replies: list[dict[str, Any]]) -> str:
    """Return the outcome word for a finding in the campaign table.

    A review round never records a finding as superseded. Only the author's
    reply to that finding does, so such a reply decides the word.
    """
    for reply in replies:
        if _identity(reply, "finding_id") == _identity(finding, "id") and reply["outcome"] == "Superseded":
            return reply["outcome"]
    return OUTCOME_OF.get(finding.get("disposition", ""), "")


def render_body(record: dict[str, Any], existing_body: str = "", comment_url: str = "") -> str:
    """Return the pull request body for a record.

    ``existing_body`` is the body the pull request has now, whose decisions
    block is carried over byte for byte. ``comment_url`` is the comment the
    record is posted in, and the line pointing at it appears only when given.
    """
    view = {
        **record,
        # The summary stands alone on its template line and is one paragraph.
        "summary": _one_line(record["summary"]),
        "commit_message": render_commit_message(record).rstrip("\n"),
        "decisions": _decisions_block(existing_body),
        "record_comment_url": comment_url,
    }
    if "campaign" in record:
        replies = record.get("replies", [])
        findings = [
            {**finding, "disposition": _outcome(finding, replies)}
            for finding in record["campaign"]["findings"]
        ]
        # A finding's id tells it from every other while one claim and one
        # artifact class cover the campaign. Its claim and class are shown
        # only when they are needed to tell two findings apart.
        if len({(finding["claim_id"], finding["artifact_class"]) for finding in findings}) <= 1:
            findings = [
                {name: value for name, value in finding.items() if name not in ("claim_id", "artifact_class")}
                for finding in findings
            ]
        view["campaign"] = {**record["campaign"], "findings": findings}
    return _fill(_template("pr-body.md"), view)


def visible_words(body: str) -> list[str]:
    """Return the words a reader sees in a body's one-pager without opening a fold.

    The one-pager is the text above the first horizontal rule. A fold is left
    out whole, its label included. A word is a run of characters with no space
    in it that holds a letter or a digit. A table's pipes, a heading's marks
    and a list's bullets hold neither, so they are not words.
    """
    one_pager = ONE_PAGER_END.split(FOLD.sub("", body), maxsplit=1)[0]
    return [token for token in one_pager.split() if re.search(r"[^\W_]", token)]


def _reply_entry(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """Return the one reply entry the arguments name, or raise ``Refusal`` when they name none or several."""
    wanted = {"finding_id": args.finding, "claim_id": args.claim, "artifact_class": args.artifact_class}
    matches = [
        entry for entry in record.get("replies", [])
        if all(value is None or entry.get(key) == value for key, value in wanted.items())
    ]
    if len(matches) != 1:
        message = (
            f"{len(matches)} reply entries match finding {args.finding}; "
            "name exactly one with --finding, --claim and --artifact-class"
        )
        raise Refusal([_finding("reply-entry", "/replies", message)])
    return matches[0]


def _read_body(path: Path | None) -> str:
    """Read an existing body without changing a byte of it, line endings included."""
    if path is None:
        return ""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RecordError("unreadable", f"cannot read {path}: {exc}") from exc


def _render(args: argparse.Namespace) -> int:
    """Run ``render``: write one artifact, or report on stderr why none was written."""
    try:
        record = read_record(args.record)
        findings = lint_record(record)
        if findings:
            raise Refusal(findings)
        if args.artifact == "commit":
            text = render_commit_message(record)
        elif args.artifact == "reply":
            text = render_reply(record, _reply_entry(record, args))
        else:
            text = render_body(record, _read_body(args.existing_body), args.comment_url)
    except RecordError as exc:
        unreadable = [_finding(exc.code, "", exc.message)]
        print(json.dumps({"valid": False, "errors": unreadable}, sort_keys=True), file=sys.stderr)
        return EXIT_UNUSABLE
    except Refusal as refusal:
        print(json.dumps({"valid": False, "errors": refusal.findings}, sort_keys=True), file=sys.stderr)
        return EXIT_INVALID
    # The artifact is written as bytes, so it is the same under every locale and on every platform.
    if args.output:
        args.output.write_bytes(text.encode("utf-8"))
    else:
        sys.stdout.buffer.write(text.encode("utf-8"))
    shown = len(visible_words(text)) if args.artifact == "body" else 0
    if shown > ONE_PAGER_WORDS:
        # The body is written all the same, because lines a generator wrote
        # count toward the bound and the author cannot shorten those.
        said = (
            f"warning: the body shows {shown} words above its horizontal rule, "
            f"and a one-pager takes at most {ONE_PAGER_WORDS}; words inside a fold are not counted"
        )
        print(said, file=sys.stderr)
    return EXIT_VALID


# Publication. A record is posted on its pull request as a comment of its own,
# and the pull request body is set to the render of that record. A later
# revision is a new comment, so the comments keep every revision and the body
# shows the newest one.

# The most characters GitHub takes in a pull request body, and in a comment.
GITHUB_LIMIT = 65536

# The first line of a record comment, which is what tells one from every other
# comment on a pull request.
MARKER = re.compile(r"<!-- change-record v\d+ pr=(?P<pr>\d+) rev=(?P<revision>\d+) sha256=(?P<digest>[0-9a-f]{64}) -->")

# GitHub gives a comment its URL when it creates the comment. That URL is the
# pull request's own, then this fragment with the comment's id where the zeros
# are. The body points at the comment, so until the comment exists the zeros
# stand for its id, and the body can be measured and shown with them. An id is
# ten digits long today. Once ids take eleven, a body within a character of the
# limit passes the measure here and GitHub refuses it. That run fails as any
# refused call does, after its comment is posted.
NEW_COMMENT = "#issuecomment-" + "0" * 10

# The shapes of the two answers `publish` reads from GitHub, which are the pull
# request and a comment on it. A commit is forty hex characters, as the record
# holds one.
COMMIT = {"type": "string", "pattern": r"^[0-9a-f]{40}(?![\s\S])"}
PULL_TO_PUBLISH = holding({"body": TEXT_OR_NONE, "html_url": NAME, "head": holding({"sha": COMMIT})})
COMMENT = holding({"id": COUNT, "body": TEXT, "html_url": NAME})

# The subcommand that fills each generated part and the function it runs, by the part's group.
GENERATORS = {
    "where_this_fits": ("context", fill_context),
    "discovered": ("discovered", fill_discovered),
    "campaign": ("campaign", fill_campaign),
}


def record_digest(record: dict[str, Any]) -> str:
    """Return the digest of ``record``'s content, as sixty-four hex characters.

    The digest is the stamp over the record without its ``record`` group, so
    it is a SHA-256 digest of JSON with sorted keys, as ``stamp`` writes it.
    The ``record`` group says where and when the record was published. Leaving
    it out means that publishing a record does not change its digest.
    """
    return stamp({name: group for name, group in record.items() if name != "record"})


def record_comment(record: dict[str, Any]) -> str:
    """Return the comment that holds ``record``, whose ``record`` group gives the revision and the digest.

    The first line is the marker. It names the schema version, the pull
    request, the revision and the digest, so a reader finds the comment and
    knows what it holds without opening it. The record follows in a fold, as
    JSON on one line with sorted keys. The JSON is written tight because a
    comment has a size limit and a generated part cannot be cut to fit. Its
    one line opens with a brace, so no line of it closes the fence around it.
    """
    held = record["record"]
    marker = (
        f"<!-- change-record v{held['schema_version']} pr={record['pr']['number']} "
        f"rev={held['revision']} sha256={held['digest']} -->"
    )
    written = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    summary = f"<details><summary>Change record, revision {held['revision']}</summary>"
    return f"{marker}\n{summary}\n\n```json\n{written}\n```\n\n</details>\n"


def newest_record_comment(comments: list[dict[str, Any]], number: int) -> dict[str, Any] | None:
    """Return the newest record comment of pull request ``number`` among ``comments``, or None when there is none.

    A record comment is one whose first line is a marker that names this pull
    request. A comment that quotes a marker further down is not one. The
    newest has the highest revision, read as a number, so 10 follows 9. Where
    two carry one revision, the newest is the one with the higher id, which
    GitHub created later. The order GitHub lists the comments in decides
    nothing. The comment comes back with the ``revision`` and the ``digest``
    its marker gives.
    """
    found = []
    for comment in comments:
        marker = MARKER.fullmatch(LINE_END.split(comment["body"], maxsplit=1)[0])
        if marker and int(marker["pr"]) == number:
            found.append({**comment, "revision": int(marker["revision"]), "digest": marker["digest"]})
    return max(found, key=lambda comment: (comment["revision"], comment["id"]), default=None)


def publish(record: dict[str, Any], path: Path, dry_run: bool) -> str:
    """Post ``record`` on its pull request, write what was posted into the file at ``path``, and say what was done.

    Every reason to refuse is checked before anything is written. The comment
    is then created, the body is set, and the file is written, in that order.
    A run that stops between two of those is finished by the next run, which
    finds the comment by its digest and writes only what is still missing.
    ``dry_run`` prints the comment and the body and writes nothing.
    """
    number = record["pr"]["number"]
    if number is None:
        message = "the record names no pull request; set `pr.number` to the number of the open pull request"
        raise RecordError("no-pull-request", message)
    pull_path = f"repos/{{owner}}/{{repo}}/pulls/{number}"
    comments_path = f"repos/{{owner}}/{{repo}}/issues/{number}/comments"
    pull = tool_json(["gh", "api", pull_path], PULL_TO_PUBLISH)
    newest = newest_record_comment(gh_pages(f"{comments_path}?per_page=100", COMMENT), number)
    if newest is None:
        # A stamp shows only that a generated part was not edited after it was
        # stamped, and a stamp can be set by hand. Before the first comment is
        # posted, each generator therefore runs over a copy of the record, and
        # the record must already be what the generator writes.
        stale = [
            _finding(
                "stale-part", f"/{group}",
                f"`{name}` would now write {GENERATED_PARTS[group]} differently, so the record is out of date "
                f"or was edited by hand; run `{name}` again",
            )
            for group, (name, fill) in GENERATORS.items()
            if regenerated(record, fill) != record
        ]
        if stale:
            raise Refusal(stale)
    digest = record_digest(record)
    posted = newest is not None and newest["digest"] == digest
    revision = 1 if newest is None else newest["revision"] + (0 if posted else 1)
    # A comment cannot name its own id, so the record is posted without one.
    kept = {name: value for name, value in record["record"].items() if name != "comment_id"}
    posting = {**record, "record": {**kept, "revision": revision, "digest": digest, "head_sha": pull["head"]["sha"]}}
    comment = newest["body"] if posted else record_comment(posting)
    existing = pull["body"] or ""
    body = render_body(posting, existing, newest["html_url"] if posted else pull["html_url"] + NEW_COMMENT)
    too_long = [
        _finding("too-long", "", f"{name} is {len(text)} characters long, and GitHub takes at most {GITHUB_LIMIT}")
        for name, text in (("the record comment", comment), ("the pull request body", body))
        if len(text) > GITHUB_LIMIT
    ]
    if too_long:
        raise Refusal(too_long)
    what = "({}, {})".format(
        "comment already posted" if posted else "new comment",
        "new body" if body != existing else "body already current",
    )
    if dry_run:
        sys.stdout.buffer.write((comment + body).encode("utf-8"))
        return f"dry run of revision {revision} {what}"
    if not posted:
        newest = tool_json(["gh", "api", comments_path, "--method", "POST", "-F", "body=@-"], COMMENT, comment)
        body = render_body(posting, existing, newest["html_url"])
    if body != existing:
        run_tool(["gh", "api", pull_path, "--method", "PATCH", "-F", "body=@-"], body)
    filed = {**posting, "record": {**posting["record"], "comment_id": newest["id"]}}
    if filed != record:
        write_record(path, filed)
    return f"published revision {revision} at {newest['html_url']} {what}"


def _publish(args: argparse.Namespace) -> int:
    """Run ``publish``: post the record and set the body, or report on stderr why nothing was written."""
    try:
        record = read_record(args.record)
        findings = lint_record(record)
        if findings:
            raise Refusal(findings)
        said = publish(record, args.record, args.dry_run)
    except RecordError as exc:
        unreadable = [_finding(exc.code, "", exc.message)]
        print(json.dumps({"valid": False, "errors": unreadable}, sort_keys=True), file=sys.stderr)
        return EXIT_UNUSABLE
    except Refusal as refusal:
        print(json.dumps({"valid": False, "errors": refusal.findings}, sort_keys=True), file=sys.stderr)
        return EXIT_INVALID
    # A dry run keeps stdout for the comment and the body alone.
    print(said, file=sys.stderr if args.dry_run else sys.stdout)
    return EXIT_VALID


def add_publish(commands: Any) -> None:
    """Add the ``publish`` subcommand to ``commands``."""
    parser = commands.add_parser(
        "publish",
        help="post a record on its pull request and set the pull request body from it",
        description="Post a record on its pull request as a new comment, and set the pull request body to the "
        "render that points at that comment. The record is linted first, and every reason to refuse is checked "
        "before anything is written. A record that is refused gets the JSON result on stderr. "
        "Exit 0 published, 1 refused, 2 unreadable or unparseable, or a call failed.",
    )
    parser.add_argument("record", type=Path, help="path to the record's JSON file")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the comment and the body to stdout, and write nothing"
    )
    parser.set_defaults(run=_publish)


def build_parser() -> argparse.ArgumentParser:
    """Build the command line. Each subcommand names the function that runs it as ``run``."""
    parser = argparse.ArgumentParser(
        prog="change_record.py",
        description="Start, fill or check a change record, the JSON document a pull request's description, "
        "commit message and review replies are written from, and render the three from it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init",
        help="write a new record for the author to fill",
        description="Write a new record with every field the author fills left empty. lint then names each "
        "of those fields. Exit 0 written, 1 a file is already there, 2 the file cannot be written.",
    )
    init.add_argument(
        "--type",
        required=True,
        choices=load_schema()["properties"]["pr"]["properties"]["type"]["enum"],
        help="the commit type of the pull request",
    )
    init.add_argument(
        "--component", required=True, type=_filled, metavar="NAME",
        help="the thing a reader would search for, such as a package or skill name",
    )
    init.add_argument(
        "--work-item", required=True, type=_filled, metavar="ID",
        help="the tracker's full id for the item the pull request delivers",
    )
    init.add_argument("record", type=Path, help="where to write the record; the file must not exist yet")
    init.set_defaults(run=_init)
    lint = commands.add_parser(
        "lint",
        help="check a record against the record schema and the writing rules",
        description="Check a record against the record schema, then against the writing rules a program "
        "can decide. Prints a JSON result to stdout. Exit 0 valid, 1 invalid, 2 unreadable or unparseable, "
        "or gh failed under --pr.",
    )
    lint.add_argument("record", type=Path, help="path to the record's JSON file")
    lint.add_argument(
        "--pr",
        type=int,
        metavar="NUMBER",
        help="also check the record against this pull request's changed paths, which are read through gh",
    )
    lint.set_defaults(run=_lint)
    add_generator(commands, "context", fill_context, "fill where_this_fits from the tracker and from GitHub")
    add_generator(commands, "discovered", fill_discovered, "fill the filed rows of discovered from the tracker")
    campaign = add_generator(
        commands, "campaign", fill_campaign, "fill campaign from the review verdicts posted on the pull request"
    )
    campaign.add_argument(
        "--pr", type=int, metavar="NUMBER",
        help="the pull request to read; leave it out when the record already holds the number",
    )
    campaign.add_argument(
        "--app", type=_filled, metavar="LOGIN",
        help="count only the reviews this login posted; without it, a review counts when a bot account posted it",
    )
    render = commands.add_parser(
        "render",
        help="render the pull request body, the commit message or a review reply from a record",
        description="Fill one template file from a record. The record is linted first. A record "
        "that is refused gets the JSON result on stderr and nothing written. "
        "Exit 0 rendered, 1 refused, 2 unreadable or unparseable.",
    )
    artifacts = render.add_subparsers(dest="artifact", required=True)
    for name, what in (
        ("body", "the pull request body"),
        ("commit", "the commit message"),
        ("reply", "the reply to one review finding"),
    ):
        artifact = artifacts.add_parser(name, help=f"render {what}", description=f"Render {what}.")
        artifact.add_argument("record", type=Path, help="path to the record's JSON file")
        artifact.add_argument("--output", type=Path, help="write the artifact to this file in place of stdout")
        artifact.set_defaults(run=_render)
    body = artifacts.choices["body"]
    body.add_argument(
        "--existing-body", type=Path,
        help="a file holding the pull request's current body, whose decisions block is carried over",
    )
    body.add_argument(
        "--comment-url", default="",
        help="the comment the record is posted in; adds the line that points at it",
    )
    reply = artifacts.choices["reply"]
    reply.add_argument("--finding", required=True, help="the finding's id, as the reply entry holds it")
    reply.add_argument("--claim", help="the entry's claim id, when two entries share a finding id")
    reply.add_argument("--artifact-class", help="the entry's artifact class, when the claim id is shared too")
    add_publish(commands)
    return parser


def main(argv: list[str]) -> int:
    """Run the subcommand the arguments name and return its exit status."""
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
