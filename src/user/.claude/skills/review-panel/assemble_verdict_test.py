#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the review-panel round assembler.

The rounds under test are emitted by the real prompt emitter and claimed through
the real dispatch gate, so the metadata and the attempt ledger the assembler reads
are the ones those scripts actually write.

Run: uv run assemble_verdict_test.py
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
ASSEMBLER_PATH = HERE / "assemble_verdict.py"
EMITTER_PATH = HERE / "emit_prompts.py"
GATE_PATH = HERE / "dispatch_gate.py"
CONTRACTS_PATH = HERE / "contracts.json"
# Source-tree-only paths to the real verdict skill, for exercising strict validation
# explicitly. The assembler itself never assumes this layout — see SCHEMA_CANDIDATES
# in assemble_verdict.py.
REVIEW_VERDICT = (
    HERE / ".." / ".." / ".." / ".agents" / "skills" / "review-verdict"
).resolve()
REVIEW_VERDICT_SCHEMA = REVIEW_VERDICT / "verdict.schema.json"
VALIDATOR = REVIEW_VERDICT / "validate_verdict.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


assembler = _load(ASSEMBLER_PATH, "assemble_verdict")
emitter = _load(EMITTER_PATH, "emit_prompts")
gate = _load(GATE_PATH, "dispatch_gate")

CONTRACTS = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))
LENSES = [lens["lens"] for lens in CONTRACTS["classes"]["typed-code"]["lenses"]]
# What each lens actually ran on this round. Two vendors, so a collapse onto one is a
# visible change rather than the fixture's own shape.
ROUTES = {
    "correctness": ("openai", "codex", "gpt-5.6-sol"),
    "security": ("moonshotai", "openrouter", "moonshotai/kimi-k2.7-code"),
    "test-adequacy": ("openai", "codex", "gpt-5.6-sol"),
    "simplification-efficiency": ("moonshotai", "openrouter", "moonshotai/kimi-k2.7-code"),
    "documentation-quality": ("openai", "codex", "gpt-5.6-sol"),
}


def run_json(main: Any, argv: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    return code, json.loads(buffer.getvalue())


def mechanical(finding_id: str, lens: str, **overrides: Any) -> dict:
    finding = {
        "id": finding_id, "lens": lens, "type": "mechanical", "ac": "C1",
        "claim": f"{finding_id}: the reader drops the trailing record",
        "evidence": f"tests/test_reader.py::test_{finding_id.lower()} fails at head",
    }
    finding.update(overrides)
    return finding


def advisory(finding_id: str, lens: str, **overrides: Any) -> dict:
    finding = {
        "id": finding_id, "lens": lens, "type": "advisory", "ac": "C2",
        "claim": f"{finding_id}: the temp path is world-readable",
    }
    finding.update(overrides)
    return finding


class Round:
    """One emitted, claimed round, ready to be assembled."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.repo = workspace / "repo"
        self.repo.mkdir(parents=True)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "panel@example.test")
        self.git("config", "user.name", "Panel Test")
        (self.repo / "a.txt").write_text("one\n", encoding="utf-8")
        self.base = self.commit("one")
        self.git("checkout", "-b", "feature")
        (self.repo / "a.txt").write_text("two\n", encoding="utf-8")
        self.head = self.commit("two")
        self.staffing = workspace / "staffing.json"
        self.staffing.write_text(json.dumps({
            "lenses": list(LENSES), "excluded": [],
            "recommending_model": "moonshotai/kimi-k2.7-code",
            "decision": "as-recommended", "force_full": False,
        }), encoding="utf-8")
        self.acs = workspace / "criteria.md"
        self.acs.write_text("- C1: the reader returns every record.\n", encoding="utf-8")
        self.dir = self.emit(1, workspace / "round-1")
        self.claim_all(self.dir)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True,
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def emit(self, number: int, out_dir: Path, *extra: str) -> Path:
        gates = self.workspace / f"gates-{number}.json"
        gates.write_text(json.dumps(
            [{"gate": "ac-derived-test-gate", "exit_status": 0, "head_sha": self.head}],
        ), encoding="utf-8")
        code, answer = run_json(emitter.main, [
            "--class", "typed-code", "--artifact-type", "typed-code", "--claim", "claim-7",
            "--round", str(number), "--acs", str(self.acs), "--target", "pull request 7",
            "--repo-root", str(self.repo), "--base-sha", self.base, "--head-sha", self.head,
            "--target-branch", "main", "--retained", "[]", "--staffing", str(self.staffing),
            "--gate-evidence", str(gates), "--schema", str(REVIEW_VERDICT_SCHEMA),
            "--out-dir", str(out_dir), *extra,
        ])
        assert code == 0, answer
        return out_dir

    def claim_all(self, out_dir: Path) -> None:
        for lens in self.staffed(out_dir):
            _, transport, model = ROUTES[lens]
            code, answer = run_json(gate.main, [
                "claim", "--out-dir", str(out_dir), "--lens", lens,
                "--transport", transport, "--model", model, "--reason", "initial",
            ])
            assert code == 0, answer

    def staffed(self, out_dir: Path | None = None) -> list[str]:
        return [entry["lens"] for entry in self.meta(out_dir)["lenses"]]

    def meta(self, out_dir: Path | None = None) -> dict:
        directory = out_dir or self.dir
        return json.loads((directory / "round.json").read_text(encoding="utf-8"))

    def reports(self, dest: Path, findings: dict[str, list[dict]] | None = None,
                overrides: dict[str, dict] | None = None,
                round_dir: Path | None = None) -> list[str]:
        """One report file per staffed lens; returns the --report flags naming them."""
        raised = findings or {}
        dest.mkdir(parents=True, exist_ok=True)
        flags: list[str] = []
        for lens in self.staffed(round_dir):
            body = {"lens": lens, "verdict": "findings" if raised.get(lens) else "clean",
                    "findings": raised.get(lens, [])}
            body.update((overrides or {}).get(lens, {}))
            path = dest / f"{lens}.report.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            flags += ["--report", f"{lens}={path}"]
        return flags

    def routes(self, dest: Path, overrides: dict[str, dict] | None = None,
               lenses: list[str] | None = None) -> Path:
        entries = []
        for lens in (lenses if lenses is not None else self.staffed()):
            vendor, transport, model = ROUTES[lens]
            entry = {"lens": lens, "vendor": vendor, "transport": transport, "model": model}
            entry.update((overrides or {}).get(lens, {}))
            entries.append(entry)
        path = dest / "routes.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return path

    def clone(self, dest: Path) -> Path:
        shutil.copytree(self.dir, dest)
        return dest


@pytest.fixture(scope="session")
def round1(tmp_path_factory) -> Round:
    return Round(tmp_path_factory.mktemp("panel"))


@pytest.fixture
def dest(tmp_path) -> Path:
    out = tmp_path / "work"
    out.mkdir()
    return out


def assemble(round_: Round, dest: Path, *, round_dir: Path | None = None,
             findings: dict[str, list[dict]] | None = None,
             reports: list[str] | None = None, routes: Path | None = None,
             extra: list[str] | None = None) -> tuple[int, dict, Path]:
    directory = round_dir or round_.dir
    flags = reports if reports is not None else round_.reports(dest, findings)
    route_file = routes if routes is not None else round_.routes(dest)
    out = dest / "verdict.json"
    code, answer = run_json(assembler.main, [
        "--round-dir", str(directory), *flags, "--routes", str(route_file),
        "--out", str(out), "--schema", str(REVIEW_VERDICT_SCHEMA), *(extra or []),
    ])
    return code, answer, out


def validate(verdict: Path, staffing: Path | None = None) -> tuple[int, dict]:
    """The shared review-verdict validator, invoked as a check run would."""
    argv = [sys.executable, str(VALIDATOR), str(verdict)]
    if staffing is not None:
        argv += ["--staffing", str(staffing)]
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def suppressions_of(out: Path) -> list[dict]:
    return json.loads((out.parent / "suppressions.json").read_text(encoding="utf-8"))


class TestRoundTrip:
    def test_b11_a_clean_round_assembles_and_validates(self, round1, dest):
        """Every staffed lens reports clean: the envelope validates against the schema
        and against the staffing record the round was dispatched from."""
        code, answer, out = assemble(round1, dest)
        assert code == 0, answer
        assert answer["verdict"] == "clean"
        assert (answer["mechanical"], answer["advisory"], answer["suppressed"]) == (0, 0, 0)
        assert validate(out, round1.staffing) == (0, {"valid": True})
        verdict = json.loads(out.read_text(encoding="utf-8"))
        assert verdict["schema_version"] == "3"
        assert [entry["lens"] for entry in verdict["lenses"]] == round1.staffed()
        assert verdict["staffing_record"] == round1.meta()["staffing_record"]

    def test_b11_a_findings_round_assembles_and_validates(self, round1, dest):
        code, answer, out = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness")],
            "security": [advisory("F9", "security")],
        })
        assert code == 0, answer
        assert answer["verdict"] == "findings"
        assert (answer["mechanical"], answer["advisory"]) == (1, 1)
        assert validate(out, round1.staffing) == (0, {"valid": True})

    def test_b11_the_envelope_carries_the_rounds_own_identity(self, round1, dest):
        code, _, out = assemble(round1, dest)
        assert code == 0
        verdict = json.loads(out.read_text(encoding="utf-8"))
        meta = round1.meta()
        for field in ("artifact_class", "round", "base_sha", "head_sha", "claim_id",
                      "retained_categories"):
            assert verdict[field] == meta[field], field

    def test_a_findings_lens_attribution_is_forced_to_the_reporting_lens(self, round1, dest):
        """A lens cannot file a finding under another lens's name."""
        code, _, out = assemble(round1, dest, findings={
            "security": [mechanical("F1", "correctness")],
        })
        assert code == 0
        verdict = json.loads(out.read_text(encoding="utf-8"))
        assert verdict["findings"][0]["lens"] == "security"

    def test_the_verdict_file_is_deterministic(self, round1, dest):
        first = assemble(round1, dest, findings={"correctness": [mechanical("F1", "correctness")]})
        text = first[2].read_text(encoding="utf-8")
        second = assemble(round1, dest, findings={"correctness": [mechanical("F1", "correctness")]})
        assert second[2].read_text(encoding="utf-8") == text
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


class TestCoverage:
    def test_b11_a_staffed_lens_with_no_report_refuses(self, round1, dest):
        """Fail closed: silence is incompleteness, never a clean lens."""
        flags = round1.reports(dest)
        code, answer, out = assemble(round1, dest, reports=flags[:-2])
        assert code == 2
        assert answer["errors"][0]["code"] == "incomplete-round"
        assert round1.staffed()[-1] in answer["errors"][0]["message"]
        assert not out.exists()

    def test_b11_the_complete_set_of_reports_assembles(self, round1, dest):
        """The acceptance twin: every staffed lens reporting is what completes the round."""
        code, answer, _ = assemble(round1, dest)
        assert code == 0, answer

    def test_a_staffed_lens_with_no_route_refuses(self, round1, dest):
        code, answer, _ = assemble(
            round1, dest, routes=round1.routes(dest, lenses=round1.staffed()[:-1])
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "incomplete-round"
        assert round1.staffed()[-1] in answer["errors"][0]["message"]

    def test_b11_a_report_from_an_unstaffed_lens_refuses(self, round1, dest):
        """Fail closed the other way: output from a lens nobody dispatched is not coverage."""
        stray = dest / "stray.report.json"
        stray.write_text(json.dumps({"lens": "prose-flow", "verdict": "clean", "findings": []}),
                         encoding="utf-8")
        flags = round1.reports(dest) + ["--report", f"prose-flow={stray}"]
        code, answer, out = assemble(round1, dest, reports=flags)
        assert code == 2
        assert answer["errors"][0]["code"] == "unstaffed-report"
        assert "prose-flow" in answer["errors"][0]["message"]
        assert not out.exists()

    def test_a_route_for_an_unstaffed_lens_refuses(self, round1, dest):
        path = dest / "routes.json"
        entries = json.loads(round1.routes(dest).read_text(encoding="utf-8"))
        entries.append({"lens": "prose-flow", "vendor": "openai", "transport": "codex",
                        "model": "gpt-5.6-sol"})
        path.write_text(json.dumps(entries), encoding="utf-8")
        code, answer, _ = assemble(round1, dest, routes=path)
        assert code == 2
        assert answer["errors"][0]["code"] == "unstaffed-report"

    def test_two_reports_for_one_lens_refuse(self, round1, dest):
        """A lens has exactly one entry; two double-count its coverage."""
        flags = round1.reports(dest)
        code, answer, _ = assemble(round1, dest, reports=flags + flags[:2])
        assert code == 2
        assert answer["errors"][0]["code"] == "duplicate-report"

    def test_a_report_filed_under_the_wrong_lens_refuses(self, round1, dest):
        code, answer, _ = assemble(
            round1, dest, reports=round1.reports(dest, overrides={"security": {"lens": "spelling"}})
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "lens-mismatch"

    def test_a_report_that_states_its_own_lens_correctly_assembles(self, round1, dest):
        """The acceptance twin: the emitted reports name themselves, and that is what passes."""
        code, answer, _ = assemble(round1, dest)
        assert code == 0, answer

    def test_a_round_directory_with_no_metadata_refuses(self, round1, dest, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, answer, _ = assemble(round1, dest, round_dir=empty)
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-round"

    def test_an_unreadable_report_refuses(self, round1, dest):
        flags = round1.reports(dest)
        flags[-1] = f"{round1.staffed()[-1]}={dest / 'absent.json'}"
        code, answer, _ = assemble(round1, dest, reports=flags)
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-report"

    def test_a_routes_entry_missing_its_model_refuses(self, round1, dest):
        code, answer, _ = assemble(
            round1, dest, routes=round1.routes(dest, overrides={"security": {"model": ""}})
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-routes"


class TestAuthorization:
    def test_b11_a_route_the_gate_never_authorized_refuses(self, round1, dest):
        """Output from a dispatch that went around the gate is refused rather than read."""
        code, answer, out = assemble(
            round1, dest,
            routes=round1.routes(dest, overrides={"security": {"model": "some-other-model"}}),
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "unauthorized-dispatch"
        assert "security" in answer["errors"][0]["message"]
        assert not out.exists()

    def test_a_transport_swap_the_gate_never_saw_refuses(self, round1, dest):
        code, answer, _ = assemble(
            round1, dest,
            routes=round1.routes(dest, overrides={"correctness": {"transport": "openrouter"}}),
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "unauthorized-dispatch"

    def test_the_claimed_routes_assemble(self, round1, dest):
        """The acceptance twin: the routes the gate recorded are the ones that pass."""
        code, answer, _ = assemble(round1, dest)
        assert code == 0, answer

    def test_a_round_with_no_attempt_ledger_refuses(self, round1, dest, tmp_path):
        directory = round1.clone(tmp_path / "unledgered")
        (directory / "attempts.jsonl").unlink()
        code, answer, _ = assemble(round1, dest, round_dir=directory)
        assert code == 2
        assert answer["errors"][0]["code"] == "unauthorized-dispatch"

    def test_a_corrupt_attempt_ledger_refuses(self, round1, dest, tmp_path):
        directory = round1.clone(tmp_path / "corrupt")
        with (directory / "attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("not a record\n")
        code, answer, _ = assemble(round1, dest, round_dir=directory)
        assert code == 2
        assert answer["errors"][0]["code"] == "unreadable-ledger"


class TestSubstitutionAndVendors:
    def test_a_declared_substitution_is_carried_into_the_lens_entry(self, round1, dest):
        """A round that lost diversity silently is indistinguishable from one that kept it."""
        substitution = {"declared_transport": "openrouter", "reason": "the credential expired",
                        "transport_error": "402 Insufficient credits"}
        routes = round1.routes(dest, overrides={
            "security": {"vendor": "openai", "transport": "codex", "model": "gpt-5.6-sol",
                         "substitution": substitution},
        })
        # The swapped route is claimed at the gate like any other dispatch.
        directory = round1.clone(dest / "swapped")
        code, _ = run_json(gate.main, [
            "claim", "--out-dir", str(directory), "--lens", "security",
            "--transport", "codex", "--model", "gpt-5.6-sol",
            "--reason", "transport-error", "--evidence", "402 Insufficient credits",
        ])
        assert code == 0
        code, answer, out = assemble(round1, dest, round_dir=directory, routes=routes)
        assert code == 0, answer
        verdict = json.loads(out.read_text(encoding="utf-8"))
        entry = next(item for item in verdict["lenses"] if item["lens"] == "security")
        assert entry["substitution"] == substitution
        assert validate(out, round1.staffing) == (0, {"valid": True})

    def test_the_distinct_vendor_count_is_reported(self, round1, dest):
        code, answer, _ = assemble(round1, dest)
        assert code == 0
        assert answer["distinct_vendors"] == len({vendor for vendor, _, _ in ROUTES.values()})

    def test_a_collapse_onto_one_vendor_shows_as_one(self, round1, dest, tmp_path):
        """One distinct vendor means the panel collapsed; the count is what says so."""
        directory = round1.clone(tmp_path / "collapsed")
        overrides = {}
        for lens in round1.staffed():
            overrides[lens] = {"vendor": "openai", "transport": "codex", "model": "gpt-5.6-sol"}
            code, _ = run_json(gate.main, [
                "claim", "--out-dir", str(directory), "--lens", lens,
                "--transport", "codex", "--model", "gpt-5.6-sol",
                "--reason", "transport-error", "--evidence", "openrouter returned 402",
            ])
            assert code == 0
        code, answer, _ = assemble(
            round1, dest, round_dir=directory, routes=round1.routes(dest, overrides=overrides)
        )
        assert code == 0, answer
        assert answer["distinct_vendors"] == 1


class TestDowngrade:
    def test_b11_an_unevidenced_mechanical_arrives_as_a_marked_advisory(self, round1, dest):
        """Never dropped and never left blocking: the demotion stays countable."""
        code, answer, out = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness", evidence="")],
        })
        assert code == 0, answer
        assert (answer["mechanical"], answer["advisory"]) == (0, 1)
        finding = json.loads(out.read_text(encoding="utf-8"))["findings"][0]
        assert finding["type"] == "advisory"
        assert finding["downgraded_from"] == "mechanical"
        assert validate(out, round1.staffing) == (0, {"valid": True})

    def test_a_mechanical_finding_with_no_evidence_key_is_downgraded_too(self, round1, dest):
        finding = mechanical("F1", "correctness")
        del finding["evidence"]
        code, answer, out = assemble(round1, dest, findings={"correctness": [finding]})
        assert code == 0, answer
        assert json.loads(out.read_text(encoding="utf-8"))["findings"][0]["type"] == "advisory"

    def test_an_evidenced_mechanical_stays_mechanical(self, round1, dest):
        """The acceptance twin: evidence is the whole of what the downgrade turns on."""
        code, answer, out = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness")],
        })
        assert code == 0
        assert answer["mechanical"] == 1
        assert "downgraded_from" not in json.loads(out.read_text(encoding="utf-8"))["findings"][0]

    def test_the_other_findings_of_that_report_are_unaffected(self, round1, dest):
        """The permissive branch: the report is not discarded over one unevidenced claim."""
        code, answer, _ = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness", evidence=" "),
                            mechanical("F2", "correctness")],
        })
        assert code == 0, answer
        assert (answer["mechanical"], answer["advisory"]) == (1, 1)


class TestDuplicateIds:
    def test_two_lenses_raising_one_id_refuse(self, round1, dest):
        code, answer, out = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness")],
            "security": [mechanical("F1", "security")],
        })
        assert code == 2
        assert answer["errors"][0]["code"] == "duplicate-finding-id"
        assert not out.exists()

    def test_distinct_ids_across_lenses_assemble(self, round1, dest):
        code, answer, _ = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness")],
            "security": [mechanical("F2", "security")],
        })
        assert code == 0, answer
        assert answer["mechanical"] == 2

    def test_a_finding_with_no_id_refuses(self, round1, dest):
        finding = mechanical("F1", "correctness")
        del finding["id"]
        code, answer, _ = assemble(round1, dest, findings={"correctness": [finding]})
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-report"


class TestIndictment:
    def test_b6_an_indictment_halts_the_round_on_the_upstream_defect(self, round1, dest):
        """A finding indicting the ruler ends the campaign, not the round: every further
        round would measure against a ruler known to be bent."""
        code, answer, out = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", "F1=a.txt", "--repo-root", str(round1.repo)],
        )
        assert code == 0, answer
        assert answer["verdict"] == "halted"
        verdict = json.loads(out.read_text(encoding="utf-8"))
        halt = verdict["halt"]
        assert halt["reason"] == "upstream-defect"
        assert halt["indicted_finding"] == "F1"
        assert halt["indicted_artifact"] == "a.txt"
        assert halt["abandoned_lenses"] == []
        assert halt["artifact_digest"] == "sha256:" + hashlib.sha256(
            (round1.repo / "a.txt").read_bytes()
        ).hexdigest()
        assert verdict["findings"], "a halt keeps the finding that caused it"
        assert validate(out, round1.staffing) == (0, {"valid": True})

    def test_b6_the_halted_verdict_is_what_the_resume_check_reads(self, round1, dest):
        """The emitter refuses a resume over an unchanged ruler, reading this envelope."""
        code, _, out = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", "F1=a.txt", "--repo-root", str(round1.repo)],
        )
        assert code == 0
        verdict = json.loads(out.read_text(encoding="utf-8"))
        with pytest.raises(emitter.Refusal) as caught:
            emitter.check_resume([verdict], str(round1.repo))
        assert caught.value.code == "unchanged-ruler"

    def test_b6_without_the_indictment_the_same_round_is_a_findings_verdict(self, round1, dest):
        """The acceptance twin: the flag, not the finding, is what halts."""
        code, answer, out = assemble(round1, dest, findings={
            "correctness": [mechanical("F1", "correctness")],
        })
        assert code == 0
        assert answer["verdict"] == "findings"
        assert "halt" not in json.loads(out.read_text(encoding="utf-8"))

    def test_an_indictment_naming_no_finding_of_this_round_refuses(self, round1, dest):
        code, answer, out = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", "F404=a.txt", "--repo-root", str(round1.repo)],
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-indictment"
        assert not out.exists()

    def test_an_unreadable_indicted_artifact_refuses(self, round1, dest):
        code, answer, _ = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", "F1=no/such/file.md", "--repo-root", str(round1.repo)],
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-indictment"

    def test_an_indictment_without_a_repo_root_refuses(self, round1, dest):
        """The recorded path is repo-relative because the resume check re-reads it there."""
        code, answer, _ = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", "F1=a.txt"],
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-indictment"

    def test_an_artifact_outside_the_repository_refuses(self, round1, dest):
        outside = dest / "outside.md"
        outside.write_text("criteria\n", encoding="utf-8")
        code, answer, _ = assemble(
            round1, dest,
            findings={"correctness": [mechanical("F1", "correctness")]},
            extra=["--indict", f"F1={outside}", "--repo-root", str(round1.repo)],
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-indictment"


class TestEnvelopeValidation:
    def test_an_envelope_the_schema_rejects_writes_nothing(self, round1, dest, tmp_path):
        directory = round1.clone(tmp_path / "bad-head")
        meta = json.loads((directory / "round.json").read_text(encoding="utf-8"))
        meta["head_sha"] = "not-a-sha"
        (directory / "round.json").write_text(json.dumps(meta), encoding="utf-8")
        code, answer, out = assemble(round1, dest, round_dir=directory)
        assert code == 2
        assert answer["errors"][0]["code"] == "invalid-envelope"
        assert not out.exists()
        assert not (out.parent / "suppressions.json").exists()

    def test_b11_a_staffing_record_edited_after_the_round_refuses(self, round1, dest, tmp_path):
        """The verdict names the bytes it is answerable to; edited bytes are not those."""
        directory = round1.clone(tmp_path / "edited-staffing")
        edited = tmp_path / "staffing-edited.json"
        edited.write_text(round1.staffing.read_text(encoding="utf-8") + " ", encoding="utf-8")
        meta = json.loads((directory / "round.json").read_text(encoding="utf-8"))
        meta["staffing_record"]["path"] = str(edited)
        (directory / "round.json").write_text(json.dumps(meta), encoding="utf-8")
        code, answer, out = assemble(round1, dest, round_dir=directory)
        assert code == 2
        assert answer["errors"][0]["code"] == "invalid-envelope"
        assert not out.exists()

    def test_b11_a_staffing_record_staffing_other_lenses_refuses(self, round1, dest, tmp_path):
        """Layer 1: coverage is checked against the staffing record, not the class table."""
        directory = round1.clone(tmp_path / "other-lenses")
        other = tmp_path / "staffing-other.json"
        other.write_text(json.dumps({
            "lenses": [*LENSES, "prose-flow"], "excluded": [],
            "recommending_model": "moonshotai/kimi-k2.7-code",
            "decision": "as-recommended", "force_full": False,
        }), encoding="utf-8")
        meta = json.loads((directory / "round.json").read_text(encoding="utf-8"))
        meta["staffing_record"] = {
            "path": str(other),
            "digest": "sha256:" + hashlib.sha256(other.read_bytes()).hexdigest(),
        }
        (directory / "round.json").write_text(json.dumps(meta), encoding="utf-8")
        code, answer, _ = assemble(round1, dest, round_dir=directory)
        assert code == 2
        assert answer["errors"][0]["code"] == "invalid-envelope"
        assert "prose-flow" in answer["errors"][0]["message"]

    def test_a_moved_staffing_record_degrades_to_schema_only_with_a_warning(
        self, round1, dest, tmp_path
    ):
        """The digest recorded at emission governs; a moved file costs the path check alone."""
        directory = round1.clone(tmp_path / "moved-staffing")
        meta = json.loads((directory / "round.json").read_text(encoding="utf-8"))
        meta["staffing_record"]["path"] = str(tmp_path / "gone" / "staffing.json")
        (directory / "round.json").write_text(json.dumps(meta), encoding="utf-8")
        code, answer, out = assemble(round1, dest, round_dir=directory)
        assert code == 0, answer
        assert any("not readable" in warning for warning in answer["warnings"])
        assert out.is_file()

    def test_a_readable_staffing_record_reports_no_warning(self, round1, dest):
        """The acceptance twin: nothing is warned about when the record is where it says."""
        code, answer, _ = assemble(round1, dest)
        assert code == 0
        assert "warnings" not in answer

    def test_no_schema_anywhere_refuses_rather_than_writing_an_unchecked_envelope(
        self, round1, dest, tmp_path
    ):
        out = dest / "verdict.json"
        code, answer = run_json(assembler.main, [
            "--round-dir", str(round1.dir), *round1.reports(dest),
            "--routes", str(round1.routes(dest)), "--out", str(out),
            "--schema", str(tmp_path / "no-such-schema.json"),
        ])
        assert code == 2
        assert answer["errors"][0]["code"] == "no-schema"
        assert not out.exists()


@pytest.fixture(scope="module")
def round2(tmp_path_factory) -> tuple[Round, Path]:
    """A real second round: round 1 assembled, dispositioned, and re-emitted.

    The ledger the suppression filter reads is therefore the one the emitter wrote from
    a verdict the assembler produced, not a fixture in its shape.
    """
    workspace = tmp_path_factory.mktemp("second")
    campaign = Round(workspace / "campaign")
    code, _, first = assemble(
        campaign, workspace,
        findings={"correctness": [mechanical("F1", "correctness")],
                  "security": [advisory("F2", "security")]},
    )
    assert code == 0
    dispositions = workspace / "dispositions.json"
    dispositions.write_text(json.dumps([
        {"round": 1, "id": "F1", "disposition": "rebutted",
         "evidence": "the reader is documented as skipping blank trailing records"},
        {"round": 1, "id": "F2", "disposition": "advisory-deferred"},
    ]), encoding="utf-8")
    (campaign.repo / "a.txt").write_text("two\nthree\n", encoding="utf-8")
    campaign.head = campaign.commit("three")
    directory = campaign.emit(
        2, workspace / "round-2",
        "--prior-verdict", str(first), "--disposition", str(dispositions),
    )
    campaign.claim_all(directory)
    return campaign, directory


class TestSuppression:
    """PANEL-B11 over a real second round: the ledger is the one the emitter wrote."""

    def test_the_emitted_ledger_carries_the_lens_that_raised_each_settled_item(self, round2):
        """Suppression matches on lens and id, so the ledger has to carry the lens."""
        source, directory = round2
        ledger = source.meta(directory)["prior_dispositions"]
        assert {(entry["lens"], entry["id"]) for entry in ledger} == {
            ("correctness", "F1"), ("security", "F2")
        }

    def test_b11_an_exact_re_citation_of_a_settled_item_is_suppressed(self, round2, dest):
        """A settled item does not re-enter the campaign, whatever the lens says this round."""
        source, directory = round2
        code, answer, out = assemble(
            source, dest, round_dir=directory,
            reports=source.reports(
                dest, {"correctness": [mechanical("F1", "correctness")]}, round_dir=directory),
        )
        assert code == 0, answer
        assert answer["suppressed"] == 1
        assert answer["verdict"] == "clean"
        assert json.loads(out.read_text(encoding="utf-8"))["findings"] == []

    def test_b11_every_suppression_names_the_settled_item_it_matched(self, round2, dest):
        """The filter is auditable: what was dropped, and what settled it."""
        source, directory = round2
        code, _, out = assemble(
            source, dest, round_dir=directory,
            reports=source.reports(
                dest, {"correctness": [mechanical("F1", "correctness")]}, round_dir=directory),
        )
        assert code == 0
        assert suppressions_of(out) == [{
            "lens": "correctness", "finding_id": "F1", "settled_id": "F1",
            "settled_round": 1, "disposition": "rebutted",
        }]

    def test_b11_the_same_id_from_another_lens_is_not_suppressed(self, round2, dest):
        """Exact re-citation only: a different lens raising that id is a different claim."""
        source, directory = round2
        code, answer, out = assemble(
            source, dest, round_dir=directory,
            reports=source.reports(
                dest, {"security": [mechanical("F1", "security")]}, round_dir=directory),
        )
        assert code == 0, answer
        assert answer["suppressed"] == 0
        assert answer["mechanical"] == 1
        assert suppressions_of(out) == []
        assert validate(out, source.staffing) == (0, {"valid": True})

    def test_b11_a_round_matching_nothing_writes_an_empty_suppression_record(self, round2, dest):
        """suppressions.json is always written, so its absence is never the answer."""
        source, directory = round2
        code, answer, out = assemble(
            source, dest, round_dir=directory,
            reports=source.reports(
                dest, {"correctness": [mechanical("F7", "correctness")]}, round_dir=directory),
        )
        assert code == 0, answer
        assert answer["suppressed"] == 0
        assert suppressions_of(out) == []

    def test_b11_the_ledger_reaches_the_envelope_with_its_evidence_intact(self, round2, dest):
        """Dispositions carry into the verdict, evidence and all, so the next round sees them."""
        source, directory = round2
        code, _, out = assemble(source, dest, round_dir=directory,
                                reports=source.reports(dest, round_dir=directory))
        assert code == 0
        carried = json.loads(out.read_text(encoding="utf-8"))["prior_dispositions"]
        rebuttal = next(entry for entry in carried if entry["id"] == "F1")
        assert rebuttal["disposition"] == "rebutted"
        assert "blank trailing records" in rebuttal["evidence"]
        assert rebuttal["round"] == 1
        assert validate(out, source.staffing) == (0, {"valid": True})

    def test_the_round_trip_closes_at_the_emitter(self, round2):
        """What the assembler writes, the emitter reads back as a prior verdict: this
        round exists only because round 1's assembled envelope seeded it, schema-checked."""
        source, directory = round2
        assert source.meta(directory)["round"] == 2
        assert source.staffed(directory) == LENSES


class TestSurface:
    def test_a_refusal_prints_json_not_a_traceback(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, str(ASSEMBLER_PATH), "--round-dir", str(tmp_path / "nowhere"),
             "--routes", str(tmp_path / "routes.json"), "--out", str(tmp_path / "v.json")],
            capture_output=True, text=True,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stdout
        assert json.loads(proc.stdout)["errors"][0]["code"] == "bad-round"

    def test_the_deployed_script_names_no_repo_source_layout(self):
        assert ".agents" not in ASSEMBLER_PATH.read_text(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
