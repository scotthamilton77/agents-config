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
EMITTER_PATH = HERE / "emit_prompts.py"
LENSES_PATH = HERE / "lenses.json"
SCHEMA_PATH = HERE / "attack-record.schema.json"

DOCUMENT = "# Ledger export\n\n- A1 The exporter writes every settled entry.\n"
REVISED = DOCUMENT + "- A2 The exporter exits non-zero when the output cannot be written.\n"
FURTHER = REVISED + "- A3 Re-running the exporter over the same ledger changes nothing.\n"
UNRELATED = REVISED + "\n## Out of scope\n\nCurrency conversion.\n"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load(CHECKER_PATH)
# The emitter is here to be run, not described: the two scripts deploy and run independently and
# cannot import each other, so what keeps their registry checks identical is a test that loads both
# and holds one loader's verdict against the other's.
emitter = _load(EMITTER_PATH)
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

    def beside(self, record: Any, folder: str) -> str:
        """The same round in a directory of its own, record and document named as the check asks.

        A record is bound to the document it names by the name it wears, so several rounds over one
        document are held apart by their directories rather than by renaming any of them.
        """
        room = self.root / folder
        room.mkdir()
        (room / self.document.name).write_bytes(self.document.read_bytes())
        path = room / self.path.name
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return str(path)


@pytest.fixture
def attack(tmp_path) -> Attack:
    return Attack(tmp_path)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Stand one lens registry in place of the shipped one for both scripts.

    Each script reads its own module-level path, so pointing both at a single file is what makes
    the two loaders answerable to the same registry. The checker's cache is cleared either side.
    """
    def use(lenses: Any) -> None:
        path = tmp_path / "lenses.json"
        path.write_text(json.dumps({"lenses": lenses}), encoding="utf-8")
        monkeypatch.setattr(checker, "LENSES_PATH", path)
        monkeypatch.setattr(emitter, "LENSES_PATH", path)
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
                            "pathlib", "typing", "unicodedata", "jsonschema"}
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

    def test_c6_the_staleness_message_names_the_command_that_reproduces_the_object_id(self, attack,
                                                                                      capsys):
        """S6-C6: the object id is taken over the document's bytes as they stand on disk, while the
        command an agent reaches for to write one down runs whatever clean filter the repository
        configures first — under a line normalising line endings, the same document then hashes
        two ways, and the round reads stale with nothing wrong with it. The message names the option
        that reproduces what the check computed, so the reader repairs the revision rather than the
        document."""
        attack.write_document(UNRELATED)
        code, result = check(attack, attack.record(), capsys)
        assert code == 1 and codes(result) == {"stale-revision"}
        assert "git hash-object --no-filters" in error_of(result, "stale-revision")["message"]

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


class TestRecordBinding:
    def test_c6_a_record_carries_the_name_of_the_document_it_reports_on(self, attack, capsys):
        """S6-C6: the record is committed beside its document and named for it, and that pair of
        names is the whole of what binds the two, since the document is looked for beside the
        record. A record copied under a second document's name then reads as a closed round over a
        document no attacker in it saw — and the copy is in every other way a record in order, so
        nothing else in the check has anything to say about it."""
        assert check(attack, attack.record(), capsys)[0] == 0
        copied = attack.save(attack.record(), "payments-ac-attack.json")
        code, result = run([copied], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"record-name-mismatch"}
        assert "document" not in result

    def test_c6_naming_a_document_to_check_against_does_not_unbind_the_record(self, attack,
                                                                              tmp_path, capsys):
        """S6-C6: --spec moves where the document is read from, never which document the record is
        a round over — that is written inside the record. A binding a caller could lift by naming
        a document on the command line would be no binding at all."""
        substitute = tmp_path / "substitute.md"
        substitute.write_text(REVISED, encoding="utf-8")
        copied = attack.save(attack.record(), "payments-ac-attack.json")
        code, result = run([copied, "--spec", str(substitute)], capsys)
        assert code == 2 and codes(result) == {"record-name-mismatch"}

    @pytest.mark.parametrize(("document", "named"), (("ledger.md", "ledger-ac-attack.json"),
                                                     ("NOTES", "NOTES-ac-attack.json"),
                                                     ("ledger.v2.md", "ledger.v2-ac-attack.json")))
    def test_c6_the_records_name_is_its_documents_without_the_extension(self, attack, capsys,
                                                                        document, named):
        """S6-C6: inverse — the name drops the document's last extension and nothing else, so a
        document with no extension, and one whose name carries a dot of its own, each have a name
        their round can be recorded under."""
        room = attack.root / "round"
        room.mkdir()
        (room / document).write_text(REVISED, encoding="utf-8")
        record = attack.record()
        record["spec_path"] = document
        (room / named).write_text(json.dumps(record, indent=2), encoding="utf-8")
        code, result = run([str(room / named)], capsys)
        assert code == 0 and result["document"] == str(room / document)

    def test_c6_the_path_the_record_was_reached_by_does_not_decide_its_name(self, attack, capsys):
        """S6-C6: the binding is read off the record's own basename, which is what copying it under
        another name changes. The directories above it are how this run was told to reach the
        record and say nothing about which round it holds, so an absolute path and a roundabout one
        name the same record."""
        path = attack.save(attack.record())
        assert run([path], capsys)[0] == 0
        assert run([f"{attack.root}/./{attack.path.name}"], capsys)[0] == 0


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

    @pytest.mark.parametrize("stray", ("a proposal the round does not hold", "one already judged"))
    def test_c6_an_acceptance_the_adjudication_discards_refuses_nothing(self, attack, capsys,
                                                                        stray):
        """S6-C6: an acceptance naming a proposal the round does not hold, and a second acceptance
        of a proposal already adjudicated, are both read by nothing, so the revision on either
        decides nothing either. Refusing the record over how one of them is written answers
        fatally, and hides the error naming the disposition itself — the one the reader has to act
        on, and the one the notation check is there to keep out of the way of."""
        record = attack.record()
        record["dispositions"].append({
            "id": "p7" if stray.startswith("a proposal") else "p1", "disposition": "accepted",
            "revision": blob_revision(FURTHER), "covering_ac": "A9"})
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unknown-proposal-id" if stray.startswith("a proposal")
                                 else "duplicate-disposition"}

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

    def test_c7_a_lens_reporting_twice_is_a_defect_in_the_record(self, attack, capsys):
        """S6-C7: coverage is read off one entry per lens, so a doubled entry is two accounts of
        one attacker — and the two may disagree, leaving nothing to read the lens's result off."""
        record = attack.empty_round()
        record["lenses"].append({"lens": "criteria-holes", "report": "empty"})
        assert codes(check(attack, record, capsys)[1]) == {"duplicate-lens"}

    def test_c7_every_proposal_names_its_producing_lens(self, attack, capsys):
        """S6-C7: the record identifies which lens produced each proposal; one that does not is
        not a record."""
        record = attack.record()
        del record["proposals"][0]["lens"]
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    def test_c7_a_proposal_credited_elsewhere_leaves_its_lens_contributing_nothing(self, attack,
                                                                                    capsys):
        """S6-C7: a lens's only proposal credited to a name the record does not report is two
        losses at once, and the record answers for both — the proposal traces to no attacker, and
        the lens that made it is left reporting proposals the round holds none of. Either alone
        refuses the record; a record showing both is told both, since repairing the attribution is
        one edit and repairing the report is another."""
        record = attack.record()
        record["proposals"][0]["lens"] = "vibes"
        code, result = check(attack, record, capsys)
        assert code == 1
        assert codes(result) == {"unreported-proposal-lens", "contradicted-proposals-report"}
        assert "edge-cases" in error_of(result, "contradicted-proposals-report")["message"]
        assert error_of(result, "unreported-proposal-lens")["id"] == "p1"

    def test_c7_a_proposal_traces_to_a_lens_that_reported_in_this_round(self, attack, capsys):
        """S6-C7: a lens that produced a proposal reported, so a proposal attributed to a name the
        record files no report for traces to no attacker at all — nothing in the round says that
        lens looked, and the proposal is adjudicated as though one had.

        The record here exits 0 without this check, and that is the case it exists for: `edge-cases`
        produced two proposals and one attribution is misspelled, so the lens keeps the other, its
        report is contradicted by nothing, and every other lens is self-consistent. The check that
        holds a report against its proposals cannot see this, and the one that reads coverage sees a
        lens set that matches. Three attribution checks that look redundant are three directions,
        and this is the only one watching a proposal whose lens is not in the record at all."""
        record = attack.record()
        record["lenses"] = [
            {"lens": name, "report": "proposals" if name == "edge-cases" else "empty"}
            for name in LENS_NAMES
        ]
        record["proposals"] = [proposal("edge-cases", "A1", "p1"),
                               proposal("edge_cases", "none", "p2")]
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unreported-proposal-lens"}
        error = error_of(result, "unreported-proposal-lens")
        assert error["id"] == "p2" and "edge_cases" in error["message"]

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

    def test_c7_a_name_differing_only_in_case_is_the_same_lens(self, attack, capsys):
        """S6-C7: a lens's name is its prompt's filename, and the volumes this runs on match names
        without regard to case or to Unicode form — so two spellings of one name were one file and
        one attacker. Held apart, the record would be told a lens is missing while the same name
        stands in it, a difference the message cannot show the reader."""
        record = attack.record()
        for entry in record["lenses"]:
            if entry["lens"] == "edge-cases":
                entry["lens"] = "Edge-Cases"
        assert check(attack, record, capsys) == (0, closed(attack))

    def test_c7_two_spellings_of_one_name_are_one_lens_reporting_twice(self, attack, capsys):
        """S6-C7: the same matching in the other direction — an entry under each spelling is not
        two lenses covering the document, it is one lens with two accounts of what it found."""
        record = attack.record()
        record["lenses"].append({"lens": "EDGE-CASES", "report": "proposals"})
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"duplicate-lens"}


COMPLETE_ENTRY = {"lens": "edge-cases", "mandate": "walk the taxonomy", "tier": "mid",
                  "transport": "openrouter"}


def lens_entry(**damage: Any) -> dict[str, Any]:
    """A registry entry both scripts accept, carrying one row's damage and nothing else.

    Every case has to isolate the field it names: an entry damaged twice over is refused for the
    first defect either script happens to look for, which is agreement neither one was tested for.
    """
    return {key: value for key, value in {**COMPLETE_ENTRY, **damage}.items() if value is not DELETE}


# Every way a registry can be damaged, and the shipped one at the head. The two scripts have to
# read each of these the same way: both take the lens set off it, or both refuse it.
REGISTRIES = [
    ("the shipped lens set", [lens_entry(lens=name) for name in LENS_NAMES]),
    ("no lens at all", []),
    ("an entry without its lens name", [lens_entry(lens=DELETE)]),
    ("a lens named with nothing", [lens_entry(lens="")]),
    ("a lens named with whitespace", [lens_entry(lens=" \t ")]),
    ("a lens name that climbs out of the round's directory", [lens_entry(lens="../edge-cases")]),
    ("a lens named for a directory", [lens_entry(lens="..")]),
    ("a lens name that is not a string", [lens_entry(lens=7)]),
    ("two lenses differing only in case", [lens_entry(), lens_entry(lens="Edge-Cases")]),
    # Escaped rather than written out: one composed character against the same character
    # written as a letter and a combining accent, which no reader tells apart on the page —
    # and one prompt file is what the filesystem makes of the pair.
    ("two lenses differing only in Unicode form",
     [lens_entry(lens="caf\u00e9-cases"), lens_entry(lens="cafe\u0301-cases")]),
    ("a lens with no mandate", [lens_entry(mandate=DELETE)]),
    ("a lens whose mandate is blank", [lens_entry(mandate="")]),
    ("a lens whose mandate is whitespace", [lens_entry(mandate="  ")]),
    ("a lens whose mandate is not a string", [lens_entry(mandate=42)]),
    ("a lens with no tier", [lens_entry(tier=DELETE)]),
    ("a lens whose tier is blank", [lens_entry(tier=" ")]),
    ("a lens with no transport", [lens_entry(transport=DELETE)]),
    ("a lens whose transport is not a string", [lens_entry(transport=["codex"])]),
]

BAD_REGISTRY = [
    ([], "declares no lens"),
    ([lens_entry(lens=DELETE)], "the entry at position 0 without a usable lens"),
    ([lens_entry(lens="  ")], "the entry at position 0 without a usable lens"),
    ([lens_entry(mandate="")], "edge-cases without a usable mandate"),
    ([lens_entry(tier=DELETE)], "edge-cases without a usable tier"),
    ([lens_entry(transport=DELETE)], "edge-cases without a usable transport"),
    ([lens_entry(), lens_entry()], "names one lens twice"),
    ([lens_entry(), lens_entry(lens="Edge-Cases")], "names one lens twice"),
    ([lens_entry(lens="../edge-cases")], "not a bare filename"),
    ([lens_entry(lens="..")], "not a bare filename"),
]


def read_registry(load: Any, refusal: type[Exception]) -> list[str] | None:
    """The lens names one script's loader takes off the registry, or None where it refuses it.

    Only the typed refusal is caught: a registry that makes either script raise something else has
    it answering `checker-failure` or `emitter-failure` where the other names the defect, which is
    a difference worth a traceback here rather than a pass.
    """
    try:
        return load()
    except refusal:
        return None


def checker_lenses() -> list[str]:
    return list(checker.declared_lenses())


def emitter_lenses() -> list[str]:
    return [entry["lens"] for entry in emitter.load_lenses()]


class TestLensRegistry:
    @pytest.mark.parametrize(("lenses", "reason"), BAD_REGISTRY)
    def test_c7_a_registry_the_emitter_would_refuse_closes_no_round(self, attack, capsys, registry,
                                                                    lenses, reason):
        """S6-C7: coverage is read off the declared set, so the set has to be the one the round was
        dispatched from — a registry declaring no lens, an entry short a key it owes or holding it
        blank, one name twice (two names differing only in case are one prompt file on the volumes
        this runs on), or a name that is not a bare filename is one the emitter refuses to emit
        from, so no round in hand came from it and coverage read off it credits attackers that
        never ran. The refusal names the entry at fault, since a registry is repaired entry by
        entry."""
        registry(lenses)
        code, result = check(attack, attack.record(), capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"no-lenses"}
        assert reason in error_of(result, "no-lenses")["message"]

    @pytest.mark.parametrize(("description", "lenses"), REGISTRIES)
    def test_c7_both_scripts_read_a_registry_the_same_way(self, registry, description, lenses):
        """S6-C7: the emitter decides which registries dispatch a round and the checker credits
        coverage off the same file, so a registry one accepts and the other refuses is either a
        round nothing can close or — the dangerous direction — a lens counted as an attacker that
        ran when no prompt for it was ever emitted. Held by running both loaders over one registry
        rather than by reading either: they deploy as separate scripts that cannot import each
        other, and hand-maintained agreement between two files is exactly what fails silently."""
        registry(lenses)
        assert read_registry(checker_lenses, checker.RecordError) == read_registry(
            emitter_lenses, emitter.Refusal), description

    def test_c7_the_shipped_registry_is_one_the_emitter_would_emit_from(self):
        """S6-C7: inverse — over the bundled file itself, not a copy of its contents, both scripts
        take the same lens set off it, so the refusal costs the skill as shipped no round at all."""
        assert list(checker.declared_lenses()) == LENS_NAMES == emitter_lenses()


class TestRetiredLens:
    def test_c7_a_lens_the_registry_no_longer_declares_closes_the_round_it_ran_in(self, attack,
                                                                                  capsys,
                                                                                  registry):
        """S6-C7: coverage is containment — every declared lens owes a report, and a report beyond
        them is a lens since retired or renamed. That record holds more coverage than the registry
        now asks for, which is surplus and not a defect; refusing it would leave every committed
        record naming that lens unclosable for good, over an attack that did run and that no edit
        to the record can undo."""
        registry([lens_entry(lens=name) for name in LENS_NAMES if name != "criteria-holes"])
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c7_a_proposal_a_retired_lens_produced_is_adjudicated_not_refused(self, attack, capsys,
                                                                              registry):
        """S6-C7: the proposals a retired lens contributed are the round's work and the record
        adjudicates them. This is what fixes the shape of the attribution check: a proposal is held
        against the lenses this record reports, which include the retired one, and never against the
        registry, which no longer names it. Read off the registry, the check would refuse every
        record holding a retired attacker's findings — the loss containment exists to avoid."""
        registry([lens_entry(lens=name) for name in LENS_NAMES if name != "edge-cases"])
        record = attack.record()
        assert record["proposals"][0]["lens"] == "edge-cases"  # attributed to the retired lens
        assert "edge-cases" in [entry["lens"] for entry in record["lenses"]]
        assert check(attack, record, capsys) == (0, closed(attack))

    def test_c7_a_lens_added_to_the_registry_still_reopens_the_rounds_it_never_faced(self, attack,
                                                                                     capsys,
                                                                                     registry):
        """S6-C7: containment runs one way. A lens the registry declares and the record does not
        report is coverage the round never obtained, so the round stays open until that attacker
        runs — which is what makes adding a lens reopen the rounds that predate it."""
        registry([lens_entry(lens=name) for name in [*LENS_NAMES, "protocol-drift"]])
        code, result = check(attack, attack.record(), capsys)
        assert code == 1 and codes(result) == {"lens-missing"}
        assert "protocol-drift" in error_of(result, "lens-missing")["message"]

    def test_c7_a_lens_name_misspelled_leaves_the_lens_it_meant_unreported(self, attack, capsys):
        """S6-C7: containment lets no name through unchecked — a report filed under a name the
        registry does not declare covers nothing, and the declared lens it was meant to be is
        missing from the record."""
        record = attack.empty_round()
        for entry in record["lenses"]:
            if entry["lens"] == "edge-cases":
                entry["lens"] = "edge_cases"
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"lens-missing"}
        assert "edge-cases" in error_of(result, "lens-missing")["message"]


def refusal_code(load: Any, refusal: type[Exception]) -> str | None:
    """The code one script refuses a document with, or None where it takes the document.

    Only the typed refusal is caught: a document that makes either script raise something else has
    it answering `checker-failure` or `emitter-failure` where the other names the defect, which is
    a difference worth a traceback here rather than a pass.
    """
    try:
        load()
    except refusal as exc:
        return exc.code
    return None


# Every shape of document either script decides about, the one a round attacks at the head. Both
# have to read each the same way: both take it as attackable, or both refuse it with one code. A
# document that is not there is left out — the checker resolves the path its record names and
# reports that absence itself, while the emitter is handed the path and refuses for want of a
# document.
DOCUMENTS = [
    ("the document a round attacks", DOCUMENT.encode("utf-8")),
    ("a document holding nothing", b""),
    ("a document of whitespace", b" \t\r\n"),
    # Escaped, since no reader sees one on the page: a non-breaking space is whitespace to a
    # reader and to `strip`, and is not a byte a comparison of bytes would call empty.
    ("a document of a non-breaking space", "\u00a0".encode()),
    ("a document that is not UTF-8 text", "# Café ledger\n".encode("latin-1")),
    ("a document holding half a surrogate pair", b"# Ledger\n\xed\xa0\x80\n"),
    ("a document that opens an untrusted section", f"{emitter.FENCE_OPEN}\n{DOCUMENT}".encode()),
    ("a document that closes one", f"{DOCUMENT}{emitter.FENCE_CLOSE}\n".encode()),
    ("a document that is nothing but a marker", emitter.FENCE_CLOSE.encode()),
    ("a document behind a byte-order mark", "\ufeff".encode() + DOCUMENT.encode()),
    ("a document of a byte-order mark alone", "\ufeff".encode()),
    ("a document holding a NUL", b"\x00" + DOCUMENT.encode()),
]


class TestDocumentRefusal:
    @pytest.mark.parametrize(("description", "content"), DOCUMENTS)
    def test_c6_both_scripts_read_a_document_the_same_way(self, tmp_path, description, content):
        """S6-C6: the emitter decides which documents a round goes out over, and the checker which
        a record may close over. A document the emitter refuses dispatched no attacker, so a record
        closing a round over one was written by hand and closing it clears work to start against
        criteria nobody attacked — an empty stub, bytes that are not text at all, or a document
        carrying a fence marker of its own, which cannot be fenced without being rewritten. Held by
        running both over one file rather than by reading either: they deploy as separate scripts
        that cannot import each other, so each carries its own copy of the refusal, and
        hand-maintained agreement between two files is what fails silently."""
        path = tmp_path / "ledger.md"
        path.write_bytes(content)
        emitted = refusal_code(lambda: emitter.read_document(str(path)), emitter.Refusal)
        checked = refusal_code(
            lambda: checker.require_attackable_document(path, path.read_bytes()),
            checker.RecordError,
        )
        assert emitted == checked, description

    @pytest.mark.parametrize(("content", "refused"),
                             ((b"# Caf\xe9 ledger\n\n- A1 The exporter writes.\n", "no-spec"),
                              (f"{REVISED}{emitter.FENCE_CLOSE}\n".encode(),
                               "spec-contains-marker")))
    def test_c6_a_document_no_round_could_have_attacked_closes_none(self, attack, capsys, content,
                                                                     refused):
        """S6-C6: the refusal is reached through the whole check and answered in its contract,
        naming the file it was decided over — a document the emitter would have turned away is not
        one an attacker read, whatever the record says about it."""
        attack.document.write_bytes(content)
        record = attack.empty_round()
        record["spec_revision"] = "sha256:" + hashlib.sha256(content).hexdigest()
        code, result = check(attack, record, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {refused}
        assert result["document"] == str(attack.document)


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

    def test_c3_a_key_written_twice_is_refused_rather_than_resolved(self, attack, capsys):
        """S6-C3: JSON keeps the last of a repeated key, so a record carrying `dispositions` twice
        is adjudicated on the second alone while the first is what stands in the text a reader
        reviews — the bytes reviewed and the bytes decided over are then two records, and nothing
        says so. The schema cannot catch it either: the repeat is gone before it validates, so what
        forbids unknown properties never sees a second one."""
        record = attack.record()
        body = json.dumps(record, indent=2)
        doubled = '{\n  "dispositions": [],' + body[1:]
        # The last key wins, so the adjudication below reads a record no reader of the file sees.
        assert json.loads(doubled) == record
        attack.path.write_text(doubled, encoding="utf-8")
        code, result = run([str(attack.path)], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"invalid-json"}

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

    # The last is a non-breaking space, escaped because a reader cannot see one otherwise.
    @pytest.mark.parametrize("blank", ("", "   \n\t\n", "\u00a0"))
    def test_c6_a_document_with_nothing_in_it_closes_no_round(self, attack, capsys, blank):
        """S6-C6: the emitter refuses to emit over a document with nothing in it, so no round in
        hand attacked one — a record closing a round over an empty stub was written by hand, and
        closing it here clears work to start against criteria nobody wrote. Both scripts are run
        over the one file, since what has to hold is that they refuse the same document and not
        merely that each refuses something; emptiness is judged as text in both, so a document of
        nothing but a non-breaking space is empty to both. The refusal names the file it read, and
        a document that states anything at all is attacked and closed (inverse)."""
        record = attack.empty_round()
        record["spec_revision"] = attack.write_document(blank)
        with pytest.raises(emitter.Refusal) as refused:
            emitter.read_document(str(attack.document))
        assert refused.value.code == "no-spec"
        code, result = check(attack, record, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"no-spec"}
        assert result["document"] == str(attack.document)
        assert result["revision"] == sha_revision(blank)
        record["spec_revision"] = attack.write_document(blank + DOCUMENT)
        assert emitter.read_document(str(attack.document))[0] == blank + DOCUMENT
        assert check(attack, record, capsys) == (0, closed(attack, clean=True))

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
                                      ["--implementation-started=yes"],
                                      ["--implementation-started=maybe"],
                                      ["--implementation-started="],
                                      ["--sepc", "doc.md", "--implementation-started=true"]))
    def test_c3_the_declaration_is_read_by_option_name_not_by_whole_argument(self, capsys, argv):
        """S6-C3: the declaration takes no value, so an agent writing one — the spelling every
        valued option takes — has argparse reject the command line outright. Matching the argument
        whole would drop the declaration along with the parse, reporting the malformed line while
        the work claimed against the round goes unanswered. Anything written there that is not a
        denial declares, an unreadable value included, since that direction fails closed."""
        code, result = run(argv, capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"bad-arguments", "ordering-violation"}

    @pytest.mark.parametrize("value", ("false", "FALSE", "0", "no", "off", " false "))
    def test_c3_a_declaration_written_as_a_denial_declares_nothing(self, attack, capsys, value):
        """S6-C3: `--implementation-started=false` says the work has not started. The flag takes no
        value, so argparse rejects the command line whichever way that argument is read and the run
        refuses either way — what is at stake is the answer, and decorating the refusal with an
        ordering violation tells the operator that work was claimed against the round, which is the
        opposite of what they wrote."""
        code, result = run([attack.save(attack.record()), f"--implementation-started={value}"],
                           capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"bad-arguments"}

    @pytest.mark.parametrize("value", ("false", "FALSE", "0", "no", "off", " false "))
    def test_c3_a_denial_written_after_the_flag_declares_nothing_either(self, attack, capsys,
                                                                        value):
        """S6-C3: `--implementation-started false` is that same denial in the other spelling a
        valued option takes, and the likelier one to reach for — it needs no reminder that the
        flag takes no value. Read as the bare flag, the answer would tell the operator that work was
        claimed against the round, which is the opposite of what they wrote."""
        code, result = run([attack.save(attack.record()), checker.DECLARATION, value], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"bad-arguments"}

    def test_c3_the_record_named_after_the_flag_is_not_read_as_a_denial(self, attack, capsys):
        """S6-C3: only a denial is read out of the argument following the flag, so a command line
        naming the record there declares as it reads. Swallowing whatever follows would leave work
        claimed against an open round unanswered — in the one spelling that parses cleanly, where
        nothing else in the result hints that the declaration was dropped."""
        attack.write_document(DOCUMENT)
        record = attack.record()
        record["dispositions"] = []
        code, result = run([checker.DECLARATION, attack.save(record)], capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unadjudicated-proposal", "ordering-violation"}

    def test_c3_one_finding_is_reported_once(self, attack, capsys):
        """S6-C3: a record repeating a lens entry contradicts its proposal list once per copy, and
        the two errors are byte-identical — a reader counting findings would see two defects where
        the record holds one, and the repeat says nothing the first did not."""
        record = attack.record()
        entry = next(one for one in record["lenses"] if one["lens"] == "absent-requirements")
        record["lenses"].append(dict(entry))
        record["proposals"] = record["proposals"][:1]
        record["dispositions"] = record["dispositions"][:1]
        code, result = check(attack, record, capsys)
        assert code == 1
        assert codes(result) == {"duplicate-lens", "contradicted-proposals-report"}
        assert len(result["errors"]) == 2

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
            (0, attack.beside(attack.record(), "closed")),
            (1, attack.beside(unfinished, "unfinished")),
            (2, str(attack.root / "absent.json")),
            (2, str(attack.root / "prose.json")),
            (2, attack.beside(malformed, "malformed")),
            (2, attack.beside(mixed, "mixed")),
        ]
        for expected, target in cases:
            command = [sys.executable, str(CHECKER_PATH), target]
            first = subprocess.run(command, capture_output=True, check=False)
            second = subprocess.run(command, capture_output=True, check=False)
            assert first.returncode == second.returncode == expected, target
            assert first.stdout == second.stdout, target


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
