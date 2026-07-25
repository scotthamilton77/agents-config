"""`grind status --handoff` -- the re-orientation projection.

The headline test is `test_a_contextless_session_re_orients_from_one_call`:
one `main(["status", "--handoff"])` invocation, and every question a
post-compaction session would otherwise have to ask a human is answered out
of that single envelope. The rest pin the pieces it is built from.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from grind.cli import main
from grind.conditions import IMPERATIVE_VERBS
from grind.fold import fold
from grind.handoff import handoff_json
from grind.model import State
from grind.serialize import full_state_json
from tests.unit.builders import event, seed_event

_NOW = datetime(2026, 7, 19, 1, 0, 0, tzinfo=UTC)

_MISSION = {
    "goal": "ship the widget rewrite",
    "out_of_scope": ["the billing migration"],
}
_PROTOCOLS = {
    "review": "codex adversarial, two rounds minimum",
    "merge": "merge-guard clean, no exceptions",
}


def _seed() -> dict[str, Any]:
    return seed_event(
        mission=_MISSION,
        protocols=_PROTOCOLS,
        lanes=[
            {
                "id": "lane-a",
                "name": "Lane A",
                "agent": "lieutenant-a",
                "queue": [
                    {"id": "wgclw.1", "title": "First item"},
                    {"id": "wgclw.2", "title": "Second item"},
                ],
            },
            {
                "id": "lane-b",
                "name": "Lane B",
                "agent": "lieutenant-b",
                "queue": [
                    {"id": "wgclw.3", "title": "Third item"},
                    {"id": "wgclw.4", "title": "Fourth item"},
                ],
            },
        ],
    )


def _rich_log() -> list[dict[str, Any]]:
    """A run that has reached every corner of the handoff's anatomy: something
    shipped, something stuck on something else, something waiting on a human,
    a PR closed unmerged into the parking lot, a lane handed over, a quirk and
    a lesson recorded, a pause standing, and an event that folded anomalously."""
    return [
        _seed(),
        # wgclw.1 -- all the way through to done
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=101, url="https://example.test/pr/101"),
        event("review_round", item="wgclw.1", kind="codex", round=1, head_sha="aaa"),
        event(
            "review_verdict", item="wgclw.1", kind="codex", round=1, head_sha="aaa", verdict="clean"
        ),
        event("item_merged", item="wgclw.1", pr=101, sha="aaa"),
        event("item_done", item="wgclw.1"),
        # wgclw.2 -- stuck on wgclw.3
        event("item_started", item="wgclw.2"),
        event("item_blocked", item="wgclw.2", on=["wgclw.3"], note="needs the shared schema"),
        # wgclw.3 -- open PR, handed to a human
        event("item_started", item="wgclw.3"),
        event("pr_opened", item="wgclw.3", pr=103),
        event("item_waiting_human", item="wgclw.3", why="needs a human ruling on the API break"),
        # wgclw.4 -- PR closed unmerged, into the parking lot
        event("item_started", item="wgclw.4"),
        event("pr_opened", item="wgclw.4", pr=104),
        event("pr_closed", item="wgclw.4", pr=104, reason="superseded", next="parked"),
        # work discovered mid-run, admitted to lane-a with its work-tracker id
        event(
            "discovered_work",
            item="wgclw.9",
            description="Ninth item",
            source="lane-a review of wgclw.1",
            rationale="the schema change needs its own item",
            disposition="enqueued",
            lane="lane-a",
            work_id="acme-9",
        ),
        # roster change, traps, and a pause
        event(
            "lane_handover",
            lane="lane-a",
            from_agent="lieutenant-a",
            to_agent="lieutenant-c",
            reason="context exhausted",
            to_model="opus",
            to_effort="high",
        ),
        event("observation", level="WARN", message="the widget test suite needs a clean build dir"),
        event("observation", level="LESSON", message="open the dashboard once, at creation"),
        event("observation", level="INFO", message="routine progress note"),
        event(
            "grind_paused",
            reason="waiting on the API ruling",
            resume_checklist=["confirm the API break with the human"],
        ),
        # an event illegal from its item's status -- accepted and flagged
        event("item_started", item="wgclw.1"),
    ]


def _state() -> State:
    return fold(_rich_log())


def _handoff() -> dict[str, Any]:
    return handoff_json(_state())


def _run(argv: Sequence[str], *, cwd: Path) -> tuple[int, dict[str, Any]]:
    out, err = StringIO(), StringIO()
    exit_code = main(list(argv), out=out, err=err, now=lambda: _NOW, cwd=cwd, env={})
    assert err.getvalue() == ""
    return exit_code, json.loads(out.getvalue())


def _written_grind(tmp_path: Path) -> Path:
    """The rich log, on disk, exactly as the CLI would have written it."""
    grind_dir = tmp_path / "run"
    grind_dir.mkdir()
    (grind_dir / "events.jsonl").write_text(
        "".join(json.dumps(evt, sort_keys=True) + "\n" for evt in _rich_log()), encoding="utf-8"
    )
    return grind_dir


def test_a_contextless_session_re_orients_from_one_call(tmp_path: Path):
    """The acceptance proof. A session with no context makes exactly one call
    and answers, from that one envelope alone, every question it would
    otherwise have had to ask the human."""
    grind_dir = _written_grind(tmp_path)

    exit_code, envelope = _run(["status", "--handoff", "--dir", str(grind_dir)], cwd=tmp_path)

    assert exit_code == 0
    assert envelope["ok"] is True
    handoff = envelope["handoff"]

    # 1. What is this run, and what is it explicitly not?
    assert handoff["summary"]["title"] == "Widget grind"
    assert handoff["summary"]["repo"] == "acme/widgets"
    assert handoff["mission"]["goal"] == "ship the widget rewrite"
    assert handoff["mission"]["out_of_scope"] == ["the billing migration"]

    # 2. Under what rules is it operating?
    assert handoff["protocols"] == _PROTOCOLS

    # 3. Is it even running, and what stands between it and running again?
    assert handoff["paused"] is True
    assert handoff["pause_reason"] == "waiting on the API ruling"
    assert handoff["resume_checklist"] == ["confirm the API break with the human"]

    # 4. Who is on which lane, and where did every item get to?
    roster = {lane["id"]: lane for lane in handoff["lanes"]}
    assert roster["lane-a"]["agent"] == "lieutenant-c"  # post-handover, not the seeded agent
    assert roster["lane-a"]["model"] == "opus"
    positions = {item["id"]: item["status"] for lane in handoff["lanes"] for item in lane["items"]}
    # wgclw.4 is absent by design: parking takes an item off its lane's queue,
    # and the parking lot below is where it is accounted for.
    assert positions == {
        "wgclw.1": "done",
        "wgclw.2": "blocked",
        "wgclw.3": "waiting-human",
        "wgclw.9": "queued",
    }
    # The work-tracker handle rides along, so the session can cross-reference
    # the item without a second source.
    work_ids = {item["id"]: item["work_id"] for lane in handoff["lanes"] for item in lane["items"]}
    assert work_ids["wgclw.9"] == "acme-9"

    # 5. Where does each lane pick up?
    frontier = {row["lane"]: row for row in handoff["frontier"]}
    assert frontier["lane-a"]["item"] == "wgclw.2"
    assert frontier["lane-b"]["item"] == "wgclw.3"

    # 6. What is stuck, and on what?
    blocked = {row["item"]: row for row in handoff["blocked"]}
    assert blocked["wgclw.2"]["note"] == "needs the shared schema"
    assert blocked["wgclw.2"]["blocked_on"] == [{"item": "wgclw.3", "status": "waiting-human"}]

    # 7. What does a human owe this run?
    docket = [entry["text"] for entry in handoff["human_docket"]]
    assert "needs a human ruling on the API break" in docket

    # 8. What already shipped, and what died on the vine?
    assert [entry["item"] for entry in handoff["merged_ledger"]] == ["wgclw.1"]
    assert [entry["item"] for entry in handoff["closed_ledger"]] == ["wgclw.4"]
    assert [entry["id"] for entry in handoff["parking_lot"]] == ["wgclw.4"]

    # 9. What traps has this repo already sprung?
    assert [obs["message"] for obs in handoff["quirks"]] == [
        "the widget test suite needs a clean build dir"
    ]
    assert [obs["message"] for obs in handoff["lessons"]] == [
        "open the dashboard once, at creation"
    ]

    # 10. What did the log accept but flag as wrong?
    assert [record["type"] for record in handoff["anomalies"]] == ["item_started"]
    assert "illegal from status" in handoff["anomalies"][0]["reason"]

    # ...and the conditions ride the same envelope, as they do for every
    # other status mode -- still one call.
    assert isinstance(envelope["conditions"], list)


def test_handoff_is_a_projection_of_the_same_fold_the_other_views_report(tmp_path: Path):
    """No new event type, no separate persistence: `--handoff` reads the same
    log the other views read and writes nothing."""
    grind_dir = _written_grind(tmp_path)
    before = (grind_dir / "events.jsonl").read_bytes()

    _, handoff_envelope = _run(["status", "--handoff", "--dir", str(grind_dir)], cwd=tmp_path)
    _, full_envelope = _run(["status", "--full", "--dir", str(grind_dir)], cwd=tmp_path)

    assert (grind_dir / "events.jsonl").read_bytes() == before
    assert not (grind_dir / "state.json").exists()
    assert handoff_envelope["conditions"] == full_envelope["conditions"]
    assert handoff_envelope["handoff"]["last_event_ts"] == full_envelope["state"]["last_event_ts"]


def test_handoff_and_full_are_mutually_exclusive(tmp_path: Path):
    grind_dir = _written_grind(tmp_path)

    exit_code, envelope = _run(
        ["status", "--handoff", "--full", "--dir", str(grind_dir)], cwd=tmp_path
    )

    assert exit_code != 0
    assert envelope["ok"] is False


def test_default_status_view_is_unchanged_by_the_new_flag(tmp_path: Path):
    grind_dir = _written_grind(tmp_path)

    _, envelope = _run(["status", "--dir", str(grind_dir)], cwd=tmp_path)

    assert "state_summary" in envelope
    assert "handoff" not in envelope


def test_log_emit_back_envelope_still_carries_no_state(tmp_path: Path):
    """The handoff is what re-orients a cold session -- deliberately not the
    `log` envelope, whose keys stay exactly as specified so nobody builds a
    recovery path on a call that cannot support one."""
    grind_dir = _written_grind(tmp_path)

    _, envelope = _run(
        ["log", "grind_resumed", "--json", "{}", "--dir", str(grind_dir)], cwd=tmp_path
    )

    assert set(envelope) == {"ok", "applied", "anomaly", "torn_tail", "delta", "conditions"}


# -- the shaped pieces -------------------------------------------------------


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in _keys(value)}
    return set()


def test_no_handoff_key_reads_as_an_instruction():
    """The `conditions.py` seam, applied to this projection's vocabulary: the
    handoff reports facts, so no key it coins -- at any depth -- may read as an
    order.

    The exemption is mechanical, not a hand-kept allow-list: a key that already
    appears in `state.json` is `State`'s vocabulary, governed where it is
    defined. Only what this projection invents is on trial here."""
    state = _state()

    coined = _keys(handoff_json(state)) - _keys(full_state_json(state))
    # The exemption is load-bearing in both directions, so pin both: it must
    # not swallow this projection's own vocabulary, and it must actually
    # resolve against the real serializer rather than degrading to a no-op.
    assert "frontier" in coined, "the exemption must not swallow the whole key set"
    assert "resume_checklist" not in coined, "State's own vocabulary must resolve as inherited"

    for key in coined:
        for word in re.split(r"[_\s]", key):
            assert word not in IMPERATIVE_VERBS, f"handoff key {key!r} reads as an imperative"


def test_frontier_is_the_frontmost_non_terminal_unparked_item_with_its_basis():
    frontier = {row["lane"]: row for row in _handoff()["frontier"]}

    # wgclw.1 is done, so lane-a's queue order moves past it to wgclw.2.
    assert frontier["lane-a"]["item"] == "wgclw.2"
    assert frontier["lane-a"]["status"] == "blocked"
    assert frontier["lane-a"]["blocked_on"] == ["wgclw.3"]
    assert "queue order" in frontier["lane-a"]["basis"]


def test_frontier_reports_a_lane_with_nothing_left_as_such():
    events = [
        _seed(),
        event("item_started", item="wgclw.3"),
        event("pr_opened", item="wgclw.3", pr=103),
        event("item_merged", item="wgclw.3", pr=103, sha="ccc"),
        event("item_done", item="wgclw.3"),
        event("item_parked", item="wgclw.4", reason="later-wave", note="next wave"),
    ]
    frontier = {row["lane"]: row for row in handoff_json(fold(events))["frontier"]}

    assert frontier["lane-b"]["item"] is None
    assert frontier["lane-b"]["status"] is None
    assert (
        frontier["lane-b"]["basis"] == "every item in the lane's queue order is terminal or parked"
    )


def test_frontier_passes_over_a_parked_item_but_stops_on_a_blocked_one():
    events = [
        _seed(),
        event("item_parked", item="wgclw.1", reason="later-wave", note="next wave"),
        event("item_blocked", item="wgclw.2", on=["wgclw.3"], note="waits on the schema"),
    ]
    frontier = {row["lane"]: row for row in handoff_json(fold(events))["frontier"]}

    assert frontier["lane-a"]["item"] == "wgclw.2"
    assert frontier["lane-a"]["status"] == "blocked"


def test_blocked_rows_carry_each_blockers_current_status_as_evidence():
    blocked = {row["item"]: row for row in _handoff()["blocked"]}

    assert list(blocked) == ["wgclw.2"]
    assert blocked["wgclw.2"]["lane"] == "lane-a"
    assert blocked["wgclw.2"]["blocked_on"] == [{"item": "wgclw.3", "status": "waiting-human"}]


def test_blocked_row_reports_an_unknown_blocker_as_a_null_status_rather_than_dropping_it():
    events = [
        _seed(),
        event("item_started", item="wgclw.2"),
        event("item_blocked", item="wgclw.2", on=["wgclw.2", "ghost-item"], note="n"),
    ]
    blocked = {row["item"]: row for row in handoff_json(fold(events))["blocked"]}

    assert {"item": "ghost-item", "status": None} in blocked["wgclw.2"]["blocked_on"]


def test_quirks_are_warn_observations_only_and_lessons_stay_separate():
    handoff = _handoff()

    assert [obs["level"] for obs in handoff["quirks"]] == ["WARN"]
    assert [obs["level"] for obs in handoff["lessons"]] == ["LESSON"]


def test_pause_fields_are_inert_on_a_running_grind():
    handoff = handoff_json(fold([_seed()]))

    assert handoff["paused"] is False
    assert handoff["pause_reason"] is None
    assert handoff["resume_checklist"] == []


def test_handoff_of_a_never_created_grind_is_shaped_but_empty():
    """A fold of zero events still yields every key, so a reader never has to
    branch on presence -- only on emptiness."""
    handoff = handoff_json(State())

    assert handoff["lanes"] == []
    assert handoff["frontier"] == []
    assert handoff["mission"] is None
    assert handoff["paused"] is False


def test_finished_grind_reports_its_closing_summary():
    events = [_seed(), event("grind_finished", summary="all four items landed")]
    handoff = handoff_json(fold(events))

    assert handoff["summary"]["finished"] is True
    assert handoff["finish_summary"] == "all four items landed"


@pytest.mark.parametrize(
    "key",
    [
        "summary",
        "mission",
        "protocols",
        "last_event_ts",
        "paused",
        "pause_reason",
        "resume_checklist",
        "finish_summary",
        "lanes",
        "frontier",
        "blocked",
        "human_docket",
        "merged_ledger",
        "closed_ledger",
        "parking_lot",
        "quirks",
        "lessons",
        "anomalies",
    ],
)
def test_every_handoff_key_is_present_on_every_run(key: str):
    """Stable, greppable structure: the key set does not depend on what the run
    happened to do, so a cold reader's expectations never depend on luck."""
    assert key in _handoff()
    assert key in handoff_json(State())


def test_parking_lot_entries_carry_the_typed_park_axis_and_category():
    events = [
        _seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=101),
        event("item_parked", item="wgclw.1", reason="ci-failure", note="flaky integration suite"),
    ]
    parking_lot = handoff_json(fold(events))["parking_lot"]

    assert parking_lot[0]["parked"] == {
        "reason": "ci-failure",
        "axis": "failure",
        "category": "machine",
        "note": "flaky integration suite",
    }


def test_item_rows_carry_the_pr_handle_and_review_position():
    events = [
        _seed(),
        event("item_started", item="wgclw.1"),
        event("pr_opened", item="wgclw.1", pr=101, url="https://example.test/pr/101"),
        event("review_round", item="wgclw.1", kind="codex", round=2, head_sha="aaa"),
    ]
    lane_a = handoff_json(fold(events))["lanes"][0]
    first_item = lane_a["items"][0]

    assert first_item["pr"] == {"number": 101, "url": "https://example.test/pr/101"}
    assert first_item["review"]["round"] == 2
    assert first_item["review"]["kind"] == "codex"
