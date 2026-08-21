"""The contract between the shipped page and the backend that serves it.

Four claims live here, and every one of them is measured against the page's own
source rather than against a list written here.

**What the page says.** The page declares the kinds it emits, the channel class
each goes out on and the payload keys each may carry, and it builds every event
through one checked constructor -- so the declaration is what the page does. The
checks below read that declaration out of the shipped bytes, cross it against
the emission sites, and then put each kind on the wire. A kind the backend has
dropped from its own accepted set turns exactly that case red.

**What a stand-in may say.** Every scripted stand-in for the page in this file
builds its messages through `page_message`, which is the page's declaration
applied in Python. A shape the page never emits cannot be built, so a check
cannot accidentally prove the backend accepts something no page will ever send
-- which is the way a page contract passes and the real page is still refused.

**What a refusal looks like.** A rejected human action must reach the human as
a banner naming the reason and saying the message was not recorded. The typed
reason is measured here; that it renders is measured in a browser, because
inspecting the code that constructs a banner is not evidence that anyone saw
one.

**What the page may read.** The board is the state read and the update read,
and nothing else. Read paths are inventoried out of the source: a page that
grew a second way to learn what the board says is a page that can disagree with
the log.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from conftest import event, post, seed_node
from fastapi.testclient import TestClient

import grillui
from grillui.channels import (
    PROTOCOL_SEVERITY,
    PROTOCOL_STATES,
    PROTOCOL_TABLE,
    TRANSPORT_SEVERITY,
    TRANSPORT_STATES,
    TRANSPORT_TABLE,
)
from grillui.log import LOG_FILE
from grillui.schemas import (
    AGENT_ACTORS,
    KNOWN_KINDS,
    MAP_CHANNEL,
    MAP_MUTATION_KINDS,
    NOTICE_KINDS,
    PROPOSABLE_KINDS,
    REJECTION_REASONS,
    STATUS_PHASES,
)

PAGE_PATH = Path(grillui.__file__).parent / "page" / "index.html"

# The routes the page is allowed to touch, and what each one is for. The board
# is the first two; the third is how anything reaches the log; the fourth is a
# control -- whether a reassessment is in flight -- which is a property of the
# process and never of the board. A fifth entry here would be a second answer
# to what the board says.
BOARD_READS = {"/state", "/updates"}
CONTROL_PATHS = {"/doctor"}
WRITE_PATHS = {"/events", "/doctor"}

# A thread channel: anything that is not the map. The page mints these itself,
# since a channel is a name rather than a claim.
THREAD = "t-1"


def page_source() -> str:
    return PAGE_PATH.read_text(encoding="utf-8")


def _fenced(marker: str) -> str:
    """The text between one pair of the page's own fence comments."""
    start, end = f"//---{marker}-START---", f"//---{marker}-END---"
    body = page_source().split(start, 1)[1].split(end, 1)[0]
    assert body.strip(), f"the page's {marker} block is empty"
    return body


def emissions() -> dict[str, dict[str, Any]]:
    """The page's own declaration of what it emits.

    Read out of the shipped bytes, not restated here: this is the page saying
    which kinds it has, on which channel class, carrying which payload keys.
    """
    body = _fenced("PAGE-EMISSIONS").strip()
    table = body.split("=", 1)[1].strip().rstrip(";")
    parsed: dict[str, dict[str, Any]] = json.loads(table)
    return parsed


def emitted_kinds() -> set[str]:
    """The kinds at the page's emission sites.

    Every event the page builds goes through one constructor whose first
    argument is a literal kind, so the call sites are what it actually emits --
    as distinct from what its table says it emits. The two are crossed below.
    """
    return set(re.findall(r'\bev\("([a-z-]+)"', page_source()))


def page_vocabulary() -> dict[str, list[str]]:
    """The backend kind sets the page carries a copy of, read from its source."""
    return {
        name: json.loads(value)
        for name, value in re.findall(r"var (\w+) = (\[[^\]]*\]);", _fenced("BACKEND-VOCABULARY"))
    }


def page_channel_state() -> dict[str, Any]:
    """The page's copy of the channel-state model, read from its source.

    Arrays and tables both: the vocabularies, the severity orders and the two
    transition tables are one contract, and a page holding half of it is a page
    that steps somewhere the backend's copy does not go.
    """
    return {
        name: json.loads(value)
        for name, value in re.findall(
            r"var (\w+) = (\[[^\]]*\]|\{.*?\n\});", _fenced("CHANNEL-STATE"), re.DOTALL
        )
    }


def function_body(name: str) -> str:
    """One function out of the page's source, up to the next one."""
    source = page_source()
    assert f"function {name}(" in source, f"the page has no {name}"
    return source.split(f"function {name}(", 1)[1].split("\nfunction ", 1)[0]


def paths(verb: str) -> set[str]:
    """Every backend path the page names, by the helper that reaches it."""
    return set(re.findall(rf'\bsrv{verb}\("([^"]+)"', page_source()))


def page_message(kind: str, channel: str, /, **payload: Any) -> dict[str, Any]:
    """One message a stand-in may post, judged by the page's own declaration.

    A stand-in that could post a shape the page never emits proves nothing: the
    backend would accept a contract no page holds it to. So the kind, the
    channel class and every payload key are checked against the table the page
    ships, and anything outside it raises here rather than reaching the wire.
    """
    rule = emissions().get(kind, {"channel": "", "payload": []})
    assert rule["channel"], f"the page never emits {kind!r}"
    on_map = channel == MAP_CHANNEL
    assert on_map == (rule["channel"] == "map"), (
        f"the page never emits {kind!r} on channel {channel!r}"
    )
    assert not set(payload) - set(rule["payload"]), (
        f"the page's {kind!r} carries no {sorted(set(payload) - set(rule['payload']))}"
    )
    return event(kind, actor="human", channel=channel, key=f"page-{uuid4().hex}", **payload)


def turns(*texts: str) -> list[dict[str, str]]:
    """The page's own turn shape: who/text pairs in a `turns[]` array."""
    return [{"who": "human", "text": text} for text in texts]


def thread_of(client: TestClient, thread_id: str) -> dict[str, Any]:
    board: dict[str, Any] = client.get("/state").json()["image1"]
    found = [one for one in board["threads"] if one["id"] == thread_id]
    assert found, f"no thread {thread_id!r} in the board"
    return found[0]


def log_lines(session_dir: Path) -> list[dict[str, Any]]:
    path = session_dir / LOG_FILE
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# One well-formed submission per kind the page emits, in the page's own shapes.
# The board content each needs is set up by the test; what is measured here is
# only that the backend has a word for the kind at all.
SHAPES: dict[str, tuple[str, dict[str, Any]]] = {
    "answer": (MAP_CHANNEL, {"target": "n1", "answer": {"option": "a", "text": None}}),
    "thread-created": (
        THREAD,
        {
            "turns": turns("Why this one?"),
            "decision": "n1",
            "kind": "user",
            "title": "T",
            "requires_action": False,
        },
    ),
    "thread-turn": (THREAD, {"turns": turns("Say more.")}),
    "thread-fold": (THREAD, {}),
    "thread-park": (THREAD, {}),
    "apply": (MAP_CHANNEL, {"pending": ["nothing-waiting"]}),
    "dismiss": (MAP_CHANNEL, {"pending": ["nothing-waiting"]}),
    "session-end": (MAP_CHANNEL, {}),
}


# ---------------------------------------------------------------- GUI-A13


def test_the_page_declares_exactly_the_kinds_its_emission_sites_use() -> None:
    """The declaration cannot drift from the code either way.

    Without this, the table is a comment: it could name a kind no call site
    uses -- so the wire check below proves the backend accepts something the
    page never sends -- or a call site could use a kind the table omits, which
    the constructor would refuse at the one moment the human needed it.
    """
    assert emitted_kinds() == set(emissions())


def test_every_event_the_page_sends_is_built_by_the_checked_constructor() -> None:
    """One constructor, so the declaration is enforced rather than described.

    The idempotency key is what makes a submission a submission, so exactly one
    place in the page may mint one. A second would be an emission the table
    never saw.

    Minting is measured as the assignment and as the page-instance prefix that
    goes into it, not as every mention of the word: the page reads keys off
    events it has already built -- to tell an event still in flight from one the
    log has taken, and to name a queued update the way the backend names it --
    and a read is not a mint. Counting mentions would make those reads look like
    second constructors while leaving a real second constructor that spelled its
    field differently entirely invisible.
    """
    source = page_source()
    assert source.count("idempotency_key:") == 1, "a second place builds an event's key"
    assert source.count("PAGE_ID") == 2, "the page-instance prefix is used outside the constructor"
    builder = source.split("function ev(", 1)[1].split("\nfunction ", 1)[0]
    assert "idempotency_key:" in builder
    assert "PAGE_ID" in builder


@pytest.mark.parametrize("kind", sorted(emitted_kinds()))
def test_every_kind_the_page_emits_is_known_to_the_backend(
    kind: str, client: TestClient, log: Any
) -> None:
    """Each kind, on the wire, in the page's own shape.

    The assertion is narrow on purpose: a submission may well be refused for
    what it says -- an apply naming nothing waiting is refused, and should be
    -- but it must never be refused for *being* that kind. That is the failure
    a page and a backend built apart produce, and it is silent until a human
    clicks the control that no longer exists.
    """
    seed_node(client, log.epoch)
    channel, payload = SHAPES[kind]
    receipt = post(client, log.epoch, page_message(kind, channel, **payload))[0]
    assert receipt["status"] != "rejected" or receipt["reason"] != "unknown event kind", (
        f"the backend has no word for {kind!r}, which the page emits: {receipt}"
    )
    assert kind in KNOWN_KINDS


def test_the_pages_queue_split_is_the_backends_own_sets() -> None:
    """The page tells a waiting change from a message it was already given.

    That split is the queue's, not a taxonomy of the page's own -- but the page
    still carries the two kind lists to read it with. A stale copy would file a
    waiting change as a message, and its decision would be answered around a
    change the human never saw.
    """
    vocabulary = page_vocabulary()
    assert set(vocabulary["PROPOSABLE_KINDS"]) == PROPOSABLE_KINDS
    assert set(vocabulary["NOTICE_KINDS"]) == NOTICE_KINDS
    assert set(vocabulary["MAP_MUTATION_KINDS"]) == MAP_MUTATION_KINDS


def test_nothing_is_announced_as_landed_before_the_log_says_it_landed() -> None:
    """A notification is written where arriving entries are read, and nowhere else.

    The failure this stops was live in a browser: applying a change announced
    it at the click, so a change the backend then refused for conflicting with
    the board still showed as one that had landed, and a change the human
    dismissed showed the same. A gesture is not an outcome, and the only thing
    that knows the difference is the log.
    """
    source = page_source()
    reader = source.split("function observe(", 1)[1].split("\nfunction ", 1)[0]
    assert source.count("NOTES.push") == reader.count("NOTES.push")
    assert (
        "NOTES.push" not in source.split("function applyPending(", 1)[1].split("\nfunction ", 1)[0]
    )


def test_the_page_never_decides_which_changes_waited() -> None:
    """The queue is asked, never re-derived.

    A page holding its own copy of "would this overwrite something the human
    decided" is a second classifier, and two classifiers agree until the moment
    they do not -- at which point the human is looking at a board the log
    denies. The page reads `pending` and the board's own lock instead.
    """
    source = page_source()
    assert "BOARD.pending" in source
    assert "d.locked" in source
    assert "autoApplies" not in source


# ---------------------------------------------------------------- GUI-A14


@pytest.mark.parametrize(
    ("kind", "channel", "payload"),
    [
        pytest.param("fold", MAP_CHANNEL, {"updates": []}, id="a-kind-the-page-never-emits"),
        pytest.param(
            "thread-turn", THREAD, {"text": "hi"}, id="a-payload-shape-the-page-never-uses"
        ),
        pytest.param("answer", THREAD, {"target": "n1"}, id="a-channel-the-page-never-uses"),
    ],
)
def test_a_stand_in_cannot_post_a_shape_the_page_never_emits(
    kind: str, channel: str, payload: dict[str, Any]
) -> None:
    """The stand-in rule, enforced on the stand-in.

    Each of these three would be accepted by the backend. That is exactly why
    the check has to refuse them: a page contract proved with a bare-text
    thread turn passes while the real page, which sends `turns[]`, is rejected.
    """
    with pytest.raises(AssertionError):
        page_message(kind, channel, **payload)


def test_a_thread_created_and_a_thread_turn_in_the_pages_turns_form_both_project(
    client: TestClient, log: Any
) -> None:
    node = seed_node(client, log.epoch)
    receipts = post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Does the gate notice a test that asserts nothing?"),
            decision=node,
            kind="user",
            title="Assertion-free tests",
            requires_action=False,
        ),
        page_message("thread-turn", THREAD, turns=turns("Take the second one.")),
    )
    assert [one["status"] for one in receipts] == ["accepted", "accepted"]
    said = [turn["text"] for turn in thread_of(client, THREAD)["turns"]]
    assert said == ["Does the gate notice a test that asserts nothing?", "Take the second one."]


def test_a_thread_createds_kind_title_and_requires_action_all_project(
    client: TestClient, log: Any
) -> None:
    """The metadata the page attaches to a thread reaches the board.

    All three drive what the human sees: the kind decides which controls the
    panel offers, the title is how the thread is found again, and the
    action-required flag is what holds the decision shut until the thread ends.
    A backend that took the turns and dropped these would render as a thread
    that quietly stopped blocking anything.
    """
    node = seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Where does merge authority come from?"),
            decision=node,
            kind="mandate",
            title="Merge authority",
            requires_action=True,
        ),
    )
    projected = thread_of(client, THREAD)
    assert projected["kind"] == "mandate"
    assert projected["title"] == "Merge authority"
    assert projected["requires_action"] is True
    assert projected["decision"] == node


def test_a_backend_bare_text_reply_projects_into_the_same_turn_list(
    client: TestClient, log: Any
) -> None:
    """One reader for both shapes.

    The page speaks in `turns[]` and an agent may answer with bare text. If the
    two projected into different places the thread would read as a monologue,
    and a backend written against only one of them passes a scripted check and
    rejects the real page.
    """
    node = seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Why is this on the board?"),
            decision=node,
            kind="user",
            title="Why",
            requires_action=False,
        ),
    )
    post(
        client,
        log.epoch,
        event(
            "thread-turn",
            actor="thread-agent",
            channel=THREAD,
            key="reply",
            text="Because nothing downstream reads without it.",
        ),
    )
    said = [(turn["who"], turn["text"]) for turn in thread_of(client, THREAD)["turns"]]
    assert said == [
        ("human", "Why is this on the board?"),
        ("thread-agent", "Because nothing downstream reads without it."),
    ]


# ---------------------------------------------------------------- GUI-A9


def test_a_page_gesture_the_backend_refuses_is_answered_with_a_typed_reason(
    client: TestClient, log: Any, session_dir: Path
) -> None:
    """Every refusal the page can provoke names one of the closed reasons.

    The banner is only as good as the string behind it: a rejection carrying a
    reason the page cannot name renders as "the backend refused that" and
    nothing else, which is the silent no-op wearing a receipt.
    """
    node = seed_node(client, log.epoch)
    before = len(log_lines(session_dir))
    refusals = post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target=node, answer={"option": None, "text": None}),
        page_message(
            "answer", MAP_CHANNEL, target="no-such-node", answer={"option": "a", "text": None}
        ),
        page_message("apply", MAP_CHANNEL, pending=["nothing-waiting"]),
        page_message("dismiss", MAP_CHANNEL, pending=["nothing-waiting"]),
    )
    named = {one["reason"] for one in refusals if one["status"] == "rejected"}
    assert named <= REJECTION_REASONS
    assert "answer without option or text" in named
    assert "unknown node id" in named
    assert "unknown pending update" in named
    assert len(log_lines(session_dir)) == before, "a refused gesture was appended anyway"


def test_applying_a_change_the_human_moved_under_is_refused_by_name(
    client: TestClient, log: Any
) -> None:
    """The conflict case, which is the one the banner exists for.

    A queued change whose target the human answered while it waited is refused
    whole, with a reason of its own. Left unsaid, the human clicks apply, sees
    nothing move, and has no way to tell that from a change that landed.
    """
    node = seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target=node, answer={"option": "a", "text": None}),
    )
    post(client, log.epoch, event("unsettle", key="propose", target=node))
    waiting = [one["id"] for one in client.get("/state").json()["image1"]["pending"]]
    assert waiting, "the agent's unsettle should be waiting for the human"
    post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target=node, answer={"option": "b", "text": None}),
    )
    refusal = post(client, log.epoch, page_message("apply", MAP_CHANNEL, pending=waiting))[0]
    assert refusal["status"] == "rejected"
    assert refusal["reason"] == "pending update conflicts with the board"
    assert client.get("/state").json()["image1"]["decisions"][0]["status"] == "settled"


def test_the_refusal_banner_says_what_a_refusal_means() -> None:
    """The wording is the criterion, not decoration.

    A banner that only names a reason leaves the human to guess whether their
    message half-landed or is queued somewhere. It has to say both things: it
    was not recorded, and nothing is going to answer it. Whether it renders is
    a browser's answer, not this file's.
    """
    banner = page_source().split('banners += \'<div class="banner refusal">', 1)[1].split("}", 1)[0]
    assert "esc(rj.reason)" in banner
    assert "not recorded" in banner
    assert "no agent will answer it" in banner
    assert 'data-act="dismiss-rejection"' in banner
    assert 'case "dismiss-rejection": WIRE.lastRejection = null;' in page_source()


# ---------------------------------------------------------------- GUI-A20


def test_the_page_learns_the_board_from_nowhere_but_the_state_and_update_reads() -> None:
    """The read-model inventory, taken off the source.

    Every other read the backend offers -- image 1, image 2, the cheap status
    check -- is a second place the board could come from, and a page holding
    two is a page that can render one while acting on the other.
    """
    assert paths("Get") == BOARD_READS | CONTROL_PATHS


def test_the_page_writes_only_through_the_event_route_and_the_doctor_control() -> None:
    assert paths("Post") == WRITE_PATHS


def test_re_reading_state_asserts_nothing_of_the_pages_own() -> None:
    """Recovery is a read. It has to be.

    A page that republished its own idea of the board on reconnect is
    byte-indistinguishable from a genuine reset, and everything settled since
    is lost with no way to tell that it happened.
    """
    hydrate = page_source().split("function hydrate()", 1)[1].split("\nfunction ", 1)[0]
    assert "srvGet" in hydrate
    assert "srvPost" not in hydrate
    assert "ev(" not in hydrate


def test_a_stale_epoch_is_turned_away_on_the_update_read_and_the_state_read_still_answers(
    client: TestClient, log: Any
) -> None:
    """What a page whose backend restarted under it actually meets.

    The refusal has to be distinguishable from an outage, and the recovery has
    to need no epoch -- otherwise the only way back is the epoch the page has
    just been told is wrong.
    """
    seed_node(client, log.epoch)
    stale = client.get("/updates", params={"epoch": "an-earlier-tenure", "cursor": 0})
    assert stale.status_code == 409
    recovered = client.get("/state")
    assert recovered.status_code == 200
    assert recovered.json()["epoch"] == log.epoch


def test_the_state_read_alone_carries_the_whole_board(client: TestClient, log: Any) -> None:
    """No delta is needed to know what the board says.

    A page that had to replay the log to know the board would be folding it --
    and a page that folds is a page that can fold differently.
    """
    node = seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Opening this."),
            decision=node,
            kind="user",
            title="Opening",
            requires_action=False,
        ),
    )
    post(client, log.epoch, event("informational", key="note", target=node, text="Noted."))
    board = client.get("/state").json()["image1"]
    assert [one["id"] for one in board["decisions"]] == [node]
    assert board["frontier"] == [node]
    assert [one["id"] for one in board["threads"]] == [THREAD]
    assert [one["kind"] for one in board["pending"]] == ["informational"]


def test_the_page_reads_the_cursor_the_update_read_hands_back(client: TestClient, log: Any) -> None:
    """The cursor is the backend's, so a page can never re-process a backlog."""
    seed_node(client, log.epoch)
    first = client.get("/updates", params={"epoch": log.epoch, "cursor": 0}).json()
    assert [one["seq"] for one in first["entries"]] == [first["seq"]]
    again = client.get("/updates", params={"epoch": log.epoch, "cursor": first["seq"]}).json()
    assert again["entries"] == []
    assert again["seq"] == first["seq"]


# ---------------------------------------------------------------- GUI-D27 / GUI-A41


def test_the_pages_channel_state_model_is_the_backends_own() -> None:
    """Both layers, both orders, both tables -- the same contract on both sides.

    The page cannot ask the backend what its own wire is doing, so it steps its
    own copy. That is exactly why the copy has to be pinned: a page stepping a
    table the backend no longer has would show a state nothing else in the system
    has a word for, and it would show it confidently.
    """
    page = page_channel_state()
    assert page["TRANSPORT_STATES"] == list(TRANSPORT_STATES)
    assert page["PROTOCOL_STATES"] == list(PROTOCOL_STATES)
    assert page["TRANSPORT_SEVERITY"] == list(TRANSPORT_SEVERITY)
    assert page["PROTOCOL_SEVERITY"] == list(PROTOCOL_SEVERITY)
    assert page["TRANSPORT_TABLE"] == TRANSPORT_TABLE
    assert page["PROTOCOL_TABLE"] == PROTOCOL_TABLE


def test_the_pages_status_phases_and_agent_actors_are_the_backends_own() -> None:
    """What the page reads the lane with.

    Which channel is waiting on an agent is read off the lane's own phases and
    off who authored an arriving entry. Both are backend vocabularies, and a
    stale copy of either leaves a channel that is waiting looking idle -- which
    is the one thing the indicator exists to prevent.
    """
    vocabulary = page_vocabulary()
    assert set(vocabulary["STATUS_PHASES"]) == STATUS_PHASES
    assert set(vocabulary["AGENT_ACTORS"]) == AGENT_ACTORS


def test_every_channel_move_the_page_makes_goes_through_the_one_checked_step() -> None:
    """One reader of each table, so a pair neither names is refused rather than
    guessed.

    A second place that indexed a table directly would be a move nothing checked,
    and it would fail the way an unchecked move always does: by leaving a channel
    in a state that renders fine and means nothing.
    """
    source = page_source()
    stepper = function_body("step")
    assert "throw new Error" in stepper
    for table in ("TRANSPORT_TABLE", "PROTOCOL_TABLE"):
        # Once in the declaration, once as an argument to the one step.
        assert source.count(table) == 2, f"{table} is read somewhere other than step()"


def test_a_transport_move_touches_no_channels_protocol_state() -> None:
    """The layer split, enforced where the wire is moved.

    The turns an agent owed before a drop are still owed after it. A transport
    handler that also cleared the channels would tell the human their message had
    been dealt with because their network blinked.
    """
    assert "CHANNELS.protocol" not in function_body("wire")


def test_the_indicator_shows_the_worst_channel_and_expands_into_the_diagnostic() -> None:
    """One light over every channel, and the expansion behind it.

    The rendering is a browser's answer, not this file's. What is measured here
    is that the light is derived from the worst channel rather than from any one
    of them, and that the expansion is derived from all of them -- an indicator
    reading only the map would show an idle board while a thread's write sat
    unacknowledged.
    """
    assert "worstChannel()" in function_body("renderIndicator")
    diagnostic = function_body("renderDiagnostic")
    assert "channelViews()" in diagnostic
    assert "view.connection" in diagnostic
    assert "view.protocol" in diagnostic
    assert 'case "diag": UI.diag = !UI.diag;' in page_source()


def test_the_page_reads_which_channel_is_owed_a_turn_off_the_lanes_own_entries() -> None:
    """The routing rule is asked, never re-derived.

    Which agent answers a gesture is the backend's decision -- a fold is made in
    a thread and answered by the grill-master on the map -- and the lane says so
    by addressing its `composing` to the channel the turn runs on. A page that
    worked it out from the kind it had just sent would be a second classifier,
    and the two would agree until a fold.
    """
    reader = function_body("track")
    assert 'onChannel(entry.channel, "owed")' in reader
    assert "PHASE_COMPOSING" in reader
    sender = function_body("send")
    assert "owed" not in sender, "the page decided for itself who owes a turn"


# ---------------------------------------------------------------- GUI-A21


def test_the_waiting_clock_starts_when_a_tier_takes_the_turn_and_not_when_the_gesture_lands() -> (
    None
):
    """`accepted` is not the start of a wait, and treating it as one leaks.

    The lane addresses `accepted` to the channel the human spoke on and
    `composing` to the channel the turn runs on, and for a fold those are two
    different channels. A clock started on `accepted` therefore starts on a
    thread that owes nothing, and nothing ever closes it -- the thread's
    `replied` never comes, because the reply is the map's. The channel sits
    there counting up against a turn it is not taking.
    """
    reader = function_body("track")
    assert "PHASE_COMPOSING" in reader
    assert "WIRE.status[entry.channel] = {" in reader
    assert "delete WIRE.status[entry.channel]" in reader
    # The one place a wait is started, so there is no second one to start it on
    # the acknowledgement.
    assert page_source().count("WIRE.status[entry.channel] = {") == 1


def test_a_wait_is_timed_from_the_lane_entry_rather_than_from_when_the_page_read_it() -> None:
    """A reload mid-turn comes back with the clock the human had.

    Timing from the read instant would restart every wait at zero on reload,
    which is the moment the elapsed time matters most: a human who has been
    waiting four minutes and reloads is told the agent has just started.
    """
    reader = function_body("track")
    assert "Date.parse(entry.timestamp)" in reader
    assert "Date.now()" not in reader, "the wait is timed from this page's clock"
    # Replayed on the reload path too, or the clock exists only for a page that
    # happened to be open when the turn began.
    assert "u.entries.forEach(track)" in function_body("hydrate")


def test_the_waiting_indicator_names_every_channel_an_agent_owes_a_turn_on() -> None:
    """One waiting channel is not the whole answer.

    Two threads and the map take turns concurrently by design. An indicator
    showing the last turn announced hides the others, and the one the human is
    actually waiting on is as likely as not among the hidden ones.
    """
    reader = function_body("owed")
    assert "Object.keys(WIRE.status)" in reader
    assert "sort" in reader, "the longest wait is not shown first"
    lane = function_body("laneText")
    assert "delivered" in lane, "the indicator does not say the message got there"
    assert 's"' in lane or "s'" in lane, "the indicator carries no elapsed count"
    assert "more" in lane, "a second waiting channel is not surfaced"


# ---------------------------------------------------------------- GUI-A23


def test_the_indicator_carries_three_signals_each_derived_from_its_own_source() -> None:
    """Reachable, agent, outbox -- three, and separately derived.

    Each fails on its own and each means something different to the human in
    front of it. Deriving one from another is how a backend that is up with
    nothing attached ends up rendering as a backend that is up and working: the
    only difference between them is the signal that was folded away.
    """
    indicator = function_body("renderIndicator")
    for signal in ("reachable", "agent", "outbox"):
        assert f'data-signal="{signal}"' in indicator, f"no {signal} signal on the indicator"
    assert "connected()" in indicator, "the reachable signal is not the transport's own answer"
    assert "agentSignal()" in indicator
    assert "outboxDepth()" in indicator


def test_a_backend_with_no_agent_attached_reads_differently_from_one_whose_agent_is_idle() -> None:
    """The two states this indicator exists to separate.

    Nobody is coming, against someone is on their way. A human told the wrong
    one either waits for a reply that no configured tier will ever produce, or
    abandons a session that was working.
    """
    reader = function_body("agentSignal")
    assert "agentSeen()" in reader
    states = set(re.findall(r'state: "([a-z]+)"', reader))
    assert states == {"owes", "absent", "idle"}, f"the agent signal has states {states}"
    # Attachment is read off the record rather than off a flag the page sets:
    # the lane's own entries and the actors who authored replies.
    seen = function_body("agentSeen")
    assert "STATUS_KIND" in seen
    assert "AGENT_ACTORS" in seen


def test_the_outbox_counts_what_the_page_sent_and_the_log_has_not_returned() -> None:
    """Depth, measured on both ends of an event's life.

    An outbox that only ever filled would climb forever and mean nothing; one
    emptied on the receipt would read as consumed while the board still did not
    show it. It fills where events go out and empties where the log brings them
    back, and a refusal -- an event that will never appear in the log -- leaves
    it too, or the depth counts work nothing is ever going to do.
    """
    assert "OUTBOX[e.idempotency_key] = true" in function_body("send")
    assert "delete OUTBOX[entry.idempotency_key]" in function_body("track")
    assert 'r.status !== "accepted"' in function_body("send")
    assert "Object.keys(OUTBOX).length" in function_body("outboxDepth")


def test_the_diagnostic_expansion_carries_each_channels_own_wait() -> None:
    """The amalgamated light shows the longest wait; the human is often asking
    about a different channel, and the expansion is where that is answered."""
    diagnostic = function_body("renderDiagnostic")
    assert "WIRE.status[view.channel]" in diagnostic
    assert "data-waited=" in diagnostic
    assert "outboxDepth()" in diagnostic


# ---------------------------------------------------------------- GUI-A22


def test_a_notification_is_stamped_with_the_clock_of_the_entry_it_reports() -> None:
    """When the agent did it, not when this page got round to reading it.

    A page arriving late reads a morning's log in one pass. Stamping those
    notifications with the read instant would date the whole session to the
    moment the browser opened, which is the one timestamp that is certainly
    wrong for every one of them.
    """
    assert "at: at" in function_body("noteFor")
    observer = function_body("observe")
    assert observer.count("entry.timestamp") == 2, "an observed update is stamped from elsewhere"
    assert "new Date()" not in page_source(), "something is stamped from this page's clock"


@pytest.mark.parametrize(
    ("surface", "expression"),
    [
        pytest.param("renderTurns", "stamp(turn.timestamp)", id="a-thread-turn"),
        pytest.param("renderNotifications", "stamp(n.at)", id="a-notification"),
        pytest.param("infoNote", "stampOf(n)", id="an-agent-message-on-its-decision"),
        pytest.param("renderBubbles", "stamp(b.at)", id="a-notification-bubble"),
    ],
)
def test_every_message_surface_renders_a_timestamp(surface: str, expression: str) -> None:
    """Thread turns and notifications alike, wherever they are met.

    `stamp` is `toLocaleString`, which is the operating system's zone by
    definition -- the browser's own, never a zone this page picked. That it
    renders as the OS zone is a browser's answer and is measured there; what is
    measured here is that each surface asks for one at all.
    """
    assert expression in function_body(surface)
    assert "toLocaleString()" in function_body("stamp")


def test_a_queue_entrys_clock_comes_from_the_log_rather_than_from_the_queue() -> None:
    """The queue carries the sequence a notice was authored at and no clock, so
    the two are read together. A page inventing one would be stamping a message
    with the time it noticed it."""
    reader = function_body("stampOf")
    assert "entryAt(item.authored_at)" in reader
    assert "stamp(e.timestamp)" in reader


# ---------------------------------------------------------------- GUI-A44


def test_a_thread_panel_pins_its_title_and_its_prompt_box() -> None:
    """Three parts, and only the middle one scrolls.

    The title with its controls and the prompt box with its actions are the two
    things a human needs at every point in a thread, and they are exactly the
    two that a single scrolling column takes away first -- at the length where a
    thread is hardest to follow and the reply hardest to compose.
    """
    pane = function_body("threadPane")
    for part in ("thead", "tbody", "tfoot"):
        assert f'class="{part}"' in pane, f"the pane has no {part}"
    source = page_source()
    assert ".threadpane .tbody { flex: 1 1 auto; min-height: 0; overflow-y: auto;" in source
    for pinned in (".thead", ".tfoot"):
        assert f".threadpane {pinned} {{ flex: none;" in source, f"{pinned} is not pinned"
    # The close and the pop-out ride in the head rather than on the slide, or
    # they scroll away with the first screen of turns.
    assert "threadBody(tid, false, chrome)" in function_body("renderThread")
    assert 'data-act="closepanel"' in function_body("renderThread")
    assert 'data-act="popout"' in function_body("renderThread")
    # The popped window is the same pane at the window's own height.
    assert "#t{height:100%}" in function_body("popOut")


# ---------------------------------------------------------------- GUI-A45


def test_a_decisions_options_are_labelled_by_position() -> None:
    """a, b, c -- the handle the free text and the threads refer to an option by.

    Position rather than the option's own id, because the id is the authoring
    agent's string and nothing makes it a letter. A label that was sometimes an
    id would be a label the human could not reliably say out loud.
    """
    assert '"abc".charAt(i)' in function_body("labelAt")
    button = function_body("optionButton")
    assert "labelAt(index)" in button
    controls = function_body("answerControls")
    assert controls.count("optionButton(") == 2, "the recommended option is labelled differently"
    assert "optionButton(d, d.options[0], 0," in controls
    assert "optionButton(d, o, i + 1," in controls


def test_an_option_and_a_note_are_one_answer_carrying_both(client: TestClient, log: Any) -> None:
    """Picking b and saying why is one gesture, and both halves survive.

    Before this the two were exclusive: the human picked an option and had
    nowhere to put the reason, so the reason went into a thread the answer does
    not carry, or nowhere. The board is what is measured -- an answer that
    carried both on the wire and folded to one of them would fail here.
    """
    node = seed_node(client, log.epoch)
    receipt = post(
        client,
        log.epoch,
        page_message(
            "answer", MAP_CHANNEL, target=node, answer={"option": "b", "text": "latency wins"}
        ),
    )[0]
    assert receipt["status"] == "accepted", receipt

    board = client.get("/state").json()["image1"]
    answered = next(one for one in board["decisions"] if one["id"] == node)
    assert answered["answer"] == {"option": "b", "text": "latency wins"}


def test_the_note_on_an_option_is_whatever_is_in_the_decisions_own_box() -> None:
    """One box, two jobs: a free-text answer on its own, the note on an option
    once one is picked. A second textarea would be an empty field on every
    decision that the human has to be told the purpose of."""
    source = page_source()
    assert 'note: (UI.drafts[id] || "").trim()' in source
    answer = function_body("answerOf")
    assert "text: payload.note || null" in answer
    assert "option: payload.option" in answer
    # Both are shown back, in that order: only the note would hide which option
    # was taken, only the option would drop the reason for taking it.
    assert 'chosen + " — " + d.answer.text' in function_body("answerTextOf")


# ---------------------------------------------------------------- GUI-A46


def test_a_dismissed_hover_overlay_returns_only_on_a_fresh_entry_of_its_zone() -> None:
    """Hiding on click was not enough on its own.

    `mouseover` fires again on the next movement inside the same element, so the
    card the human had just dismissed came straight back under their cursor
    without them ever leaving the thing they dismissed it on. The zone is held
    until the pointer has left it.

    Held as what the zone is, not as which element it currently is: almost every
    click re-renders, so an element held across one is detached by the time the
    pointer moves, matches nothing, and hands the overlay back on the first
    twitch -- the exact failure this is here to stop, reintroduced by the fix
    for it.
    """
    source = page_source()
    assert "hideHover(zoneOf(e.target))" in source, "a click does not mute the zone it hit"
    assert "MUTED = zoneKey(zone)" in source, "the mute is held as an element"
    assert "if (MUTED && zoneKey(zoneOf(e.target)) === MUTED) return;" in source
    assert "if (zoneKey(into) !== MUTED) MUTED = null;" in source
    # The key survives a re-render because it names the board, and it carries the
    # owning node because two badges may wear the same words on two decisions.
    key = function_body("zoneKey")
    assert 'el.closest(".mnode")' in key
    assert "el.dataset.why || el.dataset.otext || el.dataset.id" in key
    # One reader of what owns an overlay, so what a click mutes and what a hover
    # checks are the same zone rather than two selectors that mostly agree.
    zone = function_body("zoneOf")
    for owner in ("[data-why]", "[data-p]", ".mnode"):
        assert owner in zone
    # A click is the only thing that mutes. Leaving a zone hides its card too,
    # and must not mute on the way out -- an overlay muted by the pointer
    # drifting off it would never come back at all.
    assert source.count("hideHover(") == 2, "something other than a click mutes a zone"


# ---------------------------------------------------------------- GUI-A47


def test_an_informational_carries_a_discuss_control_wherever_it_is_read() -> None:
    """On its decision and in the notification list alike.

    An agent message read in the notification list is the same message; having
    to go and find it on its decision to answer it is the friction that makes a
    Discuss control on one surface and not the other read as a bug.
    """
    assert 'data-act="discussnotice"' in function_body("infoNote")
    assert 'data-act="discussnotice"' in function_body("renderNotifications")
    # An applied change is not a message to reply to -- it is a thing that
    # happened -- so it carries no Discuss and the inbox is where it is argued
    # with, before it lands.
    assert 'n.type === "applied-change" ? "" :' in function_body("renderNotifications")


def test_discussing_an_informational_opens_a_thread_seeded_from_it(
    client: TestClient, log: Any
) -> None:
    """The seed is the message, and the thread anchors where the message did.

    A thread seeded from anything else -- a generic opener, the decision's own
    body -- puts the agent in front of a question the human did not ask, and the
    reply answers something nobody raised.
    """
    node = seed_node(client, log.epoch)
    said = "The store choice quietly fixes the compaction one."
    post(client, log.epoch, event("informational", key="note-1", target=node, text=said))

    seeded = f"About what you said: “{said}”"
    receipt = post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            "t-notice-1",
            turns=[{"who": "human", "text": seeded}],
            decision=node,
            kind="notice",
            title="a title",
            requires_action=False,
        ),
    )[0]
    assert receipt["status"] == "accepted", receipt

    opened = thread_of(client, "t-notice-1")
    assert opened["decision"] == node
    assert opened["turns"][0]["text"] == seeded

    # And the page builds exactly that: the message's own words, on the
    # message's own decision.
    builder = function_body("discussNotice")
    assert 'ev("thread-created"' in builder
    assert 'text: "About what you said: “" + said + "”"' in builder
    assert "decision: target" in builder


def test_a_message_is_found_by_the_same_id_in_the_queue_and_in_the_notifications() -> None:
    """One lookup over both, because they are one message.

    The queue holds it while the board still carries it and the notification
    list holds it once the board has moved on. Two lookups would make Discuss
    work on one surface and silently do nothing on the other.
    """
    builder = function_body("discussNotice")
    assert "BOARD.pending.filter" in builder
    assert "NOTES.filter" in builder


# ---------------------------------------------------------------- GUI-A48


def test_a_queue_entrys_id_is_the_authoring_entrys_key(client: TestClient, log: Any) -> None:
    """The derivation §8.5 states, measured on the wire.

    This is the only stable name a queue entry has, and read-state is persisted
    against it. A minted id would be stable inside one fold and mean nothing to
    a second reader of the same log -- including the same page after a reload.
    """
    node = seed_node(client, log.epoch)
    # The queue holds what would overwrite something the human decided, so the
    # human decides first. An agent change on an unanswered node lands as it
    # arrives and never becomes a queue entry to name.
    post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target=node, answer={"option": "a", "text": None}),
    )
    post(
        client,
        log.epoch,
        event("revise", key="single-1", target=node, title="A revision", why="because"),
    )
    post(
        client,
        log.epoch,
        event(
            "fold",
            key="fold-1",
            updates=[
                {"kind": "revise", "target": node, "title": "First", "why": "one"},
                {"kind": "revise", "target": node, "title": "Second", "why": "two"},
            ],
        ),
    )
    ids = {one["id"] for one in client.get("/state").json()["image1"]["pending"]}
    # A single update wears the entry's key; a fold's sub-updates wear key#index,
    # indexed by position in `updates`.
    assert "single-1" in ids, ids
    assert "fold-1#0" in ids, ids
    assert "fold-1#1" in ids, ids


def test_the_page_derives_a_queue_id_the_way_the_backend_does() -> None:
    """Restated in the page, and it has to be: the page cannot ask.

    The index counts every object in `updates`, including one the page then
    drops for naming no kind. An index taken after the filter names a different
    update than the queue does, and the two disagree exactly on the malformed
    fold nobody is looking at.
    """
    reader = function_body("updatesIn")
    assert 'one.uid = key + "#" + i;' in reader
    assert "one.uid = key;" in reader
    assert 'typeof u !== "object"' in reader, "the index is taken after the kind filter"
    # And it is what a queue entry's own text is found by, rather than a
    # kind-and-target match: a fold carrying two revises of one decision has two
    # entries the queue tells apart and that match cannot.
    assert "u.uid === item.id" in function_body("sourceOf")


def test_mark_all_read_writes_nothing_to_the_backend() -> None:
    """Read-state is presentation state and does not cross the wire.

    It is not board state, no agent is dispatched the fact that a human looked
    at something, and the server-authority rule does not reach it. That it
    appends no event is asserted in a browser; that no code path could is
    asserted here.
    """
    for reader in ("markAllRead", "markRead", "saveRead", "loadRead"):
        body = function_body(reader)
        assert "send(" not in body, f"{reader} reaches the wire"
        assert "ev(" not in body, f"{reader} builds an event"
        assert "srvPost" not in body and "srvGet" not in body, f"{reader} touches the backend"


def test_read_state_survives_a_reload_and_the_notification_list_deliberately_does_not() -> None:
    """Two different things, and separating them is the whole design.

    The list starts empty on purpose: a page arriving mid-session must not
    announce a morning's work as news. Read-state cannot start empty, because
    the markers it clears are not the list's -- the ✉ on a decision comes off
    the queue in image 1, which comes back on every reload. Without persistence,
    marking everything read and reloading would restore every marker the human
    had just dealt with.
    """
    source = page_source()
    assert "window.localStorage" in function_body("saveRead")
    assert "window.localStorage" in function_body("loadRead")
    assert '"grillui:read:" + WIRE.epoch' in function_body("readKey")
    # Loaded once the epoch is known, which is the state read -- the same place
    # a reload learns which session it is coming back to.
    assert "loadRead();" in function_body("hydrate")
    # The list is still built only from what arrives after this page did: the
    # reload path reads the whole log as a lookup table and touches the
    # notifications not at all.
    assert "NOTES" not in function_body("hydrate"), "a reload rebuilds the list from the log"
    assert source.count("NOTES.push") == 2, "notifications are written outside the observer"


def test_every_unread_marker_is_asked_of_the_one_read_set() -> None:
    """One set over both surfaces, because they are one question.

    A count over the notification list alone would clear on a reload while the
    ✉ markers the queue carries stayed lit, and the human would be told there
    was nothing to read while looking at something to read.
    """
    ids = function_body("unreadIds")
    assert "unreadNotes()" in ids
    assert "unreadNotices()" in ids
    assert "isRead(n.id)" in function_body("unreadNotes")
    assert "isRead(n.id)" in function_body("unreadNotices")
    assert "unreadIds().length" in function_body("unreadCount")
    # And the marker surfaces read the unread set rather than the queue whole.
    assert "unreadNotices(id).length" in function_body("itemIcons")
    assert "unreadNotices(id).length" in function_body("renderMap")


# ---------------------------------------------------------------- GUI-A50


def test_the_shipped_page_has_no_dark_theme_styles() -> None:
    """One palette, and no second one hiding behind a media query.

    A dark variant nobody asked for is a second set of colours to keep true --
    and it appears only on the machines whose operating system is set that way,
    which is the set of machines the person shipping it is least likely to be
    on.
    """
    source = page_source().lower()
    for absent in ("prefers-color-scheme", "color-scheme", "@media (prefers", "dark"):
        assert absent not in source, f"the shipped page carries {absent!r}"


# ---------------------------------------------------------------- serving


def test_the_backend_serves_the_page_it_ships(client: TestClient) -> None:
    """One build. A page served from anywhere else can speak an older protocol
    to a backend that has moved on, and neither end can tell."""
    served = client.get("/")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/html")
    assert served.text == page_source()
