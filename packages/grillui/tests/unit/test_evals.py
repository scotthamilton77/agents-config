"""The replay suite's loader, its checks, and what its report says.

Nothing here reaches a model. What is proved is that a case loads, that the
prompt it pins is the prompt today's code renders, and that each check fails the
document it is there to catch and passes the one it is not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.__main__ import BASELINE, check, matrix_of, read_seat, seat_of
from evals.cases import CASES, CaseRefusedError, load_case, load_cases
from evals.checks import (
    a_revise_supplies_what_it_revises,
    added_nodes_carry_short_and_body,
    option_references_name_their_decision,
    the_reply_is_the_map_document,
    the_rulings_are_the_ones_owed,
    the_stop_verdict_is_expected,
    the_turn_speaks_once,
)
from grillui.schemas import GrillMasterDocument
from grillui.tiers import CLAUDE_TRANSPORT, CODEX_TRANSPORT, TierConfig, compose, system_prompt


def document(**overrides: Any) -> GrillMasterDocument:
    """A turn that passes every check, before an override breaks one."""
    return GrillMasterDocument.model_validate(
        {"text": "", "updates": [], "supersedes": [], "rulings": [], "stop": {"met": False}}
        | overrides
    )


def ruling(decision: str) -> dict[str, str]:
    return {"decision": decision, "ruling": "stands", "why": "it still asks the right question"}


# --- the fixtures ---------------------------------------------------------------


def test_every_checked_in_case_renders_the_prompt_it_pins() -> None:
    """
    Given every case checked in
    When each is rendered through the prompt code a session composes with
    Then the byte length is the one the case records, where it records one: a
         case whose recorded turn today's prompt no longer reproduces is a case
         replaying something that was never sent.
    """
    cases = load_cases()

    assert cases, "no cases are checked in"
    for case in cases:
        if case.context_bytes is None:
            continue
        system = system_prompt(case.tier, case.context.agent)
        prompt = compose(case.recorded, case.context, list(case.entries))
        assert len(system.encode()) + len(prompt.encode()) == case.context_bytes, case.name


def test_the_seed_cases_are_the_behaviours_this_suite_watches() -> None:
    """
    Given the cases checked in
    When they are read
    Then the three seeded behaviours are among them: a turn owing rulings, a
         turn owing none, and a turn whose recorded reply revised without
         changing anything.
    """
    owed = {case.name: case.owed_rulings for case in load_cases()}

    assert owed["2026-09-04-expert-owed-rulings"] == ("d2", "d3")
    assert owed["2026-09-04-first-rung-nothing-owed"] == ()
    assert owed["2026-08-27-revise-without-substance"] == ()


@pytest.mark.parametrize("named", ["../elsewhere/dispatch.json", "/etc/passwd", ".."])
def test_a_case_naming_a_path_outside_itself_is_refused(named: str, tmp_path: Path) -> None:
    """
    Given a case naming a file outside its own directory
    When it is loaded
    Then it is refused: a case that reads what the checkout does not carry
         replays a turn nobody else can see.
    """
    where = tmp_path / "borrowed"
    where.mkdir()
    (where / "case.json").write_text(
        json.dumps(
            {"tier": "fast", "channel": "map", "stop": False, "owed_rulings": [], "log": named}
        ),
        encoding="utf-8",
    )

    with pytest.raises(CaseRefusedError):
        load_case(where)


def test_a_case_missing_one_of_its_three_files_is_refused(tmp_path: Path) -> None:
    """
    Given a case directory carrying only its expectations
    When it is loaded
    Then it is refused by name rather than read half-way.
    """
    where = tmp_path / "partial"
    where.mkdir()
    (where / "case.json").write_text(
        json.dumps({"tier": "fast", "channel": "map", "stop": False, "owed_rulings": []}),
        encoding="utf-8",
    )

    with pytest.raises(CaseRefusedError):
        load_case(where)


def test_a_case_disagreeing_with_its_dispatch_about_what_is_owed_is_refused(
    tmp_path: Path,
) -> None:
    """
    Given a case claiming rulings its dispatch does not put in question
    When it is loaded
    Then it is refused: the expectation and the dispatch are two statements of
         one fact, and a case where they differ tests neither.
    """
    seeded = CASES / "2026-09-04-first-rung-nothing-owed"
    where = tmp_path / "mismatched"
    where.mkdir()
    for name in ("dispatch.json", "log.jsonl"):
        (where / name).write_text((seeded / name).read_text(encoding="utf-8"), encoding="utf-8")
    case = json.loads((seeded / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"owed_rulings": ["d9"]}), encoding="utf-8")

    with pytest.raises(CaseRefusedError):
        load_case(where)


# --- the checks -----------------------------------------------------------------


def test_a_reply_that_is_not_the_document_fails_the_shape_check() -> None:
    assert the_reply_is_the_map_document("just prose") is not None
    assert the_reply_is_the_map_document(document().model_dump_json()) is None


def test_rulings_are_held_to_exactly_what_the_dispatch_owes() -> None:
    owed = ("d2", "d3")

    assert the_rulings_are_the_ones_owed(document(rulings=[ruling("d2")]), owed) is not None
    assert the_rulings_are_the_ones_owed(document(rulings=[ruling("d9")]), ()) is not None
    assert (
        the_rulings_are_the_ones_owed(document(rulings=[ruling("d2"), ruling("d3")]), owed) is None
    )
    assert the_rulings_are_the_ones_owed(document(), ()) is None


def test_an_added_node_without_short_or_body_fails() -> None:
    node = {"kind": "add-node", "title": "What confirms a match?"}
    thin = document(updates=[node])
    whole = document(updates=[node | {"short": "Confirm", "body": "How?"}])

    assert added_nodes_carry_short_and_body(thin) is not None
    assert added_nodes_carry_short_and_body(whole) is None


def test_a_turn_speaking_through_two_channels_fails() -> None:
    both = document(
        text="Here is the answer.",
        updates=[{"kind": "informational", "text": "And also this."}],
    )

    assert the_turn_speaks_once(both) is not None
    assert the_turn_speaks_once(both, limit=2) is None
    assert the_turn_speaks_once(document(text="Just the notice.")) is None


def test_an_option_named_without_its_decision_fails() -> None:
    bare = document(text="Option b makes every perceptual match a guess.")
    qualified = document(text="Option b of d1 makes every perceptual match a guess.")

    assert option_references_name_their_decision(bare) is not None
    assert option_references_name_their_decision(qualified) is None


def test_the_stop_verdict_is_held_to_the_cases_expectation() -> None:
    assert the_stop_verdict_is_expected(document(stop={"met": True}), expected=False) is not None
    assert the_stop_verdict_is_expected(document(stop={"met": False}), expected=False) is None


def test_a_revise_that_changes_nothing_fails() -> None:
    revise = {"kind": "revise", "target": "d3", "basis": 25, "why": "It cannot auto-apply."}
    why_only = document(updates=[revise])
    substantive = document(updates=[revise | {"title": "What may auto-apply?"}])

    assert a_revise_supplies_what_it_revises(why_only) is not None
    assert a_revise_supplies_what_it_revises(substantive) is None


# --- the run and its report -----------------------------------------------------


def test_a_reply_that_is_not_a_document_is_not_checked_for_what_it_cannot_have() -> None:
    """
    Given a reply that is not the map document
    When it is checked
    Then the shape check fails and no check that reads a document is claimed to
         have passed on a document there is none of.
    """
    case = load_cases()[0]

    results = check(case, "just prose", None)

    assert results[the_reply_is_the_map_document.__name__] is not None
    assert the_rulings_are_the_ones_owed.__name__ not in results


def test_a_prompt_token_count_far_from_the_baseline_fails_its_check() -> None:
    """
    Given a case carrying a measured prompt-token baseline
    When a run bills far more than it
    Then the baseline check fails, so a seat that quietly grew its seed is
         caught here rather than on the next invoice.
    """
    case = next(one for one in load_cases() if one.prompt_tokens is not None)
    reply = document().model_dump_json()

    assert check(case, reply, case.prompt_tokens)[BASELINE] is None
    assert check(case, reply, case.prompt_tokens * 3)[BASELINE] is not None
    assert check(case, reply, None)[BASELINE] is not None


def test_the_seat_a_case_runs_on_is_the_one_the_session_would_use() -> None:
    """
    Given the seat table a session is configured with
    When a case names its rung
    Then the expert case takes the expert seat and the first-rung case the map's,
         so a lean-seat regression in the drivers shows here.
    """
    config = TierConfig.from_env({})
    cases = {one.name: one for one in load_cases()}

    assert seat_of(cases["2026-09-04-expert-owed-rulings"], config).transport == CLAUDE_TRANSPORT
    assert seat_of(cases["2026-09-04-first-rung-nothing-owed"], config).transport == CODEX_TRANSPORT


def test_a_seat_is_read_as_transport_model_and_effort() -> None:
    seated = read_seat("codex:gpt-5.6-luna:medium")

    assert (seated.transport, seated.model, seated.effort) == ("codex", "gpt-5.6-luna", "medium")
    assert read_seat("openrouter:some-model").effort is None
    with pytest.raises(ValueError, match="transport:model"):
        read_seat("nonsense")


def test_the_matrix_says_which_check_failed_on_which_seat() -> None:
    runs = [
        {"case": "a", "seat": "codex:m", "sample": 1, "checks": {"one": None, "two": "broke"}},
        {"case": "a", "seat": "claude:n", "sample": 1, "checks": {"one": None}},
    ]

    matrix = matrix_of(runs)

    assert "| a | codex:m | 1 | pass | FAIL |" in matrix
    assert "| a | claude:n | 1 | pass | - |" in matrix


def test_a_failed_check_exits_non_zero_and_the_report_holds_the_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a run whose reply fails a check
    When the suite finishes
    Then it exits non-zero and the report holds the raw reply, the counts and
         the matrix: a gate that only printed would leave nothing to read.
    """
    import evals.__main__ as suite

    failing = document(rulings=[ruling("d9")]).model_dump_json()
    monkeypatch.setattr(suite, "replay", lambda *_: (failing, 9786, 1.5))

    code = suite.main(["--case", "2026-09-04-first-rung-nothing-owed", "--report", str(tmp_path)])

    assert code == 1
    assert (tmp_path / "matrix.md").read_text(encoding="utf-8").count("FAIL") == 1
    kept = next((tmp_path / "2026-09-04-first-rung-nothing-owed").iterdir())
    assert (kept / "1.txt").read_text(encoding="utf-8") == failing
    assert json.loads((kept / "1.json").read_text(encoding="utf-8"))["wall_seconds"] == 1.5


def test_a_run_whose_checks_all_pass_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.__main__ as suite

    monkeypatch.setattr(suite, "replay", lambda *_: (document().model_dump_json(), 9786, 1.0))

    assert (
        suite.main(["--case", "2026-09-04-first-rung-nothing-owed", "--report", str(tmp_path)]) == 0
    )
