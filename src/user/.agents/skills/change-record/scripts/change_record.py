#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Start and check a change record, the JSON document a pull request's description is written from.

Usage: uv run change_record.py init --type TYPE --component NAME --work-item ID <record.json>
       uv run change_record.py lint [--pr NUMBER] <record.json>

``init`` writes a new record with every field the author fills left empty.
It never replaces a file. Exit 0 written, 1 a file is already there, 2 the
file cannot be written or the call is wrong.

``lint`` checks a record against the record schema, then against the writing
rules a program can decide, and prints a JSON result to stdout. With ``--pr``
it also reads that pull request's changed paths through ``gh`` and checks the
record against them. Exit 0 valid, 1 invalid, 2 unreadable, unparseable,
called wrongly, or ``gh`` failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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

# The commit types whose pull request body carries a risk table of one row.
ONE_RISK_ROW_TYPES = frozenset({"docs", "chore", "build", "ci", "style", "revert"})

# The type that opens a commit subject, and the component in parentheses after it.
SUBJECT_OPENING = re.compile(r"(?P<type>[^\s(:]*)(?:\((?P<component>[^)]*)\))?")

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

# The form of a link to a comment.
URL = re.compile(r"https?://\S+")

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


def closing_id(text: str) -> str | None:
    """Return what stands in the brackets that close ``text``, or None when no brackets close it.

    A title and a commit subject close with the work item's short id in
    brackets. Space inside the brackets and after them is no part of what
    they hold.
    """
    body = text.rstrip()
    opening = body.rfind("[")
    if opening < 0 or not body.endswith("]"):
        return None
    return body[opening + 1 : -1].strip()


def _closes_the_text(text: str, match: re.Match[str]) -> bool:
    """Say whether the id at ``match`` stands alone in the brackets that close ``text``."""
    return closing_id(text) == match.group() and text[match.end():].strip() == "]"


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


def short_id(work_item_id: str) -> str:
    """Return a work item's short id, which is its full id without the project prefix.

    The prefix is everything up to and including the last hyphen, so a project
    name that holds a hyphen of its own goes with it. An id with no hyphen is
    already short.
    """
    return work_item_id.rsplit("-", 1)[-1]


def _commit_subject(record: dict[str, Any]) -> Iterator[dict[str, str]]:
    """Report each way the commit subject departs from its form.

    The form is a type, a component in parentheses, the wording, and the work
    item's short id in brackets at the end. The type and the component are the
    record's own, so the subject and the pull request cannot name different ones.
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
    one_line = isinstance(criteria, str) and criteria.strip() and len(criteria.splitlines()) == 1
    if kind == "spec" and not one_line:
        message = "a `spec` pull request's criteria is one line, saying whether they were attacked and where the record is"
        yield _finding("required-group", "/criteria", message)
    rows = len(record["risk"]["rows"])
    if kind in ONE_RISK_ROW_TYPES and rows > 1:
        message = f"a `{kind}` pull request takes one risk row, and this table has {rows}"
        yield _finding("required-group", "/risk/rows", message)
    if record["risk"]["reaches_outside_package"]:
        for name in ("reach_graph", "task_flow"):
            if not record.get("blast_radius", {}).get(name, "").strip():
                message = "the change reaches outside its package, so the record holds this diagram"
                yield _finding("required-group", f"/blast_radius/{name}", message)


def pr_changed_paths(number: int) -> list[str]:
    """Return the paths pull request ``number`` changes, read through the ``gh`` executable.

    The pull request is looked up in the repository of the working directory.
    A ``gh`` that cannot be run, or that fails, raises a ``RecordError``,
    because a check that could not read the paths has decided nothing.
    """
    command = ["gh", "pr", "diff", str(number), "--name-only"]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RecordError("gh-failed", f"cannot run `{' '.join(command)}`: {exc}") from exc
    if proc.returncode != 0:
        reason = proc.stderr.strip() or "it printed no reason"
        raise RecordError("gh-failed", f"`{' '.join(command)}` exited {proc.returncode}: {reason}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _reach(record: dict[str, Any], changed: list[str]) -> Iterator[dict[str, str]]:
    """Report a record that says the change stays inside its package when ``changed`` says otherwise.

    A path's top-level component is its first segment: the directory at the
    root that the path sits under, or the file itself when it sits at the root.
    The check is coarse on purpose, because it knows no repository's layout.
    Two packages under one top-level directory count as one component, so a
    pass here does not prove the flag.
    """
    components = sorted({path.split("/", 1)[0] for path in changed})
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

    ``content`` is a generated part as ``generated_parts`` gives it: a group
    without its own stamp field, or the list of filed rows.
    """
    written = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(written.encode("utf-8")).hexdigest()


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
    filed = [row for row in discovered["rows"] if row != NONE and row["status"] == "filed"]
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
            message = "a rejection gets a reply only when a reviewer asks; give the URL of the comment that asked for it"
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
    _commit_subject,
    _commit_body,
    _groups_by_type,
    _stale_stamps,
    _replies,
    _reply_counts,
    _unfilled,
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
    print(f"wrote {args.record}")
    return EXIT_VALID


def _filled(text: str) -> str:
    """Return ``text`` as a command-line argument's value, and refuse it when it is blank."""
    if not text.strip():
        raise argparse.ArgumentTypeError("the value is blank")
    return text


def build_parser() -> argparse.ArgumentParser:
    """Build the command line. Each subcommand names the function that runs it as ``run``."""
    parser = argparse.ArgumentParser(
        prog="change_record.py",
        description="Start or check a change record, the JSON document a pull request's description, "
        "commit message and review replies are written from.",
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
    return parser


def main(argv: list[str]) -> int:
    """Run the subcommand the arguments name and return its exit status."""
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
