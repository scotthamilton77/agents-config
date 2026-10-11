#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the change record's schema, its templates and the lint over a record.

Run: uv run change_record_test.py
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
REFERENCES = SKILL / "references"
SCHEMA = json.loads((REFERENCES / "record.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))

# The groups a record of any commit type carries. The others depend on the type
# or are filled by a generator, so their absence is not a structural fault.
REQUIRED_GROUPS = [
    "pr", "work_item", "summary", "heads_up", "risk", "changes", "discovered",
    "verification", "commit", "record",
]
OPTIONAL_GROUPS = [
    "where_this_fits", "blast_radius", "design_notes", "campaign", "criteria", "replies",
]

REWRITABLE = {
    "pr.title",
    "work_item.gloss",
    "summary",
    "heads_up[]",
    "risk.rows[].failure", "risk.rows[].exposed", "risk.rows[].evidence", "risk.rows[].recovery",
    "changes[].topic", "changes[].text",
    "design_notes",
    "discovered.rows[].reason",
    "criteria[].promise",
    "commit.subject", "commit.why", "commit.change", "commit.verification",
    "replies[].change", "replies[].verification",
}

# Places a template fills from something other than one record field.
COMPUTED_SLOTS = {"commit_message", "decisions", "record_comment_url"}

SLOT = re.compile(r"\$\{([^}]*)\}")

PR_BODY_HEADINGS = [
    "## Heads-up",
    "## Where this fits",
    "## Risk",
    "## Changes",
    "## Discovered work",
    "## Verification",
    "### Review campaign",
    "## Criteria",
]

# Every heading, fold label, table header and line label, in the order a reader meets it.
TEMPLATE_MARKERS = {
    "pr-body.md": [
        "## Heads-up",
        "## Where this fits",
        "this PR:",
        "Builds on:",
        "Concurrent:",
        "<details><summary>Scope of the owning item</summary>",
        "| Slice | What it covers | Status |",
        "## Risk",
        "| What could go wrong | Who or what is exposed | How we know it did not | What to do if it did |",
        "<details><summary>Blast radius</summary>",
        "```mermaid",
        "```mermaid",
        "## Changes",
        "<details><summary>Design notes</summary>",
        "## Discovered work",
        "| Item | Status | What it is | Why not in this PR |",
        "\n---\n",
        "## Verification",
        ": exit ",
        ", run standalone from ",
        "- Not run:",
        "### Review campaign",
        "| Reviewer | Rounds | Findings | Fixed | Rejected | Deferred |",
        "Terminal-clean at",
        "Approval is a machine attestation of that head.",
        "<details><summary>Findings by round</summary>",
        "| Round | Id | Finding in plain words | Disposition | Reason | Commit |",
        "## Criteria",
        "| Criterion | What it promises | Evidence |",
        "<details><summary>Proposed commit message</summary>",
        "Rendered from change record",
        ", revision ",
        "Generated with",
    ],
    "commit-message.txt": [
        "\n\nWork item ",
        "\n\nWhy\n",
        "\n\nChange\n",
        "\n\nVerification\n",
        "\n\nWork-item: ",
        "\nCo-authored-by: ",
    ],
    "review-reply.txt": ["Outcome: ", "\nChange: ", "\nVerification: "],
}


def lint(record: Any, tmp_path: Path) -> tuple[int, dict[str, Any]]:
    """Run the lint subcommand over ``record`` in a child process and parse what it printed."""
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "lint", str(path)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


def assert_fails_naming(record: Any, field: str, tmp_path: Path) -> None:
    code, result = lint(record, tmp_path)
    assert code == 1
    assert result["valid"] is False
    assert field in [error["path"] for error in result["errors"]], result["errors"]


def example() -> dict[str, Any]:
    return copy.deepcopy(EXAMPLE)


def marked_paths(node: dict[str, Any], path: str = "") -> set[str]:
    """Return the record path of every field under ``node`` that the schema marks rewritable."""
    found = {path} if node.get("x-rewritable") is True else set()
    for name, child in node.get("properties", {}).items():
        found |= marked_paths(child, f"{path}.{name}" if path else name)
    if "items" in node:
        found |= marked_paths(node["items"], f"{path}[]")
    return found


def object_schemas(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Return every subschema that can validate an object, with where it sits in the schema file."""
    if isinstance(node, list):
        children = enumerate(node)
        found = []
    elif isinstance(node, dict):
        children = node.items()
        kinds = node.get("type", [])
        takes_object = "object" in ([kinds] if isinstance(kinds, str) else kinds)
        found = [(path, node)] if takes_object or "properties" in node else []
    else:
        return []
    for key, child in children:
        found += object_schemas(child, f"{path}/{key}")
    return found


def schema_at(slot: str) -> dict[str, Any] | None:
    """Return the subschema a template slot names, or None when the schema has no such field."""
    node = SCHEMA
    for segment in slot.split("."):
        name, each = segment.removesuffix("[]"), segment.endswith("[]")
        node = node.get("properties", {}).get(name)
        if node is None or (each and "items" not in node):
            return None
        if each:
            node = node["items"]
    return node


class TestSchema:
    def test_the_schema_defines_exactly_the_record_groups(self):
        assert sorted(SCHEMA["properties"]) == sorted(REQUIRED_GROUPS + OPTIONAL_GROUPS)

    def test_the_schema_requires_exactly_the_groups_every_commit_type_carries(self):
        assert SCHEMA["required"] == REQUIRED_GROUPS

    def test_every_object_in_the_schema_refuses_a_field_it_does_not_define(self):
        objects = object_schemas(SCHEMA)
        assert len(objects) > 20
        for path, node in objects:
            assert node.get("additionalProperties") is False, path

    def test_the_schema_marks_exactly_the_rewritable_fields(self):
        assert marked_paths(SCHEMA) == REWRITABLE
        # A mark outside the record's own fields would be one the walk above cannot see.
        assert json.dumps(SCHEMA).count('"x-rewritable"') == len(REWRITABLE)

    def test_the_field_table_names_exactly_the_schema_groups(self):
        table = (REFERENCES / "fields.md").read_text(encoding="utf-8")
        first_cells = [line.split("|")[1] for line in table.splitlines() if line.startswith("| `")]
        named = {name for cell in first_cells for name in re.findall(r"`([a-z_]+)`", cell)}
        assert named == set(SCHEMA["properties"])


class TestLint:
    def test_cr_l1_the_pr_843_example_passes(self, tmp_path: Path):
        assert lint(EXAMPLE, tmp_path) == (0, {"valid": True})

    def test_the_example_carries_every_group_the_schema_defines(self):
        assert set(EXAMPLE) == set(SCHEMA["properties"])

    @pytest.mark.parametrize("group", REQUIRED_GROUPS)
    def test_cr_l1_a_record_missing_a_required_group_fails_naming_it(self, group: str, tmp_path: Path):
        record = example()
        del record[group]
        assert_fails_naming(record, f"/{group}", tmp_path)

    def test_cr_l1_an_unknown_top_level_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["reviewers_notes"] = "nothing the schema defines"
        assert_fails_naming(record, "/reviewers_notes", tmp_path)

    def test_cr_l1_an_unknown_nested_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["risk"]["rows"][0]["likelihood"] = "low"
        assert_fails_naming(record, "/risk/rows/0/likelihood", tmp_path)

    def test_cr_l1_a_gate_exit_status_given_as_an_object_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["verification"]["gates"][0]["exit_status"] = {"code": 0}
        assert_fails_naming(record, "/verification/gates/0/exit_status", tmp_path)

    def test_cr_l1_a_reply_text_given_as_an_object_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["replies"][0]["change"] = {"text": record["replies"][0]["change"]}
        assert_fails_naming(record, "/replies/0/change", tmp_path)

    def test_a_missing_nested_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        del record["work_item"]["gloss"]
        assert_fails_naming(record, "/work_item/gloss", tmp_path)

    def test_a_discovered_row_is_the_none_entry_or_a_row_object(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"] = ["None."]
        assert lint(record, tmp_path) == (0, {"valid": True})
        record["discovered"]["rows"] = ["Nothing."]
        assert_fails_naming(record, "/discovered/rows/0", tmp_path)

    def test_criteria_is_a_table_or_one_line(self, tmp_path: Path):
        record = example()
        record["criteria"] = "Attacked twice; the record is beside the spec."
        assert lint(record, tmp_path) == (0, {"valid": True})
        record["criteria"] = [{"id": "A1"}]
        assert_fails_naming(record, "/criteria/0/promise", tmp_path)

    def test_each_fault_is_reported_once_and_in_path_order(self, tmp_path: Path):
        record = example()
        del record["summary"]
        del record["changes"]
        record["zebra"] = 1
        record["alpha"] = 1
        _, result = lint(record, tmp_path)
        paths = [error["path"] for error in result["errors"]]
        assert paths == ["/alpha", "/changes", "/summary", "/zebra"]
        assert {error["code"] for error in result["errors"]} == {"schema"}


class TestCommandLine:
    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False
        )

    def test_a_record_that_cannot_be_read_exits_2_with_the_reason(self, tmp_path: Path):
        proc = self.run("lint", str(tmp_path / "absent.json"))
        assert proc.returncode == 2
        assert json.loads(proc.stdout)["errors"][0]["code"] == "unreadable"

    def test_a_record_that_is_not_json_exits_2_with_the_reason(self, tmp_path: Path):
        path = tmp_path / "record.json"
        path.write_text("{not json", encoding="utf-8")
        proc = self.run("lint", str(path))
        assert proc.returncode == 2
        assert json.loads(proc.stdout)["errors"][0]["code"] == "invalid-json"

    def test_a_record_that_is_not_an_object_fails_at_the_root(self, tmp_path: Path):
        path = tmp_path / "record.json"
        path.write_text("[]", encoding="utf-8")
        proc = self.run("lint", str(path))
        assert proc.returncode == 1
        assert json.loads(proc.stdout)["errors"][0]["path"] == ""

    @pytest.mark.parametrize("argv", [(), ("lint",), ("polish", "record.json")])
    def test_a_call_the_parser_cannot_read_exits_2(self, argv: tuple[str, ...]):
        proc = self.run(*argv)
        assert proc.returncode == 2
        assert "usage:" in proc.stderr


class TestTemplates:
    @pytest.mark.parametrize("name", sorted(TEMPLATE_MARKERS))
    def test_a_template_holds_its_headings_and_labels_in_order(self, name: str):
        text = (REFERENCES / name).read_text(encoding="utf-8")
        position = 0
        for marker in TEMPLATE_MARKERS[name]:
            found = text.find(marker, position)
            assert found >= 0, f"{marker!r} is missing or out of order"
            position = found + len(marker)

    def test_the_pr_body_template_has_no_heading_beyond_the_eight(self):
        text = (REFERENCES / "pr-body.md").read_text(encoding="utf-8")
        assert [line for line in text.splitlines() if line.startswith("#")] == PR_BODY_HEADINGS

    @pytest.mark.parametrize("name", sorted(TEMPLATE_MARKERS))
    def test_every_slot_names_a_record_field_or_a_computed_place(self, name: str):
        slots = SLOT.findall((REFERENCES / name).read_text(encoding="utf-8"))
        assert slots
        for slot in slots:
            assert slot in COMPUTED_SLOTS or schema_at(slot) is not None, slot

    def test_a_dollar_sign_in_a_template_always_opens_a_slot(self):
        for name in TEMPLATE_MARKERS:
            text = (REFERENCES / name).read_text(encoding="utf-8")
            assert text.count("$") == len(SLOT.findall(text)), name


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
