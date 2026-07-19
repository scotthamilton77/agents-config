"""Replay property: fold is pure and time-independent (spec's Testing section).

`fold(log)` re-run on the same events (or a re-parsed copy of the same log
text) must produce an equal `State` every time -- delete-and-refold is the
runtime's whole recovery story, so nondeterminism here is a correctness bug,
not a cosmetic one.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from grind.fold import fold
from grind.log import fold_log, parse_event_log
from tests.unit.builders import event, seed_event

_EVENTS = [
    seed_event(),
    event("item_started", item="wgclw.1"),
    event("pr_opened", item="wgclw.1", pr=7, url="https://example.com/pr/7"),
    event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="a1"),
    event(
        "review_verdict",
        item="wgclw.1",
        kind="codex",
        round=1,
        head_sha="a1",
        verdict="findings",
        findings=[{"severity": "low", "summary": "nit", "disposition": "wont-fix"}],
    ),
    event("item_merged", item="wgclw.1", pr=7, sha="a1"),
    event("item_done", item="wgclw.1"),
    event("item_blocked", item="wgclw.2", on=["does-not-exist"]),
    event("observation", level="WARN", message="watch this repo's flaky CI"),
]


def test_folding_the_same_events_twice_yields_equal_state() -> None:
    first = fold(_EVENTS)
    second = fold(_EVENTS)

    assert asdict(first) == asdict(second)


def test_folding_an_unrelated_events_list_object_with_equal_content_is_equal() -> None:
    # A fresh list built from copies of the same dicts (as a fresh parse from
    # disk would produce), not the same Python objects.
    copy_of_events = [dict(evt) for evt in _EVENTS]

    original = fold(_EVENTS)
    replayed = fold(copy_of_events)

    assert asdict(original) == asdict(replayed)


def test_delete_and_refold_via_log_text_is_byte_identical() -> None:
    text = "\n".join(json.dumps(e) for e in _EVENTS) + "\n"

    parsed_once = parse_event_log(text)
    parsed_twice = parse_event_log(text)
    assert parsed_once.events == parsed_twice.events

    state_once = fold_log(text)
    state_twice = fold_log(text)
    assert asdict(state_once) == asdict(state_twice)
