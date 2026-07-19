"""Fold behavior for the grind lifecycle's seeding event, `grind_created`."""

from __future__ import annotations

from grind.fold import fold


def _seed_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "ts": "2026-07-19T00:00:00Z",
        "type": "grind_created",
        "title": "Widget grind",
        "repo": "acme/widgets",
        "mission": {"goal": "ship widgets", "out_of_scope": ["gadgets"]},
        "protocols": {"review": "codex"},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "name": "Lane A",
                "agent": "lieutenant-a",
                "model": "sonnet",
                "effort": "medium",
                "queue": [
                    {"id": "wgclw.1", "title": "First item"},
                    {"id": "wgclw.2", "title": "Second item"},
                ],
            }
        ],
    }
    event.update(overrides)
    return event


def test_grind_created_seeds_header_fields() -> None:
    state = fold([_seed_event()])

    assert state.title == "Widget grind"
    assert state.repo == "acme/widgets"
    assert state.mission == {"goal": "ship widgets", "out_of_scope": ["gadgets"]}
    assert state.protocols == {"review": "codex"}


def test_grind_created_seeds_lanes_and_items_as_queued() -> None:
    state = fold([_seed_event()])

    assert set(state.lanes) == {"lane-a"}
    lane = state.lanes["lane-a"]
    assert lane.name == "Lane A"
    assert lane.agent == "lieutenant-a"
    assert lane.item_ids == ["wgclw.1", "wgclw.2"]

    assert state.items["wgclw.1"].status == "queued"
    assert state.items["wgclw.1"].title == "First item"
    assert state.items["wgclw.1"].lane == "lane-a"


def test_seeded_blocker_edges_fold_item_as_blocked_not_queued() -> None:
    event = _seed_event()
    lanes = event["lanes"]
    assert isinstance(lanes, list)
    lanes[0]["queue"].append({"id": "wgclw.3", "title": "Depends on wgclw.1", "on": ["wgclw.1"]})

    state = fold([event])

    assert state.items["wgclw.3"].status == "blocked"
    assert state.items["wgclw.3"].blocked_on == ("wgclw.1",)


def test_second_grind_created_is_an_anomaly_leaving_board_unchanged() -> None:
    first = _seed_event()
    second = _seed_event(title="Different title")

    state = fold([first, second])

    assert state.title == "Widget grind"
    assert len(state.anomalies) == 1
    assert state.anomalies[0].type == "grind_created"
