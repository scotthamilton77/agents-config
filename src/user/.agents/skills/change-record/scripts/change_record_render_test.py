#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for rendering a pull request body, a commit message and review replies from a change record.

Run: uv run change_record_render_test.py

The golden files hold the exact render of every example record: the one the
skill ships, and those under ``evals/records`` that exist only for the suites.
After a record or a template changes on purpose, rewrite them all with:

    uv run change_record_render_test.py --regenerate
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
REFERENCES = SKILL / "references"
# The example the skill ships, and the examples that exist only for the suites.
# Those sit under a directory the installer never ships.
EXAMPLES = sorted(
    [*(SKILL / "examples").glob("*.json"), *(SKILL / "evals" / "records").glob("*.json")],
    key=lambda path: path.name,
)
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))

# The four feature pull requests that an example is built from.
FOUR_EXAMPLES = ["pr-838", "pr-839", "pr-843", "pr-846"]

# The golden files sit under a directory the installer never ships, because
# they exist only for this suite.
GOLDEN = SKILL / "evals" / "golden"
REGENERATE = "uv run change_record_render_test.py --regenerate"

# The two markers another tool puts around the region of a body that it owns.
OPENING = "<!-- prgroom:decisions:start -->"
CLOSING = "<!-- prgroom:decisions:end -->"
DECISIONS = (
    f"{OPENING}\n"
    "## Decisions\n"
    "<!-- d:r1:thread-7 --> - **[r1]** Keep the pin table flat. _(decided_by: author)_\n"
    "<details><summary>Earlier rounds</summary>\n"
    "\n"
    "<!-- d:r0:thread-2 --> - **[r0]** Trailing spaces and a carriage return stay.  \r\n"
    "</details>\n"
    f"{CLOSING}"
)
COMMENT_URL = "https://github.com/example/repo/pull/843#issuecomment-1"

# The most words that the part of a body above its horizontal rule shows a reader.
ONE_PAGER_WORDS = 400

# A fold, from its opening tag to its closing one, and the horizontal rule that ends the one-pager.
FOLD = re.compile(r"<details[\s>].*?</details>", re.DOTALL)
RULE = re.compile(r"^---$", re.MULTILINE)

FEAT_HEADINGS = [
    "## Heads-up",
    "## Where this fits",
    "## Risk",
    "## Changes",
    "## Discovered work",
    "## Verification",
    "## Criteria",
]

# What a commit message must never hold, as a pattern over the rendered text.
COMMIT_MARKUP = {
    "table": re.compile(r"^(?=.*\|)(?=.*-)[ \t|:-]+$", re.MULTILINE),
    "details": re.compile(r"<details", re.IGNORECASE),
    "fence": re.compile(r"^ {0,3}(```|~~~)", re.MULTILINE),
    "comment": re.compile(r"<!--"),
}

# Each kind of markup, with the commit field a case puts it in and what it does
# to that field's text. Every edit keeps the body's sentence and word counts in
# range, so the markup is the only reason left to refuse the record.
MARKUP_CASES = {
    "table": ("change", lambda text: text.rsplit(". ", 1)[0] + ".\n\n| Slot | Effort |\n| --- | --- |\n| mid | low |"),
    "details": ("why", lambda text: text.rstrip(".") + " <details><summary>All</summary>mid at low</details>."),
    "fence": ("verification", lambda text: text + "\n\n```text\nexit 0\n```"),
    "json-fence": ("verification", lambda text: text + "\n\n```json\n{\"exit\": 0}\n```"),
    "comment": ("change", lambda text: text.rstrip(".") + " <!-- mid at low -->."),
}

# Labels that open a template line which also holds a slot, each with the text
# a test puts in its place. A line holding no slot is edited whole instead.
LABEL_EDITS = {
    "pr-body.md": [
        ("    this PR: ", "    this pull request: "),
        ("Builds on: ", "Rests on: "),
        ("- Not run: ", "- Skipped: "),
        ("Terminal-clean at ", "Clean at "),
        ("Rendered from change record ", "Rendered from record "),
        ("Generated with ", "Made with "),
    ],
    "commit-message.txt": [
        ("Work item ", "Item "),
        ("Work-item: ", "Item-id: "),
        ("Co-authored-by: ", "Written-with: "),
    ],
    "review-reply.txt": [
        ("Outcome: ", "Result: "),
        ("Change: ", "Difference: "),
        ("Verification: ", "Check: "),
    ],
}


def run(*argv: Any, script: Path = SCRIPT) -> subprocess.CompletedProcess[bytes]:
    """Run the script in a child process and return what it wrote, as bytes."""
    return subprocess.run(
        [sys.executable, str(script), *map(str, argv)], capture_output=True, check=False
    )


def write(record: Any, tmp_path: Path) -> Path:
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def render(record: Any, tmp_path: Path, artifact: str, *flags: Any, script: Path = SCRIPT) -> str:
    """Render one artifact from ``record`` and return it, failing the test when render refuses."""
    proc = run("render", artifact, write(record, tmp_path), *flags, script=script)
    assert proc.returncode == 0, proc.stderr.decode("utf-8")
    assert proc.stderr == b""
    return proc.stdout.decode("utf-8")


def refusal(record: Any, tmp_path: Path, artifact: str, *flags: Any) -> list[dict[str, str]]:
    """Assert that render refuses and writes nothing, and return the errors it reported.

    The output file already exists, so a refusal that truncated or replaced it
    would show.
    """
    output = tmp_path / "artifact.out"
    output.write_text("untouched", encoding="utf-8")
    proc = run("render", artifact, write(record, tmp_path), "--output", output, *flags)
    assert proc.returncode == 1, proc.stderr.decode("utf-8")
    assert proc.stdout == b""
    assert output.read_text(encoding="utf-8") == "untouched"
    result = json.loads(proc.stderr)
    assert result["valid"] is False
    return result["errors"]


def example() -> dict[str, Any]:
    return copy.deepcopy(EXAMPLE)


def valid(record: dict[str, Any]) -> dict[str, Any]:
    """Stamp the generated parts a case reshaped, and fail the case unless lint accepts the record.

    A case that expects a render builds a record ``render`` would take, so no
    case pins the form of something that can never be rendered.
    """
    change_record.stamp_generated(record)
    assert change_record.lint_record(record) == []
    return record


def constructs(text: str) -> list[str]:
    """Name each construct ``text`` holds outside a code span, read with the readers the lint uses."""
    plain = change_record.outside_code(text)
    found = [name for name, pattern in change_record.MACHINE_CONTENT.items() if pattern.search(plain)]
    if COMMIT_MARKUP["table"].search(text):
        found.append("a table")
    if list(change_record.fence_openings(text)):
        found.append("a fenced block")
    return found


def read_trailers(message: str) -> list[list[str]]:
    """Return each trailer git reads from ``message``, as a key and a value.

    Git ends a line at a line feed alone, so its output is split on that
    character and on nothing else a text reader would also take for a line end.
    """
    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"], input=message.encode("utf-8"), capture_output=True, check=True
    )
    return [line.split(": ", 1) for line in parsed.stdout.decode("utf-8").split("\n") if line]


def three_trailers(record: dict[str, Any]) -> list[list[str]]:
    """Return the three trailers a record's commit message must end with, and no other."""
    by = record["commit"]["attribution"]
    return [
        ["Work-item", record["work_item"]["id"]],
        ["Co-authored-by", by["co_author"]],
        [by["session_key"], by["session_url"]],
    ]


def put(record: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Set the field at ``path``, written as lint writes a path, and return the record."""
    *parents, last = path.strip("/").split("/")
    node: Any = record
    for name in parents:
        node = node[int(name)] if isinstance(node, list) else node[name]
    node[int(last) if isinstance(node, list) else last] = value
    return record


def at(record: dict[str, Any], path: str) -> Any:
    """Return what the record holds at ``path``, written as lint writes a path."""
    node: Any = record
    for name in path.strip("/").split("/"):
        node = node[int(name)] if isinstance(node, list) else node[name]
    return node


def retyped(record: dict[str, Any], kind: str) -> dict[str, Any]:
    """Give the example record another commit type.

    The type must be as long as the example's own, so the subject stays within its limit.
    """
    assert len(kind) == len(record["pr"]["type"])
    record["pr"]["type"] = kind
    record["pr"]["title"] = record["pr"]["title"].replace("feat(", f"{kind}(", 1)
    record["commit"]["subject"] = record["commit"]["subject"].replace("feat(", f"{kind}(", 1)
    return record


def reply_flags(entry: dict[str, Any]) -> list[str]:
    """Return the flags that select exactly this reply entry."""
    flags = ["--finding", entry["finding_id"]]
    if "claim_id" in entry:
        flags += ["--claim", entry["claim_id"]]
    if "artifact_class" in entry:
        flags += ["--artifact-class", entry["artifact_class"]]
    return flags


def existing_body(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "existing-body.md"
    path.write_bytes(text.encode("utf-8"))
    return path


def artifacts(record_path: Path) -> dict[str, bytes]:
    """Render every artifact of the record at ``record_path``, keyed by its golden file's suffix."""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    rendered = {}
    for suffix, argv in {"pr-body": ["body"], "commit-message": ["commit"]}.items():
        proc = run("render", *argv, record_path)
        assert proc.returncode == 0, proc.stderr.decode("utf-8")
        rendered[suffix] = proc.stdout
    replies = []
    for entry in record.get("replies", []):
        proc = run("render", "reply", record_path, *reply_flags(entry))
        assert proc.returncode == 0, proc.stderr.decode("utf-8")
        replies.append(proc.stdout)
    rendered["review-replies"] = b"\n".join(replies)
    return rendered


def visible_words(body: str) -> list[str]:
    """Return the words a reader sees in a body's one-pager without opening a fold.

    The one-pager is the text above the first horizontal rule. A fold is left
    out whole, its label included. A word is a run of characters with no space
    in it that holds a letter or a digit. A table's pipes, a heading's marks
    and a list's bullets hold neither, so they are not words.
    """
    one_pager = RULE.split(FOLD.sub("", body), maxsplit=1)[0]
    return [token for token in one_pager.split() if re.search(r"[^\W_]", token)]


def assert_commit_message_form(record: dict[str, Any], message: str, labelled: bool = True) -> None:
    """Assert that ``message`` opens with the record's work item and ends with exactly the three trailers.

    ``labelled`` says whether the message carries its three labelled sections.
    The trailers are read back with git, which is what reads them after a merge.
    """
    lines = message.split("\n")
    item, by = record["work_item"], record["commit"]["attribution"]
    assert lines[0] == record["commit"]["subject"]
    assert lines[1] == ""
    assert lines[2] == f"Work item {item['id']}, {item['gloss']}."

    labels = [line for line in lines if line in ("Why", "Change", "Verification")]
    assert labels == (["Why", "Change", "Verification"] if labelled else [])

    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=message, capture_output=True, text=True, check=True,
    )
    trailers = [line.split(": ", 1) for line in parsed.stdout.splitlines()]
    assert [key for key, _ in trailers] == ["Work-item", "Co-authored-by", by["session_key"]]
    assert dict(trailers) == {
        "Work-item": item["id"],
        "Co-authored-by": by["co_author"],
        by["session_key"]: by["session_url"],
    }


def golden_path(record_path: Path, suffix: str) -> Path:
    return GOLDEN / f"{record_path.stem}.{suffix}.txt"


def regenerate() -> int:
    """Rewrite every golden file from the example records and return an exit status."""
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for stale in GOLDEN.glob("*.txt"):
        stale.unlink()
    for record_path in EXAMPLES:
        for suffix, rendered in artifacts(record_path).items():
            golden_path(record_path, suffix).write_bytes(rendered)
            print(f"wrote {golden_path(record_path, suffix).relative_to(SKILL)}")
    return 0


def first_reply(record: dict[str, Any], outcome: str) -> dict[str, Any]:
    """Return a reply entry of ``record`` with ``outcome``, making one when the record has none."""
    for entry in record["replies"]:
        if entry["outcome"] == outcome:
            return entry
    entry = record["replies"][0]
    entry["outcome"] = outcome
    if outcome == "Rejected":
        entry["request_url"] = "https://github.com/example/repo/pull/843#discussion_r1"
    return entry


def commit_fixture(kind: str) -> dict[str, Any]:
    """Return the example record, changed into one of the three commit message fixtures."""
    record = example()
    if kind == "another-tool":
        record["commit"]["attribution"] = {
            "tool": "Codex CLI",
            "co_author": "GPT 6.1 Sol <noreply@openai.com>",
            "session_key": "Codex-Session",
            "session_url": "https://chatgpt.com/codex/session/0199",
        }
    if kind == "trivial":
        for section in ("why", "change", "verification"):
            del record["commit"][section]
        record["commit"]["trivial"] = "A one-word spelling fix needs no account."
    return record


class TestCrL17TemplatesDriveTheRender:
    def edit(self, text: str, name: str) -> str:
        """Change every heading, column title, fold label and line label a template holds.

        A line with no slot is a heading, a table header or a fold line, and it
        gains a suffix. The same edit over a render moves it the way the edited
        template must.
        """
        template = (REFERENCES / name).read_text(encoding="utf-8")
        whole = {
            line for line in template.splitlines()
            if "${" not in line and not line.startswith("{{") and re.search("[A-Za-z]", line)
        }
        lines = [f"{line} (edited)" if line in whole else line for line in text.split("\n")]
        text = "\n".join(lines)
        for old, new in LABEL_EDITS[name]:
            text = re.sub(rf"(?m)^{re.escape(old)}", new, text)
        return text

    @pytest.mark.parametrize(("name", "artifact"), [
        ("pr-body.md", "body"),
        ("commit-message.txt", "commit"),
        ("review-reply.txt", "reply"),
    ])
    def test_cr_l17_an_edited_template_changes_its_artifact_the_same_way(
        self, name: str, artifact: str, tmp_path: Path
    ):
        record = example()
        flags: list[Any] = []
        if artifact == "body":
            # This block holds no line a template also holds, so the edit below leaves it alone.
            block = f"{OPENING}\n## Decisions\n- one\n{CLOSING}"
            flags = ["--existing-body", existing_body(tmp_path, block), "--comment-url", COMMENT_URL]
        if artifact == "reply":
            flags = reply_flags(first_reply(record, "Fixed"))
        shipped = render(record, tmp_path, artifact, *flags)

        skill = tmp_path / "skill"
        shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "evals"))
        template = skill / "references" / name
        edited = self.edit(template.read_text(encoding="utf-8"), name)
        assert edited != template.read_text(encoding="utf-8")
        template.write_text(edited, encoding="utf-8")

        followed = render(record, tmp_path, artifact, *flags, script=skill / "scripts" / "change_record.py")
        assert followed != shipped
        assert followed == self.edit(shipped, name)

    def test_cr_l17_the_edit_reaches_every_heading_and_label_of_each_template(self):
        # The case above proves the render follows whatever the edit changes, so
        # this one proves the edit leaves no heading or label of a template alone.
        for name in LABEL_EDITS:
            template = (REFERENCES / name).read_text(encoding="utf-8")
            edited = self.edit(template, name).splitlines()
            for before, after in zip(template.splitlines(), edited, strict=True):
                opening = before.split("${")[0]
                if not before.startswith("{{") and re.search("[A-Za-z]", opening):
                    assert before != after, f"{name}: {before!r} is not edited"


class TestCrR1Body:
    @pytest.mark.parametrize("record_path", EXAMPLES, ids=lambda path: path.stem)
    def test_cr_r1_each_example_renders_byte_identical_to_its_golden_files(self, record_path: Path):
        for suffix, rendered in artifacts(record_path).items():
            golden = golden_path(record_path, suffix)
            assert golden.is_file(), f"{golden.name} is missing; run: {REGENERATE}"
            assert rendered == golden.read_bytes(), f"{golden.name} is stale; run: {REGENERATE}"

    def test_the_golden_directory_holds_one_file_per_example_and_artifact(self):
        expected = {
            golden_path(record_path, suffix).name
            for record_path in EXAMPLES
            for suffix in ("pr-body", "commit-message", "review-replies")
        }
        assert {path.name for path in GOLDEN.iterdir()} == expected, f"run: {REGENERATE}"

    def test_cr_r1_the_four_feat_examples_are_all_among_those_rendered(self):
        kinds = {path.stem: json.loads(path.read_text(encoding="utf-8"))["pr"]["type"] for path in EXAMPLES}
        assert {name: kinds.get(name) for name in FOUR_EXAMPLES} == dict.fromkeys(FOUR_EXAMPLES, "feat")

    @pytest.mark.parametrize("record_path", EXAMPLES, ids=lambda path: path.stem)
    def test_cr_r1_a_feat_body_carries_the_seven_headings_in_order(self, record_path: Path):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record["pr"]["type"] != "feat":
            pytest.skip("the heading set of another commit type is not this case's")
        body = golden_path(record_path, "pr-body").read_text(encoding="utf-8")
        assert [line for line in body.splitlines() if line.startswith("## ")] == FEAT_HEADINGS

    @pytest.mark.parametrize("record_path", EXAMPLES, ids=lambda path: path.stem)
    def test_cr_r1_a_feat_body_shows_at_most_400_words_above_its_rule(self, record_path: Path):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record["pr"]["type"] != "feat":
            pytest.skip("the bound on another commit type's body is not this case's")
        body = golden_path(record_path, "pr-body").read_text(encoding="utf-8")
        assert RULE.search(body), "the body has no horizontal rule to end its one-pager"
        shown = len(visible_words(body))
        assert shown <= ONE_PAGER_WORDS, f"{record_path.stem} shows {shown} words above its rule"

    def test_the_word_count_is_of_what_a_reader_sees_without_opening_a_fold(self):
        body = (
            "The gate halts.\n"
            "\n"
            "## Risk\n"
            "| What fails | Who |\n"
            "| --- | --- |\n"
            "| A pin reads low\\|high. | Round 12 |\n"
            "<details><summary>Blast radius</summary>\n"
            "\n"
            "Every word here waits behind the fold.\n"
            "</details>\n"
            "- **Pins.** One more (#7).\n"
            "\n"
            "---\n"
            "\n"
            "## Verification\n"
            "Nothing below the rule is counted.\n"
        )
        # The fold goes whole, label and all. The cells of the table stay, and its pipes are no words.
        assert visible_words(body) == [
            "The", "gate", "halts.",
            "Risk",
            "What", "fails", "Who",
            "A", "pin", "reads", "low\\|high.", "Round", "12",
            "**Pins.**", "One", "more", "(#7).",
        ]
        # A body with no fold and no rule is counted whole.
        assert visible_words("- One.\n- Two | three.\n") == ["One.", "Two", "three."]

    def test_the_body_holds_every_static_line_of_its_template_in_order(self, tmp_path: Path):
        body = render(
            example(), tmp_path, "body",
            "--existing-body", existing_body(tmp_path, DECISIONS), "--comment-url", COMMENT_URL,
        )
        template = (REFERENCES / "pr-body.md").read_text(encoding="utf-8")
        position = 0
        for line in template.splitlines():
            if "${" in line or line.startswith("{{") or not line:
                continue
            found = body.find(f"{line}\n", position)
            assert found >= 0, f"{line!r} is missing or out of order"
            position = found + len(line)
        assert "{{" not in body
        assert "${" not in body


class TestBodyDetails:
    def findings_rows(self, body: str) -> list[list[str]]:
        """Return the cells of each row of the findings table, in the order the body holds them."""
        fold = body.split("<details><summary>Findings by round</summary>")[1].split("</details>")[0]
        rows = [line[2:-2].split(" | ") for line in fold.splitlines() if line.startswith("| ")]
        return rows[2:]

    def test_a_missing_optional_group_takes_its_heading_and_fold_with_it(self):
        # A docs record carries no criteria and one risk row, so lint accepts it without them.
        record = retyped(example(), "docs")
        for group in ("where_this_fits", "blast_radius", "design_notes", "campaign", "criteria"):
            del record[group]
        del record["risk"]["rows"][1:]
        record["risk"]["reaches_outside_package"] = False
        body = change_record.render_body(valid(record))
        assert [line for line in body.splitlines() if line.startswith("#")] == FEAT_HEADINGS[:-1]
        for gone in ("Scope of the owning item", "Blast radius", "Design notes", "Builds on", "mermaid"):
            assert gone not in body
        assert f"## Where this fits\n    this PR: {record['work_item']['slice']}\n\n## Risk\n" in body
        assert "\n\n\n" not in body

    def test_one_blast_radius_diagram_renders_alone(self):
        record = example()
        del record["blast_radius"]["task_flow"]
        # A record needs both diagrams only when the change reaches outside its package.
        record["risk"]["reaches_outside_package"] = False
        body = change_record.render_body(valid(record))
        assert body.count("```mermaid") == 1
        assert "<details><summary>Blast radius</summary>" in body

    @pytest.mark.parametrize(("path", "empty"), [
        ("/blast_radius", {"reach_graph": "", "task_flow": ""}),
        ("/blast_radius", {"reach_graph": " \n", "task_flow": "\t"}),
        ("/blast_radius/task_flow", "  \n"),
        ("/design_notes", " \n "),
        ("/design_notes", ""),
    ], ids=["both-diagrams-empty", "both-diagrams-blank", "one-diagram-blank", "notes-blank", "notes-empty"])
    def test_a_group_whose_every_value_is_empty_renders_as_an_absent_group_does(self, path: str, empty: Any):
        record = example()
        # A record needs its diagrams only when the change reaches outside its package.
        record["risk"]["reaches_outside_package"] = False
        with_empty = put(copy.deepcopy(record), path, empty)
        *parents, last = path.strip("/").split("/")
        del (at(record, "/".join(parents)) if parents else record)[last]
        assert change_record.render_body(valid(with_empty)) == change_record.render_body(valid(record))

    @pytest.mark.parametrize(("path", "fold"), [
        ("/where_this_fits/scope", "Scope of the owning item"),
        ("/campaign/findings", "Findings by round"),
    ])
    def test_a_fold_over_an_empty_list_is_left_out(self, path: str, fold: str):
        record = example()
        assert f"<summary>{fold}</summary>" in change_record.render_body(record)
        body = change_record.render_body(valid(put(record, path, [])))
        assert fold not in body
        assert "<details>\n\n</details>" not in body.replace("<summary></summary>", "")

    @pytest.mark.parametrize(("clean", "findings"), [(True, True), (False, True), (True, False), (False, False)])
    def test_a_blank_line_follows_the_reviewer_table_whatever_comes_after_it(self, clean: bool, findings: bool):
        record = example()
        if not clean:
            record["campaign"]["terminal_sha"] = ""
        if not findings:
            record["campaign"]["findings"] = []
        body = change_record.render_body(valid(record))
        last = record["campaign"]["reviewers"][-1]
        after = body.split(f"| {last['reviewer']} | {last['rounds']} |", 1)[1].split("\n", 1)[1]
        sentence = f"Terminal-clean at {record['campaign']['terminal_sha']}. Approval is a machine attestation of that head.\n"
        fold = "<details><summary>Findings by round</summary>\n"
        expected = "\n" + (sentence if clean else "") + (fold if findings else "\n## Criteria\n" if clean else "## Criteria\n")
        # One blank line parts the table from what follows, and no second one follows it.
        assert after.startswith(expected), after[:160]
        assert "\n\n\n" not in body

    def test_a_campaign_with_no_clean_round_and_no_finding_renders_its_table_alone(self):
        record = example()
        record["campaign"]["terminal_sha"] = ""
        record["campaign"]["findings"] = []
        body = change_record.render_body(valid(record))
        assert "### Review campaign" in body
        assert "Terminal-clean" not in body
        assert "Findings by round" not in body
        record["campaign"]["reviewers"] = []
        assert "### Review campaign" not in change_record.render_body(valid(record))

    def test_a_none_entry_renders_one_row_or_one_bullet_reading_none(self):
        record = example()
        record["heads_up"] = ["None."]
        record["discovered"]["rows"] = ["None."]
        record["verification"]["not_run"] = ["None."]
        body = change_record.render_body(valid(record))
        assert "## Heads-up\n- None.\n\n" in body
        assert "| --- | --- | --- | --- |\n| None. |  |  |  |\n\n---\n" in body
        assert "- Not run: None.\n" in body

    def test_a_one_line_criteria_fills_the_first_cell_of_one_row(self):
        # A spec record holds its criteria as one line of text, where the template has a table row.
        record = retyped(example(), "spec")
        record["criteria"] = "Attacked twice, and the attack record sits beside the spec."
        body = change_record.render_body(valid(record))
        assert f"| --- | --- | --- |\n| {record['criteria']} |  |  |\n\n<details>" in body

    def test_a_row_in_flight_names_its_pull_request_beside_the_status(self):
        record = example()
        record["where_this_fits"]["scope"] = [
            {"slice": "A", "covers": "the pins", "status": "this PR"},
            {"slice": "B", "covers": "the gate", "status": "in flight", "pr": 774},
        ]
        record["discovered"]["rows"] = [
            {"status": "filed", "item": "example-1.2", "what": "A follow-on.", "reason": "It is larger."},
            {"status": "not filed", "what": "A gap.", "reason": "Nobody asks for it."},
            {"status": "in flight", "pr": 777, "what": "A sentence waits.", "reason": "The file is capped."},
        ]
        body = change_record.render_body(valid(record))
        assert "| A | the pins | this PR |\n| B | the gate | in flight (#774) |\n</details>" in body
        assert (
            "| example-1.2 | filed | A follow-on. | It is larger. |\n"
            "|  | not filed | A gap. | Nobody asks for it. |\n"
            "|  | in flight (#777) | A sentence waits. | The file is capped. |\n"
        ) in body

    def test_references_to_pull_requests_read_inline_and_an_empty_list_reads_none(self):
        record = example()
        record["where_this_fits"]["builds_on"] = []
        record["where_this_fits"]["concurrent"] = [
            {"pr": 777, "gloss": "a prose fix"}, {"pr": 774, "gloss": "the next slice"},
        ]
        body = change_record.render_body(valid(record))
        assert "\nBuilds on: none. Concurrent: #777 (a prose fix), #774 (the next slice).\n" in body

    @pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"], ids=["LF", "CR", "CRLF"])
    def test_a_table_cell_escapes_a_pipe_and_keeps_a_line_break_inside_its_row(self, ending: str):
        record = example()
        record["risk"]["rows"][0]["failure"] = f"A pin reads low|high.{ending}Nobody notices."
        record["blast_radius"]["reach_graph"] = "graph LR\n  A -->|writes| B"
        body = change_record.render_body(valid(record))
        assert "\n| A pin reads low\\|high.<br>Nobody notices. | " in body
        assert "\r" not in body
        # A diagram is not a table row, so its edge labels keep their pipes and its lines.
        assert "```mermaid\ngraph LR\n  A -->|writes| B\n```" in body

    @pytest.mark.parametrize("ending", ["\n", "\r", "\r\n", "\n\n", " \n  "], ids=["LF", "CR", "CRLF", "blank", "spaced"])
    def test_prose_the_template_sets_on_one_line_reads_a_line_break_as_one_space(self, ending: str):
        record = example()
        first, rest = record["summary"].split(". ", 1)
        record["summary"] = f"{first}.{ending}{rest}"
        record["heads_up"][0] = f"The gates ran with the system bash first.{ending}Another shell hangs one test."
        record["changes"][0]["text"] = f"One pin per slot.{ending}No pin names a model."
        record["verification"]["not_run"] = [f"The browser run,{ending}because no page changed."]
        body = change_record.render_body(valid(record))
        assert body.startswith(f"{EXAMPLE['summary']}\n\n## Heads-up\n")
        assert "\n- The gates ran with the system bash first. Another shell hangs one test.\n" in body
        assert f"\n- **{record['changes'][0]['topic']}.** One pin per slot. No pin names a model.\n" in body
        assert "\n- Not run: The browser run, because no page changed.\n" in body
        assert "\r" not in body

    def test_a_block_keeps_its_own_lines(self):
        record = example()
        record["design_notes"] = "The first reason.\n\nThe second reason.\nIts next line."
        body = change_record.render_body(valid(record))
        assert "</summary>\n\nThe first reason.\n\nThe second reason.\nIts next line.\n</details>" in body

    def test_the_pointer_line_appears_only_with_a_comment_url(self):
        record = example()
        record["record"]["revision"] = 3
        assert "Rendered from change record" not in change_record.render_body(valid(record))
        body = change_record.render_body(record, comment_url=COMMENT_URL)
        tool = record["commit"]["attribution"]["tool"]
        assert f"\nRendered from change record {COMMENT_URL}, revision 3.\nGenerated with {tool} " in body

    def test_the_findings_table_reads_each_disposition_as_an_outcome_word(self):
        record = example()
        dispositions = ["fixed", "rebutted", "advisory-deferred", "transferred", None, "fixed", "fixed"]
        findings = [
            {"claim_id": "claim-a", "artifact_class": "prose", "round": 1, "id": f"lens.r1.f{n}", "claim": "x"}
            for n in range(len(dispositions))
        ]
        for finding, disposition in zip(findings, dispositions, strict=True):
            if disposition:
                finding["disposition"] = disposition
        # The last finding shares its id with the one before it and sits under another claim.
        findings[6]["id"] = findings[5]["id"]
        findings[6]["claim_id"] = "claim-b"
        record["campaign"]["findings"] = findings

        def reply(finding: dict[str, Any], outcome: str) -> dict[str, Any]:
            """Return a reply to ``finding`` with the wording of a reply the example already holds."""
            named = {key: finding[key] for key in ("claim_id", "artifact_class")}
            return {**EXAMPLE["replies"][0], **named, "finding_id": finding["id"], "outcome": outcome}

        # Each fixed finding takes one reply. The author calls one of the three superseded.
        record["replies"] = [
            reply(findings[0], "Fixed"), reply(findings[5], "Superseded"), reply(findings[6], "Fixed"),
        ]
        shown = [row[3] for row in self.findings_rows(change_record.render_body(valid(record)))]
        # Only the author's reply calls a finding superseded, and only the finding it names.
        assert shown == ["Fixed", "Rejected", "Deferred", "Deferred", "", "Superseded", "Fixed"]

    def test_the_body_carries_the_commit_message_exactly_as_the_merge_will_use_it(self):
        message = change_record.render_commit_message(example())
        assert f"\n```text\n{message}```\n</details>\n" in change_record.render_body(example())

    def test_a_render_leaves_the_record_it_was_given_unchanged(self):
        record = example()
        change_record.render_body(record, DECISIONS, COMMENT_URL)
        change_record.render_commit_message(record)
        change_record.render_reply(record, record["replies"][0])
        assert record == EXAMPLE

    def test_output_goes_to_the_named_file_and_not_to_stdout(self, tmp_path: Path):
        output = tmp_path / "body.md"
        assert render(example(), tmp_path, "body", "--output", output) == ""
        assert output.read_bytes() == run("render", "body", write(example(), tmp_path)).stdout


class TestCrR2Decisions:
    def test_cr_r2_a_decisions_block_is_carried_byte_for_byte_at_the_templates_position(
        self, tmp_path: Path
    ):
        old = f"An older summary.\r\n\r\n{DECISIONS}\n\nGenerated with something else\n"
        body = render(example(), tmp_path, "body", "--existing-body", existing_body(tmp_path, old))
        assert body.count(DECISIONS) == 1
        assert "<details><summary>Earlier rounds</summary>" in DECISIONS
        assert "<!-- d:r1:thread-7 -->" in DECISIONS
        # The template puts the block between the commit message fold and the closing line.
        without = render(example(), tmp_path, "body")
        assert body == without.replace("</details>\n\nGenerated with", f"</details>\n\n{DECISIONS}\n\nGenerated with")
        assert "An older summary" not in body
        # A body rendered once is the existing body of the next render, and the block survives that too.
        assert render(example(), tmp_path, "body", "--existing-body", existing_body(tmp_path, body)) == body

    @pytest.mark.parametrize("old", [None, "A body nobody but the author wrote.\n\n## Decisions\n- by hand\n"])
    def test_cr_r2_a_body_with_no_decisions_block_renders_no_decisions_heading(
        self, old: str | None, tmp_path: Path
    ):
        flags = [] if old is None else ["--existing-body", existing_body(tmp_path, old)]
        body = render(example(), tmp_path, "body", *flags)
        assert "Decisions" not in body
        assert "prgroom" not in body
        assert body == render(example(), tmp_path, "body")


class TestCrR8Sentinels:
    @pytest.mark.parametrize(("old", "named"), [
        (f"Summary.\n\n## Decisions\n- one\n{CLOSING}\n", [OPENING]),
        (f"Summary.\n\n{OPENING}\n## Decisions\n- one\n", [CLOSING]),
        (f"Summary.\n\n{CLOSING}\n## Decisions\n- one\n{OPENING}\n", [CLOSING, OPENING]),
    ], ids=["opening-missing", "closing-missing", "closing-before-opening"])
    def test_cr_r8_a_body_with_a_broken_decisions_block_is_refused_naming_the_sentinel(
        self, old: str, named: list[str], tmp_path: Path
    ):
        errors = refusal(example(), tmp_path, "body", "--existing-body", existing_body(tmp_path, old))
        assert [error["code"] for error in errors] == ["decisions-block"]
        for sentinel in named:
            assert sentinel in errors[0]["message"]

    @pytest.mark.parametrize("old", [
        f"{OPENING}\n- one\n{CLOSING}\n{OPENING}\n- two\n{CLOSING}\n",
        f"{OPENING}\n{OPENING}\n- one\n{CLOSING}\n",
    ], ids=["two-blocks", "opening-twice"])
    def test_a_body_holding_a_sentinel_twice_is_refused(self, old: str, tmp_path: Path):
        errors = refusal(example(), tmp_path, "body", "--existing-body", existing_body(tmp_path, old))
        assert OPENING in errors[0]["message"]


class TestCrR3CommitMessage:
    @pytest.mark.parametrize(("kind", "session_key"), [
        ("claude-session", "Claude-Session"),
        ("another-tool", "Codex-Session"),
        ("trivial", "Claude-Session"),
    ])
    def test_cr_r3_the_message_opens_with_the_work_item_and_ends_with_exactly_three_trailers(
        self, kind: str, session_key: str, tmp_path: Path
    ):
        record = commit_fixture(kind)
        assert record["commit"]["attribution"]["session_key"] == session_key
        assert_commit_message_form(record, render(record, tmp_path, "commit"), labelled=kind != "trivial")

    @pytest.mark.parametrize("record_path", EXAMPLES, ids=lambda path: path.stem)
    def test_cr_r3_each_example_renders_a_message_with_its_work_item_and_exactly_three_trailers(
        self, record_path: Path
    ):
        proc = run("render", "commit", record_path)
        assert proc.returncode == 0, proc.stderr.decode("utf-8")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert_commit_message_form(record, proc.stdout.decode("utf-8"))

    def test_cr_r3_a_trivial_message_is_the_subject_the_work_item_line_and_the_trailers(
        self, tmp_path: Path
    ):
        record = commit_fixture("trivial")
        item, by = record["work_item"], record["commit"]["attribution"]
        assert render(record, tmp_path, "commit") == (
            f"{record['commit']['subject']}\n"
            "\n"
            f"Work item {item['id']}, {item['gloss']}.\n"
            "\n"
            f"Work-item: {item['id']}\n"
            f"Co-authored-by: {by['co_author']}\n"
            f"{by['session_key']}: {by['session_url']}\n"
        )

    @pytest.mark.parametrize("path", [
        "/pr/title",
        "/work_item/id",
        "/work_item/gloss",
        "/work_item/slice",
        "/commit/attribution/tool",
        "/commit/attribution/co_author",
        "/commit/attribution/session_key",
        "/commit/attribution/session_url",
    ])
    @pytest.mark.parametrize("tail", ["\nReviewed-by: A reader", "\nSee session.", "\rX-injected: yes", "\r\n"])
    def test_cr_r3_lint_refuses_a_line_break_in_a_value_set_on_one_line_naming_the_field(
        self, path: str, tail: str, tmp_path: Path
    ):
        record = example()
        put(record, path, at(record, path) + tail)
        found = [(error["code"], error["path"]) for error in refusal(record, tmp_path, "commit")]
        assert ("line-break", path) in found, found

    @pytest.mark.parametrize("ending", ["\n", "\r", "\r\n"], ids=["LF", "CR", "CRLF"])
    def test_cr_r3_a_line_break_in_the_subject_is_reported_once_by_the_rule_on_its_form(
        self, ending: str, tmp_path: Path
    ):
        # The subject has a rule of its own for its whole one-line form, so the
        # rule on one-line fields leaves the subject to it and one fault draws one finding.
        record = example()
        record["commit"]["subject"] = record["commit"]["subject"].replace(" and ", f"{ending}and ", 1)
        assert ending in record["commit"]["subject"]
        errors = refusal(record, tmp_path, "commit")
        about_the_break = [error for error in errors if "line break" in error["message"]]
        assert [(error["code"], error["path"]) for error in about_the_break] == [("commit-subject", "/commit/subject")]
        # The carriage return and line feed together make the subject one character too long as well.
        assert {error["code"] for error in errors} == {"commit-subject"}

    @pytest.mark.parametrize("key", ["Claude Session", "Claude_Session", "Claude.Session", " Claude-Session", "Claude-Session ", "Sesión", "a:b"])
    def test_cr_r3_lint_refuses_a_session_key_git_would_not_read_as_a_trailer_key(self, key: str, tmp_path: Path):
        record = example()
        record["commit"]["attribution"]["session_key"] = key
        # Git reads none of the three trailers once one line of the last paragraph is not a trailer.
        assert read_trailers(change_record.render_commit_message(record)) != three_trailers(record)
        found = [(error["code"], error["path"]) for error in refusal(record, tmp_path, "commit")]
        assert found == [("session-key", "/commit/attribution/session_key")]

    @pytest.mark.parametrize("edit", [
        lambda record: None,
        lambda record: record["commit"]["attribution"].update(session_key="X-1", session_url="urn:session:1?a=b#c"),
        lambda record: record["work_item"].update(gloss="reviewer settings: effort and tools, as a cost control"),
        lambda record: record["commit"].update(verification=record["commit"]["verification"] + " Signed-off-by: nobody."),
        lambda record: record["commit"].update(why=record["commit"]["why"].replace(". ", ".\n", 1)),
        lambda record: record["commit"].update(change=record["commit"]["change"].replace(". ", ". ---- ", 1)),
    ], ids=["as-shipped", "odd-key-and-url", "gloss-with-a-colon", "trailer-shaped-prose", "line-break-in-why", "four-hyphens"])
    def test_cr_r3_a_record_lint_accepts_renders_exactly_its_three_trailers(self, edit: Any):
        record = example()
        edit(record)
        assert read_trailers(change_record.render_commit_message(valid(record))) == three_trailers(record)

    @pytest.mark.parametrize("pad", range(1, 15))
    def test_cr_r3_three_hyphens_never_open_a_line_and_end_the_message_for_git(self, pad: int):
        # Git reads a line that opens with three hyphens as the end of the message.
        # The hyphens slide across the wrap column, and every record that renders keeps its trailers.
        record = example()
        rest = record["commit"]["change"].split(". ", 1)[1]
        opening = "The panel's configuration holds effort and tools for every slot"
        record["commit"]["change"] = f"{opening} {'x' * pad} --- and so on. {rest}"
        assert len(opening) == 63
        assert change_record.lint_record(record) == []
        try:
            message = change_record.render_commit_message(record)
        except change_record.Refusal as refused:
            assert [(error["code"], error["path"]) for error in refused.findings] == [("commit-markup", "/commit/change")]
        else:
            assert read_trailers(message) == three_trailers(record)
            assert not re.search(r"(?m)^---(\s|$)", message)

    def test_cr_r3_a_section_that_opens_with_three_hyphens_is_refused(self, tmp_path: Path):
        record = example()
        record["commit"]["why"] = "--- " + record["commit"]["why"]
        found = [(error["code"], error["path"]) for error in refusal(record, tmp_path, "commit")]
        assert found == [("commit-markup", "/commit/why")]

    def test_each_section_follows_its_label_and_wraps_at_72_columns(self):
        record = example()
        record["work_item"]["gloss"] = "a gloss that runs well past the seventy-second column of the line it sits on"
        record["commit"]["attribution"]["session_url"] = "https://example.com/" + "s" * 70
        message = change_record.render_commit_message(valid(record))
        commit = record["commit"]
        assert len(commit["subject"]) > 72
        for label, section in (("Why", "why"), ("Change", "change"), ("Verification", "verification")):
            assert len(commit[section]) > 72
            wrapped = textwrap.fill(commit[section], 72, break_long_words=False, break_on_hyphens=False)
            assert f"\n\n{label}\n{wrapped}\n\n" in message
        # Only the three sections wrap. The subject, the work item line and a trailer never do.
        assert [line for line in message.split("\n") if len(line) > 72] == [
            commit["subject"],
            f"Work item {record['work_item']['id']}, {record['work_item']['gloss']}.",
            f"{commit['attribution']['session_key']}: {commit['attribution']['session_url']}",
        ]


class TestCrR4CommitMarkup:
    @pytest.mark.parametrize("record_path", EXAMPLES, ids=lambda path: path.stem)
    def test_cr_r4_no_example_renders_a_commit_message_holding_markup(self, record_path: Path):
        proc = run("render", "commit", record_path)
        assert proc.returncode == 0, proc.stderr.decode("utf-8")
        message = proc.stdout.decode("utf-8")
        assert message
        assert constructs(message) == []

    @pytest.mark.parametrize("kind", sorted(MARKUP_CASES))
    def test_cr_r4_a_commit_field_carrying_markup_is_refused_naming_the_field(
        self, kind: str, tmp_path: Path
    ):
        field, edit = MARKUP_CASES[kind]
        record = example()
        record["commit"][field] = edit(record["commit"][field])
        assert COMMIT_MARKUP[kind.removeprefix("json-")].search(record["commit"][field])
        # The body carries the commit message in a fold, so it is refused too.
        for artifact in ("commit", "body"):
            errors = refusal(record, tmp_path, artifact)
            # The lint refuses some kinds before render's own check runs. Either
            # way the markup is the one fault, and the refusal names its field.
            assert {error["path"] for error in errors} == {f"/commit/{field}"}, errors
            assert {error["code"] for error in errors} <= {"commit-markup", "machine-content"}, errors

    @pytest.mark.parametrize("kind", sorted(MARKUP_CASES))
    def test_cr_r4_the_render_itself_refuses_each_kind_whether_or_not_lint_would(self, kind: str):
        field, edit = MARKUP_CASES[kind]
        record = example()
        record["commit"][field] = edit(record["commit"][field])
        # Lint knows a fold, a comment and a fenced JSON block. A table and any other fence are render's alone.
        assert (change_record.lint_record(record) == []) == (kind in ("table", "fence"))
        with pytest.raises(change_record.Refusal) as refused:
            change_record.render_commit_message(record)
        assert [(error["code"], error["path"]) for error in refused.value.findings] == [
            ("commit-markup", f"/commit/{field}")
        ]

    def test_markup_quoted_in_a_code_span_is_a_literal_and_renders(self):
        record = example()
        record["commit"]["change"] = record["commit"]["change"].rstrip(".") + ", in a `<details>` fold."
        assert "`<details>`" in change_record.render_commit_message(valid(record))

    @pytest.mark.parametrize("pad", range(12))
    def test_cr_r4_a_quoted_construct_is_never_split_by_the_wrap_and_stays_a_literal(self, pad: int):
        # The quoted comment slides across the wrap column. Wherever it lands, the span
        # is whole on one line, so the readers the lint uses find no construct in the message.
        quoted = "`a literal <!-- kept for the next reader -->`"
        record = example()
        record["commit"]["why"] = (
            f"A reader could not tell a note the author quoted{' so' * pad}, such as {quoted}, "
            "from a real one. Review cost was unpredictable."
        )
        message = change_record.render_commit_message(valid(record))
        assert quoted in message
        assert constructs(message) == []

    def test_cr_r4_a_code_span_longer_than_the_wrap_column_stays_whole_on_its_own_line(self):
        span = "`" + "<details> a quoted fold that runs on, " * 3 + "past the column`"
        assert len(span) > 72
        record = example()
        record["commit"]["why"] = f"A reader met {span} in a note. Review cost was unpredictable."
        message = change_record.render_commit_message(valid(record))
        assert f"\n{span}\n" in message
        assert constructs(message) == []

    def test_cr_r4_a_construct_the_wrap_would_make_is_refused(self):
        # Three backticks in running prose open a fence where the wrap puts them first on a line.
        record = example()
        record["commit"]["why"] = (
            "A reader could not tell where the quoted note ended and the text began ``` and so on. "
            "Review cost was unpredictable."
        )
        assert change_record.lint_record(record) == []
        with pytest.raises(change_record.Refusal) as refused:
            change_record.render_commit_message(record)
        assert [(error["code"], error["path"]) for error in refused.value.findings] == [("commit-markup", "/commit/why")]

    def test_the_work_item_gloss_reaches_the_message_and_is_held_to_the_same_rule(self, tmp_path: Path):
        record = example()
        record["work_item"]["gloss"] = "predictable settings <!-- for now -->"
        errors = refusal(record, tmp_path, "commit")
        assert {error["path"] for error in errors} == {"/work_item/gloss"}, errors


class TestCrR5Reply:
    @pytest.mark.parametrize("outcome", ["Fixed", "Superseded", "Rejected", "Deferred"])
    def test_cr_r5_a_reply_is_three_labelled_lines_opening_with_its_outcome(
        self, outcome: str, tmp_path: Path
    ):
        record = example()
        entry = first_reply(record, outcome)
        reply = render(record, tmp_path, "reply", *reply_flags(entry))
        lines = reply.splitlines()
        assert len(lines) == 3
        assert lines[0] == f"Outcome: {outcome}."
        assert lines[1].startswith(f"Change: {entry['change']}")
        assert lines[2] == f"Verification: {entry['verification']}"
        assert reply.endswith("\n")

    def test_cr_r5_a_reply_with_a_commit_ends_its_change_line_with_it_in_parentheses(
        self, tmp_path: Path
    ):
        record = example()
        entry = first_reply(record, "Fixed")
        entry["commit"] = "75bb090c"
        reply = render(record, tmp_path, "reply", *reply_flags(entry))
        assert reply.splitlines()[1] == f"Change: {entry['change']} (75bb090c)"

    @pytest.mark.parametrize("commit", [None, ""])
    def test_cr_r5_a_reply_with_no_commit_ends_its_change_line_with_no_parenthesis(
        self, commit: str | None, tmp_path: Path
    ):
        record = example()
        entry = first_reply(record, "Fixed")
        entry.pop("commit", None)
        if commit is not None:
            entry["commit"] = commit
        reply = render(record, tmp_path, "reply", *reply_flags(entry))
        assert reply.splitlines()[1] == f"Change: {entry['change']}"

    @pytest.mark.parametrize("field", ["change", "verification"])
    @pytest.mark.parametrize("ending", ["\n", "\r", "\r\n", "\n\n"], ids=["LF", "CR", "CRLF", "blank"])
    def test_cr_r5_a_line_break_in_a_reply_s_prose_leaves_it_three_lines(
        self, field: str, ending: str, tmp_path: Path
    ):
        record = example()
        entry = first_reply(record, "Fixed")
        whole = entry[field]
        assert ". " in whole
        entry[field] = whole.replace(". ", f".{ending}", 1)
        reply = render(record, tmp_path, "reply", *reply_flags(entry))
        entry[field] = whole
        assert reply.split("\n") == [
            "Outcome: Fixed.",
            f"Change: {entry['change']} ({entry['commit']})",
            f"Verification: {entry['verification']}",
            "",
        ]
        assert "\r" not in reply

    def test_a_finding_with_no_reply_entry_is_refused(self, tmp_path: Path):
        errors = refusal(example(), tmp_path, "reply", "--finding", "nobody.r9.f9")
        assert [error["code"] for error in errors] == ["reply-entry"]
        assert "nobody.r9.f9" in errors[0]["message"]

    def test_two_entries_for_one_finding_id_are_told_apart_by_their_claim(self, tmp_path: Path):
        record = example()
        twin = copy.deepcopy(record["replies"][0])
        twin["claim_id"] = "another-claim"
        twin["commit"] = "0ddba11"
        record["replies"].append(twin)
        errors = refusal(record, tmp_path, "reply", "--finding", twin["finding_id"])
        assert [error["code"] for error in errors] == ["reply-entry"]
        assert "--claim" in errors[0]["message"]
        assert render(record, tmp_path, "reply", *reply_flags(twin)).splitlines()[1].endswith(" (0ddba11)")
        assert " (0ddba11)" not in render(record, tmp_path, "reply", *reply_flags(record["replies"][0]))


class TestCrR6LintFirst:
    @pytest.mark.parametrize("artifact", ["body", "commit", "reply"])
    def test_cr_r6_a_record_that_fails_lint_renders_nothing_and_exits_with_the_lint_output(
        self, artifact: str, tmp_path: Path
    ):
        record = example()
        flags = reply_flags(record["replies"][0]) if artifact == "reply" else []
        del record["summary"]
        record["risk"]["rows"][0]["likelihood"] = "low"
        linted = run("lint", write(record, tmp_path))
        assert linted.returncode == 1

        output = tmp_path / "artifact.out"
        proc = run("render", artifact, write(record, tmp_path), "--output", output, *flags)
        assert proc.returncode == linted.returncode
        assert proc.stderr == linted.stdout
        assert proc.stdout == b""
        assert not output.exists()
        assert refusal(record, tmp_path, artifact, *flags) == json.loads(linted.stdout)["errors"]


class TestCrR7Determinism:
    def test_cr_r7_two_renders_and_a_render_of_the_reserialized_record_are_byte_identical(
        self, tmp_path: Path
    ):
        first = tmp_path / "first.json"
        first.write_text(json.dumps(EXAMPLE), encoding="utf-8")
        once = artifacts(first)
        assert artifacts(first) == once

        rewritten = tmp_path / "rewritten.json"
        rewritten.write_text(
            json.dumps(EXAMPLE, sort_keys=True, indent=4, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        assert rewritten.read_bytes() != first.read_bytes()
        assert json.loads(rewritten.read_text(encoding="utf-8")) == EXAMPLE
        assert artifacts(rewritten) == once
        assert all(once.values())


class TestCommandLine:
    @pytest.mark.parametrize("argv", [
        ("render",),
        ("render", "body"),
        ("render", "summary", "record.json"),
        ("render", "reply", "record.json"),
        ("render", "commit", "record.json", "--finding", "a.r1.f1"),
    ])
    def test_a_call_the_parser_cannot_read_exits_2(self, argv: tuple[str, ...]):
        proc = run(*argv)
        assert proc.returncode == 2
        assert b"usage: change_record.py" in proc.stderr
        assert b"render" in proc.stderr

    def test_a_record_or_an_existing_body_that_cannot_be_read_exits_2_and_writes_nothing(
        self, tmp_path: Path
    ):
        absent = run("render", "body", tmp_path / "absent.json")
        assert absent.returncode == 2
        assert absent.stdout == b""
        assert json.loads(absent.stderr)["errors"][0]["code"] == "unreadable"

        proc = run("render", "body", write(example(), tmp_path), "--existing-body", tmp_path / "absent.md")
        assert proc.returncode == 2
        assert proc.stdout == b""
        assert json.loads(proc.stderr)["errors"][0]["code"] == "unreadable"


if __name__ == "__main__":
    if sys.argv[1:] == ["--regenerate"]:
        sys.exit(regenerate())
    sys.exit(pytest.main([__file__, "-q"]))
