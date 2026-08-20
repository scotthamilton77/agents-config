"""Shared fixtures and builders for the backend-core suite.

The builders default to the boring case so a test states only the fact it is
about: `event()` produces a well-formed submission, and each test overrides the
one field its claim turns on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from grillui.api import create_app
from grillui.log import SessionLog

SEED_NODE = "n1"


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    return tmp_path / "session"


@pytest.fixture
def log(session_dir: Path) -> SessionLog:
    return SessionLog(session_dir)


@pytest.fixture
def client(log: SessionLog) -> TestClient:
    return TestClient(create_app(log))


def event(
    kind: str = "informational",
    /,
    *,
    actor: str = "grill-master",
    channel: str = "map",
    key: str | None = "k1",
    **payload: Any,
) -> dict[str, Any]:
    """One well-formed submission, minus whatever the caller overrides."""
    body: dict[str, Any] = {
        "kind": kind,
        "actor": actor,
        "channel": channel,
        "payload": payload,
    }
    if key is not None:
        body["idempotency_key"] = key
    return body


def post(client: TestClient, epoch: str, *events: dict[str, Any]) -> list[dict[str, Any]]:
    """Submit a batch and return its receipts as plain JSON."""
    response = client.post("/events", json={"epoch": epoch, "events": list(events)})
    assert response.status_code == 200
    receipts: list[dict[str, Any]] = response.json()
    return receipts


def seed_node(client: TestClient, epoch: str, node_id: str = SEED_NODE) -> str:
    """Mint one node so tests about node ids have a known one to name."""
    receipt = post(
        client,
        epoch,
        event(
            "add-node",
            key=f"seed-{node_id}",
            target=node_id,
            short=node_id,
            title="Which storage?",
            body="Pick the storage layer.",
            prereqs=[],
            options=[
                {"id": "a", "text": "Append-only log", "pcr": ["audit", "size", "compaction"]},
                {"id": "b", "text": "Mutable table"},
            ],
        ),
    )[0]
    assert receipt["status"] == "accepted"
    return node_id


def seeded_log_file(session_dir: Path, entries: int) -> Path:
    """Write a log of `entries` lines directly, so a test can stand a process up
    against a session that is already large without paying for the writes."""
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "log.jsonl"
    lines = [
        json.dumps(
            {
                "seq": seq,
                "epoch": "earlier-tenure",
                "kind": "informational",
                "idempotency_key": f"seeded-{seq}",
                "timestamp": "2026-08-18T09:00:00.000+00:00",
                "actor": "grill-master",
                "channel": "map",
                "payload": {},
            }
        )
        for seq in range(1, entries + 1)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
