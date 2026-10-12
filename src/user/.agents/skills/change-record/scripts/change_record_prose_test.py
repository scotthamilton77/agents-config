#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the two subcommands that give a record's wording to an editor and take the accepted rewrites back.

Run: uv run change_record_prose_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import hashlib
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FIXTURES = {
    "843": SKILL / "examples" / "pr-843.json",
    "838": SKILL / "evals" / "records" / "pr-838.json",
    "839": SKILL / "evals" / "records" / "pr-839.json",
    "846": SKILL / "evals" / "records" / "pr-846.json",
}
EXAMPLE = json.loads(FIXTURES["843"].read_text(encoding="utf-8"))
SUBJECT = EXAMPLE["commit"]["subject"]

# The example with a row a generator wrote at the head of its heads-up list,
# and a filed row closing its discovered work.
SEEDED = copy.deepcopy(EXAMPLE)
SEEDED["heads_up"].insert(0, "campaign: No review round has run on this pull request.")
SEEDED["discovered"]["rows"].append(
    {"status": "filed", "item": "ab-1x.2", "what": "A follow-up.", "reason": "The tracker's own reason."}
)
FILED_REASON = f"/discovered/rows/{len(SEEDED['discovered']['rows']) - 1}/reason"

QUESTIONS = [{"field": "/risk/rows/0/evidence", "question": "Which test shows that every slot has a pin?"}]


def swap(text: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` in ``text``, and fail when ``old`` is not there to replace."""
    assert old in text
    return text.replace(old, new)


# One pass over the example. The editor proposes three rewrites. The author
# takes the third out, and corrects the first before applying it.
PROPOSED_SUMMARY = swap(EXAMPLE["summary"], "Every reviewer receives", "Each reviewer is handed")
CORRECTED_SUMMARY = swap(EXAMPLE["summary"], "Every reviewer receives", "Each reviewer gets")
NEW_WHY = swap(
    EXAMPLE["commit"]["why"],
    "Review cost and coverage were unpredictable.",
    "Nobody could predict review cost or coverage.",
)
NEW_CHANGE = swap(EXAMPLE["changes"][0]["text"], "pins effort", "sets effort")

# One case for each kind of protected value: the field, the text it holds, a
# replacement that drops or changes the value, and the value as a refusal names it.
PROTECTED = {
    "tracker-id": ("/summary", "It closes ab-1x.2 today.", "It closes ab-1x.3 today.", "ab-1x.2"),
    "tracker-id-by-prefix": (
        "/summary", "It sits under agents-config-9k9 now.", "It sits under the milestone now.", "agents-config-9k9",
    ),
    "criterion-id": ("/summary", "It meets CR-W4 in full.", "It meets CR-W5 in full.", "CR-W4"),
    "decision-id": ("/summary", "It follows D16 closely.", "It follows the decision closely.", "D16"),
    "pr-number": ("/summary", "It builds on #843 directly.", "It builds on #844 directly.", "#843"),
    "url": (
        "/summary", "See https://example.com/a/b for more.", "See https://example.com/a/c for more.",
        "https://example.com/a/b",
    ),
    "sha": ("/summary", "It landed in 3550f20d cleanly.", "It landed cleanly.", "3550f20d"),
    "number": ("/summary", "The limit is 65,536 characters.", "The limit is 65,535 characters.", "65,536"),
    "code-span": ("/summary", "Run `make ci` first.", "Run `make test` first.", "`make ci`"),
    "disposition": ("/summary", "The finding was rebutted there.", "The finding was answered there.", "rebutted"),
    "outcome": ("/summary", "Its outcome is Superseded now.", "Its outcome is replaced now.", "superseded"),
    "status": ("/summary", "The other slice is in flight.", "The other slice is under way.", "in flight"),
    "attribution": ("/summary", "Written with Claude Code throughout.", "Written with a tool.", "Claude Code"),
    "subject-type": ("/commit/subject", SUBJECT, swap(SUBJECT, "feat(", "fix("), "feat"),
    "subject-component": ("/commit/subject", SUBJECT, swap(SUBJECT, "(review-panel)", "(panel)"), "(review-panel)"),
    "subject-closing-id": ("/commit/subject", SUBJECT, swap(SUBJECT, "[9k9.408]", "(9k9.408)"), "[9k9.408]"),
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content(record: dict[str, Any]) -> dict[str, Any]:
    """Return ``record`` without its bookkeeping group."""
    return {name: group for name, group in record.items() if name != "record"}


def digest_of(record: dict[str, Any]) -> str:
    """Return the record's digest, worked out apart from the script under test."""
    return sha256(json.dumps(content(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def at(record: Any, field: str) -> Any:
    """Return what ``record`` holds at ``field``, read apart from the script under test."""
    node = record
    for name in field.split("/")[1:]:
        node = node[int(name)] if isinstance(node, list) else node[name]
    return node


def put(record: dict[str, Any], field: str, text: str) -> dict[str, Any]:
    """Return a copy of ``record`` whose ``field`` holds ``text``."""
    changed = copy.deepcopy(record)
    parent, _, last = field.rpartition("/")
    holder = at(changed, parent)
    holder[int(last) if isinstance(holder, list) else last] = text
    return changed


def listed(record: dict[str, Any]) -> list[str]:
    """Return the path of every field of ``record`` an editor may rewrite, written out from the list of them."""
    generated = ("context: ", "discovered: ", "campaign: ")
    criteria = record.get("criteria", [])
    risk, heads_up = record["risk"]["rows"], record["heads_up"]
    return [
        "/pr/title",
        "/work_item/gloss",
        "/summary",
        *(f"/heads_up/{i}" for i, row in enumerate(heads_up) if row != "None." and not row.startswith(generated)),
        *(f"/risk/rows/{i}/{cell}" for i in range(len(risk)) for cell in ("failure", "exposed", "evidence", "recovery")),
        *(f"/changes/{i}/{part}" for i in range(len(record["changes"])) for part in ("topic", "text")),
        *(["/design_notes"] if "design_notes" in record else []),
        *(
            f"/discovered/rows/{i}/reason"
            for i, row in enumerate(record["discovered"]["rows"])
            if isinstance(row, dict) and row["status"] != "filed"
        ),
        *(f"/criteria/{i}/promise" for i in range(len(criteria)) if isinstance(criteria, list)),
        "/commit/subject",
        *(f"/commit/{name}" for name in ("why", "change", "verification") if name in record["commit"]),
        *(f"/replies/{i}/{part}" for i in range(len(record.get("replies", []))) for part in ("change", "verification")),
    ]


class Ran(NamedTuple):
    code: int
    out: str
    err: str

    @property
    def errors(self) -> list[dict[str, str]]:
        """Return the findings of the JSON result that closes stderr."""
        result = json.loads(self.err.strip().splitlines()[-1])
        assert result["valid"] is False
        return result["errors"]


class Desk:
    """A record file and a response file in a directory of their own, and the two subcommands run over them."""

    def __init__(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self.path = tmp_path / "record.json"
        self.response_path = tmp_path / "response.json"
        self.capsys = capsys
        self.write(EXAMPLE)

    def write(self, record: dict[str, Any]) -> bytes:
        """Write ``record`` in the layout the script writes, and return the file's bytes."""
        self.path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return self.path.read_bytes()

    def record(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def run(self, *argv: str) -> Ran:
        code = change_record.main(list(argv))
        captured = self.capsys.readouterr()
        return Ran(code, captured.out, captured.err)

    def request(self) -> dict[str, Any]:
        ran = self.run("extract-prose", str(self.path))
        assert ran.code == 0, ran.err
        return json.loads(ran.out)

    def fields(self) -> list[str]:
        return [section["field"] for section in self.request()["sections"]]

    def response(self, rewrites: dict[str, str], **more: Any) -> dict[str, Any]:
        """Return the response an editor gives the record's request, with one replacement per field of ``rewrites``."""
        request = self.request()
        digests = {section["field"]: section["digest"] for section in request["sections"]}
        replacements = [
            {"field": field, "section_digest": digests.get(field, sha256("")), "text": text}
            for field, text in rewrites.items()
        ]
        counted = {"proposed": len(replacements), "replacements": replacements}
        return {"record_digest": request["record_digest"], **counted, **more}

    def apply(self, response: dict[str, Any] | str) -> Ran:
        written = response if isinstance(response, str) else json.dumps(response)
        self.response_path.write_text(written, encoding="utf-8")
        return self.run("apply-prose", str(self.path), str(self.response_path))

    def refuse(self, response: dict[str, Any]) -> list[dict[str, str]]:
        """Apply ``response``, check that it is refused with the record file as it was, and return the findings."""
        before = self.path.read_bytes()
        ran = self.apply(response)
        assert ran.code == 1, ran.out + ran.err
        assert self.path.read_bytes() == before
        return ran.errors


@pytest.fixture
def desk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Desk:
    return Desk(tmp_path, capsys)


class Passed(NamedTuple):
    response: dict[str, Any]
    after: dict[str, Any]


@pytest.fixture
def passed(desk: Desk) -> Passed:
    """Apply the one pass over the example, and return the response as the author left it and the record it gave."""
    response = desk.response({"/summary": PROPOSED_SUMMARY, "/commit/why": NEW_WHY, "/changes/0/text": NEW_CHANGE})
    del response["replacements"][2]
    response["replacements"][0]["corrected"] = CORRECTED_SUMMARY
    # Restating the editor's own text corrects nothing, so this entry is not counted as corrected.
    response["replacements"][1]["corrected"] = NEW_WHY
    ran = desk.apply(response)
    assert ran.code == 0, ran.err
    return Passed(response, desk.record())


class TestCrW1ExtractProse:
    @pytest.mark.parametrize("name", list(FIXTURES))
    def test_cr_w1_the_request_holds_the_record_its_digest_the_checks_and_exactly_the_listed_sections(
        self, desk: Desk, name: str
    ):
        record = json.loads(FIXTURES[name].read_text(encoding="utf-8"))
        desk.write(record)
        request = desk.request()
        assert request["record"] == record
        assert request["record_digest"] == digest_of(record)
        assert sorted(section["field"] for section in request["sections"]) == sorted(listed(record))
        for section in request["sections"]:
            assert section["text"] == at(record, section["field"])
            assert section["digest"] == sha256(section["text"])
        checks = re.findall(r"^\d\. .+$", (SKILL / "SKILL.md").read_text(encoding="utf-8"), re.MULTILINE)
        assert len(checks) == 7
        assert all(check in request["writing_checks"] for check in checks)

    def test_cr_w1_a_filed_reason_a_generated_row_and_the_entry_for_an_empty_list_are_no_sections(self, desk: Desk):
        desk.write(SEEDED)
        fields = desk.fields()
        assert "/heads_up/0" not in fields and "/heads_up/1" in fields
        assert FILED_REASON not in fields and "/discovered/rows/0/reason" in fields
        desk.write({**EXAMPLE, "heads_up": ["None."]})
        assert not [field for field in desk.fields() if field.startswith("/heads_up")]

    def test_cr_w1_clearing_a_mark_in_a_copied_schema_takes_the_field_out_of_the_request(
        self, desk: Desk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        schema = json.loads(change_record.SCHEMA_PATH.read_text(encoding="utf-8"))
        del schema["properties"]["summary"]["x-rewritable"]
        copied = tmp_path / "record.schema.json"
        copied.write_text(json.dumps(schema), encoding="utf-8")
        monkeypatch.setattr(change_record, "SCHEMA_PATH", copied)
        assert sorted(desk.fields()) == sorted(set(listed(EXAMPLE)) - {"/summary"})

    def test_a_skill_text_with_no_writing_checks_fails_naming_the_file(
        self, desk: Desk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        bare = tmp_path / "SKILL.md"
        bare.write_text("# A skill\n\n## The record\n\nNo checks are stated here.\n", encoding="utf-8")
        monkeypatch.setattr(change_record, "SKILL_TEXT", bare)
        ran = desk.run("extract-prose", str(desk.path), "--output", str(tmp_path / "request.json"))
        assert ran.code == 2
        assert str(bare) in ran.errors[0]["message"]
        assert not (tmp_path / "request.json").exists()

    def test_a_record_that_does_not_fit_the_schema_is_refused_by_both_subcommands(self, desk: Desk):
        response = desk.response({"/summary": CORRECTED_SUMMARY})
        desk.write({name: group for name, group in EXAMPLE.items() if name != "discovered"})
        ran = desk.run("extract-prose", str(desk.path))
        assert (ran.code, ran.out) == (1, "")
        assert [finding["path"] for finding in ran.errors] == ["/discovered"]
        assert [finding["code"] for finding in desk.refuse(response)] == ["schema"]


class TestNeitherSubcommandLeavesTheProcess:
    def test_no_executable_on_the_fenced_path_is_run(self, desk: Desk, shim_dir: Path, tmp_path: Path):
        # The fence leaves these four names on the search path and no other, and a shim comes first on it.
        log = tmp_path / "calls.log"
        for name in ("gh", "work", "git", "python3"):
            shim = shim_dir / name
            shim.write_text(f"#!/bin/sh\necho {name} >> {shlex.quote(str(log))}\n", encoding="utf-8")
            shim.chmod(0o755)
        response = desk.response({"/summary": CORRECTED_SUMMARY}, questions=QUESTIONS)
        ran = desk.run("extract-prose", str(desk.path), "--output", str(tmp_path / "request.json"))
        assert (ran.code, ran.out) == (0, "")
        assert json.loads((tmp_path / "request.json").read_text(encoding="utf-8")) == desk.request()
        assert desk.apply(response).code == 0
        assert desk.record()["summary"] == CORRECTED_SUMMARY
        assert not log.exists()


class TestCrW2StaleAndMalformedResponses:
    def test_cr_w2_a_response_written_against_another_record_is_refused(self, desk: Desk):
        response = {**desk.response({"/summary": CORRECTED_SUMMARY}), "record_digest": "0" * 64}
        assert [finding["code"] for finding in desk.refuse(response)] == ["stale-record"]

    def test_cr_w2_a_replacement_written_against_another_wording_is_refused_naming_its_section(self, desk: Desk):
        # The replacement also drops a value the summary holds, and a stale replacement is judged no further.
        response = desk.response({"/summary": "A summary in other words."})
        response["replacements"][0]["section_digest"] = sha256("another wording")
        (finding,) = desk.refuse(response)
        assert (finding["code"], finding["path"]) == ("stale-section", "/summary")

    def test_cr_w2_a_valid_replacement_ahead_of_a_stale_one_is_not_applied(self, desk: Desk):
        response = desk.response({"/summary": CORRECTED_SUMMARY, "/commit/why": NEW_WHY})
        response["replacements"][1]["section_digest"] = sha256("another wording")
        (finding,) = desk.refuse(response)
        assert (finding["code"], finding["path"]) == ("stale-section", "/commit/why")

    def test_cr_w2_a_second_replacement_for_one_section_is_stale(self, desk: Desk):
        response = desk.response({"/summary": CORRECTED_SUMMARY})
        response.update(proposed=2, replacements=response["replacements"] * 2)
        (finding,) = desk.refuse(response)
        assert (finding["code"], finding["path"]) == ("stale-section", "/summary")

    @pytest.mark.parametrize(
        ("spoil", "where"),
        [
            pytest.param(lambda entry: entry.pop("text"), "/replacements/0/text", id="missing-field"),
            pytest.param(lambda entry: entry.update(corrected=7), "/replacements/0/corrected", id="wrong-type"),
        ],
    )
    def test_cr_w2_a_response_that_fails_its_schema_is_refused_naming_the_section(
        self, desk: Desk, spoil: Any, where: str
    ):
        response = desk.response({"/summary": CORRECTED_SUMMARY})
        spoil(response["replacements"][0])
        (finding,) = desk.refuse(response)
        assert (finding["code"], finding["path"]) == ("response-schema", where)
        assert "/summary" in finding["message"]

    def test_cr_w2_a_response_that_is_not_json_is_refused(self, desk: Desk):
        before = desk.path.read_bytes()
        ran = desk.apply("these words are no JSON")
        assert ran.code == 2
        assert [finding["code"] for finding in ran.errors] == ["invalid-json"]
        assert desk.path.read_bytes() == before

    def test_cr_w2_a_response_holding_more_replacements_than_were_proposed_is_refused(self, desk: Desk):
        response = {**desk.response({"/summary": CORRECTED_SUMMARY}), "proposed": 0}
        assert [finding["code"] for finding in desk.refuse(response)] == ["proposed-count"]

    def test_cr_w2_a_response_of_questions_alone_is_valid_applies_nothing_and_prints_them(self, desk: Desk):
        before = desk.path.read_bytes()
        ran = desk.apply(desk.response({}, questions=QUESTIONS))
        assert ran.code == 0
        assert f"question on {QUESTIONS[0]['field']}: {QUESTIONS[0]['question']}" in ran.out.splitlines()
        assert desk.path.read_bytes() == before


class TestCrW3OnlyRewritableFields:
    @pytest.mark.parametrize(
        "field",
        [
            pytest.param("/work_item/slice", id="unmarked"),
            pytest.param("/heads_up/0", id="generated-row"),
            pytest.param(FILED_REASON, id="filed-reason"),
            pytest.param("/no/such/field", id="unknown"),
        ],
    )
    def test_cr_w3_a_replacement_for_a_field_that_is_no_section_is_refused_naming_it(self, desk: Desk, field: str):
        desk.write(SEEDED)
        (finding,) = desk.refuse(desk.response({field: "Another wording."}))
        assert (finding["code"], finding["path"]) == ("not-rewritable", field)


class TestCrW4ProtectedValues:
    @pytest.mark.parametrize(
        ("field", "old", "new", "value"), [pytest.param(*case, id=kind) for kind, case in PROTECTED.items()]
    )
    def test_cr_w4_a_replacement_that_drops_or_changes_a_protected_value_is_refused_naming_it(
        self, desk: Desk, field: str, old: str, new: str, value: str
    ):
        desk.write(put(EXAMPLE, field, old))
        (finding,) = desk.refuse(desk.response({field: new}))
        assert (finding["code"], finding["path"]) == ("protected-value", field)
        assert f"`{value}`" in finding["message"]

    def test_cr_w4_a_value_set_elsewhere_in_its_sentence_is_the_same_value(self):
        old = "Follow section 3.4. The page is https://example.com/a/b."
        new = "Section 3.4 applies, and https://example.com/a/b, the page, says how."
        for text in (old, new):
            assert change_record.protected_values(text, "/summary", EXAMPLE) == {"3.4", "https://example.com/a/b"}
        # An id with no hyphen has no project prefix, and no word of the text is then read as an id of the project.
        unprefixed = {**EXAMPLE, "work_item": {**EXAMPLE["work_item"], "id": "solo"}}
        assert change_record.protected_values("Plain words alone.", "/summary", unprefixed) == set()


class TestCrW5AppliedSections:
    def test_cr_w5_exactly_the_accepted_sections_change_the_revision_is_bumped_and_the_result_passes_lint(
        self, passed: Passed
    ):
        accepted = put(put(EXAMPLE, "/summary", CORRECTED_SUMMARY), "/commit/why", NEW_WHY)
        assert content(passed.after) == content(accepted)
        assert passed.after["record"]["revision"] == EXAMPLE["record"]["revision"] + 1
        assert change_record.lint_record(passed.after) == []

    def test_cr_w5_the_entry_names_each_applied_section_with_its_old_and_new_digests(self, passed: Passed):
        (entry,) = passed.after["record"]["rewrites"]
        assert entry["sections"] == [
            {"field": "/summary", "old_digest": sha256(EXAMPLE["summary"]), "new_digest": sha256(CORRECTED_SUMMARY)},
            {"field": "/commit/why", "old_digest": sha256(EXAMPLE["commit"]["why"]), "new_digest": sha256(NEW_WHY)},
        ]

    def test_a_result_that_fails_lint_is_refused_with_the_lint_findings(self, desk: Desk):
        one_sentence = "A run that dies follows a fixed recovery sequence."
        assert one_sentence in EXAMPLE["summary"]
        (finding,) = desk.refuse(desk.response({"/summary": one_sentence}))
        assert (finding["code"], finding["path"]) == ("summary-length", "/summary")

    @pytest.mark.parametrize(
        "render", [change_record.render_body, change_record.render_commit_message], ids=["body", "commit"]
    )
    def test_a_render_changes_only_in_the_lines_of_the_applied_sections(self, passed: Passed, render: Any):
        before, after = render(EXAMPLE).splitlines(), render(passed.after).splitlines()
        gone = {word for line in before if line not in after for word in line.split()}
        come = {word for line in after if line not in before for word in line.split()}
        assert gone and gone <= set(f"{EXAMPLE['summary']} {EXAMPLE['commit']['why']}".split())
        assert come and come <= set(f"{CORRECTED_SUMMARY} {NEW_WHY}".split())


class TestCrW6SecondRun:
    def test_cr_w6_the_same_response_a_second_time_is_refused_on_its_section_digests(self, desk: Desk, passed: Passed):
        stale = [finding["path"] for finding in desk.refuse(passed.response) if finding["code"] == "stale-section"]
        assert stale == ["/summary", "/commit/why"]

    def test_cr_w6_a_response_of_questions_alone_is_accepted_both_times_and_changes_nothing(self, desk: Desk):
        before = desk.path.read_bytes()
        response = desk.response({}, questions=QUESTIONS)
        assert [desk.apply(response).code, desk.apply(response).code] == [0, 0]
        assert desk.path.read_bytes() == before


class TestCrW9OnePassPerRevision:
    def test_cr_w9_a_second_pass_waits_for_a_revision_of_the_authors_own(self, desk: Desk, passed: Passed):
        produced = passed.after["record"]["revision"]
        assert [entry["revision"] for entry in passed.after["record"]["rewrites"]] == [produced]
        fresh = desk.response({"/changes/0/text": NEW_CHANGE})
        assert [finding["code"] for finding in desk.refuse(fresh)] == ["one-pass"]
        # An author's edit reaches the record as its next revision, which is the number publishing the edit gives it.
        edited = put(passed.after, "/work_item/slice", "the first slice of three in the item's acceptance text")
        desk.write({**edited, "record": {**edited["record"], "revision": produced + 1}})
        assert desk.apply(desk.response({"/changes/0/text": NEW_CHANGE})).code == 0
        assert desk.record()["changes"][0]["text"] == NEW_CHANGE
        assert [entry["revision"] for entry in desk.record()["record"]["rewrites"]] == [produced, produced + 2]


class TestCrW10Counts:
    def test_cr_w10_the_entry_counts_what_was_proposed_pruned_corrected_and_applied(self, passed: Passed):
        entry = passed.after["record"]["rewrites"][-1]
        counts = {name: entry[name] for name in ("proposed", "pruned", "corrected", "applied")}
        assert counts == {"proposed": 3, "pruned": 1, "corrected": 1, "applied": 2}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
