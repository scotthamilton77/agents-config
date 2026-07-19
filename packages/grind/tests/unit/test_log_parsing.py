"""parse_event_log: JSONL reading, torn-tail tolerance, and fold_log's composition."""

from __future__ import annotations

import json

import pytest

from grind.log import LogCorruptionError, fold_log, parse_event_log
from tests.unit.builders import seed_event


def _line(evt: dict[str, object]) -> str:
    return json.dumps(evt)


def test_parses_well_formed_lines_in_order() -> None:
    events = [seed_event(), {"ts": "t", "type": "item_started", "item": "wgclw.1"}]
    text = "\n".join(_line(e) for e in events) + "\n"

    parsed = parse_event_log(text)

    assert parsed.events == events
    assert parsed.torn_tail is False


def test_empty_log_parses_to_no_events() -> None:
    parsed = parse_event_log("")

    assert parsed.events == []
    assert parsed.torn_tail is False


def test_a_truncated_final_line_is_dropped_and_flagged_as_torn_tail() -> None:
    good = _line(seed_event())
    torn = '{"ts": "t", "type": "item_started", "item": "wgc'  # cut off mid-write
    text = good + "\n" + torn  # no trailing newline: the torn fragment

    parsed = parse_event_log(text)

    assert parsed.events == [seed_event()]
    assert parsed.torn_tail is True


def test_a_malformed_line_that_is_not_the_tail_raises() -> None:
    good = _line(seed_event())
    text = "not json at all\n" + good + "\n"

    with pytest.raises(LogCorruptionError):
        parse_event_log(text)


def test_a_non_finite_constant_off_the_tail_is_treated_as_corruption() -> None:
    # A non-finite constant is non-standard JSON, so a non-tail line carrying
    # one is corruption -- same disposition as any other malformed non-tail
    # line, not a silently-accepted value.
    good = _line(seed_event())
    text = '{"ts": "t", "type": "item_started", "item": "x", "n": NaN}\n' + good + "\n"

    with pytest.raises(LogCorruptionError):
        parse_event_log(text)


def test_a_non_finite_constant_on_the_final_line_is_dropped_as_torn_tail() -> None:
    # On the tail, a non-parsing line follows the torn-tail convention: dropped
    # and flagged, never silently folded in.
    good = _line(seed_event())
    text = good + "\n" + '{"ts": "t", "type": "item_started", "item": "x", "n": Infinity}'

    parsed = parse_event_log(text)

    assert parsed.events == [seed_event()]
    assert parsed.torn_tail is True


def test_fold_log_records_a_torn_tail_as_an_attention_raising_observation() -> None:
    good = _line(seed_event())
    torn = '{"ts": "t", "type": "item_start'
    text = good + "\n" + torn

    state = fold_log(text)

    assert state.seeded is True
    assert any("torn_tail" in o.message for o in state.observations)
    assert any(a.auto for a in state.attention)


def test_fold_log_records_a_torn_tail_in_the_anomaly_projection() -> None:
    good = _line(seed_event())
    torn = '{"ts": "t", "type": "item_start'
    text = good + "\n" + torn

    state = fold_log(text)

    torn_anomalies = [a for a in state.anomalies if a.type == "torn_tail"]
    assert len(torn_anomalies) == 1
    assert torn_anomalies[0].reason
