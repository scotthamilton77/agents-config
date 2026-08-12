#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""Tests for the review-panel dispatch gate.

Run: uv run dispatch_gate_test.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
GATE_PATH = HERE / "dispatch_gate.py"
HARVEST_PATH = HERE / "harvest.md"
SKILL_PATH = HERE / "SKILL.md"


def _load_gate():
    spec = importlib.util.spec_from_file_location("dispatch_gate", GATE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

REPORT = {"lens": "correctness", "verdict": "clean", "findings": []}


@pytest.fixture
def round_dir(tmp_path) -> Path:
    path = tmp_path / "round-1"
    path.mkdir()
    return path


def claim_argv(round_dir: Path, **overrides: Any) -> list[str]:
    """The flags of one claim. An override of ``None`` drops its flag entirely."""
    args: dict[str, Any] = {
        "--out-dir": str(round_dir),
        "--lens": "correctness",
        "--transport": "codex",
        "--model": "gpt-5.6-terra",
        "--reason": "initial",
    }
    args.update(overrides)
    flat = ["claim"]
    for key, value in args.items():
        if value is None:
            continue
        flat += [key, str(value)]
    return flat


def run(argv_list: list[str], capsys) -> tuple[int, dict]:
    code = gate.main(argv_list)
    return code, json.loads(capsys.readouterr().out)


def authorize(round_dir: Path, capsys, **overrides: Any) -> dict:
    code, answer = run(claim_argv(round_dir, **overrides), capsys)
    assert code == gate.EXIT_OK, answer
    return answer


def refuse(argv_list: list[str], capsys) -> dict:
    code, answer = run(argv_list, capsys)
    assert code == gate.EXIT_REFUSED, answer
    return answer


def codes(answer: dict) -> list[str]:
    return [error["code"] for error in answer["errors"]]


def ledger(round_dir: Path) -> list[dict]:
    return gate.read_ledger(round_dir / gate.LEDGER_NAME)


def kinds(round_dir: Path, kind: str) -> list[dict]:
    return [record for record in ledger(round_dir) if record["kind"] == kind]


def write_output(answer: dict, body: str) -> Path:
    path = Path(answer["output_path"])
    path.write_text(body, encoding="utf-8")
    return path


def transport_recovery(round_dir: Path, capsys, error: str, **overrides: Any) -> dict:
    return authorize(
        round_dir, capsys, **{"--reason": "transport-error", "--evidence": error, **overrides}
    )


class TestFirstClaim:
    """AC1: the first dispatch is authorized, recorded in full, and never rewritten."""

    def test_first_claim_is_authorized_with_a_full_attempt_record(self, round_dir, capsys):
        answer = authorize(round_dir, capsys)
        assert answer["authorized"] is True
        assert answer["lens"] == "correctness"
        assert answer["attempt"] == 1
        assert answer["transport"] == "codex"
        assert answer["model"] == "gpt-5.6-terra"
        assert answer["reason"] == "initial"
        assert answer["timestamp"].endswith("Z")
        assert answer["cwd"]
        assert answer["output_path"]

    def test_the_attempt_lands_in_the_rounds_ledger(self, round_dir, capsys):
        authorize(round_dir, capsys)
        claims = kinds(round_dir, "claim")
        assert (round_dir / "attempts.json").is_file()
        assert len(claims) == 1
        for field in ("lens", "attempt", "transport", "model", "cwd", "reason", "timestamp"):
            assert field in claims[0], field
        assert claims[0]["output_path"] == str(
            round_dir.resolve() / "correctness.attempt-1.out"
        )

    def test_cwd_is_the_process_working_directory_not_a_declaration(
        self, round_dir, capsys, tmp_path, monkeypatch
    ):
        """A dispatch run from the wrong tree reviews the wrong code, so the gate
        measures the directory rather than accepting a claim about it."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        answer = authorize(round_dir, capsys)
        assert Path(answer["cwd"]).resolve() == elsewhere.resolve()

    def test_output_path_is_unique_per_lens_and_attempt(self, round_dir, capsys):
        first = authorize(round_dir, capsys)
        second = transport_recovery(round_dir, capsys, "503 upstream")
        other_lens = authorize(round_dir, capsys, **{"--lens": "security"})
        paths = [first["output_path"], second["output_path"], other_lens["output_path"]]
        assert len(set(paths)) == 3
        assert all(Path(p).parent == round_dir.resolve() for p in paths)

    def test_the_ledger_is_append_only_across_invocations(self, round_dir, capsys):
        authorize(round_dir, capsys)
        after_first = (round_dir / "attempts.json").read_bytes()
        transport_recovery(round_dir, capsys, "503 upstream")
        after_second = (round_dir / "attempts.json").read_bytes()
        assert after_second.startswith(after_first)
        assert len(after_second) > len(after_first)

    def test_a_refused_claim_rewrites_nothing_and_grants_no_attempt(self, round_dir, capsys):
        authorize(round_dir, capsys)
        after_first = (round_dir / "attempts.json").read_bytes()
        refuse(claim_argv(round_dir, **{"--reason": "wishful"}), capsys)
        assert (round_dir / "attempts.json").read_bytes().startswith(after_first)
        assert len(kinds(round_dir, "claim")) == 1


class TestRecoveryReason:
    """AC2: a claim after the first declares a known reason and the prior failure."""

    def test_a_missing_reason_is_refused(self, round_dir, capsys):
        answer = refuse(claim_argv(round_dir, **{"--reason": None}), capsys)
        assert codes(answer) == ["unknown-reason"]

    def test_an_unknown_reason_is_refused(self, round_dir, capsys):
        authorize(round_dir, capsys)
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "rate-limited", "--evidence": "429"}), capsys
        )
        assert codes(answer) == ["unknown-reason"]

    def test_a_first_dispatch_may_not_declare_a_failure(self, round_dir, capsys):
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "transport-error", "--evidence": "503"}), capsys
        )
        assert codes(answer) == ["unknown-reason"]

    def test_a_later_dispatch_may_not_declare_itself_initial(self, round_dir, capsys):
        authorize(round_dir, capsys)
        answer = refuse(claim_argv(round_dir, **{"--reason": "initial"}), capsys)
        assert codes(answer) == ["unknown-reason"]

    def test_a_recovery_without_evidence_is_refused(self, round_dir, capsys):
        authorize(round_dir, capsys)
        answer = refuse(claim_argv(round_dir, **{"--reason": "transport-error"}), capsys)
        assert codes(answer) == ["no-failure-evidence"]

    def test_blank_evidence_is_no_evidence(self, round_dir, capsys):
        authorize(round_dir, capsys)
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "unusable-output", "--evidence": "   "}), capsys
        )
        assert codes(answer) == ["no-failure-evidence"]

    def test_the_prior_failure_is_recorded_verbatim(self, round_dir, capsys):
        authorize(round_dir, capsys)
        transport_recovery(round_dir, capsys, "402 Insufficient credits")
        assert kinds(round_dir, "claim")[1]["evidence"] == "402 Insufficient credits"


class TestBounds:
    """AC3/AC4/AC5/AC6: how far recovery goes, and what a refusal at the end says."""

    def test_a_second_unusable_output_recovery_is_refused(self, round_dir, capsys):
        authorize(round_dir, capsys)
        authorize(
            round_dir, capsys, **{"--reason": "unusable-output", "--evidence": "half a sentence"}
        )
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "unusable-output", "--evidence": "prose again"}),
            capsys,
        )
        assert codes(answer) == ["attempts-exhausted"]
        assert len(kinds(round_dir, "claim")) == 2

    def test_a_fourth_dispatch_is_refused_whatever_the_reason_mix(self, round_dir, capsys):
        authorize(round_dir, capsys)
        transport_recovery(round_dir, capsys, "503 upstream")
        authorize(round_dir, capsys, **{"--reason": "unusable-output", "--evidence": "prose"})
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "transport-error", "--evidence": "503 again"}),
            capsys,
        )
        assert codes(answer) == ["attempts-exhausted"]
        assert len(kinds(round_dir, "claim")) == 3

    def test_a_mixed_exhaustion_carries_no_halt_guidance(self, round_dir, capsys):
        """Halting is a claim about the round's remaining dispatches; a reviewer
        that produced garbage says nothing about the routes."""
        authorize(round_dir, capsys)
        authorize(round_dir, capsys, **{"--reason": "unusable-output", "--evidence": "prose"})
        answer = refuse(
            claim_argv(round_dir, **{"--reason": "unusable-output", "--evidence": "prose again"}),
            capsys,
        )
        assert "halt" not in answer

    def test_an_all_transport_exhaustion_names_every_route_and_its_error(self, round_dir, capsys):
        authorize(round_dir, capsys)
        transport_recovery(
            round_dir,
            capsys,
            "402 Insufficient credits",
            **{"--transport": "openrouter", "--model": "anthropic/claude-opus-5"},
        )
        transport_recovery(
            round_dir,
            capsys,
            "503 upstream unavailable",
            **{"--transport": "openrouter", "--model": "moonshotai/kimi-k2"},
        )
        answer = refuse(
            claim_argv(
                round_dir,
                **{
                    "--reason": "transport-error",
                    "--evidence": "at capacity",
                    "--transport": "codex",
                    "--model": "gpt-5.6-terra",
                },
            ),
            capsys,
        )
        routes = answer["halt"]["exhausted_routes"]
        assert [(r["transport"], r["model"]) for r in routes] == [
            ("codex", "gpt-5.6-terra"),
            ("openrouter", "anthropic/claude-opus-5"),
            ("openrouter", "moonshotai/kimi-k2"),
        ]
        assert [r["error"] for r in routes] == [
            "402 Insufficient credits",
            "503 upstream unavailable",
            "at capacity",
        ]
        assert answer["halt"]["guidance"]

    def test_the_last_failure_reaches_the_halt_guidance(self, round_dir, capsys):
        """The refused claim carries the failure that ran the lens out; it exists
        nowhere else, so the guidance would otherwise be one route short."""
        authorize(round_dir, capsys)
        transport_recovery(round_dir, capsys, "first error")
        transport_recovery(round_dir, capsys, "second error")
        answer = refuse(
            claim_argv(
                round_dir, **{"--reason": "transport-error", "--evidence": "third error"}
            ),
            capsys,
        )
        assert "third error" in answer["errors"][0]["message"]
        assert kinds(round_dir, "refusal")[0]["evidence"] == "third error"

    def test_every_authorized_recovery_carries_a_backoff_in_range(self, round_dir, capsys):
        authorize(round_dir, capsys)
        second = transport_recovery(round_dir, capsys, "503 upstream")
        third = transport_recovery(round_dir, capsys, "503 again")
        for answer in (second, third):
            assert 15 <= answer["backoff_seconds"] <= 30

    def test_a_first_dispatch_waits_for_nothing(self, round_dir, capsys):
        assert "backoff_seconds" not in authorize(round_dir, capsys)

    def test_the_bound_is_per_lens(self, round_dir, capsys):
        authorize(round_dir, capsys)
        transport_recovery(round_dir, capsys, "503 upstream")
        transport_recovery(round_dir, capsys, "503 again")
        assert authorize(round_dir, capsys, **{"--lens": "security"})["attempt"] == 1


class TestIngest:
    """AC7/AC8: the tolerance ladder in code, and output nobody claimed."""

    def test_a_whole_body_object_is_the_first_rung(self, round_dir, capsys):
        answer = authorize(round_dir, capsys)
        output = write_output(answer, json.dumps(REPORT))
        code, ingested = run(["ingest", "--out-dir", str(round_dir), "--output", str(output)],
                             capsys)
        assert code == gate.EXIT_OK
        assert ingested["report"] == REPORT
        assert ingested["recovery"] == "whole-body"
        assert (ingested["lens"], ingested["attempt"]) == ("correctness", 1)

    @pytest.mark.parametrize("fence", ["```json", "```"])
    def test_a_single_fenced_object_is_the_second_rung(self, round_dir, capsys, fence):
        answer = authorize(round_dir, capsys)
        output = write_output(answer, f"{fence}\n{json.dumps(REPORT)}\n```\n")
        code, ingested = run(["ingest", "--out-dir", str(round_dir), "--output", str(output)],
                             capsys)
        assert code == gate.EXIT_OK
        assert ingested["report"] == REPORT
        assert ingested["recovery"] == "fenced-block"

    def test_an_object_behind_a_preamble_is_the_third_rung(self, round_dir, capsys):
        answer = authorize(round_dir, capsys)
        output = write_output(
            answer, f"Here is my review:\n{json.dumps(REPORT)}\nHappy to expand on any of it.\n"
        )
        code, ingested = run(["ingest", "--out-dir", str(round_dir), "--output", str(output)],
                             capsys)
        assert code == gate.EXIT_OK
        assert ingested["report"] == REPORT
        assert ingested["recovery"] == "first-object"

    def test_a_parsed_report_records_its_outcome_on_the_claimed_attempt(self, round_dir, capsys):
        answer = authorize(round_dir, capsys)
        output = write_output(answer, json.dumps(REPORT))
        run(["ingest", "--out-dir", str(round_dir), "--output", str(output)], capsys)
        outcome = kinds(round_dir, "outcome")[0]
        assert (outcome["lens"], outcome["attempt"]) == ("correctness", 1)
        assert outcome["outcome"] == "parsed"
        assert outcome["recovery"] == "whole-body"

    @pytest.mark.parametrize(
        "body",
        [
            "The change looks fine to me, no findings.",
            "",
            '["correctness", "clean"]',
            "```\nnot json at all\n```",
        ],
    )
    def test_anything_past_the_ladder_is_unparseable(self, round_dir, capsys, body):
        answer = authorize(round_dir, capsys)
        output = write_output(answer, body)
        refused = refuse(["ingest", "--out-dir", str(round_dir), "--output", str(output)], capsys)
        assert codes(refused) == ["unparseable-output"]
        assert "report" not in refused

    def test_an_unparseable_body_records_its_outcome_too(self, round_dir, capsys):
        answer = authorize(round_dir, capsys)
        output = write_output(answer, "no report here")
        refuse(["ingest", "--out-dir", str(round_dir), "--output", str(output)], capsys)
        outcome = kinds(round_dir, "outcome")[0]
        assert (outcome["lens"], outcome["outcome"]) == ("correctness", "unparseable")

    def test_output_no_claim_assigned_is_refused(self, round_dir, capsys):
        authorize(round_dir, capsys)
        stray = round_dir / "correctness.out"
        stray.write_text(json.dumps(REPORT), encoding="utf-8")
        answer = refuse(["ingest", "--out-dir", str(round_dir), "--output", str(stray)], capsys)
        assert codes(answer) == ["unclaimed-attempt"]

    def test_an_unclaimed_ingest_is_itself_recorded(self, round_dir, capsys):
        """The hole a bypassed dispatch leaves is the point; the ledger names it."""
        authorize(round_dir, capsys)
        stray = round_dir / "correctness.out"
        stray.write_text(json.dumps(REPORT), encoding="utf-8")
        refuse(["ingest", "--out-dir", str(round_dir), "--output", str(stray)], capsys)
        assert kinds(round_dir, "refusal")[0]["code"] == "unclaimed-attempt"

    def test_a_claimed_path_holding_no_file_is_a_transport_failure(self, round_dir, capsys):
        """A transport that writes its file only on success writes nothing when it
        fails, and the attempt's own path is empty rather than holding a stale
        report from the attempt before it."""
        answer = authorize(round_dir, capsys)
        refused = refuse(
            ["ingest", "--out-dir", str(round_dir), "--output", answer["output_path"]], capsys
        )
        assert codes(refused) == ["no-output"]
        assert "transport-error" in refused["errors"][0]["message"]
        assert kinds(round_dir, "outcome")[0]["outcome"] == "no-output"

    def test_ingest_without_an_output_flag_is_refused(self, round_dir, capsys):
        answer = refuse(["ingest", "--out-dir", str(round_dir)], capsys)
        assert codes(answer) == ["no-output-path"]

    def test_a_stale_report_cannot_be_ingested_as_a_later_attempt(self, round_dir, capsys):
        """Attempt 1's file is not attempt 2's: the second attempt's own path is
        what ingest reads, so last round's body cannot answer for this one."""
        first = authorize(round_dir, capsys)
        write_output(first, json.dumps(REPORT))
        second = transport_recovery(round_dir, capsys, "503 upstream")
        refused = refuse(
            ["ingest", "--out-dir", str(round_dir), "--output", second["output_path"]], capsys
        )
        assert codes(refused) == ["no-output"]


class TestGateSurface:
    """Refusals for a malformed request, and the stdout contract they all keep."""

    def test_a_missing_lens_is_refused(self, round_dir, capsys):
        assert codes(refuse(claim_argv(round_dir, **{"--lens": None}), capsys)) == ["no-lens"]

    def test_a_lens_name_that_is_a_path_is_refused(self, round_dir, capsys):
        answer = refuse(claim_argv(round_dir, **{"--lens": "../escape"}), capsys)
        assert codes(answer) == ["no-lens"]

    @pytest.mark.parametrize("missing", ["--transport", "--model"])
    def test_an_undeclared_route_is_refused(self, round_dir, capsys, missing):
        answer = refuse(claim_argv(round_dir, **{missing: None}), capsys)
        assert codes(answer) == ["no-route-declaration"]

    def test_a_lens_the_round_does_not_declare_is_refused(self, round_dir, capsys):
        (round_dir / "round.json").write_text(
            json.dumps({"lenses": [{"lens": "correctness"}, {"lens": "security"}]}),
            encoding="utf-8",
        )
        answer = refuse(claim_argv(round_dir, **{"--lens": "corectness"}), capsys)
        assert codes(answer) == ["unknown-lens"]

    def test_a_round_declaring_no_lenses_accepts_any_lens_name(self, round_dir, capsys):
        (round_dir / "round.json").write_text("{not json", encoding="utf-8")
        assert authorize(round_dir, capsys, **{"--lens": "house-lens"})["attempt"] == 1

    @pytest.mark.parametrize(
        "argv_tail",
        [["claim", "--lens", "correctness", "--transport", "codex", "--model", "m",
          "--reason", "initial"],
         ["ingest", "--output", "somewhere.out"]],
    )
    def test_an_unparseable_ledger_stops_both_verbs(self, round_dir, capsys, argv_tail):
        """A bound cannot be enforced against a history that does not parse, so
        neither verb proceeds on one."""
        (round_dir / "attempts.json").write_text("{}\nnot a record\n", encoding="utf-8")
        answer = refuse([*argv_tail, "--out-dir", str(round_dir)], capsys)
        assert codes(answer) == ["unreadable-ledger"]

    def test_an_unexpected_fault_is_still_json(self, round_dir, capsys, monkeypatch):
        def explode() -> str:
            raise RuntimeError("clock unavailable")

        monkeypatch.setattr(gate, "now", explode)
        answer = refuse(claim_argv(round_dir), capsys)
        assert codes(answer) == ["gate-failure"]
        assert answer["authorized"] is False

    def test_a_refusal_names_the_verb_it_refused(self, round_dir, capsys):
        assert refuse(claim_argv(round_dir, **{"--lens": None}), capsys)["authorized"] is False
        assert refuse(["ingest", "--out-dir", str(round_dir)], capsys)["ingested"] is False

    def test_the_deployed_gate_carries_no_planning_jargon(self):
        """The gate deploys into other projects, where this repo's planning
        vocabulary names nothing."""
        jargon = re.compile(r"\bD[0-9]|\bAC[0-9]|\bslice\b|\bcharter\b|\bmilestone\b",
                            re.IGNORECASE)
        for path in (GATE_PATH, HARVEST_PATH):
            hits = [line for line in path.read_text(encoding="utf-8").splitlines()
                    if jargon.search(line)]
            assert not hits, f"{path.name}: {hits}"

    def test_the_prose_routes_authorization_through_the_gate(self):
        """AC10: the invoker is told to ask the gate, not to count attempts."""
        harvest = HARVEST_PATH.read_text(encoding="utf-8")
        for token in ("dispatch_gate.py", "claim", "ingest", "transport-error",
                      "unusable-output"):
            assert token in harvest, token
        assert "dispatch_gate.py" in SKILL_PATH.read_text(encoding="utf-8")

    def test_the_skill_body_stays_within_its_budget(self):
        """The same four-characters-per-token proxy the rest of this skill is held to."""
        body = SKILL_PATH.read_text(encoding="utf-8").split("---", 2)[2]
        assert len(body) <= 8000, len(body)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
