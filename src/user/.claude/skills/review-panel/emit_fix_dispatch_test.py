#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the review-panel fix-dispatch emitter.

Run: uv run emit_fix_dispatch_test.py
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
DISPATCH_PATH = HERE / "emit_fix_dispatch.py"
EMITTER_PATH = HERE / "emit_prompts.py"
# Source-tree-only path to the real verdict schema, for exercising strict
# jsonschema validation explicitly. The script itself never assumes this layout
# — see SCHEMA_CANDIDATES in emit_fix_dispatch.py.
REVIEW_VERDICT_SCHEMA = (
    HERE / ".." / ".." / ".." / ".agents" / "skills" / "review-verdict" / "verdict.schema.json"
).resolve()

SHA_A = "a" * 40
SHA_B = "b" * 40


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dispatcher = _load(DISPATCH_PATH, "emit_fix_dispatch")
emitter = _load(EMITTER_PATH, "emit_prompts")


def mechanical(finding_id: str, lens: str = "correctness", **overrides: Any) -> dict:
    finding = {
        "id": finding_id, "lens": lens, "type": "mechanical", "ac": "C1",
        "claim": f"{finding_id}: the reader drops the trailing record",
        "evidence": f"tests/test_reader.py::test_{finding_id.lower()} fails at head",
    }
    finding.update(overrides)
    return finding


def advisory(finding_id: str, lens: str = "security", **overrides: Any) -> dict:
    finding = {
        "id": finding_id, "lens": lens, "type": "advisory", "ac": "C2",
        "claim": f"{finding_id}: the temp path is world-readable",
    }
    finding.update(overrides)
    return finding


def verdict_document(findings: list[dict], **overrides: Any) -> dict:
    document = {
        "schema_version": "3",
        "artifact_class": "typed-code",
        "round": 2,
        "base_sha": SHA_A,
        "head_sha": SHA_B,
        "claim_id": "claim-7",
        "retained_categories": [],
        "staffing_record": {"digest": "sha256:" + "c" * 64, "path": "staffing.json"},
        "lenses": [{"lens": "correctness", "verdict": "findings", "vendor": "openai",
                    "transport": "codex", "model": "gpt-5.6-sol"}],
        "prior_dispositions": [],
        "verdict": "findings" if findings else "clean",
        "findings": findings,
    }
    document.update(overrides)
    return document


def write_verdict(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run(argv: list[str], capsys) -> tuple[int, dict]:
    code = dispatcher.main(argv)
    return code, json.loads(capsys.readouterr().out)


def argv(verdict: Path, out: Path, **overrides: Any) -> list[str]:
    args = {"--verdict": str(verdict), "--out": str(out),
            "--schema": str(REVIEW_VERDICT_SCHEMA)}
    args.update(overrides)
    flat: list[str] = []
    for key, value in args.items():
        flat += [key, str(value)]
    return flat


class TestRefusals:
    def test_b5_a_clean_round_emits_no_dispatch(self, tmp_path, capsys):
        """A clean round has nothing to fix, and a dispatch saying so is invented work."""
        verdict = write_verdict(tmp_path, verdict_document([]))
        out = tmp_path / "fix.md"
        code, answer = run(argv(verdict, out), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "no-dispatch-for-clean"
        assert not out.exists()

    def test_b5_a_findings_round_does_emit_one(self, tmp_path, capsys):
        """The acceptance twin: the same shape with a blocking finding emits."""
        verdict = write_verdict(tmp_path, verdict_document([mechanical("F1")]))
        out = tmp_path / "fix.md"
        code, answer = run(argv(verdict, out), capsys)
        assert code == 0, answer
        assert answer == {"emitted": True, "out": str(out), "mechanical": 1, "advisory": 0}
        assert out.is_file()

    def test_b5_a_halted_round_emits_no_dispatch(self, tmp_path, capsys):
        """A halt is answered upstream or by re-dispatch, never by fixing the artifact."""
        halted = verdict_document(
            [mechanical("F1")],
            verdict="halted",
            halt={"reason": "upstream-defect", "indicted_finding": "F1",
                  "indicted_artifact": "docs/criteria.md",
                  "artifact_digest": "sha256:" + "d" * 64, "abandoned_lenses": []},
        )
        code, answer = run(argv(write_verdict(tmp_path, halted), tmp_path / "fix.md"), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "no-dispatch-for-halted"

    def test_b5_the_same_findings_without_the_halt_emit(self, tmp_path, capsys):
        """The acceptance twin: the halt block, not the findings, is what refuses."""
        verdict = write_verdict(tmp_path, verdict_document([mechanical("F1")]))
        code, _ = run(argv(verdict, tmp_path / "fix.md"), capsys)
        assert code == 0

    def test_b5_an_advisory_only_round_has_nothing_to_dispatch(self, tmp_path, capsys):
        """Advisories are carried as advisories; none of them blocks."""
        verdict = write_verdict(tmp_path, verdict_document([advisory("F9")]))
        out = tmp_path / "fix.md"
        code, answer = run(argv(verdict, out), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "no-blocking-findings"
        assert not out.exists()

    def test_b5_one_mechanical_alongside_advisories_dispatches(self, tmp_path, capsys):
        """The acceptance twin: a single blocking finding is enough to dispatch."""
        verdict = write_verdict(tmp_path, verdict_document([advisory("F9"), mechanical("F1")]))
        code, answer = run(argv(verdict, tmp_path / "fix.md"), capsys)
        assert code == 0
        assert (answer["mechanical"], answer["advisory"]) == (1, 1)

    def test_b5_an_unreadable_verdict_refuses(self, tmp_path, capsys):
        code, answer = run(argv(tmp_path / "absent.json", tmp_path / "fix.md"), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-verdict"

    def test_b5_a_schema_invalid_verdict_refuses(self, tmp_path, capsys):
        """A dispatch written from an invalid verdict cites findings nothing stands behind."""
        document = verdict_document([mechanical("F1")])
        del document["staffing_record"]
        code, answer = run(argv(write_verdict(tmp_path, document), tmp_path / "fix.md"), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-verdict"

    def test_b5_the_schema_valid_twin_emits(self, tmp_path, capsys):
        """The acceptance twin: the same verdict with its staffing record emits."""
        code, _ = run(
            argv(write_verdict(tmp_path, verdict_document([mechanical("F1")])),
                 tmp_path / "fix.md"),
            capsys,
        )
        assert code == 0

    def test_b5_a_mechanical_finding_with_blank_evidence_is_not_this_scripts_problem(
        self, tmp_path, capsys
    ):
        """The downgrade happens at assembly; here an unevidenced mechanical is schema-invalid."""
        document = verdict_document([mechanical("F1", evidence="  ")])
        code, answer = run(argv(write_verdict(tmp_path, document), tmp_path / "fix.md"), capsys)
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-verdict"

    def test_no_schema_on_disk_falls_back_to_the_structural_minimum(self, tmp_path, capsys):
        """Without a schema the verdict is still read, and a non-verdict is still refused."""
        absent = tmp_path / "no-such-schema.json"
        code, _ = run(
            argv(write_verdict(tmp_path, verdict_document([mechanical("F1")])),
                 tmp_path / "fix.md", **{"--schema": str(absent)}),
            capsys,
        )
        assert code == 0
        not_a_verdict = tmp_path / "other.json"
        not_a_verdict.write_text(json.dumps({"findings": "none"}), encoding="utf-8")
        code, answer = run(
            argv(not_a_verdict, tmp_path / "fix2.md", **{"--schema": str(absent)}), capsys
        )
        assert code == 2
        assert answer["errors"][0]["code"] == "bad-verdict"


class TestCompleteness:
    @pytest.fixture
    def dispatch(self, tmp_path, capsys) -> str:
        document = verdict_document(
            [mechanical("F1"), mechanical("F2", lens="test-adequacy"), advisory("F9")]
        )
        out = tmp_path / "fix.md"
        code, answer = run(argv(write_verdict(tmp_path, document), out), capsys)
        assert code == 0, answer
        assert (answer["mechanical"], answer["advisory"]) == (2, 1)
        return out.read_text(encoding="utf-8")

    def test_b5_every_mechanical_finding_is_referenced_in_full(self, dispatch):
        """Completeness is the contract: id, lens, criterion, claim, and evidence, per finding."""
        for finding in (mechanical("F1"), mechanical("F2", lens="test-adequacy")):
            assert finding["id"] in dispatch
            assert finding["lens"] in dispatch
            assert finding["ac"] in dispatch
            assert finding["claim"] in dispatch
            assert finding["evidence"] in dispatch

    def test_b5_advisories_are_shown_as_not_blocking(self, dispatch):
        """The advisory appears, in a section that says it blocks nothing."""
        blocking, _, non_blocking = dispatch.partition("## Advisories")
        assert "F9" not in blocking
        assert "F9" in non_blocking
        assert "not blocking" in non_blocking.splitlines()[0]

    def test_b5_the_dispatch_names_the_round_it_answers(self, dispatch):
        assert "claim-7" in dispatch
        assert SHA_B in dispatch

    def test_b5_all_four_clauses_are_present(self, dispatch):
        for clause in ("Smallest net change", "Mutation evidence for code fixes",
                       "Replacement-first for prose", "Narration sweep"):
            assert clause in dispatch, clause

    def test_b5_the_growth_clause_states_the_shared_triviality_boundary(self, dispatch):
        """One boundary, two consumers: the number here is the emitter's constant."""
        assert f"{emitter.TRIVIALITY_BOUNDARY} lines" in dispatch
        assert dispatcher.TRIVIALITY_BOUNDARY == emitter.TRIVIALITY_BOUNDARY

    def test_b5_the_mutation_clause_asks_for_the_observation_the_ledger_requires(self, dispatch):
        """Clause 2 and the ledger's unsupported-fix refusal ask for the same thing."""
        clause = dispatch.split("Mutation evidence for code fixes", 1)[1]
        assert "fails without it and passes with it" in clause
        assert "test" in clause

    def test_b5_the_narration_clause_forbids_transition_commentary(self, dispatch):
        clause = dispatch.split("Narration sweep", 1)[1]
        assert "current decision" in clause

    def test_a_blank_evidence_line_is_omitted_rather_than_emitted_empty(self, tmp_path, capsys):
        """A downgraded advisory says why it is advisory instead of showing an empty field."""
        document = verdict_document(
            [mechanical("F1"), advisory("F2", downgraded_from="mechanical")]
        )
        out = tmp_path / "fix.md"
        code, _ = run(argv(write_verdict(tmp_path, document), out), capsys)
        assert code == 0
        text = out.read_text(encoding="utf-8")
        assert "- Evidence: \n" not in text
        assert "Downgraded from mechanical" in text


class TestSurface:
    def test_stdout_is_json_and_deterministic(self, tmp_path):
        """Two runs of the same input produce byte-identical stdout and dispatch."""
        verdict = write_verdict(tmp_path, verdict_document([mechanical("F1"), advisory("F9")]))
        out = tmp_path / "fix.md"
        runs = []
        for _ in (1, 2):
            proc = subprocess.run(
                [sys.executable, str(DISPATCH_PATH), *argv(verdict, out)],
                capture_output=True, text=True,
            )
            assert proc.returncode == 0, proc.stdout + proc.stderr
            runs.append((proc.stdout, out.read_text(encoding="utf-8")))
        assert runs[0] == runs[1]
        assert runs[0][0].strip() == json.dumps(json.loads(runs[0][0]), sort_keys=True)

    def test_a_refusal_prints_json_not_a_traceback(self, tmp_path):
        """Stdout is a parsed contract: a refusal exits 2 carrying a typed code."""
        proc = subprocess.run(
            [sys.executable, str(DISPATCH_PATH), "--verdict", str(tmp_path / "nope.json"),
             "--out", str(tmp_path / "fix.md")],
            capture_output=True, text=True,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stdout
        assert json.loads(proc.stdout)["errors"][0]["code"] == "bad-verdict"

    def test_the_deployed_script_names_no_repo_source_layout(self):
        """Schema discovery may assume the deployed sibling layout only."""
        assert ".agents" not in DISPATCH_PATH.read_text(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
