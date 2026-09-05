"""Shared fixtures and builders for the backend-core suite.

The builders default to the boring case so a test states only the fact it is
about: `event()` produces a well-formed submission, `handoff_doc()` a conforming
briefing, and each test overrides the one field its claim turns on.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from grillui.api import create_app
from grillui.dispatch import agent_for
from grillui.lane import Lane
from grillui.log import HANDOFF_FILE, LOG_FILE, SessionLog
from grillui.schemas import (
    APPLY_KIND,
    CONTEXT_BYTES_KEY,
    CONTEXT_LIMIT_KEY,
    PROMPT_TOKENS_KEY,
    PROPOSABLE_KINDS,
    RULINGS_KEY,
    STOP_KEY,
    TIER_KEY,
    DispatchContext,
    EventSubmission,
    LogEntry,
    ThreadConclusion,
    ThreadProjection,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from grillui.schemas import Receipt

SEED_NODE = "n1"
TIMEOUT = 5.0
AGENT_ACTORS = frozenset({"grill-master", "thread-agent"})

# How long a write racing an agent's reply is given to land. It only has to
# reach an append, so this is generous for what it measures -- and it is paid
# only when the lock does its job and holds the racer off.
RACE_WINDOW = 0.25

# One conforming handoff, with every optional part of the node shape present on
# some node: a mandate, talk seeds, a fog rule, an option trio. A builder that
# only ever produced the minimum would let the seeding drop everything optional
# and still pass.
HANDOFF: dict[str, Any] = {
    "handoff_version": 1,
    "session": {
        "id": "grill-1",
        "title": "Session store design",
        "created": "2026-08-18T09:00:00+00:00",
        "author": "main agent",
    },
    "impetus": "The store shape is about to be built and nobody has argued against it.",
    "context": "The log is append-only and the page is a renderer.",
    "constraints": ["no new services"],
    "grilling_brief": {
        "posture": "hard on cost and on recovery",
        "stop_when": "every decision is settled or parked with a named blocker",
    },
    "plan": {
        "statement": "Design the session store.",
        "decisions": [
            {
                "id": "d1",
                "short": "Store",
                "title": "Which storage?",
                "prereqs": [],
                "body": "Pick the storage layer.",
                "options": [
                    {"id": "a", "text": "Append-only log", "pcr": ["audit", "size", "compaction"]},
                    {"id": "b", "text": "Mutable table"},
                ],
                "talk": {"why": "Recovery rests on it.", "zoom": "Consider a crash mid-write."},
            },
            {
                "id": "d2",
                "short": "Compaction",
                "title": "When is the log compacted?",
                "prereqs": ["d1"],
                "body": "Say when, or say never.",
                "options": [
                    {"id": "a", "text": "Never"},
                    {"id": "b", "text": "On restart"},
                ],
                "mandate": {
                    "threadId": "t-compaction",
                    "scope": "retention",
                    "title": "Compaction policy",
                    "notice": "Any answer opens this thread.",
                },
                "fogUntil": "d1",
                "fogTitle": "Settle the store first",
            },
        ],
    },
}


def handoff_doc(**overrides: Any) -> dict[str, Any]:
    """A conforming handoff, deep-copied so a test may edit it freely."""
    return {**copy.deepcopy(HANDOFF), **overrides}


def write_handoff(directory: Path, document: dict[str, Any], name: str = HANDOFF_FILE) -> Path:
    """Put a handoff where a backend would find it."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# What the scripted seats say by default, and what every check that is not
# about the notice's wording reads back out of the log.
REPLY_TEXT = "The log is the recovery source. Compaction is the next question."


class _Absent:
    """The sentinel that takes a key out of a document, since `None` is itself a
    shape a document may carry wrongly."""


_ABSENT = _Absent()


def document(
    text: Any = REPLY_TEXT,
    updates: Any = (),
    supersedes: Any = (),
    rulings: Any = (),
    stop: Any = None,
    **broken: Any,
) -> str:
    """One grill-master map document, defaulting to the turn that proposes
    nothing and rules on nothing.

    Every field is loosely typed and `broken` takes any extra key, because half
    of what this builds is documents that are wrong on purpose: a builder that
    only produced valid ones could not state the invalid case at all. Passing
    `_ABSENT` for a field leaves that key out. Building the invalid case out of
    the valid one is what keeps it invalid for the stated reason and no other.
    """
    body: dict[str, Any] = {
        "text": text,
        "updates": [dict(one) for one in updates] if isinstance(updates, Iterable) else updates,
        "supersedes": list(supersedes) if isinstance(supersedes, Iterable) else supersedes,
        "rulings": [dict(one) for one in rulings] if isinstance(rulings, Iterable) else rulings,
        "stop": {"met": False, "why": ""} if stop is None else stop,
        **broken,
    }
    return json.dumps({key: value for key, value in body.items() if value is not _ABSENT})


@dataclass
class SpyDriver:
    """A tier that records what the log already said when it was handed a turn.

    `hold` keeps the turn in flight until the test releases it, which is how a
    slow model is stood in for without one. `reply` is what the turn says into
    the log before it finishes, for the cases about where a reply lands rather
    than about when it starts.
    """

    tier: str = "fast"
    hold: bool = False
    reply: str | None = None
    seen: list[LogEntry] = field(default_factory=list)
    dispatches: list[Path] = field(default_factory=list)
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)

    def run(self, log: SessionLog, dispatch: Path, /) -> None:
        self.seen = log.entries()
        self.dispatches.append(dispatch)
        self.started.set()
        if self.hold:
            self.release.wait(TIMEOUT)
        if self.reply is not None:
            log.submit(
                [
                    EventSubmission(
                        kind="informational",
                        actor="grill-master",
                        idempotency_key=f"reply-{uuid4().hex}",
                        payload={"text": self.reply},
                    )
                ],
                log.epoch,
            )
        self.finished.set()


@dataclass
class ScriptedCli:
    """A `claude` CLI that answers to order and remembers its argv.

    `overlapping` is what the single-process rule is proved against: it records
    whether a second turn was ever inside this call while a first still was.
    """

    reply: str = field(default_factory=document)
    session_id: str = "chain-1"
    usage: dict[str, Any] | None = None
    calls: list[list[str]] = field(default_factory=list)
    directories: list[Path] = field(default_factory=list)
    hold: float = 0.0
    overlapping: bool = False
    _inside: int = 0

    def __call__(self, argv: list[str], directory: Path, /) -> str:
        self.calls.append(list(argv))
        self.directories.append(directory)
        self._inside += 1
        self.overlapping = self.overlapping or self._inside > 1
        time.sleep(self.hold)
        self._inside -= 1
        printed: dict[str, Any] = {"session_id": self.session_id, "result": self.reply}
        # Absent by default: a CLI that printed no usage is the shape every
        # check written before the measurement existed was written against.
        if self.usage is not None:
            printed["usage"] = self.usage
        return json.dumps(printed)


@dataclass
class ScriptedFast:
    """A fast model that answers to order and remembers what it was asked.

    `prompt_tokens` is what the provider is scripted to have counted the prompt
    at. It defaults to nothing, which is the shape of a provider that reported
    no usage -- the case every check written before the measurement existed was
    written against.

    Replies default to a well-formed grill-master document, which is what the
    map channel takes and the only shape it takes. A thread channel reads the
    same bytes as the `text` inside them, so one default serves both.

    `replies` is the script for a seat that has to answer more than once -- the
    retry a refused document buys, and the second turn a press asks for. The
    last one stands once the script runs out, so a seat that always answers the
    same way states it once.
    """

    reply: str | None = None
    replies: Sequence[str] = ()
    prompt_tokens: int | None = None
    calls: list[dict[str, str]] = field(default_factory=list)

    def __call__(
        self, *, model: str, system: str, prompt: str, shaped: bool = False
    ) -> tuple[str, int | None]:
        self.calls.append(
            {"model": model, "system": system, "prompt": prompt, "shaped": str(shaped)}
        )
        return self._said, self.prompt_tokens

    @property
    def _said(self) -> str:
        if self.replies:
            return self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return document() if self.reply is None else self.reply


def driven(log: SessionLog, driver: Any, expert: Any = None) -> TestClient:
    """A client over one log with a tier attached, and optionally an expert one."""
    return TestClient(create_app(log, driver, expert=expert))


def run_turns(lane: Lane, *events: EventSubmission) -> list[dict[str, Any]]:
    """Accept a batch and wait out every turn it scheduled."""
    receipts, turns = lane.accept(list(events), lane.log.epoch)
    for turn in turns:
        turn.join(TIMEOUT)
        # A join that timed out returns normally; a hung turn must fail here,
        # not leak into later tests as a background thread over shared state.
        assert not turn.is_alive(), "a scheduled turn outlived its timeout"
    assert all(receipt.status == "accepted" for receipt in receipts)
    return [receipt.model_dump() for receipt in receipts]


class InterleavingLog(SessionLog):
    """A log that lets one waiting writer in the instant an agent's reply lands.

    The hook fires after an agent's own append has returned, which is exactly
    the moment between the reply and whatever the driver writes next about it --
    the transfer a policy escalation buys, and the warning a measured turn
    raises. A second thread let in there is the race the append lock has to
    close: it finds the reply on the record and has to find the entry that
    belongs with it too, or the two are filed either side of somebody else's
    write.

    One shot, and only for an agent's append: the human's own turn goes through
    this same door on its way in, and a hook that fired there would be testing
    the window before the reply rather than the one after it.
    """

    hook: Callable[[], None] | None = None

    def submit(self, batch: Sequence[EventSubmission], epoch: str) -> list[Receipt]:
        receipts = super().submit(batch, epoch)
        if self.hook is not None and any(event.actor in AGENT_ACTORS for event in batch):
            armed, self.hook = self.hook, None
            armed()
        return receipts


def replies(log: SessionLog) -> list[dict[str, Any]]:
    """Every agent reply, read back out of the log file on disk."""
    lines = (log.directory / LOG_FILE).read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return [
        entry["payload"]
        for entry in entries
        if entry["actor"] in {"grill-master", "thread-agent"} and TIER_KEY in entry["payload"]
    ]


# What every reply carries about its own context size. A check that pins an
# attribution in full is about who took the turn; the measurement varies with
# the prompt's length, so leaving it in would turn each of those into a check on
# the wording of a fixture.
SIZE_KEYS = (CONTEXT_BYTES_KEY, PROMPT_TOKENS_KEY, CONTEXT_LIMIT_KEY)

# The two keys every grill-master turn carries whether or not it ruled on
# anything. A check that pins an attribution in full is about who took the turn;
# the rulings are their own subject and have their own checks.
DOCUMENT_KEYS = (RULINGS_KEY, STOP_KEY)


def attributions(log: SessionLog) -> list[dict[str, Any]]:
    """Every agent reply, with the size measurement and the ruling keys off."""
    return [
        {key: value for key, value in reply.items() if key not in SIZE_KEYS + DOCUMENT_KEYS}
        for reply in replies(log)
    ]


def dispatch_context(
    channel: str = "map", conclusion: ThreadConclusion | None = None
) -> DispatchContext:
    """A dispatch context with an empty board, for the cases that are about what
    surrounds the board rather than what is in it."""
    return DispatchContext(
        agent=agent_for(channel),
        channel=channel,
        epoch="e",
        seq=0,
        image2=ThreadProjection(epoch="e", seq=0),
        conclusion=conclusion,
    )


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


def pending_queue(client: TestClient) -> list[dict[str, Any]]:
    """The queue as the page reads it, off the state read rather than a fold of
    the test's own -- what the human is looking at is what the server says."""
    response = client.get("/state")
    assert response.status_code == 200
    queue: list[dict[str, Any]] = response.json()["image1"]["pending"]
    return queue


def proposed(client: TestClient, target: str | None = None) -> list[str]:
    """The ids of the map mutations waiting on the human, newest last.

    A notice is not one of them, so the filter is on the kind rather than on
    membership of the queue: both live there and only one is applicable.
    """
    return [
        item["id"]
        for item in pending_queue(client)
        if item["kind"] in PROPOSABLE_KINDS and (target is None or item["target"] == target)
    ]


def queue_gesture(
    client: TestClient,
    epoch: str,
    kind: str,
    *pending: str,
    key: str | None = None,
    actor: str = "human",
    channel: str = "map",
) -> dict[str, Any]:
    """The human acting on the queue: apply what the agent proposed, or end it."""
    return post(
        client,
        epoch,
        event(
            kind,
            actor=actor,
            channel=channel,
            key=key or f"{kind}-{uuid4().hex}",
            pending=list(pending),
        ),
    )[0]


def apply_all(client: TestClient, epoch: str, target: str | None = None) -> dict[str, Any]:
    """Apply every proposal waiting, or every one against a given decision.

    The gesture a test makes when its subject is what the board does afterwards
    rather than the applying itself: without it, a test that used to write the
    board directly as an agent would be pinning a divergence instead of a fix.
    """
    return queue_gesture(client, epoch, APPLY_KIND, *proposed(client, target))


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
