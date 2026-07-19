"""Shared event-builder helpers for fold tests."""

from __future__ import annotations

from typing import Any


def seed_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "ts": "2026-07-19T00:00:00Z",
        "type": "grind_created",
        "title": "Widget grind",
        "repo": "acme/widgets",
        "mission": {"goal": "ship widgets"},
        "protocols": {},
        "config": {},
        "lanes": [
            {
                "id": "lane-a",
                "name": "Lane A",
                "agent": "lieutenant-a",
                "queue": [
                    {"id": "wgclw.1", "title": "First item"},
                    {"id": "wgclw.2", "title": "Second item"},
                ],
            }
        ],
    }
    event.update(overrides)
    return event


def event(evt_type: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ts": "2026-07-19T00:05:00Z", "type": evt_type}
    payload.update(fields)
    return payload
