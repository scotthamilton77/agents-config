#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the ac-attack record checker.

Run: uv run check_record_test.py
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
CHECKER_PATH = HERE / "check_record.py"
LENSES_PATH = HERE / "lenses.json"
SCHEMA_PATH = HERE / "attack-record.schema.json"

DOCUMENT = "# Ledger export\n\n- A1 The exporter writes every settled entry.\n"
REVISED = DOCUMENT + "- A2 The exporter exits non-zero when the output cannot be written.\n"
FURTHER = REVISED + "- A3 Re-running the exporter over the same ledger changes nothing.\n"
UNRELATED = REVISED + "\n## Out of scope\n\nCurrency conversion.\n"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_record", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
LENS_NAMES = [lens["lens"] for lens in json.loads(LENSES_PATH.read_text(encoding="utf-8"))["lenses"]]


def sha_revision(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def blob_revision(text: str) -> str:
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def proposal(lens: str, target: str, identifier: str) -> dict[str, Any]:
    return {
        "id": identifier, "lens": lens, "target_ac": target,
        "hole": "an unwritable output path is never exercised",
        "proposed_ac": "the exporter exits non-zero when the output cannot be written",
        "red_test_sketch": {"given": "a read-only output directory",
                            "when": "the exporter runs", "expect": "a non-zero exit status"},
    }


class Attack:
    """A document, a record beside it, and the revisions that name both."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.document = root / "ledger-export.md"
        self.path = root / "ledger-export-ac-attack.json"
        self.write_document(REVISED)

    def write_document(self, text: str) -> str:
        self.document.write_text(text, encoding="utf-8")
        return sha_revision(text)

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "spec_path": self.document.name,
            "spec_revision": sha_revision(DOCUMENT),
            "lenses": [
                {"lens": name, "report": "proposals" if name != "criteria-holes" else "empty"}
                for name in LENS_NAMES
            ],
            "proposals": [proposal("edge-cases", "A1", "p1"),
                          proposal("absent-requirements", "none", "p2")],
            "dispositions": [
                {"id": "p1", "disposition": "accepted", "rationale": "a real hole",
                 "revision": sha_revision(REVISED), "covering_ac": "A2"},
                {"id": "p2", "disposition": "rejected",
                 "rationale": "currency conversion is out of scope for this document"},
            ],
        }

    def empty_round(self) -> dict[str, Any]:
        record = self.record()
        record["spec_revision"] = sha_revision(REVISED)
        record["lenses"] = [{"lens": name, "report": "empty"} for name in LENS_NAMES]
        record["proposals"] = []
        record["dispositions"] = []
        return record

    def save(self, record: Any, name: str | None = None) -> str:
        path = self.root / name if name else self.path
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return str(path)


@pytest.fixture
def attack(tmp_path) -> Attack:
    return Attack(tmp_path)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Stand a lens registry in place of the shipped one, clearing the cache either side of it."""
    def use(lenses: Any) -> None:
        path = tmp_path / "lenses.json"
        path.write_text(json.dumps({"lenses": lenses}), encoding="utf-8")
        monkeypatch.setattr(checker, "LENSES_PATH", path)
        checker.declared_lenses.cache_clear()
    yield use
    checker.declared_lenses.cache_clear()


def run(args: list[str], capsys) -> tuple[int, dict]:
    code = checker.main(args)
    return code, json.loads(capsys.readouterr().out)


def check(attack: Attack, record: Any, capsys, *extra: str) -> tuple[int, dict]:
    return run([attack.save(record), *extra], capsys)


def closed(attack: Attack, clean: bool = False, revision: str | None = None) -> dict[str, Any]:
    """The whole result a terminating round prints, document named, for exact comparison."""
    return {
        "clean": clean, "complete": True, "errors": [], "document": str(attack.document),
        "revision": revision or sha_revision(attack.document.read_text(encoding="utf-8")),
    }


def codes(result: dict) -> set[str]:
    return {error["code"] for error in result["errors"]}


def error_of(result: dict, code: str) -> dict:
    return next(error for error in result["errors"] if error["code"] == code)


DELETE = object()
CACHES = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under root, minus the caches the interpreter and the test runner write."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not CACHES & set(path.relative_to(root).parts)
    }


# Taken before any test invokes the checker: a stray file it leaves in its own directory is then
# caught however early it appeared, rather than being folded into a baseline taken after the fact.
SKILL_DIR_UNTOUCHED = snapshot(HERE)


BUNDLED = ("check_record.py", "lenses.json", "attack-record.schema.json")


def skill_copy(tmp_path: Path, corrupt: dict[str, str | None]) -> Path:
    """A standalone copy of the deployed skill, with its bundled data damaged as asked."""
    dest = tmp_path / "skill"
    dest.mkdir()
    for name in BUNDLED:
        shutil.copy(HERE / name, dest / name)
    for name, content in corrupt.items():
        if content is None:
            (dest / name).unlink()
        else:
            (dest / name).write_text(content, encoding="utf-8")
    return dest


class TestCompleteRound:
    def test_c3_a_fully_adjudicated_round_is_complete(self, attack, capsys):
        """S6-C3: the disposition set covers every proposal id, so the round terminates."""
        code, result = check(attack, attack.record(), capsys)
        assert code == 0
        assert result == closed(attack)

    def test_c3_a_proposal_without_a_disposition_blocks_termination(self, attack, capsys):
        """S6-C3: coverage is decided from the record — one unadjudicated proposal leaves the
        round open, and the checker names which."""
        record = attack.record()
        record["dispositions"] = record["dispositions"][:1]
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unadjudicated-proposal"}
        assert result["errors"][0]["id"] == "p2"

    def test_c3_a_duplicate_or_unknown_proposal_id_is_rejected(self, attack, capsys):
        """S6-C3: a disposition set that adjudicates one proposal twice, or one the round does
        not hold, is not an account of the round."""
        record = attack.record()
        record["dispositions"].append(dict(record["dispositions"][1]))
        assert codes(check(attack, record, capsys)[1]) == {"duplicate-disposition"}
        record = attack.record()
        record["dispositions"].append({"id": "p7", "disposition": "rejected", "rationale": "no"})
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unknown-proposal-id"}
        assert error_of(result, "unknown-proposal-id")["id"] == "p7"

    def test_c3_two_proposals_may_not_share_an_id(self, attack, capsys):
        """S6-C3: the id is what a disposition adjudicates through, so two proposals wearing one
        id leave every disposition naming it ambiguous — refused rather than resolved towards
        either proposal, since the record cannot say which was adjudicated."""
        record = attack.record()
        record["proposals"][1]["id"] = "p1"
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"duplicate-proposal-id", "unknown-proposal-id"}
        assert error_of(result, "duplicate-proposal-id")["id"] == "p1"

    def test_c3_dropping_a_proposal_leaves_the_rest_bound_to_their_dispositions(self, attack,
                                                                                capsys):
        """S6-C3: a malformed proposal is dropped from the round, which moves every proposal after
        it up a position; dispositions name their proposal by id, so the survivors stay paired
        with the adjudication written for them instead of silently re-pointing at a neighbour."""
        attack.write_document(DOCUMENT)
        record = attack.record()
        del record["proposals"][0]
        del record["dispositions"][0]
        record["lenses"] = [
            {"lens": name, "report": "proposals" if name == "absent-requirements" else "empty"}
            for name in LENS_NAMES
        ]
        assert [entry["id"] for entry in record["proposals"]] == ["p2"]
        assert record["dispositions"][0]["id"] == "p2"
        assert check(attack, record, capsys)[0] == 0

    def test_c3_an_acceptance_must_name_the_revision_that_carries_it(self, attack, capsys):
        """S6-C3: accepting with the document unchanged adjudicates nothing — the proposal is
        neither carried into the criteria nor answered — in whichever notation the unchanged
        revision is written; the same acceptance naming the revision that does carry it closes
        the round (inverse)."""
        attack.write_document(DOCUMENT)
        for unchanged in (sha_revision(DOCUMENT), blob_revision(DOCUMENT)):
            record = attack.record()
            record["spec_revision"] = unchanged
            record["dispositions"][0]["revision"] = unchanged
            code, result = check(attack, record, capsys)
            assert code == 1 and codes(result) == {"unincorporated-acceptance"}
            assert error_of(result, "unincorporated-acceptance")["id"] == "p1"
        attack.write_document(REVISED)
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c3_rechecking_a_complete_record_is_a_no_op(self, attack, monkeypatch, capsys):
        """S6-C3: re-running over a complete record decides the same thing from the record and
        changes nothing on disk — not the record or the document, not the checker's own directory,
        and not the directory it was run from, where a scratch file would be easiest to leave. The
        inputs are captured before the first run, so a checker that rewrote any of them would be
        caught rather than compared against itself (repeated invocation)."""
        workdir = attack.root / "run-from-here"
        workdir.mkdir()
        monkeypatch.chdir(workdir)
        path = attack.save(attack.record())
        before = snapshot(attack.root)
        assert set(before) == {attack.document.name, attack.path.name}
        first = run([path], capsys)
        second = run([path], capsys)
        assert first == second == (0, closed(attack))
        assert snapshot(attack.root) == before
        assert snapshot(HERE) == SKILL_DIR_UNTOUCHED
        assert list(workdir.iterdir()) == []


class TestEmptyUnion:
    def test_c4_a_round_where_no_lens_proposes_anything_terminates_clean(self, attack, capsys):
        """S6-C4: the empty union is a first-class outcome, not a degenerate one — every lens
        reported, nothing was proposed, and the round is over."""
        code, result = check(attack, attack.empty_round(), capsys)
        assert code == 0
        assert result == closed(attack, clean=True)


class TestOrdering:
    def test_c4_implementation_claimed_against_an_open_round_violates_the_ordering(self, attack,
                                                                                   capsys):
        """S6-C4: the round runs before implementation; the invoker declares the observation and
        the checker decides against the record, never by consulting a tracker."""
        record = attack.record()
        record["dispositions"] = []
        code, result = check(attack, record, capsys, "--implementation-started")
        assert code == 1
        assert "ordering-violation" in codes(result)
        assert "unadjudicated-proposal" in codes(result)

    def test_c4_the_check_can_reach_nothing_but_the_files_it_is_handed(self):
        """S6-C4: the verdict comes from the record, the document, and the declared observation —
        never from a tracker, which would make the same round decide differently on two machines.
        Held against what the module imports and calls rather than what it says about itself: the
        import allowlist leaves no route to a subprocess, a socket, or an HTTP client, the
        declared dependencies put none of them in reach, and nothing is imported dynamically."""
        source = CHECKER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add("." * node.level + (node.module or "").split(".")[0])
        assert imported == {"__future__", "argparse", "functools", "hashlib", "json", "sys",
                            "pathlib", "typing", "jsonschema"}
        assert '# dependencies = ["jsonschema>=4"]' in source
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not called & {"eval", "exec", "compile", "__import__"}

    def test_c4_a_complete_round_permits_the_work_to_start(self, attack, capsys):
        """S6-C4: inverse — the declaration is not itself a violation once the round is closed."""
        code, result = check(attack, attack.record(), capsys, "--implementation-started")
        assert code == 0 and result["errors"] == []

    def test_c4_implementation_claimed_with_no_record_at_all_violates_the_ordering(self, attack,
                                                                                   capsys):
        """S6-C4: the strongest form of the violation — work claimed where no round exists —
        fails closed rather than reading an absent record as agreement."""
        code, result = run([str(attack.root / "missing.json"), "--implementation-started"], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"unreadable", "ordering-violation"}


class TestStaleness:
    def test_c6_an_unadjudicated_edit_makes_the_round_stale(self, attack, capsys):
        """S6-C6: a later change to the attacked document invalidates the round's completion —
        the old disposition set says nothing about text no attacker has read."""
        attack.write_document(UNRELATED)
        code, result = check(attack, attack.record(), capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"stale-revision"}

    def test_c6_an_edit_an_acceptance_drove_keeps_the_round_current(self, attack, capsys):
        """S6-C6: inverse — a revision an acceptance names accounts for the document, so
        incorporating a proposal cannot invalidate the round that drove the incorporation."""
        record = attack.record()
        assert record["spec_revision"] == sha_revision(DOCUMENT)
        assert attack.document.read_text(encoding="utf-8") == REVISED
        assert check(attack, record, capsys)[0] == 0

    def test_c6_a_document_still_at_the_revision_attacked_does_not_close_an_accepting_round(
            self, attack, capsys):
        """S6-C6: an acceptance says the document was edited to carry the proposal, so a document
        still hashing to the revision attacked means that edit was reverted, lost in a rebase, or
        never made. Closing the round would clear work to start against criteria every accepted
        proposal is absent from — and this is decided, not attested: the checker holds the
        document's bytes and can see they are the pre-attack ones."""
        record = attack.record()
        attack.write_document(DOCUMENT)
        assert record["spec_revision"] == sha_revision(DOCUMENT)
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"stale-revision"}

    def test_c6_a_round_that_accepted_nothing_stands_at_the_revision_it_attacked(self, attack,
                                                                                 capsys):
        """S6-C6: inverse — only an acceptance obliges the document to have moved, so a round that
        proposed nothing, and one whose every proposal was rejected, close over the document
        exactly as attacked."""
        assert check(attack, attack.empty_round(), capsys) == (0, closed(attack, clean=True))
        record = attack.record()
        record["dispositions"][0] = {"id": "p1", "disposition": "rejected",
                                     "rationale": "A1 already covers the unwritable output"}
        attack.write_document(DOCUMENT)
        assert check(attack, record, capsys)[0] == 0

    def test_c6_the_document_must_match_every_revision_an_acceptance_names(self, attack, capsys):
        """S6-C6: the document is one content, so a record whose acceptances name two different
        revisions asks it to be in two states at once — and settling for either one would close
        the round with the other acceptance's criterion provably absent from the text in front of
        the checker, whether its revision names a reverted edit or was never a revision at all.
        An acceptance names the revision the document reached once every accepted proposal was in
        it, and the round closes once they all do (inverse)."""
        record = attack.record()
        record["dispositions"][1] = {"id": "p2", "disposition": "accepted",
                                     "rationale": "a second real hole",
                                     "revision": sha_revision(FURTHER), "covering_ac": "A3"}
        accepted = {disposition["revision"] for disposition in record["dispositions"]}
        assert accepted == {sha_revision(REVISED), sha_revision(FURTHER)}
        for text in (REVISED, FURTHER, UNRELATED):
            attack.write_document(text)
            code, result = check(attack, record, capsys)
            assert code == 1 and codes(result) == {"stale-revision"}
        attack.write_document(FURTHER)
        for disposition in record["dispositions"]:
            disposition["revision"] = sha_revision(FURTHER)
        assert check(attack, record, capsys) == (0, closed(attack))

    def test_c6_an_object_id_names_the_same_content_as_its_digest(self, attack, capsys):
        """S6-C6: the revision is content-addressed in either notation, so a record keyed
        throughout to object ids is checkable against the document itself."""
        record = attack.record()
        record["spec_revision"] = blob_revision(DOCUMENT)
        record["dispositions"][0]["revision"] = blob_revision(REVISED)
        assert check(attack, record, capsys)[0] == 0
        record["dispositions"][0]["revision"] = blob_revision(UNRELATED)
        assert check(attack, record, capsys)[0] == 1


class TestProvenance:
    def test_c6_the_answer_names_the_document_it_was_decided_against(self, attack, tmp_path,
                                                                     capsys):
        """S6-C6: a round checked against a copy handed to --spec answers a different question
        from one checked against the live document — here the same record reads complete against
        a copy holding the revision its acceptance names, while the document beside it has moved
        on to text no attacker read. The answer carries the file it read and what that file hashes
        to, so the substitution is on the record rather than invisible to whoever reads the
        verdict."""
        code, result = check(attack, attack.record(), capsys)
        assert code == 0
        assert result["document"] == str(attack.document)
        assert result["revision"] == sha_revision(REVISED)
        substitute = tmp_path / "substitute.md"
        substitute.write_text(REVISED, encoding="utf-8")
        attack.write_document(UNRELATED)
        assert check(attack, attack.record(), capsys)[0] == 1
        code, result = run([str(attack.path), "--spec", str(substitute)], capsys)
        assert code == 0
        assert result["document"] == str(substitute)
        assert result["revision"] == sha_revision(REVISED)

    def test_c6_an_unfinished_round_names_its_document_too(self, attack, capsys):
        """S6-C6: the pair reports what was read, not what was concluded, so a verdict of stale
        or unfinished says which document it was reached against — the reading a caller most
        needs to check before it edits either one."""
        attack.write_document(UNRELATED)
        code, result = check(attack, attack.record(), capsys)
        assert code == 1 and codes(result) == {"stale-revision"}
        assert result["document"] == str(attack.document)
        assert result["revision"] == sha_revision(UNRELATED)

    def test_c6_the_revision_is_written_in_the_records_own_notation(self, attack, capsys):
        """S6-C6: the reader holds this revision against the record's as a string, so it is
        written the way that record writes revisions; the same content in the other notation
        shares no characters with it and would read as a different document."""
        record = attack.record()
        record["spec_revision"] = blob_revision(DOCUMENT)
        record["dispositions"][0]["revision"] = blob_revision(REVISED)
        code, result = check(attack, record, capsys)
        assert code == 0 and result["revision"] == blob_revision(REVISED)

    def test_c6_a_refusal_reached_after_the_document_was_read_names_it(self, attack, capsys,
                                                                       registry):
        """S6-C6: the pair reports the file the run had in hand, not the verdict it reached, so a
        refusal raised after the document was opened carries it — dropping it there would leave a
        reader unable to tell a run that never opened a document from one that read this one."""
        registry([])
        code, result = check(attack, attack.record(), capsys)
        assert code == 2 and codes(result) == {"no-lenses"}
        assert result["document"] == str(attack.document)
        assert result["revision"] == sha_revision(REVISED)

    def test_c6_an_unexpected_failure_names_the_document_it_had_read(self, attack, capsys,
                                                                     monkeypatch):
        """S6-C6: the catch-all knows least about what went wrong and so gives up least of what it
        does know — anything escaping after the document was hashed is still answered against a
        named file, in the one shape every other answer takes."""
        def broken(*_: Any) -> list[dict[str, Any]]:
            raise RuntimeError("the check itself broke")

        monkeypatch.setattr(checker, "check", broken)
        code, result = check(attack, attack.record(), capsys)
        assert code == 2 and codes(result) == {"checker-failure"}
        assert result["document"] == str(attack.document)
        assert result["revision"] == sha_revision(REVISED)

    @pytest.mark.parametrize("broken", ("no-record", "unreadable", "schema"))
    def test_c6_a_check_that_read_no_document_names_none(self, attack, capsys, broken):
        """S6-C6: the pair is an observation of a file the check opened. A run that failed before
        opening one omits both keys rather than naming a document it never read or padding the
        answer with a null that a caller would have to tell apart from a real reading."""
        record = attack.record()
        record["schema_version"] = "2"
        target = {"no-record": [], "unreadable": [str(attack.root / "absent.json")],
                  "schema": [attack.save(record)]}[broken]
        code, result = run(target, capsys)
        assert code == 2
        assert "document" not in result and "revision" not in result


class TestRevisionNotation:
    @pytest.mark.parametrize("where", ("attacked", "acceptance"))
    def test_c6_a_record_mixing_the_two_notations_is_refused(self, attack, capsys, where):
        """S6-C6: revisions are compared as strings and a hash cannot be turned back into the
        content it names, so a record mixing the notations could pass an unchanged document off as
        an incorporation — the two strings differ while the content is identical. Every revision
        the adjudication reads is held to one notation instead."""
        record = attack.record()
        if where == "attacked":
            record["spec_revision"] = blob_revision(DOCUMENT)
        else:
            record["dispositions"][0]["revision"] = blob_revision(REVISED)
        code, result = check(attack, record, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"mixed-revision-notation"}

    def test_c6_a_revision_left_on_a_rejection_decides_nothing_and_refuses_nothing(self, attack,
                                                                                   capsys):
        """S6-C6: only an acceptance's revision is adjudicated, so one left behind on a
        disposition flipped to rejected is read by nothing. Refusing the record over how it is
        written would send the reader to debug a field that decides no part of the round."""
        record = attack.record()
        record["dispositions"][1]["revision"] = blob_revision(UNRELATED)
        assert check(attack, record, capsys) == (0, closed(attack))

    @pytest.mark.parametrize("where", ("attacked", "acceptance"))
    def test_c6_a_revision_carrying_whitespace_is_refused(self, attack, capsys, where):
        """S6-C6: an agent piping `git hash-object` in gets its trailing newline, and the schema's
        pattern does not catch it — Python's `$` matches before a newline at the end of a string.
        The same content then reads as two revisions: an acceptance can name the very revision it
        attacked, escape the comparison that catches an unincorporated acceptance, and close the
        round over a document nobody edited."""
        attack.write_document(DOCUMENT)
        record = attack.record()
        record["spec_revision"] = sha_revision(DOCUMENT) + ("\n" if where == "attacked" else "")
        record["dispositions"][0]["revision"] = sha_revision(DOCUMENT) + (
            "" if where == "attacked" else "\n")
        assert checker.schema_errors(record) == []
        code, result = check(attack, record, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"untrimmed-revision"}
        assert "git hash-object" in error_of(result, "untrimmed-revision")["message"]

    def test_c6_either_notation_alone_decides_the_round_the_same_way(self, attack, capsys):
        """S6-C6: inverse — a notation is a way of writing a revision, not a different revision,
        so the same round written wholly in digests and wholly in object ids closes either way,
        each answered in the notation the record it decided is written in."""
        digests = attack.record()
        object_ids = copy.deepcopy(digests)
        object_ids["spec_revision"] = blob_revision(DOCUMENT)
        object_ids["dispositions"][0]["revision"] = blob_revision(REVISED)
        assert check(attack, digests, capsys) == (0, closed(attack))
        assert check(attack, object_ids, capsys) == (
            0, closed(attack, revision=blob_revision(REVISED)))


class TestLensCoverage:
    def test_c7_a_lens_that_did_not_report_leaves_the_round_unfinished(self, attack, capsys):
        """S6-C7: a silent or errored attack lens has no entry and the round is incomplete —
        fail closed, never inferring coverage from an empty proposal list."""
        record = attack.empty_round()
        record["lenses"] = [entry for entry in record["lenses"]
                            if entry["lens"] != "criteria-holes"]
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"lens-missing"}
        assert "criteria-holes" in result["errors"][0]["message"]

    def test_c7_lens_reports_must_match_the_declared_set_one_for_one(self, attack, capsys):
        """S6-C7: coverage is a comparison against the declared lens set, so a doubled entry or
        a lens nobody dispatched is a defect in the record."""
        record = attack.empty_round()
        record["lenses"].append({"lens": "criteria-holes", "report": "empty"})
        assert codes(check(attack, record, capsys)[1]) == {"duplicate-lens"}
        record = attack.empty_round()
        record["lenses"].append({"lens": "vibes", "report": "empty"})
        assert codes(check(attack, record, capsys)[1]) == {"unknown-lens"}

    def test_c7_every_proposal_names_its_producing_lens(self, attack, capsys):
        """S6-C7: the record identifies which lens produced each proposal; one that does not is
        not a record."""
        record = attack.record()
        del record["proposals"][0]["lens"]
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    def test_c7_a_proposal_cannot_be_attributed_to_an_undeclared_lens(self, attack, capsys):
        """S6-C7: coverage is read off the declared set, so a proposal credited to a lens nobody
        dispatched is unattributable — and the lens that did report it is left contributing
        nothing, which the record also has to answer for."""
        record = attack.record()
        record["proposals"][0]["lens"] = "vibes"
        code, result = check(attack, record, capsys)
        assert code == 1
        assert codes(result) == {"unknown-proposal-lens", "contradicted-proposals-report"}
        error = error_of(result, "unknown-proposal-lens")
        assert error["id"] == "p1" and "vibes" in error["message"]

    def test_c7_a_lens_reporting_empty_cannot_have_proposals_attributed_to_it(self, attack,
                                                                              capsys):
        """S6-C7: the report and the proposal list are two accounts of one round — a lens that
        said it found nothing, credited with a proposal, means one of them is wrong and the
        record cannot say which."""
        record = attack.record()
        record["proposals"].append(proposal("criteria-holes", "A1", "p3"))
        record["dispositions"].append({"id": "p3", "disposition": "rejected",
                                       "rationale": "already covered by A2"})
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"contradicted-empty-report"}
        assert "criteria-holes" in result["errors"][0]["message"]

    def test_c7_a_lens_reporting_proposals_must_have_contributed_one(self, attack, capsys):
        """S6-C7: the inverse loss — a lens reported holes and the record carries none of them,
        so a proposal an attacker made is a hole nobody will adjudicate."""
        record = attack.record()
        record["proposals"] = record["proposals"][:1]
        record["dispositions"] = record["dispositions"][:1]
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"contradicted-proposals-report"}
        assert "absent-requirements" in result["errors"][0]["message"]

    def test_c7_reports_and_proposals_that_agree_close_the_round(self, attack, capsys):
        """S6-C7: inverse of all three — a record whose reports and proposals are one account,
        with proposals or without any, terminates."""
        assert check(attack, attack.record(), capsys)[0] == 0
        assert check(attack, attack.empty_round(), capsys)[0] == 0


BAD_REGISTRY = [
    ([], "declares no lens"),
    ([{"mandate": "attack it", "tier": "mid", "transport": "codex"}], "without its lens name"),
    ([{"lens": "edge-cases"}, {"lens": "edge-cases"}], "names one lens twice"),
    ([{"lens": "edge-cases"}, {"lens": "Edge-Cases"}], "names one lens twice"),
    ([{"lens": "../edge-cases"}], "not a bare filename"),
    ([{"lens": ".."}], "not a bare filename"),
]


class TestLensRegistry:
    @pytest.mark.parametrize(("lenses", "reason"), BAD_REGISTRY)
    def test_c7_a_registry_the_emitter_would_refuse_closes_no_round(self, attack, capsys, registry,
                                                                    lenses, reason):
        """S6-C7: coverage is read off the declared set, so the set has to be the one the round was
        dispatched from — a registry declaring no lens, an entry without a name, one name twice
        (two names differing only in case are one prompt file on the volumes this runs on), or a
        name that is not a bare filename is one the emitter refuses to emit from, so no round in
        hand came from it and coverage read off it credits attackers that never ran."""
        registry(lenses)
        code, result = check(attack, attack.record(), capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"no-lenses"}
        assert reason in error_of(result, "no-lenses")["message"]

    def test_c7_the_shipped_registry_is_one_the_emitter_would_emit_from(self):
        """S6-C7: inverse — the registry both scripts read passes the check the emitter applies to
        it, so the refusal costs the skill as shipped no round at all."""
        assert list(checker.declared_lenses()) == LENS_NAMES


class TestProposalShape:
    @pytest.mark.parametrize("field", ("id", "lens", "target_ac", "hole", "proposed_ac",
                                       "red_test_sketch"))
    @pytest.mark.parametrize("mutation", ("absent", "blank"))
    def test_c2_every_part_of_a_proposal_is_required_and_carries_content(self, attack, capsys,
                                                                         field, mutation):
        """S6-C2: a proposal is a testable claim in every part — an absent field and a field
        holding only whitespace are the same defect, and either drops the item as malformed
        rather than sending an unattributable or contentless item to adjudication."""
        record = attack.record()
        if mutation == "absent":
            del record["proposals"][0][field]
        elif field == "red_test_sketch":
            record["proposals"][0][field] = {}
        else:
            record["proposals"][0][field] = " \t "
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    @pytest.mark.parametrize("part", ("given", "when", "expect"))
    @pytest.mark.parametrize("mutation", ("absent", "blank"))
    def test_c2_the_sketch_needs_all_three_parts(self, attack, capsys, part, mutation):
        """S6-C2: the three-part sketch is the boundary between a testable claim and a concern —
        a starting state, an action, and an observable outcome, none of them missing or blank."""
        record = attack.record()
        if mutation == "absent":
            del record["proposals"][0]["red_test_sketch"][part]
        else:
            record["proposals"][0]["red_test_sketch"][part] = "  "
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    def test_c2_a_proposal_naming_all_three_parts_is_a_testable_claim(self, attack, capsys):
        """S6-C2: inverse — an item that names a state, an action and an outcome enters the
        round and is adjudicated."""
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c2_prose_in_place_of_a_proposal_is_rejected(self, attack, capsys):
        """S6-C2: a bare worry returned by an attacker never enters the round as a proposal."""
        record = attack.record()
        record["proposals"][0] = {"id": "p1", "lens": "edge-cases", "concern": "this feels risky"}
        assert check(attack, record, capsys)[0] == 2


BAD_ENVELOPE = [
    ("schema_version", DELETE), ("schema_version", "2"), ("schema_version", 1),
    ("spec_path", DELETE), ("spec_path", "   "), ("spec_path", ["ledger-export.md"]),
    ("spec_revision", DELETE), ("spec_revision", "revision-7"), ("spec_revision", "sha256:beef"),
    ("lenses", DELETE), ("lenses", []), ("lenses", "every one of them"),
    ("lenses", [{"lens": "edge-cases"}]), ("lenses", [{"lens": "edge-cases", "report": "maybe"}]),
    ("proposals", DELETE), ("proposals", {"0": "a proposal"}),
    ("dispositions", DELETE), ("dispositions", "none of them"),
    ("dispositions", [{"id": "p1"}]), ("dispositions", [{"id": "p1", "disposition": "deferred"}]),
    ("dispositions", [{"disposition": "rejected", "rationale": "no"}]),
    ("dispositions", [{"id": "  ", "disposition": "rejected", "rationale": "no"}]),
    ("dispositions", [{"id": "p1", "disposition": "accepted"}]),
    ("attacker", "whoever ran the round"),
]

# The fields each verdict needs to be an adjudication at all: an acceptance names where the
# proposal landed, a rejection why it did not.
BAD_DISPOSITION = [
    ("accepted", "revision", DELETE), ("accepted", "covering_ac", DELETE),
    ("accepted", "covering_ac", " \t "),
    ("rejected", "rationale", DELETE), ("rejected", "rationale", "   "),
]


class TestRecordShape:
    @pytest.mark.parametrize(("field", "value"), BAD_ENVELOPE)
    def test_c3_the_records_envelope_is_fixed(self, attack, capsys, field, value):
        """S6-C3: the record's top-level fields are all required and each has a stated shape; a
        field absent, of the wrong type, or outside its vocabulary is not a record, and the check
        says so before deciding anything about the round."""
        record = attack.record()
        if value is DELETE:
            del record[field]
        else:
            record[field] = value
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    @pytest.mark.parametrize(("verdict", "field", "value"), BAD_DISPOSITION)
    def test_c3_each_verdict_carries_the_fields_that_make_it_an_adjudication(self, attack, capsys,
                                                                             verdict, field,
                                                                             value):
        """S6-C3: an acceptance names the revision and criterion that now carry the proposal and a
        rejection states its reason — a field absent and a field holding only whitespace name
        neither. The shape of a disposition is the schema's to fix, so the record is refused as
        unusable before any question about the round is decided from it."""
        record = attack.record()
        entry = next(one for one in record["dispositions"] if one["disposition"] == verdict)
        if value is DELETE:
            del entry[field]
        else:
            entry[field] = value
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}
        assert field in result["errors"][0]["message"]

    def test_c3_the_declared_envelope_is_the_whole_record(self, attack, capsys):
        """S6-C3: inverse — those six fields, correctly shaped, are a record and nothing more is
        expected of it."""
        record = attack.record()
        assert set(record) == set(
            json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required"])
        assert check(attack, record, capsys)[0] == 0


class TestUnusableInput:
    def test_c3_a_missing_record_is_typed_not_a_crash(self, attack, capsys):
        """S6-C3: the checker reports a typed error for input it cannot use (dependency
        failure), rather than raising."""
        code, result = run([str(attack.root / "absent.json")], capsys)
        assert code == 2 and codes(result) == {"unreadable"}

    def test_c3_a_non_json_record_is_typed_not_a_crash(self, attack, capsys):
        """S6-C3: an unparseable record is reported, never treated as an empty round."""
        attack.path.write_text("not json at all", encoding="utf-8")
        code, result = run([str(attack.path)], capsys)
        assert code == 2 and codes(result) == {"invalid-json"}

    def test_c6_a_record_naming_a_document_that_is_gone_is_reported(self, attack, capsys):
        """S6-C6: staleness is decided against the document, so its absence is reported rather
        than passed over."""
        record = attack.record()
        path = attack.save(record)
        attack.document.unlink()
        code, result = run([path], capsys)
        assert code == 2 and codes(result) == {"spec-unreadable"}

    def test_c6_the_document_is_found_beside_the_record_or_by_flag(self, attack, tmp_path, capsys):
        """S6-C6: the record names the document it attacked; the checker resolves it beside the
        record, and --spec points at it when the document has moved."""
        assert check(attack, attack.record(), capsys)[0] == 0
        moved = tmp_path / "elsewhere.md"
        moved.write_text(attack.document.read_text(encoding="utf-8"), encoding="utf-8")
        attack.document.unlink()
        code, _ = run([str(attack.path), "--spec", str(moved)], capsys)
        assert code == 0

    def test_c6_the_document_is_read_beside_the_record_and_nowhere_else(self, attack, tmp_path,
                                                                        monkeypatch, capsys):
        """S6-C6: the record is committed beside the document it names, so that directory is the
        only one the check reads it from; a same-named file in whatever directory the check is run
        from is another document, and a round checked against it decides nothing about this one.
        Absent beside the record, the check says so rather than falling through to that file.
        --spec still points at the document when it has genuinely moved."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / attack.document.name).write_text(UNRELATED, encoding="utf-8")
        path = attack.save(attack.record())
        monkeypatch.chdir(elsewhere)
        assert run([path], capsys)[0] == 0
        code, result = run([path, "--spec", attack.document.name], capsys)
        assert code == 1 and codes(result) == {"stale-revision"}
        attack.document.unlink()
        code, result = run([path], capsys)
        assert code == 2 and codes(result) == {"spec-unreadable"}

    @pytest.mark.parametrize("named", ("../ledger-export.md", "sub/ledger-export.md", "..",
                                       "/tmp/ledger-export.md"))
    def test_c6_a_record_names_its_document_by_bare_filename(self, attack, capsys, named):
        """S6-C6: the record's own directory is the only one the check reads the document from, and
        a spec_path that is not a bare filename leads straight back out of it — naming a document
        this record was not committed beside and no attacker in the round read. Refused rather than
        resolved, since the round would otherwise close over that text."""
        record = attack.record()
        record["spec_path"] = named
        code, result = check(attack, record, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"spec-not-a-bare-filename"}
        assert "document" not in result

    def test_c6_spec_given_without_a_document_is_refused_not_ignored(self, attack, capsys):
        """S6-C6: --spec names the document to decide the round against, so an empty one is a
        caller that meant to name a document and did not — a wrapper passing through an unset
        variable. Reading the record's own document instead would answer a question nobody asked
        and green-light the round against whatever file sits beside the record."""
        for blank in ("", "   "):
            code, result = run([attack.save(attack.record()), "--spec", blank], capsys)
            assert code == 2 and codes(result) == {"no-spec"}
            assert "document" not in result

    def test_c3_output_is_deterministic_and_sorted(self, attack, capsys):
        """S6-C3: two runs over the same broken record print byte-identical JSON, so the result
        can be diffed and stored."""
        record = attack.record()
        record["dispositions"] = []
        record["lenses"] = record["lenses"][1:]
        first = check(attack, copy.deepcopy(record), capsys)
        second = check(attack, copy.deepcopy(record), capsys)
        assert first == second
        emitted = [error["code"] for error in first[1]["errors"]]
        assert emitted == sorted(emitted)

    def test_a_failure_exits_cleanly_from_the_command_line(self, attack):
        """S6-C3: exit status carries the answer and no traceback escapes to stderr."""
        proc = subprocess.run(
            [sys.executable, str(CHECKER_PATH), str(attack.root / "absent.json")],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        assert json.loads(proc.stdout)["complete"] is False

    def test_c3_naming_no_record_answers_in_the_contract(self, attack, capsys):
        """S6-C3: every failure the check documents answers in its JSON contract — naming no
        record at all is unusable input like any other, not an argument-parsing accident that
        escapes the contract, and it is never read as an absence of findings."""
        code, result = run([], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"no-record"}
        code, result = run(["--implementation-started"], capsys)
        assert code == 2 and codes(result) == {"no-record", "ordering-violation"}

    def test_c3_naming_no_record_stays_in_the_contract_from_the_command_line(self, tmp_path):
        """S6-C3: through the command boundary too — stdout is the parsed answer, and argparse's
        usage text on stderr would leave the caller with nothing to read."""
        proc = subprocess.run([sys.executable, str(CHECKER_PATH)], capture_output=True, text=True,
                              check=False, cwd=str(tmp_path))
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr and "usage:" not in proc.stderr
        result = json.loads(proc.stdout)
        assert result["complete"] is False
        assert [error["code"] for error in result["errors"]] == ["no-record"]

    @pytest.mark.parametrize("argv", (["--sepc", "doc.md"], ["record.json", "--spec"]))
    def test_c3_an_unparseable_command_line_answers_in_the_contract(self, tmp_path, argv):
        """S6-C3: argparse exits by itself on an unknown option, or one given without its value,
        which would end the run with usage text on stderr and nothing on stdout. A caller parsing
        stdout must not have to special-case the one failure that predates the parse."""
        proc = subprocess.run([sys.executable, str(CHECKER_PATH), *argv], capture_output=True,
                              text=True, check=False, cwd=str(tmp_path))
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        result = json.loads(proc.stdout)
        assert result["complete"] is False
        assert [error["code"] for error in result["errors"]] == ["bad-arguments"]

    def test_c3_an_unparseable_command_line_still_answers_the_declaration(self, capsys):
        """S6-C3: the declaration is read off the argument list rather than off the parse, so work
        claimed against a round whose command line the check could not even read is still a
        violation — it fails closed like every other form of it."""
        code, result = run(["--sepc", "doc.md", "--implementation-started"], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"bad-arguments", "ordering-violation"}
        assert "document" not in result

    @pytest.mark.parametrize("argv", (["--implementation-started=true"],
                                      ["--sepc", "doc.md", "--implementation-started=true"]))
    def test_c3_the_declaration_is_read_by_option_name_not_by_whole_argument(self, capsys, argv):
        """S6-C3: the declaration takes no value, so an agent writing one — the spelling every
        valued option takes — has argparse reject the command line outright. Matching the argument
        whole would drop the declaration along with the parse, reporting the malformed line while
        the work claimed against the round goes unanswered."""
        code, result = run(argv, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"bad-arguments", "ordering-violation"}

    @pytest.mark.parametrize("damaged", ("lenses.json", "attack-record.schema.json"))
    @pytest.mark.parametrize("damage", (None, "{not json"))
    def test_c3_damaged_bundled_data_is_typed_not_a_traceback(self, attack, tmp_path, damaged,
                                                              damage):
        """S6-C3: the check's own data is a dependency like any other — missing or corrupt, it
        fails typed on stdout, because a traceback is not an answer a caller can parse."""
        record_path = attack.save(attack.record())
        skill = skill_copy(tmp_path, {damaged: damage})
        proc = subprocess.run(
            [sys.executable, str(skill / "check_record.py"), record_path],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        result = json.loads(proc.stdout)
        assert result["complete"] is False
        assert [error["code"] for error in result["errors"]] == ["checker-failure"]

    def test_c3_output_is_byte_identical_through_the_command_boundary(self, attack):
        """S6-C3: two runs of the command over the same inputs print the same bytes, so a stored
        answer can be compared with a fresh one without normalising anything first — for a closed
        round, an unfinished one, and every shape of input the check refuses outright, where a
        message assembled from whatever went wrong is likeliest to vary between runs."""
        unfinished = attack.record()
        unfinished["dispositions"] = []
        unfinished["lenses"] = unfinished["lenses"][1:]
        malformed = attack.record()
        malformed["schema_version"] = "2"
        mixed = attack.record()
        mixed["dispositions"][0]["revision"] = blob_revision(REVISED)
        (attack.root / "prose.json").write_text("not json at all", encoding="utf-8")
        cases = [
            (0, attack.save(attack.record(), "closed.json")),
            (1, attack.save(unfinished, "unfinished.json")),
            (2, str(attack.root / "absent.json")),
            (2, str(attack.root / "prose.json")),
            (2, attack.save(malformed, "malformed.json")),
            (2, attack.save(mixed, "mixed.json")),
        ]
        for expected, target in cases:
            command = [sys.executable, str(CHECKER_PATH), target]
            first = subprocess.run(command, capture_output=True, check=False)
            second = subprocess.run(command, capture_output=True, check=False)
            assert first.returncode == second.returncode == expected, target
            assert first.stdout == second.stdout, target


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
