"""The replay suite's loader, its checks, and what its report says.

Nothing here reaches a model. What is proved is that a case loads, that the
prompt it pins is the prompt today's code renders, and that each check fails the
document it is there to catch and passes the one it is not.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from evals.__main__ import BASELINE, DEPENDENT, Tap, check, matrix_of, read_seat, seat_of
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
from grillui.drivers import seat_driver
from grillui.lane import AgentUnreachableError
from grillui.schemas import FAST_TIER, HEAVY_TIER, MAP_CHANNEL, GrillMasterDocument
from grillui.tiers import (
    CLAUDE_TRANSPORT,
    CODEX_TRANSPORT,
    TierConfig,
    UnknownTransportError,
    compose,
    system_prompt,
)

CASE = "2026-09-04-first-rung-nothing-owed"


def document(**overrides: Any) -> GrillMasterDocument:
    """A turn that passes every check, before an override breaks one."""
    return GrillMasterDocument.model_validate(
        {"text": "", "updates": [], "supersedes": [], "rulings": [], "stop": {"met": False}}
        | overrides
    )


def seeded_case(where: Path) -> Path:
    """A copy of a checked-in case, for a test that spoils one field of it."""
    where.mkdir(parents=True)
    for name in ("dispatch.json", "log.jsonl", "case.json"):
        (where / name).write_text((CASES / CASE / name).read_text(encoding="utf-8"), "utf-8")
    return where


def codex_stream(said: str, output_tokens: int = 7) -> str:
    """What `codex exec --json` prints for one turn."""
    return "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "t"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": said}}),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 11, "output_tokens": output_tokens},
                }
            ),
        ]
    )


def ruling(decision: str) -> dict[str, str]:
    return {"decision": decision, "ruling": "stands", "why": "it still asks the right question"}


# --- the fixtures ---------------------------------------------------------------


def test_every_checked_in_case_renders_the_prompt_it_pins() -> None:
    """
    Given every case checked in
    When each is rendered through the prompt code a session composes with
    Then its combined byte length is the one the case records, where it records
         one: a case whose recorded turn today's prompt no longer renders at the
         size it was sent at is a case replaying something else.
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
    cases = {one.name: one for one in load_cases()}

    assert cases["2026-09-04-expert-owed-rulings"].owed_rulings == ("d2", "d3")
    assert cases["2026-09-04-first-rung-nothing-owed"].owed_rulings == ()

    # The disagreement case is the first-rung map turn at that seq. What its
    # recorded reply did is not in the fixture, so the turn is pinned, not it.
    revise = cases["2026-08-27-revise-without-substance"]
    assert (revise.tier, revise.channel, revise.context.seq) == (FAST_TIER, MAP_CHANNEL, 25)
    assert revise.owed_rulings == ()


@pytest.mark.parametrize("named", ["../elsewhere/dispatch.json", "/etc/passwd", ".."])
def test_a_case_naming_a_path_outside_itself_is_refused(named: str, tmp_path: Path) -> None:
    """
    Given a complete case that also names a file outside its own directory
    When it is loaded
    Then that name is what refuses it: a case reading what the checkout does
         not carry replays a turn nobody else can see.
    """
    where = seeded_case(tmp_path / "borrowed")
    case = json.loads((where / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"log": named}), encoding="utf-8")

    with pytest.raises(CaseRefusedError, match="reads nothing outside"):
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
    where = seeded_case(tmp_path / "mismatched")
    case = json.loads((where / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"owed_rulings": ["d9"]}), encoding="utf-8")

    with pytest.raises(CaseRefusedError, match="owes"):
        load_case(where)


def test_a_case_sampling_nothing_is_refused(tmp_path: Path) -> None:
    """
    Given a case asking for no samples
    When it is loaded
    Then it is refused, by the rule a sample count on the command line is held
         to: a run that took no turn reports no failure and reads as a pass.
    """
    where = seeded_case(tmp_path / "empty")
    case = json.loads((where / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"samples": 0}), encoding="utf-8")

    with pytest.raises(CaseRefusedError, match="at least one sample"):
        load_case(where)


def test_a_stop_expectation_that_is_not_a_boolean_is_refused(tmp_path: Path) -> None:
    """
    Given a case whose stop expectation is written as a string
    When it is loaded
    Then it is refused: read for truth, "false" is true, and the case then
         checks for the opposite verdict to the one it was written with.
    """
    where = seeded_case(tmp_path / "stringly")
    case = json.loads((where / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"stop": "false"}), encoding="utf-8")

    with pytest.raises(CaseRefusedError, match="not true or false"):
        load_case(where)


def test_a_case_takes_its_channel_from_the_dispatch_it_replays(tmp_path: Path) -> None:
    """
    Given a case whose expectations name a channel of their own
    When it is loaded
    Then the dispatch's channel is the one it carries: the seat is chosen by it
         and the driver reads it off the record, so a second statement of it can
         only disagree.
    """
    where = seeded_case(tmp_path / "restated")
    case = json.loads((where / "case.json").read_text(encoding="utf-8"))
    (where / "case.json").write_text(json.dumps(case | {"channel": "t-9"}), encoding="utf-8")

    assert load_case(where).channel == MAP_CHANNEL


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


def test_a_reply_that_is_not_a_document_fails_every_check_that_reads_one() -> None:
    """
    Given a reply that is not the map document
    When it is checked
    Then every check has a verdict and each dependent one fails for the reason
         the shape check gave: a cell left blank reads as a check nobody ran,
         and the matrix is the whole record of what a seat did.
    """
    case = load_cases()[0]

    results = check(case, "just prose", None, baseline=True)

    shape = results[the_reply_is_the_map_document.__name__]
    assert shape is not None
    assert results[the_rulings_are_the_ones_owed.__name__] == shape
    assert all(results[one.__name__] == shape for one in DEPENDENT)


def test_a_seat_that_refuses_twice_is_a_red_row_carrying_what_it_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a seat whose reply the document gate refuses on both attempts
    When the suite runs
    Then the row is red for the stated reason and carries the reply the seat
         sent and what it cost: the turn happened and was paid for, and a run
         that raised, or one that recorded blanks, is the only record of it.
    """
    import evals.__main__ as suite

    case = next(one for one in load_cases() if one.name == CASE)
    config = TierConfig.from_env({})
    seat = seat_of(case, config)
    driver = seat_driver(config, seat, tier=case.tier)
    driver.cli = lambda *_args: codex_stream("just prose", output_tokens=31)  # type: ignore[union-attr]
    monkeypatch.setattr(suite, "seat_driver", lambda *_args, **_kwargs: driver)

    code = suite.main(["--case", CASE, "--report", str(tmp_path)])

    run = json.loads((tmp_path / "matrix.json").read_text("utf-8"))[0]
    assert code == 1
    assert run["output_tokens"] == 31
    assert run["output_bytes"] == len(b"just prose")
    assert run["wall_seconds"] >= 0
    reason = run["checks"][the_reply_is_the_map_document.__name__]
    assert reason is not None
    assert all(run["checks"][one.__name__] == reason for one in DEPENDENT)
    kept = next((tmp_path / CASE).iterdir())
    assert (kept / "1.txt").read_text(encoding="utf-8") == "just prose"


def test_a_check_that_does_not_apply_is_not_a_check_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a case run on a seat other than the one its baseline was measured on
    When the report is written
    Then the baseline is marked as not applying rather than passed or failed: a
         model that was never measured cannot be held to another model's count.
    """
    import evals.__main__ as suite

    monkeypatch.setattr(
        suite, "replay", lambda *_: (document().model_dump_json(), 9786, 40, 1.0, None)
    )

    assert (
        suite.main(["--case", CASE, "--seat", "codex:another-model", "--report", str(tmp_path)])
        == 0
    )

    rows = [one for one in (tmp_path / "matrix.md").read_text(encoding="utf-8").splitlines()[2:]]
    added = next(one for one in rows if "another-model" in one)
    default = next(one for one in rows if "another-model" not in one)
    assert "| - |" in added, added
    assert "| - |" not in default, default


def test_a_prompt_token_count_far_from_the_baseline_fails_its_check() -> None:
    """
    Given a case carrying a measured prompt-token baseline
    When a run bills far more than it
    Then the baseline check fails, so a seat that quietly grew its seed is
         caught here rather than on the next invoice.
    """
    case = next(one for one in load_cases() if one.prompt_tokens is not None)
    reply = document().model_dump_json()
    baseline = case.prompt_tokens

    def counted(tokens: int | None) -> str | None:
        return check(case, reply, tokens, baseline=True)[BASELINE]

    margin = int(baseline * 0.1)

    assert counted(baseline) is None
    # The boundary itself, and the first count outside it, in both directions.
    assert counted(baseline + margin) is None
    assert counted(baseline - margin) is None
    assert counted(baseline + margin + 1) is not None
    assert counted(baseline - margin - 1) is not None
    assert counted(None) is not None
    assert BASELINE not in check(case, reply, baseline, baseline=False)


def test_a_case_whose_member_file_is_a_symlink_is_refused(tmp_path: Path) -> None:
    """
    Given a case whose log is a link to a file elsewhere on the machine
    When it is loaded
    Then it is refused: a case reads nothing outside its own directory, and a
         link is a route out of it that the name alone does not show. The bytes
         it would pull in are composed into a prompt sent to a third party.
    """
    seeded = CASES / CASE
    where = tmp_path / "linked"
    where.mkdir()
    for name in ("dispatch.json", "case.json"):
        (where / name).write_text((seeded / name).read_text(encoding="utf-8"), encoding="utf-8")
    (where / "log.jsonl").symlink_to(seeded / "log.jsonl")

    with pytest.raises(CaseRefusedError, match=r"log\.jsonl"):
        load_case(where)


def test_an_added_node_is_held_to_each_field_on_its_own() -> None:
    """
    Given an added node missing only one of the fields the board renders
    When it is checked
    Then it fails either way round: a check that only caught a node missing both
         would pass one the page draws half of.
    """
    node = {
        "kind": "add-node",
        "title": "What confirms a match?",
        "short": "Confirm",
        "body": "How?",
    }

    assert added_nodes_carry_short_and_body(document(updates=[node])) is None
    for missing in ("short", "body"):
        thin = {one: value for one, value in node.items() if one != missing}
        assert added_nodes_carry_short_and_body(document(updates=[thin])) is not None, missing


def test_a_ruling_given_twice_is_not_the_ruling_that_was_owed() -> None:
    """
    Given a turn ruling on one decision twice
    When the rulings are checked
    Then it fails: the board shows a decision the turn judged once and a record
         that judged it twice, and nothing says which reading is the turn's.
    """
    twice = document(rulings=[ruling("d2"), ruling("d2"), ruling("d3")])

    assert the_rulings_are_the_ones_owed(twice, ("d2", "d3")) is not None
    assert (
        the_rulings_are_the_ones_owed(document(rulings=[ruling("d2"), ruling("d3")]), ("d2", "d3"))
        is None
    )


def test_an_option_named_in_an_update_is_held_to_the_same_rule_as_the_notice() -> None:
    """
    Given a turn naming an option without its decision inside an update rather
          than in the notice
    When it is checked
    Then it fails: the human reads both, and a rule that stopped at the notice
         would be satisfied by moving the sentence.
    """
    spoken = document(updates=[{"kind": "informational", "text": "Take option b."}])
    qualified = document(updates=[{"kind": "informational", "text": "Take option b of d1."}])

    assert option_references_name_their_decision(spoken) is not None
    assert option_references_name_their_decision(qualified) is None


def test_a_sample_count_below_one_is_refused(tmp_path: Path) -> None:
    """
    Given a run asked for no samples
    When the arguments are read
    Then it is refused rather than exiting clean having sampled nothing, which
         reads exactly like a suite that passed.
    """
    import evals.__main__ as suite

    with pytest.raises(SystemExit):
        suite.main(["--case", CASE, "-n", "-1", "--report", str(tmp_path)])


def test_every_sample_is_taken_and_any_one_of_them_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a case sampled three times, whose last sample alone fails a check
    When the suite runs
    Then every sample is taken and the run fails: a check that held twice and
         broke on the third held by luck.
    """
    import evals.__main__ as suite

    replies = [
        document().model_dump_json(),
        document().model_dump_json(),
        document(rulings=[ruling("d9")]).model_dump_json(),
    ]
    taken: list[str] = []

    def sampling(*_args: object) -> tuple[str, int | None, int | None, float, str | None]:
        taken.append(replies[len(taken)])
        return taken[-1], 9786, 40, 1.0, None

    monkeypatch.setattr(suite, "replay", sampling)

    code = suite.main(["--case", CASE, "-n", "3", "--report", str(tmp_path)])

    assert len(taken) == 3
    assert code == 1
    assert (tmp_path / "matrix.md").read_text(encoding="utf-8").count("FAIL") == 1


def test_the_clock_runs_on_a_seam_that_raises() -> None:
    """
    Given a seam that spends time and then raises
    When the turn is timed
    Then what it spent is on the record: a transport failure reported as taking
         no time is the one turn whose cost the report denies.
    """

    def raising() -> None:
        time.sleep(0.001)
        raise AgentUnreachableError(FAST_TIER)

    tap = Tap(raising)
    with pytest.raises(AgentUnreachableError):
        tap()

    assert tap.seconds > 0


def test_a_replay_sends_the_turn_through_the_seats_own_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Given a scripted seat standing in for the transport
    When a case is replayed
    Then the turn goes out through the driver the session builds, over a session
         log reconstructed from the case, and what comes back is read as that
         transport's reply.
    """
    import evals.__main__ as suite

    said = document(text="The board holds.").model_dump_json()
    sent: list[list[str]] = []

    def scripted(argv: object, _directory: Path, /) -> str:
        sent.append(list(argv))  # type: ignore[arg-type]
        return codex_stream(said)

    case = next(one for one in load_cases() if one.name == CASE)
    config = TierConfig.from_env({})
    seat = seat_of(case, config)
    driver = seat_driver(config, seat, tier=case.tier)
    driver.cli = scripted  # type: ignore[union-attr]
    monkeypatch.setattr(suite, "seat_driver", lambda *_args, **_kwargs: driver)

    reply, prompt_tokens, output_tokens, seconds, refused = suite.replay(case, seat, config)

    assert reply == said
    assert (prompt_tokens, output_tokens) == (11, 7)
    assert seconds >= 0
    assert refused is None
    assert sent and sent[0][0] == "codex"


def test_a_case_directory_that_is_a_link_out_of_the_tree_is_refused(tmp_path: Path) -> None:
    """
    Given a case directory that is a link to a session elsewhere on the machine
    When the cases are loaded
    Then it is refused: the containment is on the tree, so a link at the
         directory is the same route out as a link at one of its files.
    """
    root = tmp_path / "cases"
    root.mkdir()
    (root / "borrowed").symlink_to(CASES / CASE, target_is_directory=True)

    with pytest.raises(CaseRefusedError, match="the case directory"):
        load_cases(root)


def test_an_unnarrowed_run_takes_every_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given no case named on the command line
    When the suite runs
    Then every checked-in case is taken: a suite that quietly ran one of them
         reports green on the two it never asked.
    """
    import evals.__main__ as suite

    monkeypatch.setattr(
        suite, "replay", lambda *_: (document().model_dump_json(), 4868, 40, 1.0, None)
    )

    suite.main(["--report", str(tmp_path)])

    taken = {one["case"] for one in json.loads((tmp_path / "matrix.json").read_text("utf-8"))}
    assert taken == {one.name for one in load_cases()}
    # A narrowing nothing answers is refused, even beside one that does.
    with pytest.raises(SystemExit):
        suite.main(["--case", CASE, "--case", "typo", "--report", str(tmp_path)])


def test_a_seat_named_twice_does_not_overwrite_its_own_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given the case's own seat named again on the command line
    When the suite runs
    Then it is taken once: two runs keyed by the same seat write one another's
         reply and counts over each other, and the report reads as one run.
    """
    import evals.__main__ as suite

    monkeypatch.setattr(
        suite, "replay", lambda *_: (document().model_dump_json(), 9786, 40, 1.0, None)
    )

    suite.main(["--case", CASE, "--seat", "codex:gpt-5.6-luna:medium", "--report", str(tmp_path)])

    assert len(json.loads((tmp_path / "matrix.json").read_text("utf-8"))) == 1


def test_a_seat_on_a_transport_no_session_has_is_refused() -> None:
    """
    Given a seat naming a transport this session cannot sit on
    When the arguments are read
    Then it is refused before anything runs, rather than reaching a driver that
         has no seam to send through and dying with no report written.
    """
    with pytest.raises(UnknownTransportError):
        read_seat("typo:some-model")


def test_the_stop_verdict_is_held_both_ways() -> None:
    """
    Given a case expecting the grilling to be over and one expecting it not to be
    When each turn's verdict is checked
    Then each is held to its own case: a check that only ever caught a turn
         stopping early would pass one that never stops at all.
    """
    assert the_stop_verdict_is_expected(document(stop={"met": False}), expected=True) is not None
    assert the_stop_verdict_is_expected(document(stop={"met": True}), expected=True) is None


def test_two_updates_that_speak_are_two_channels() -> None:
    """
    Given a turn speaking twice through updates and not at all in its notice
    When the speech channels are counted
    Then it fails: the human reads both, and counting the notice alone would
         pass a shelf of them.
    """
    twice = document(
        updates=[
            {"kind": "informational", "text": "One thing."},
            {"kind": "informational", "text": "And another."},
        ]
    )

    assert the_turn_speaks_once(twice) is not None
    assert the_turn_speaks_once(twice, limit=2) is None


def test_each_case_is_replayed_on_the_seat_it_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given an expert case and a thread case
    When the suite runs them
    Then each turn is sent to its own rung's seat: a run that put every case on
         one seat is a green report about seats nobody sat on.
    """
    import evals.__main__ as suite

    config = TierConfig.from_env({})
    expert = next(one for one in load_cases() if one.tier == HEAVY_TIER)
    thread = replace(expert, name="t", tier=FAST_TIER, channel="t-1", prompt_tokens=None)
    seats: list[object] = []
    monkeypatch.setattr(suite, "load_cases", lambda: [expert, thread])
    monkeypatch.setattr(
        suite,
        "replay",
        lambda _case, seat, _config: (
            seats.append(seat) or (document().model_dump_json(), 4868, 40, 1.0, None)
        ),
    )

    suite.main(["--report", str(tmp_path)])

    assert seats == [config.expert_seat, config.thread_seat]


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
    for refused in ("nonsense", "codex:m:medium:extra", "openrouter:m:high", "codex:m:brisk"):
        with pytest.raises(ValueError):
            read_seat(refused)


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
    monkeypatch.setattr(suite, "replay", lambda *_: (failing, 9786, 812, 1.5, None))

    code = suite.main(["--case", CASE, "--report", str(tmp_path)])

    assert code == 1
    assert (tmp_path / "matrix.md").read_text(encoding="utf-8").count("FAIL") == 1
    kept = next((tmp_path / CASE).iterdir())
    assert (kept / "1.txt").read_text(encoding="utf-8") == failing
    recorded = json.loads((kept / "1.json").read_text(encoding="utf-8"))
    assert recorded["wall_seconds"] == 1.5
    assert recorded["prompt_tokens"] == 9786
    assert recorded["output_tokens"] == 812


def test_a_run_whose_checks_all_pass_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.__main__ as suite

    monkeypatch.setattr(
        suite, "replay", lambda *_: (document().model_dump_json(), 9786, 40, 1.0, None)
    )

    assert suite.main(["--case", CASE, "--report", str(tmp_path)]) == 0
