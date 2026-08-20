"""The context images, folded from the log and nothing else.

`fold` is a pure function of an epoch and a sequence of entries: no clock, no
randomness, no I/O. The same log therefore always yields the same images, and an
image rebuilt from disk matches one held in memory. Writing an image to a file is
a separate step downstream of this module -- the image files are derived caches,
never a recovery source.

The fold tolerates any entry the appender accepted. An entry whose payload it
cannot read contributes what it can and no more, because a projector that raises
on an accepted entry takes the session down with it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from grillui.schemas import (
    Answer,
    Decision,
    HistoryEntry,
    Image1,
    Image2,
    LogEntry,
    Option,
    SettledEntry,
    Thread,
    ThreadTurn,
)


def fold(epoch: str, entries: Sequence[LogEntry]) -> Image2:
    """Fold the log into image 2. Image 1 is this, minus history."""
    decisions: dict[str, Decision] = {}
    threads: dict[str, Thread] = {}
    history: dict[str, list[HistoryEntry]] = {}
    seq = 0

    for entry in entries:
        seq = entry.seq
        if entry.kind == "add-node":
            _add_node(decisions, entry)
        elif entry.kind == "thread-created":
            _create_thread(threads, entry)
        elif entry.kind == "thread-turn":
            _append_turns(threads, entry)
        elif entry.kind in {"answer", "settle"}:
            _settle(decisions, entry)
        _record_history(history, entry)

    settled = [
        SettledEntry(id=node.id, answer=_answer_text(node))
        for node in decisions.values()
        if node.status == "settled"
    ]
    settled_ids = {item.id for item in settled}
    frontier = [
        node.id
        for node in decisions.values()
        if node.status == "open" and all(p in settled_ids for p in node.prereqs)
    ]

    return Image2(
        epoch=epoch,
        seq=seq,
        decisions=list(decisions.values()),
        frontier=frontier,
        settled=settled,
        threads=list(threads.values()),
        # ponytail: the pending queue is empty until the update-kinds work lands
        # the accept/apply path that fills it.
        pending=[],
        history=history,
    )


def to_image1(image: Image2) -> Image1:
    """Image 2 without its history, which is the only field that separates them."""
    return Image1(**image.model_dump(exclude={"history"}))


def _add_node(decisions: dict[str, Decision], entry: LogEntry) -> None:
    node_id = entry.payload.get("target") or entry.payload.get("id")
    if not isinstance(node_id, str):
        return
    decisions[node_id] = Decision(
        id=node_id,
        short=_text(entry.payload, "short"),
        title=_text(entry.payload, "title"),
        body=_text(entry.payload, "body"),
        prereqs=_strings(entry.payload.get("prereqs")),
        options=_options(entry.payload.get("options")),
    )


def _settle(decisions: dict[str, Decision], entry: LogEntry) -> None:
    node_id = entry.payload.get("target")
    node = decisions.get(node_id) if isinstance(node_id, str) else None
    if node is None:
        return
    raw = entry.payload.get("answer")
    if not isinstance(raw, Mapping):
        return
    node.answer = Answer(option=_or_none(raw.get("option")), text=_or_none(raw.get("text")))
    node.status = "settled"


def _create_thread(threads: dict[str, Thread], entry: LogEntry) -> None:
    thread_id = _thread_id(entry)
    threads[thread_id] = Thread(
        id=thread_id,
        decision=_or_none(entry.payload.get("decision")),
        kind=_text(entry.payload, "kind"),
        title=_text(entry.payload, "title"),
        requires_action=entry.payload.get("requires_action") is True,
        turns=_turns(entry),
    )


def _append_turns(threads: dict[str, Thread], entry: LogEntry) -> None:
    thread_id = _thread_id(entry)
    thread = threads.get(thread_id)
    if thread is None:
        thread = Thread(id=thread_id)
        threads[thread_id] = thread
    thread.turns = [*thread.turns, *_turns(entry)]


def _turns(entry: LogEntry) -> list[ThreadTurn]:
    """One reader for both shapes the protocol carries: the page's `turns[]`
    array of who/text pairs, and a backend-authored bare-text reply."""
    raw = entry.payload.get("turns")
    if isinstance(raw, list):
        return [
            ThreadTurn(
                who=turn.get("who", entry.actor),
                text=str(turn.get("text", "")),
                timestamp=str(turn.get("timestamp", entry.timestamp)),
            )
            for turn in raw
            if isinstance(turn, Mapping) and turn.get("text")
        ]
    text = entry.payload.get("text")
    if isinstance(text, str) and text:
        return [ThreadTurn(who=entry.actor, text=text, timestamp=entry.timestamp)]
    return []


def _record_history(history: dict[str, list[HistoryEntry]], entry: LogEntry) -> None:
    node_id = entry.payload.get("target")
    if not isinstance(node_id, str):
        return
    history.setdefault(node_id, []).append(
        HistoryEntry(
            seq=entry.seq,
            timestamp=entry.timestamp,
            kind=entry.kind,
            actor=entry.actor,
            why=_text(entry.payload, "why"),
        )
    )


def _thread_id(entry: LogEntry) -> str:
    return entry.channel


def _answer_text(node: Decision) -> str:
    if node.answer is None:
        return ""
    return node.answer.text or node.answer.option or ""


def _options(raw: object) -> list[Option]:
    if not isinstance(raw, list):
        return []
    return [
        Option(
            id=str(item.get("id", "")),
            text=str(item.get("text", "")),
            pcr=_pcr(item.get("pcr")),
        )
        for item in raw
        if isinstance(item, Mapping)
    ]


def _pcr(raw: object) -> list[str] | None:
    values = _strings(raw)
    return values if len(values) == 3 else None


def _strings(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
