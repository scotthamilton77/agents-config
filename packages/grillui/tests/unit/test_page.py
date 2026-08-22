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
from conftest import apply_all, event, handoff_doc, post, seed_node
from fastapi.testclient import TestClient

from grillui.api import PAGE_DIR, assemble_page, page_html
from grillui.capture import capture
from grillui.channels import (
    PROTOCOL_SEVERITY,
    PROTOCOL_STATES,
    PROTOCOL_TABLE,
    TRANSPORT_SEVERITY,
    TRANSPORT_STATES,
    TRANSPORT_TABLE,
)
from grillui.claim import CLAIM_STATES
from grillui.escalation import in_expert_mode
from grillui.log import LOG_FILE
from grillui.schemas import (
    AGENT_ACTORS,
    ANSWERABLE_KINDS,
    FAST_TIER,
    FROM_THREAD_KEY,
    HEAVY_TIER,
    KNOWN_KINDS,
    LIFECYCLE_KINDS,
    MAP_CHANNEL,
    MAP_MUTATION_KINDS,
    NOTICE_KINDS,
    PROPOSABLE_KINDS,
    QUEUE_GESTURE_KINDS,
    RECOMMENDATION_KEY,
    REJECTION_REASONS,
    SESSION_END_KIND,
    SESSION_START_KIND,
    STATUS_PHASES,
    THREAD_GESTURE_KINDS,
    TIER_KEY,
    TRANSFER_FLAG,
    Handoff,
)

# The routes the page is allowed to touch, and what each one is for. The board
# is the first two; the third is how anything reaches the log; the last two are
# controls -- whether a reassessment is in flight, and which window this session
# belongs to -- and both are properties of the process rather than of the board.
# A further board read here would be a second answer to what the board says.
BOARD_READS = {"/state", "/updates"}
CONTROL_PATHS = {"/doctor"}
WRITE_PATHS = {"/events", "/doctor", "/claim"}

# A thread channel: anything that is not the map. The page mints these itself,
# since a channel is a name rather than a claim.
THREAD = "t-1"


def page_source() -> str:
    """The document the backend serves, assembled from the page's three sources.

    Every check here reads this rather than one of the sources: what the browser
    is handed is what the claims are about, and which file a line was authored in
    is not something the page's contract has an opinion on.
    """
    return page_html()


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


def page_constants() -> dict[str, str]:
    """The backend's payload keys as the page spells them, from its source.

    A second reader beside `page_vocabulary`, because these are single strings
    rather than sets: a key the page reads a tier off is one word, and a page
    holding a stale one fails silently in both directions -- nothing highlights
    and nothing escalates.
    """
    return {
        name: json.loads(value)
        for name, value in re.findall(r'var (\w+) = ("[^"]*");', _fenced("BACKEND-VOCABULARY"))
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
    "thread-close": (THREAD, {}),
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

    The page-instance id has one other reader, and only one: the window claim
    seeds this window's name from it the first time it presents one. That is the
    same fact the key uses it for -- this page instance, distinct from any other
    -- so it is reused rather than minted again, and the count here is what stops
    a third reader appearing unannounced.
    """
    source = page_source()
    assert source.count("idempotency_key:") == 1, "a second place builds an event's key"
    assert source.count("PAGE_ID") == 3, "the page-instance prefix is used outside the constructor"
    builder = source.split("function ev(", 1)[1].split("\nfunction ", 1)[0]
    assert "idempotency_key:" in builder
    assert "PAGE_ID" in builder
    assert "PAGE_ID" in function_body("claimHolder")


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


def test_the_page_writes_only_through_the_event_route_and_the_two_controls() -> None:
    """The log has one door, and the controls beside it write nothing to it."""
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
    assert observer.count("entry.timestamp") == 1, "an observed update is stamped from elsewhere"
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


# ---------------------------------------------------------------- GUI-A59


def test_a_decisions_seed_prompts_are_controls_on_its_thread_pane() -> None:
    """One control per seed field the decision declared, and none where it
    declared none.

    Seed text with no control on the surface is data nothing consumes: the node
    shape has carried it from the first handoff, and without a button the only
    way to say one is to retype it. Which fields there are is read off the
    decision rather than listed in the page, so a seed the page does not know
    the name of is still a seed someone wrote.
    """
    controls = function_body("seedControls")
    assert 'if (!d || !d.talk) return "";' in controls, "a decision without seeds still renders one"
    assert "Object.keys(d.talk)" in controls, "the fields are a list the page keeps"
    assert 'data-act="seed"' in controls
    # Both panes, because both are thread panes: the one for a discussion under
    # way and the one for a decision nobody has said anything on yet, which is
    # the state most seeds are written for.
    pane = function_body("threadBody")
    assert "seedControls(anchor, null)" in pane, "a thread not yet opened offers no seed"
    assert "seedControls(t.decision, tid)" in pane, "an open thread offers no seed"


def test_pressing_a_seed_says_it_as_the_humans_own_turn() -> None:
    """The seed rides the path a typed turn rides -- same event, same channel,
    same outbox -- so it is a shortcut for the human's hands rather than a
    second way into the log. On a decision nothing has been said on yet, saying
    a seed is what opens the thread.

    The text comes off the board, never off the button: the pane is redrawn from
    the board on every tick, and a control that carried its own copy would send
    the seed as it read when the button was drawn.
    """
    assert "saySeed(tid, id, el.dataset.field)" in click_cases()["seed"]
    said = function_body("saySeed")
    assert "d.talk[field]" in said, "the seed's words come from somewhere other than the board"
    assert "sayInThread(tid, text)" in said
    assert "startThread(id, text)" in said
    assert "seed" in write_acts(), "a closed session still offers to say a seed"


def test_a_seeds_words_reach_the_pane_as_words_rather_than_as_markup() -> None:
    """The seed is authored by whatever assembled the handoff, and it is the
    label on its own control. A tag inside it would be a tag on the page the
    human is answering decisions on."""
    assert "esc(d.talk[f])" in function_body("seedControls")


def test_the_popped_window_offers_the_same_seeds_as_the_pane() -> None:
    """The popped window is the same pane, so it renders the same controls --
    and the bridge back has to carry which seed was pressed, which is the one
    thing the copy can say that the main window cannot work out for itself."""
    assert "el.dataset.field" in function_body("popOut"), "the popped window drops the field"
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert 'act === "seed"' in bridge
    assert "(thread(tid) || {}).decision" in bridge, "the decision comes from the popped button"


# ---------------------------------------------------------------- the two thread gestures


def test_closing_a_thread_is_offered_beside_parking_it_wherever_parking_is() -> None:
    """The two are one choice -- come back to this, or be done with it -- and a
    choice with one option on screen is not one.

    Counted against the branches of the pane's foot rather than against a
    number written here: a foot that grew a third branch offering park alone
    would leave the human able to set a thread aside and unable to finish with
    it, in exactly the state the terminal result then reports as unfinished.
    """
    foot = balanced_body("threadBody")
    assert foot.count('data-act="park"') == foot.count("closeControl(tid)"), (
        "a branch offers park without close"
    )
    assert foot.count('data-act="park"') == 2, "the foot's park branches were not read"
    control = function_body("closeControl")
    assert 'data-act="closethread"' in control
    assert "esc(tid)" in control, "the control names its thread unescaped"
    # The panel's own ✕ dismisses the view and is neither gesture, so the two
    # are spelled differently on purpose.
    assert 'data-act="close"' not in page_source(), "the gesture and the panel dismiss collide"


def test_the_popped_window_can_close_the_thread_it_is_showing() -> None:
    """The popped pane renders the same foot, so its close has to reach the same
    handler or it is a button that does nothing in that window."""
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert 'act === "closethread"' in bridge
    assert "closeThread(tid)" in bridge


def test_the_popped_window_can_open_the_thread_it_is_a_draft_of() -> None:
    """A thread that does not exist yet pops out like any other, and its Send is
    the only thing that would ever create it.

    Reaching nothing is the worst shape this can take: the human types the first
    turn, presses Send, and the window neither opens a thread nor says it did
    not. So the bridge routes that act to the one function that opens a thread,
    on the anchor the window came with -- and the pane the window is a copy of
    drew its box from the same reader, since a pane and a bridge naming
    different decisions would open the thread on the wrong one.
    """
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert 'act === "draftsay"' in bridge, "a popped draft's Send reaches nothing"
    assert "startThread(anchor, text)" in bridge
    assert "draftsay" in write_acts(), "the act that opens a thread is not a write"
    assert "draftAnchor(tid)" in balanced_body("threadBody"), "the pane reads its own anchor"
    assert "draftAnchor(tid)" in function_body("popOut"), "the window is handed no anchor"
    # A seed is the same act with the words already written, and saySeed opens
    # the thread when there is none -- which on a draft is always.
    assert "(thread(tid) || {}).decision || anchor" in bridge
    assert "el.dataset.act==='draftsay'" in function_body("popOut"), "the box keeps the sent turn"


def test_a_popped_window_carries_the_draft_it_was_opened_on() -> None:
    """The anchor is read once, when the window opens, and travels with it.

    Read at the moment of the click instead, it comes out of the one draft slot
    this window keeps -- and that slot holds whichever draft the board opened
    last. Pop a draft on one decision out, open a draft on another on the board,
    and the popped Send anchored to the second decision, or to none at all and
    opened the session thread. Nothing the board does afterwards reaches a
    window that was handed its own.
    """
    boot = function_body("popOut")
    assert "var anchor=" in boot, "the popped window is not told which draft it is on"
    assert r'JSON.stringify(draftAnchor(tid) || null).replace(/</g, "\\u003c")' in boot
    assert "window.opener.popAct(tid,anchor," in boot, "the anchor is not what the act carries"
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert "draftAnchor" not in bridge, "the bridge resolves the anchor for itself"
    assert "UI.draftFor" not in bridge, "the bridge reads the board's own draft slot"


def test_a_popped_window_follows_the_thread_its_own_first_turn_opened() -> None:
    """The window was opened on a draft, and a draft's name is not what the
    thread its first turn opens is called.

    The window has to be told, and it is the only thing that may hold the
    answer: kept for it here, under the draft's name, it is state every window
    on that name shares -- so one window's turn moved another window onto a
    thread it was never opened on. The act hands the new thread back instead,
    and the window that asked keeps it.
    """
    assert "return tid;" in function_body("startThread"), "nothing learns the new thread's name"
    assert "UI.popFollow" not in page_source(), "the shared follow map is gone"
    assert "threadBody(tid, true)" in page_source(), "the window is not asking for its own thread"
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert "return thread(tid) ? sayInThread(tid, text) : startThread(anchor, text);" in bridge, (
        "a Send from a pane drawn before the first turn opens a second thread"
    )
    boot = function_body("popOut")
    assert "made=window.opener.popAct(" in boot and "if(made)tid=made;" in boot


def test_a_closed_thread_keeps_the_box_that_opens_it_again() -> None:
    """Re-opening rides the turn, so the box is the whole affordance.

    A parked or folded thread keeps no box: neither re-opens, and a box whose
    turn changed nothing would be the page offering a way back the fold does
    not have. Both boxes are built by one reader, since an open thread and a
    closed one take the same turn on the same channel.
    """
    pane = balanced_body("threadBody")
    assert 'var closed = t.state === "closed";' in pane
    assert 'closed ? sayBox(sayId, tid) : ""' in pane, "a closed thread has no way back"
    assert pane.count("sayBox(sayId, tid)") == 2, "the two boxes are not one reader"
    box = function_body("sayBox")
    assert 'data-act="say"' in box and 'data-send="say"' in box
    assert "say" in write_acts(), "a closed session still offers to re-open a thread"


def test_closing_a_thread_is_a_write_the_ended_surface_takes_away() -> None:
    """The gesture writes to the log, so an ended board must stop offering it --
    the same rule park is held to."""
    assert "closethread" in write_acts()
    assert "closeThread(tid)" in click_cases()["closethread"]


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


# ---------------------------------------------------------------- GUI-A60


def test_an_options_tradeoff_rides_on_its_own_icon_and_on_nothing_larger() -> None:
    """The trio the wire has always carried, read at last -- and read once.

    Where it is read decides how invasive the overlay is. A target the size of
    the option fires on every pass of the pointer towards that option, so the
    card lands over the answers exactly as the human reaches for one. The
    overlay resolves its owner through a single selector, so the whole of the
    difference between an icon-sized target and a block-sized one is which
    element the three statements are written onto. Nothing else needs saying
    here, and nothing else may carry them.

    That an icon is on screen, that only it raises a card, and that the card
    lands inside the window are a layout engine's answers and are measured in a
    browser. What is measured here is that the source can only mean one thing.
    """
    source = page_source()
    icon = function_body("pcrIcon")
    # The option's own trio, read in one place, and no icon promising a reason
    # that is not there.
    assert "o.pcr" in icon, "the page never reads the option's trade-off"
    assert source.count("o.pcr") == 1, "something other than the icon reads the trade-off"
    assert 'if (!p[0]) return "";' in icon, "an option carrying no trade-off still gets an icon"
    assert 'class="pcricon"' in icon, "the trade-off hangs off something other than an icon"
    # A real button, so the trade-off is reachable from a keyboard without a
    # tabindex of its own, and so focus and hover are the same affordance.
    assert 'type="button"' in icon, "the icon cannot take focus"
    # The statements are on the icon, which is what the overlay's one selector
    # finds -- and the option control carries none of them, so neither it nor
    # the block around it can ever be the owner that selector resolves to.
    button = function_body("optionButton")
    assert "pcrIcon(o)" in button, "the option renders no icon beside it"
    for attribute in ("data-p=", "data-c=", "data-r=", "data-otext="):
        assert attribute in icon, f"the icon does not carry {attribute}"
        assert attribute not in button, f"the option control still carries {attribute}"
    # One card builder, so what a pointer raises and what a keyboard raises
    # cannot drift into two overlays saying different things.
    assert source.count("function pcrCard(") == 1
    assert source.count("showHover(pcrCard(o), o.getBoundingClientRect())") == 2, (
        "hover and focus do not raise the same card"
    )
    # Focus leaving the icon takes the card away without muting the zone: a zone
    # muted by focus moving off it would never hand its card back at all.
    assert 'document.addEventListener("focusout"' in source
    # Placed against its own measured size. The card is as tall as the words in
    # it, and the longest trade-off is raised from the bottom edge of the pane
    # -- where a guessed height puts it off the bottom of the window.
    place = function_body("showHover")
    assert "HOVER.offsetHeight" in place, "the card's height is guessed, not measured"
    assert "window.innerHeight - h - 6" in place, "the card is not held inside the window"


# ---------------------------------------------------------------- GUI-A47


def test_an_informational_carries_a_discuss_control_wherever_it_is_read() -> None:
    """On its decision and in the notification list alike.

    An agent message read in the notification list is the same message; having
    to go and find it on its decision to answer it is the friction that makes a
    Discuss control on one surface and not the other read as a bug.
    """
    assert 'data-act="discussnotice"' in function_body("infoNote")
    # Unconditionally in the list, because the list carries nothing but
    # messages: a change that happened is on the board and is argued with in the
    # inbox before it lands, never here.
    assert 'data-act="discussnotice"' in function_body("renderNotifications")
    assert "n.type ===" not in function_body("renderNotifications")


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

    Scoped to the session token rather than to the epoch, and that is the second
    decision here. The ids in this set name log entries, and the log outlives any
    one process: an epoch-scoped set is discarded by a restart that invalidated
    none of them, and every marker the human already dealt with lights up again.
    The token is the session's own identity, which is exactly the scope those ids
    are valid in -- and it also keeps two sessions that reuse a loopback port out
    of each other's read-state, which the epoch did only by accident.
    """
    source = page_source()
    assert "window.localStorage" in function_body("saveRead")
    assert "window.localStorage" in function_body("loadRead")
    assert '"grillui:read:" + CLAIM.token' in function_body("readKey")
    assert "WIRE.epoch" not in function_body("readKey"), "read-state is scoped to the tenure again"
    # Loaded once the token is known, which the claim answers with before the
    # board is read at all -- and this is the one moment a reload has to look
    # like the session the human left rather than a new one.
    assert "loadRead();" in function_body("hydrate")
    # The list is still built only from what arrives after this page did: the
    # reload path reads the whole log as a lookup table and touches the
    # notifications not at all.
    assert "NOTES" not in function_body("hydrate"), "a reload rebuilds the list from the log"
    assert source.count("NOTES.push") == 1, "notifications are written outside the observer"


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


# ---------------------------------------------------------------- GUI-A56


def test_a_change_that_landed_raises_no_notification() -> None:
    """The board renders it, so the lane does not.

    The observer is the one place a notification is written, and a map mutation
    leaves it having marked the decision it moved and written nothing. What a
    receipt would have said is on that decision's block and in its history
    already, so the lane would be restating the board -- and a lane that
    restates the board is one the human stops opening, taking the messages that
    are only in it down with it.
    """
    observer = function_body("observe")
    mutation = observer.split("MAP_MUTATION_KINDS.indexOf(u.kind) < 0", 1)[1]
    assert "NOTES.push" not in mutation, "a landed change is announced as well as rendered"
    assert "UI.touched.push(u.target)" in mutation, "nothing marks the decision that moved"
    # The status lane and the human's own gestures never reach it either, which
    # is the same rule read on the entry rather than on the update.
    assert "if (entry.kind === STATUS_KIND) return;" in observer
    assert 'if (entry.actor === "human" && entry.kind !== APPLY_KIND) return;' in observer


def test_a_message_the_board_can_render_is_not_also_announced() -> None:
    """One message, one surface, and the board gets first refusal.

    A message naming a decision is read on that decision's block. Prose that
    arrived carrying board changes is framing for those changes and is read on
    them. Only a message with no decision to land on reaches the lane -- which
    is what leaves the lane worth opening.
    """
    observer = function_body("observe")
    assert "noticeHomes(" in observer
    assert "if (!homes.length) {" in observer, "the lane is written without asking the board"
    homes = function_body("noticeHomes")
    # Derived from the log, so the reload that empties the lane renders the
    # message in the same place it was before.
    assert "entryAt(item.authored_at)" in homes
    assert "MAP_MUTATION_KINDS.indexOf(u.kind)" in homes
    # And a home is a decision the board is carrying, so "the board shows this
    # already" is measured rather than assumed.
    assert "node(id)" in homes


def test_agent_framing_renders_on_the_decision_its_entry_changed() -> None:
    """Every surface that shows a message asks the same question of it.

    The collapsed block, the expanded block and the ✉ markers alike: a message
    routed to a decision by one surface and not another is one the human is told
    about and cannot find.
    """
    source = page_source()
    assert source.count("noticesOn(id).forEach(function (n) { h += infoNote(n); });") == 2
    assert "noticesOn(id)" in function_body("unreadNotices")
    assert "noticeHomes(n)" in function_body("noticesOn")


def test_a_message_reaches_every_surface_as_words_rather_than_as_markup() -> None:
    """Wherever the policy routes it. The agent's prose is untrusted input on
    the board, in the lane and in the bubble stack, and the routing decides
    which of those it reaches rather than whether it is escaped."""
    for surface, expression in (
        ("infoNote", "esc(summarise(n))"),
        ("renderNotifications", "esc(n.text)"),
        ("renderBubbles", "esc(b.text"),
    ):
        assert expression in function_body(surface), f"{surface} renders prose unescaped"


# ---------------------------------------------------------------- GUI-A19


def test_the_pages_claim_states_are_the_backends_own_and_are_named_by_position() -> None:
    """The page holds no word for a claim state the backend cannot answer with.

    Named by position rather than restated, so the two lists cannot drift into
    the shape where the page recognises `granted` and the backend has renamed it
    -- which reads as a permanent refusal on a session nobody else has.
    """
    assert page_vocabulary()["CLAIM_STATES"] == list(CLAIM_STATES)
    source = page_source()
    for index, name in enumerate(("CLAIM_GRANTED", "CLAIM_REFUSED", "CLAIM_SUPERSEDED")):
        assert f"{name} = CLAIM_STATES[{index}]" in source, f"{name} restates the backend's word"


def test_the_claim_is_a_name_this_window_keeps_where_a_second_window_cannot_find_it() -> None:
    """Session storage, and the choice is the whole feature.

    Session storage is the one origin store scoped to a single window: it
    survives this window's reload -- so a reload is never a lockout -- and it is
    not there for a second window to read and present as its own. Local storage
    would hand the claiming window's name straight to the next window opened on
    the same origin, and every second window would be granted the session it is
    supposed to be refused.
    """
    holder = function_body("claimHolder")
    assert "window.sessionStorage" in holder
    assert "window.localStorage" not in holder, "a second window would find this name"
    assert "window.sessionStorage" in function_body("claim")
    # Read-state is the opposite case and stays in local storage: it is the
    # human's, not the window's, and it has to outlive the window that set it.
    assert "window.localStorage" in function_body("saveRead")


def test_one_call_is_the_claim_the_reload_the_reconnect_and_the_take_over() -> None:
    """Four situations, one request, so there is one answer to keep true.

    They are the same question -- is this the name that holds the session -- and
    splitting them into separate routes would mean four places where a window
    could be told it holds a session it does not.
    """
    body = function_body("claim")
    assert 'srvPost("/claim"' in body
    assert "holder: claimHolder()" in body
    assert "takeover: !!takeover" in body
    assert page_source().count('srvPost("/claim"') == 1, "a second route presents a claim"
    # The boot claim, the periodic re-presentation, and the human's gesture.
    assert "claim(false).then(poll)" in page_source()
    assert "setInterval(function () { claim(false); }" in page_source()
    assert 'case "takeover": claim(true);' in page_source()


def test_only_an_answer_moves_the_claim_and_a_failed_request_never_does() -> None:
    """A dropped packet is not a supersede.

    A page that read a failed request as a lost claim would hide a working board
    the moment the wire blinked -- and it would do it on the one path that has no
    way of knowing anything at all.
    """
    body = function_body("claim")
    assert "CLAIM.state = c.state;" in body
    # The rejection handler is the wire's own reporter and nothing else: it takes
    # the error whole, so there is no branch in which a failure writes a state.
    assert "}, wireFailed);" in body, "the failure path is not the bare wire reporter"
    assert body.count("CLAIM.state =") == 1, "a second path writes the claim state"


def test_a_window_that_is_not_the_sessions_never_draws_a_board() -> None:
    """ "Not a working board" is enforced at the one place that draws one.

    A banner over the board is not this: the decisions are still there and the
    human still answers them. So the gate is on the render itself, and the board
    poll is gated too -- a window that will not draw what it reads has no reason
    to be reading it.
    """
    assert "if (!boardShown()) { renderNotice(); return; }" in function_body("render")
    gate = function_body("boardShown")
    assert "CLAIM_REFUSED" in gate and "CLAIM_SUPERSEDED" in gate
    assert "if (CLAIM.state !== CLAIM_GRANTED) return;" in function_body("poll")


def test_the_refused_and_superseded_windows_each_say_what_happened_to_them() -> None:
    """Two situations, two sentences, and a way back from both.

    Told apart because the human's next move differs: one window is looking at a
    session somebody else opened, the other held it and was taken over and has a
    board on screen it must stop trusting. Both offer the take-over, because a
    superseded window is a refused window that used to hold it.
    """
    notice = function_body("renderNotice")
    assert "CLAIM.state === CLAIM_SUPERSEDED" in notice
    assert "took this session over" in notice
    assert "already has this session" in notice
    assert 'data-act="takeover"' in notice
    assert 'id="claimnotice"' in notice and 'data-claim="' in notice
    # Nothing of the board survives on screen beside it.
    assert 'getElementById("overlay").innerHTML = ""' in notice
    assert 'getElementById("bubbles").innerHTML = ""' in notice


def test_the_claim_is_kept_out_of_the_connection_indicator() -> None:
    """A refused claim says nothing about the wire, and the wire says nothing
    about the claim.

    The backend answered a refusal immediately and clearly, which is a healthy
    transport by every measure the indicator has; folding the refusal in would
    put "nothing is listening" beside a reply that just arrived. The two layers
    the indicator does carry are the transport's and each channel's, and a window
    holding no session has no channels to report on at all -- which is why the
    notice replaces the indicator rather than colouring it.
    """
    for surface in ("renderIndicator", "renderDiagnostic", "worstChannel", "severityOf"):
        body = function_body(surface)
        assert "CLAIM" not in body, f"{surface} reads the claim"
    assert "renderIndicator" not in function_body("renderNotice")
    # And the claim's own call reports the wire, because it is a real request
    # over the same transport every other one uses.
    assert 'wire("reached")' in function_body("claim")


def test_the_claim_control_appends_nothing_and_builds_no_event() -> None:
    """Session control is not board history, measured on the page's side too.

    The backend's half is measured at the wire; this is the half that says no
    code path on the page could ask it to be otherwise.
    """
    for control in ("claim", "claimHolder", "boardShown", "renderNotice"):
        body = function_body(control)
        assert "ev(" not in body, f"{control} builds an event"
        assert "send(" not in body, f"{control} reaches the write route"


# ------------------------------------------------- GUI-U11, GUI-A33/A34/A35


def test_the_payload_keys_the_page_reads_a_tier_off_are_the_backends_own() -> None:
    """Three keys, spelled once each, pinned to the backend's own spelling.

    The page reads the tier a channel is waiting on, the escalation advice a
    reply carries, and writes the flag that moves a channel between tiers. All
    three are payload content rather than envelope fields, so nothing validates
    them on the way past: a page holding a stale spelling would show a control
    that highlights for nothing and sends a transfer the backend never reads.
    """
    constants = page_constants()
    assert constants["TIER_KEY"] == TIER_KEY
    assert constants["RECOMMENDATION_KEY"] == RECOMMENDATION_KEY
    assert constants["TRANSFER_FLAG"] == TRANSFER_FLAG


def test_only_a_turn_the_human_speaks_declares_the_transfer_flag() -> None:
    """The flag rides turns, and the table is what says which kinds those are.

    A transfer forces the next *turn* on a channel, so the flag belongs on the
    kinds that are a turn -- and the backend only owes a reply to those. A fold,
    a park or a queue verb carrying it would set a channel's mode with no turn
    behind it to spend the expert on, and on a fold it would set the wrong
    channel's: the fold's reply comes back on the map, not in the thread.
    """
    declaring = {kind for kind, rule in emissions().items() if TRANSFER_FLAG in rule["payload"]}
    assert declaring, "no kind carries the transfer flag, so the control forces nothing"
    assert declaring <= ANSWERABLE_KINDS
    assert not declaring & (THREAD_GESTURE_KINDS | QUEUE_GESTURE_KINDS | LIFECYCLE_KINDS)


def test_the_flag_is_stamped_by_the_one_checked_constructor_off_the_declaration() -> None:
    """One place writes it, and the table decides where it goes.

    A per-site stamp is how a turn ends up leaving without the flag: the human
    presses the control, the one emission site nobody updated sends a turn that
    says nothing about the tier, and the mode silently stands still. Driving it
    off the declaration means adding a kind to the table is the whole change.
    """
    # Assignments only: the page reads the same key back to learn a channel's
    # mode, and a comparison is not a second writer.
    written = re.findall(r"payload\[TRANSFER_FLAG\] = [^=]", page_source())
    assert len(written) == 1, "a second place stamps the flag"
    builder = function_body("ev")
    assert "rule.payload.indexOf(TRANSFER_FLAG)" in builder
    assert "payload[TRANSFER_FLAG] = onExpert(channel)" in builder


def test_a_page_turn_carrying_the_flag_moves_that_channel_and_only_that_one(
    client: TestClient, log: Any
) -> None:
    """The page's own shape, on the wire, read back by the backend's own reader.

    This is the join the two halves of the feature meet at: the page declares a
    key on a turn, and the backend decides which tier answers by looking for
    exactly that key on exactly that channel. Asserted through `page_message`,
    so a shape the page never emits could not have proved it.
    """
    seed_node(client, log.epoch)
    answer = {"option": "a", "text": None}
    post(client, log.epoch, page_message("answer", MAP_CHANNEL, target="n1", answer=answer))
    assert not in_expert_mode(log.entries(), MAP_CHANNEL)

    post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target="n1", answer=answer, transfer=True),
    )
    assert in_expert_mode(log.entries(), MAP_CHANNEL)
    # One channel's gesture is that channel's alone, which is what makes the
    # control per-channel rather than a session-wide switch.
    assert not in_expert_mode(log.entries(), THREAD)

    post(
        client,
        log.epoch,
        page_message("thread-turn", THREAD, turns=turns("Say more."), transfer=True),
    )
    assert in_expert_mode(log.entries(), THREAD)
    post(
        client,
        log.epoch,
        page_message("thread-turn", THREAD, turns=turns("Back to you."), transfer=False),
    )
    assert not in_expert_mode(log.entries(), THREAD)
    assert in_expert_mode(log.entries(), MAP_CHANNEL)


def test_the_control_is_on_every_channel_and_is_never_disabled() -> None:
    """The map's channel and each open thread's, and active on all of them.

    Always active is the decision rather than an omission: the moment a human
    most wants an expert is the moment the fast tier is going badly, which is
    also the moment a control gated on the channel being idle would be greyed
    out. The label names the switch the press makes, so the channel already on
    the expert offers the way back.
    """
    control = function_body("transferControl")
    assert "disabled" not in control
    assert "Return to fast agent" in control, "the escalated channel does not offer the way back"
    assert "Transfer to expert" in control
    assert 'data-mode="' in control
    assert "transferControl(MAP)" in function_body("renderShell")
    assert "transferControl(tid)" in function_body("threadBody")
    # The popped-out thread is the same pane, so its control has to reach the
    # same handler rather than being a button that does nothing in that window.
    assert 'act === "transfer"' in page_source()


# ------------------------------------------------------ GUI-U22, GUI-A63


def test_the_control_names_the_action_and_never_the_state() -> None:
    """Two labels, each naming the press rather than where the channel is.

    A label naming the tier the channel is on is the failure this pins against:
    the human reads a state word on a control as where the channel is now, and
    so infers the opposite of what pressing it does -- which is how a transfer
    that did happen gets read as one that did not.
    """
    control = function_body("transferControl")
    assert '(on ? "⚡ Return to fast agent" : "⚡ Transfer to expert")' in control
    for state in ("Fast agent mode", "Expert mode", "Expert agent mode"):
        assert state not in page_source(), f"the control wears {state!r} as a state"


def test_the_control_carries_no_state_styling_in_either_position() -> None:
    """Identical in both positions, so nothing about it reads as a tier.

    Both halves are pinned because either alone passes while the control is
    still coloured: a rule with nobody to apply it to is dead CSS, and a class
    with no rule today is a fill one stylesheet edit away.
    """
    control = function_body("transferControl")
    assert '" on"' not in control, "the control still wears a state class"
    assert ".btn.transfer.on" not in page_source(), "the state fill is still in the stylesheet"
    # The agent's recommendation is not state colouring: it is the agent asking,
    # and GUI-U11 keeps it. A ring rather than a fill is what keeps the two
    # legible apart, so it stays pinned as a ring.
    assert ".btn.transfer.rec { box-shadow:" in page_source()


# ------------------------------------------------------ GUI-U21, GUI-A62


def test_the_page_spells_the_two_tiers_the_way_the_backend_does() -> None:
    """The label is chosen by matching the log's own word, so the two spellings
    are one contract: a page holding a stale one labels nothing at all while the
    log says plainly which tier answered."""
    constants = page_constants()
    assert constants["FAST_TIER"] == FAST_TIER
    assert constants["HEAVY_TIER"] == HEAVY_TIER


def test_a_turn_is_labelled_by_its_own_tier_and_never_by_the_channels_mode() -> None:
    """`tierLabel` takes a tier and nothing else, and every caller hands it one
    read off the turn or off the entry that authored it.

    Taking the channel would relabel every turn from before a transfer as the
    tier that came after it -- and the transcript is the human's only evidence
    that the transfer changed anything.
    """
    label = function_body("tierLabel")
    assert "expert agent" in label
    assert "fast agent" in label
    assert "onExpert" not in label, "the label is read off the channel's current mode"
    assert "TRANSFER" not in label
    # Read off the projected turn on a thread, and off the authoring entry on the
    # map channel -- where a turn reaches the page as a queue item instead.
    assert "tierLabel(turn.tier)" in function_body("renderTurns")
    assert "tierLabel(tierAt(n.authored_at))" in function_body("infoNote")
    assert "tierLabel(tierAt(n.seq))" in function_body("renderNotifications")


def test_an_unattributed_turn_is_labelled_as_nothing_rather_than_as_a_guess() -> None:
    """A tier the page does not recognise, and none at all, both label nothing.

    The human's turns and the backend's have no tier, and neither does an agent
    turn an older session recorded before tiers were written down. Defaulting
    such a turn to either tier would put a claim on screen that the log does not
    make.
    """
    label = function_body("tierLabel")
    assert label.count("return") == 1
    assert (
        'return tier === HEAVY_TIER ? "expert agent" : tier === FAST_TIER ? "fast agent" : "";'
    ) in label
    # Every caller falls back to something that is not a tier, so an
    # unattributed turn still says who spoke without naming a tier for them.
    for caller in ("renderTurns", "infoNote"):
        assert '|| "Agent"' in function_body(caller), f"{caller} guesses a tier"


def test_the_mode_and_the_highlight_are_read_from_the_log_the_page_already_holds() -> None:
    """Neither is on image 1, and neither is remembered.

    The mode is the last thing the log said about that channel -- the human's own
    turn carrying the flag, or the lane's `transferred` entry where the policy
    moved it -- so a reload, a second window and a restarted backend all agree,
    because all three read one record. The highlight is the channel's latest
    agent reply and no earlier one, so a reply that meets no condition is what
    takes it away; advice about a question two turns ago is not advice about this
    one.

    The reply filter needs both halves: the lane's own `composing` entry names a
    tier as well, so a filter on the key alone reads the status lane.
    """
    mode = function_body("loggedMode")
    assert 'e.actor === "human"' in mode, "an agent's own payload could move the channel"
    assert "TRANSFER_FLAG in e.payload" in mode
    assert "e.payload.phase === PHASE_TRANSFERRED" in mode, "a policy transfer moves nothing here"
    assert "for (var i = LOG.length - 1; i >= 0; i--)" in mode, "the mode is not the last gesture"

    highlight = function_body("recommended")
    assert "AGENT_ACTORS.indexOf(e.actor) < 0" in highlight
    assert "TIER_KEY in e.payload" in highlight
    assert "e.payload[RECOMMENDATION_KEY] || null" in highlight
    assert "for (var i = LOG.length - 1; i >= 0; i--)" in highlight


def test_the_control_follows_the_log_rather_than_the_click_the_policy_overtook() -> None:
    """GUI-U24: after a policy transfer the control names the tier the channel
    is on, and not the one the human's own last click named.

    The click is an intent held until the log speaks after it, which is why it
    carries where the log stood when it was made. Without that, a human who had
    just sent a channel back to the fast tier would see *Transfer to expert* on a
    channel the policy had since escalated -- and their next turn, which stamps
    the flag off exactly this reading, would silently undo the transfer.
    """
    assert "since: LOG.length" in function_body("toggleTransfer"), "the click is not placed"
    assert "meant.since > said.at" in function_body("onExpert"), "a stale click outranks the log"
    assert '(on ? "⚡ Return to fast agent"' in function_body("transferControl")


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


def test_the_served_document_is_self_contained() -> None:
    """Three sources, one document. The split is a source-side convenience, and a
    page that reached for a file over the network would be a page that can render
    before its own styles or its own script arrive -- or without them."""
    document = page_source()
    assert len(re.findall(r"^<style>$", document, re.MULTILINE)) == 1
    assert len(re.findall(r"^<script>$", document, re.MULTILINE)) == 1
    for external in ("<link", "src=", "@import", "url("):
        assert external not in document, f"the served page fetches {external!r}"


# ---------------------------------------------------------------- the page's sinks

# An id on this board is text somebody else wrote: a handoff names its decisions,
# an agent names the thread its mandate opens, and the backend derives a queue
# entry's id from an entry an agent authored. All of it reaches this page as
# board content and all of it is put into markup, so an id carrying a quote or a
# tag is markup unless the page makes it text first.
#
# The escaper is the page's own and is measured at the sinks rather than at the
# source: a constraint on what an id may contain would have to hold in the log,
# in the handoff and in every agent, and the one place that can be checked is
# where the string becomes markup.
AUTHORED_ID = r"(?:\w+\.)*(?:id|tid|uid|nid|alert|target|threadId)"
# A line that builds markup: it opens a tag inside a string, or it writes an
# attribute. Lines that merely compose an id -- a new thread's, a seed sentence's
# -- are not sinks and are not judged.
MARKUP_LINE = re.compile(r'"[^"]*<|\S="')
# An attribute that carries an id, interpolating something that is not the
# escaper. Fail-closed on purpose: the rule is every one of them, so there is no
# list of approved exceptions to keep in step with the page.
ID_ATTRIBUTE = re.compile(r"""(?:data-[a-z-]+|\bid)="[^"<]*' \+ (?!esc\()[^+]+""")
RAW_AUTHORED = re.compile(r"\+ (" + AUTHORED_ID + r") \+")


def markup_lines() -> list[tuple[int, str]]:
    """Every line of the page that builds markup, with its number."""
    return [
        (number, line)
        for number, line in enumerate(page_source().splitlines(), 1)
        if MARKUP_LINE.search(line)
    ]


def page_word(name: str) -> str:
    """One `var NAME = "...";` the page declares."""
    found = re.search(rf'var {name} = ("[^"]*");', page_source())
    assert found, f"the page has no {name}"
    word: str = json.loads(found.group(1))
    return word


def write_acts() -> list[str]:
    """The page's own list of the acts that write."""
    found = re.search(r"var WRITE_ACTS = (\[.*?\]);", page_source(), re.DOTALL)
    assert found, "the page declares no WRITE_ACTS"
    listed: list[str] = json.loads(found.group(1))
    return listed


def click_cases() -> dict[str, str]:
    """Each act the click handler routes, and the code it routes it to."""
    handler = page_source().split('document.addEventListener("click"', 1)[1].split("\n});", 1)[0]
    cases = {}
    for chunk in re.split(r'\n\s*case "', handler)[1:]:
        act, code = chunk.split('"', 1)
        cases[act] = code
    assert "pick" in cases, "the click handler was not read"
    return cases


def balanced_body(name: str) -> str:
    """One function's body, brace-matched.

    Stricter than `function_body`, which reads to the next `function` keyword and
    so swallows whatever is declared some other way in between. The call graph
    below is only true if a function's body is its own.
    """
    source = page_source()
    opening = source.index("{", source.index(f"function {name}("))
    depth = 0
    for at in range(opening, len(source)):
        if source[at] == "{":
            depth += 1
        elif source[at] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : at + 1]
    unclosed = f"{name} is never closed"
    raise AssertionError(unclosed)


def reaches_send(code: str, seen: set[str] | None = None) -> bool:
    """Whether this code puts an event on the wire, through however many hops.

    The page's writes all funnel through `send`, so reaching it is the whole
    definition of a write -- and following the call graph rather than listing the
    handlers is what keeps the answer true when a new one is added.
    """
    if "send(" in code:
        return True
    seen = set() if seen is None else seen
    for name in re.findall(r"\b([a-zA-Z_$][\w$]*)\(", code):
        if name in seen or f"function {name}(" not in page_source():
            continue
        seen.add(name)
        if reaches_send(balanced_body(name), seen):
            return True
    return False


def acts_that_write() -> set[str]:
    return {act for act, code in click_cases().items() if reaches_send(code)}


def test_every_id_the_page_puts_in_an_attribute_goes_through_the_escaper() -> None:
    """An id an agent chose, rendered as text rather than as markup.

    An id carrying a double quote closes the attribute it is written into: the
    click delegation that reads `data-id` off the element loses the rest of the
    id, and whatever followed the quote is parsed as markup on a page the human
    is answering decisions on. Every id-bearing attribute is therefore escaped,
    with no exceptions to keep a list of.
    """
    offenders = [
        (number, match.group(0))
        for number, line in markup_lines()
        for match in ID_ATTRIBUTE.finditer(line)
    ]
    assert not offenders, f"attributes interpolating something other than esc(): {offenders}"


def test_no_authored_id_reaches_the_markup_unescaped() -> None:
    """The same rule where an id is the words on screen rather than an attribute.

    A node's id under the map node, the label on a decision block, the heading
    over its history: each is board content and each is a place a tag in an id
    would be a tag on the page.
    """
    offenders = [
        (number, match.group(1))
        for number, line in markup_lines()
        for match in RAW_AUTHORED.finditer(line)
    ]
    assert not offenders, f"ids reaching markup unescaped: {offenders}"


def test_the_popped_window_is_handed_its_thread_id_as_data() -> None:
    """The pop-out writes a boot script into another document, and the thread id
    is in it. A closing script tag inside the id would end that script where it
    sits, leaving the popped window with a thread it cannot draw and a fragment
    of the id as markup."""
    assert r'JSON.stringify(tid).replace(/</g, "\\u003c")' in function_body("popOut")


# ---------------------------------------------------------------- the mandate's hold


def test_a_mandated_thread_concludes_only_on_an_answer_it_is_holding() -> None:
    """Concluding is what applies the answer, so an empty conclusion is not one.

    Folding a mandated thread with nothing held used to end it having settled
    nothing -- and a mandated decision whose thread has ended is answerable by an
    ordinary click, which is the single route to an answer the mandate exists to
    close. The gesture is refused at the fold rather than only hidden on the
    button, because the pop-out window folds through the same call.
    """
    body = function_body("foldThread")
    branch = body.split('if (t.kind === "mandate")', 1)[1].split("\n  if (held)", 1)[0]
    assert "if (!held)" in branch
    assert branch.count("refuse(") == 2, "the mandate branch turns two things away"
    assert "send(" not in branch, "the mandate branch puts nothing on the wire"


def test_an_answer_held_through_a_revise_is_not_settled_onto_a_dead_option() -> None:
    """The options belong to the agent, and a thread takes time.

    An answer records whatever option id it is sent -- there is no reason in the
    backend's closed vocabulary for refusing one that names an option the
    decision no longer has, so it would settle onto something nobody can read.
    The hold goes instead, and the human is told which of the two things
    happened rather than reading a generic refusal.
    """
    body = function_body("foldThread")
    assert "optionOn(t.decision, held.option)" in body
    assert "UI.drafts[t.decision] = held.note" in body, "the words that came with the pick are kept"
    check = function_body("optionOn")
    assert "d.options.some" in check


def test_abandoning_a_held_answer_leaves_the_mandated_thread_where_it_is() -> None:
    """A mandate names one thread id, and nothing creates that id twice.

    Parking the thread on an abandon left the next pick held against a
    conversation that could be neither spoken in nor concluded: the decision sat
    in `awaiting-thread` with no way out but abandoning again. The thread is the
    mandate's rather than the answer's, so it stays -- and it is not counted as
    a blocking thread, because the hold it represents is the mandate's own and
    is already refused around.
    """
    abandon = function_body("abandonAnswer")
    assert "thread-park" not in abandon
    assert "send(" not in abandon, "abandoning an answer nobody sent writes nothing"
    blocking = function_body("blockingThreads")
    assert "d.mandate.threadId" in blocking and "tid !== mandated" in blocking
    assert "mandateHolding(id)" in function_body("holdOn"), "the hold is a hold of its own"


def test_a_pick_made_after_an_abandon_tells_the_thread_what_it_is_holding() -> None:
    """The thread is what concludes, and it concludes on what it discussed.

    A second pick into a thread that already exists used to say nothing, so the
    agent went on discussing a leaning the human had changed and the conclusion
    applied the new one.
    """
    body = function_body("answerDecision")
    assert 'ev("thread-turn", d.mandate.threadId' in body
    assert 'ev("thread-created", d.mandate.threadId' in body
    assert "seedForMandate(d, payload)" in body


def test_a_held_answer_survives_the_reload_that_leaves_its_thread_standing() -> None:
    """A reload used to drop the hold while the thread went on blocking.

    The human came back to a decision that was locked by a conversation whose
    only conclusion applied an answer no longer anywhere -- and nothing on the
    page said the pick was gone. The hold is written where this window's reload
    finds it, on every move that touches it.
    """
    source = page_source()
    assert 'UI.held = loadWindow("held", {})' in function_body("hydrate")
    assert 'saveWindow("held", UI.held)' in function_body("saveHeld")
    assert "sessionStorage" in function_body("loadWindow")
    mutations = re.findall(
        r"(delete UI\.held\[[^\]]+\];|UI\.held\[[^\]]+\] = [^\n]*)\n(\s*\S[^\n]*)", source
    )
    assert mutations, "the hold is never written"
    for wrote, following in mutations:
        assert "saveHeld();" in following, f"{wrote!r} is not made durable"


# ---------------------------------------------------------------- the session's end


def test_the_ending_the_page_watches_for_is_the_entry_the_backend_appends(
    client: TestClient, log: Any
) -> None:
    """One word for the ending, at both ends of the wire.

    The page reads its own end off the log it already holds, so the kind it
    looks for has to be the kind the backend writes. A page holding a stale one
    would render a finished session as a live board with a sick backend.
    """
    receipt = post(client, log.epoch, page_message(SESSION_END_KIND, MAP_CHANNEL))[0]
    assert receipt["status"] == "accepted"
    entries = client.get("/updates", params={"epoch": log.epoch, "cursor": 0}).json()["entries"]
    assert [one for one in entries if one["kind"] == SESSION_END_KIND]
    assert page_word("SESSION_END_KIND") == SESSION_END_KIND
    over = function_body("sessionOver")
    assert "e.kind === SESSION_END_KIND" in over and "ENDED" in over


def test_a_session_that_has_ended_is_rendered_as_ended_rather_than_as_a_dead_backend() -> None:
    """The backend stops because the session ended, not because it broke.

    Left to the transport, the ending reads as `no backend` over a fully live
    board, under an invitation to restart something the human deliberately
    finished. The ended notice comes first and the wire's own banner is not
    shown beside it.
    """
    shell = function_body("renderShell")
    assert "if (sessionOver()) {" in shell
    assert shell.index("if (sessionOver()) {") < shell.index(
        'CHANNELS.transport === "disconnected"'
    )
    assert "} else if (CHANNELS.transport" in shell, "the two banners are alternatives"


def test_nothing_more_is_said_into_a_log_that_has_been_closed() -> None:
    """Every write refuses, and the surface stops offering to make one.

    The receipt is what settles it as well as the log: a launched backend stops
    the moment the terminal entry is durable, so the update read that would
    carry that entry may never answer.
    """
    assert "|| sessionOver()) return;" in function_body("send")
    assert "if (sessionOver()) return;" in function_body("poll")
    assert "if (sessionOver()) return;" in function_body("callDoctor")
    assert "ENDED = true;" in function_body("send")
    seal = function_body("sealSurface")
    assert "el.disabled = true" in seal and "ta.disabled = true" in seal
    assert "sealSurface();" in function_body("render")


def test_a_popped_window_ends_with_the_session_that_opened_it() -> None:
    """A pop-out is part of this session, so the ending reaches it too.

    It is a second document with its own controls, redrawn on its own clock from
    the main window's pane, so neither half of the ending arrives on its own.
    The surface is sealed by the same reader rather than by a copy of the rule
    living over there, and on the tick rather than inside the redraw -- the
    redraw does nothing when the pane's html is unchanged, and a session ending
    changes the log, not necessarily the thread on screen. The bridge refuses
    every write besides, so a control drawn before the last seal is still a
    gesture the session turns away rather than one it swallows.
    """
    assert "function sealSurface(doc)" in page_source(), "the seal reaches one document only"
    assert "doc = doc || document;" in function_body("sealSurface")
    boot = function_body("popOut")
    assert "window.opener.sealSurface(document)" in boot, "the popped window is never sealed"
    assert "setInterval(function(){draw();seal();},600)" in boot, "the seal rides the redraw"
    bridge = page_source().split("window.popAct = function", 1)[1].split("\n};", 1)[0]
    assert "if (sessionOver() && WRITE_ACTS.indexOf(act) >= 0) return null;" in bridge


def test_every_act_that_writes_is_one_the_ended_surface_takes_away() -> None:
    """The list and the call graph, crossed.

    A control left live over a `send` that refuses is a click the page swallows
    while the human watches themselves make it. Which acts write is followed
    through the calls rather than restated, so an act added later is measured
    rather than assumed.
    """
    writing = acts_that_write()
    assert "pick" in writing and "fold" in writing, "the call graph was not followed"
    still_offered = writing - set(write_acts())
    assert not still_offered, f"acts that write and are still offered: {still_offered}"


# ---------------------------------------------------------------- the discussed change


def test_a_discussion_thread_holds_the_change_it_was_opened_to_judge() -> None:
    """Keyed by its thread, and kept where this window's reload finds it.

    The binding used to be one slot in page memory: a reload emptied it while
    the popped window still showed the apply and dismiss controls, and clicking
    them did nothing at all. One slot also meant a second discussion overwrote
    the first, so a pop-out could resolve a change on a decision it was never
    about.
    """
    assert "UI.pendingThread" not in page_source(), "the single slot is gone"
    opened = function_body("discussPending")
    assert "UI.discussing[tid] = id;" in opened and "saveDiscussing();" in opened
    assert 'UI.discussing = loadWindow("discussing", {})' in function_body("hydrate")
    assert "UI.discussing[tid] || null" in function_body("threadBody")
    popped = page_source().split("window.popAct = function", 1)[1]
    popped = popped.split("\n};", 1)[0]
    assert popped.count("UI.discussing[tid]") == 4, "the pop-out asks about its own thread"


# ---------------------------------------------------------------- the human's place


def test_taking_the_caret_never_moves_the_page() -> None:
    """One defect, three symptoms, and one place it is answered.

    A bare `focus()` reveals its element by scrolling every scrollable ancestor
    and then the document. The page takes the caret on every re-render, and a
    re-render is a poll tick, an arriving message, or a click on anything -- so
    the same call was, in turn: the outbox chip scrolling its own drop-down off
    the top of the window; a notification throwing away the place the human had
    scrolled the decision log to; and a decision taller than the log landing
    with its first option at the top and its title above the edge, because the
    box the caret goes to is at the bottom of the block.

    Measured as the absence of a bare call rather than the presence of a good
    one: a fourth site added later is the same defect back, and only the absence
    catches that. Where the board follows the human stays `centerOn`'s decision,
    made in one place.
    """
    source = page_source()
    assert ".focus()" not in source, "a caret is taken somewhere without preventScroll"
    assert source.count("preventScroll") == 2, "a focus site does not hold the page still"
    assert "el.focus({ preventScroll: true });" in function_body("takeCaret")
    # Every caret the board takes goes through the one helper, and the caret
    # position rides with it -- restoring the selection is what made one of the
    # sites a second call rather than a call to the same helper.
    assert function_body("render").count("takeCaret(") == 4
    assert "el.setSelectionRange(caret, caret)" in function_body("takeCaret")


def test_a_re_render_puts_the_decision_log_back_where_the_human_had_it() -> None:
    """Read before the shell is replaced, written after, unconditionally.

    The fresh element starts at zero, so a restore that only ran sometimes is a
    log that jumps sometimes -- which is how this was reported: intermittently,
    with no pattern the human could name.
    """
    body = function_body("render")
    assert "cy: col ? col.scrollTop : 0" in body
    assert "if (col2) col2.scrollTop = keep.cy;" in body
    # And the map with it, so panning survives the same re-render.
    assert "map2.scrollLeft = keep.mx; map2.scrollTop = keep.my;" in body


def test_a_thread_follows_its_newest_turn_unless_the_human_scrolled_up() -> None:
    """The turns are their own scroller, replaced whole on every re-render.

    Held to the rule a chat log follows, and to both halves of it. A reader at
    the bottom is following the conversation, so an arriving turn is on screen
    without a gesture; a reader who has scrolled up is reading what is up there,
    and an arrival is not a reason to take it away from them. Always scrolling
    to the bottom satisfies the report that produced this and is the worse bug.

    A panel with no place yet -- one that has just opened, or one showing a
    different thread from the one measured -- counts as at the bottom, because a
    thread opens at its newest turn.
    """
    assert "el.scrollHeight - el.scrollTop - el.clientHeight <= THREAD_STICK" in function_body(
        "atThreadBottom"
    )
    assert 'document.querySelector("#overlay .tbody")' in function_body("threadScroller")
    body = function_body("render")
    assert "ty: tb ? tb.scrollTop : 0, tbottom: atThreadBottom(tb)" in body
    assert (
        "tb2.scrollTop = (panelKey === UI.lastPanelKey && !keep.tbottom)"
        " ? keep.ty : tb2.scrollHeight;" in body
    )
    # The popped-out thread is the same pane in another window, redrawn by its
    # own loop -- so the rule is written into that loop too, or it holds in one
    # window and not the other.
    popped = function_body("popOut")
    assert "var bot=!tb||tb.scrollHeight-tb.scrollTop-tb.clientHeight<=40;" in popped
    assert "if(tb2)tb2.scrollTop=bot?tb2.scrollHeight:ty;" in popped


def test_the_decision_column_names_itself_and_says_nothing_further() -> None:
    """The ordering caption is gone.

    It described an implementation property nobody reading the board can act
    on, sitting next to the one word that says what the panel is.
    """
    column = function_body("renderColumn")
    assert "tree order" not in column and "re-sorts" not in column
    assert '<div class="card"><h3>Decisions</h3>' in column


# ----------------------------------------------------------------- GUI-A57
# The header, and the thread that is about the board rather than about the plan.


MARKUP_TITLE = "Store <img src=x onerror=\"document.title='markup ran'\"> design"
REFERENCE = "Answering a decision opens whatever waited on it. Park a thread to set it aside."
HELP_THREAD = "t-help"


def _opened(log: Any, **overrides: Any) -> dict[str, Any]:
    """A session's opening entry, as the backend appends it from a briefing.

    Appended by the backend rather than posted: starting a session is not a
    kind any client may send, so a briefing that arrived over the wire would
    never reach the log at all.
    """
    document: dict[str, Any] = handoff_doc(**overrides)
    log.record(SESSION_START_KIND, document)
    return document


def _opening(client: TestClient, epoch: str) -> dict[str, Any]:
    """The briefing as the page reads it: off the update read, from the start."""
    read = client.get("/updates", params={"epoch": epoch, "cursor": 0}).json()
    found = [one for one in read["entries"] if one["kind"] == SESSION_START_KIND]
    assert found, "the opening entry is not in what the page reads"
    payload: dict[str, Any] = found[0]["payload"]
    return payload


def _intro() -> str:
    """The header block the shell writes, out of the page's own source."""
    body = function_body("renderShell")
    assert '<div class="intro">' in body, "the shell writes no header"
    return body.split('<div class="intro">', 1)[1].split("banners", 1)[0]


def test_the_header_is_the_sessions_own_name_and_nothing_else() -> None:
    """
    Given the shell's header block
    When it is read out of the page's source
    Then it renders the session's title, escaped, and no prose beside it.

    The paragraph that used to sit here explained who owns the log and how to
    drive the board -- an explanation every human reads past on the way to the
    first decision, in the one place they look to learn what this session is.
    What it said is the help thread's to say, when asked.
    """
    intro = _intro()
    assert "esc(sessionTitle())" in intro, "the header does not name the session"
    assert "<p>" not in intro, "the header still carries a paragraph"
    assert "holds the log, assigns every sequence" not in page_source()
    assert "The backend owns this session" not in page_source()


def test_the_title_comes_from_the_briefing_the_backend_recorded() -> None:
    """
    Given the page's title reader
    When its source is read
    Then it takes the title off the log's opening entry, under the backend's
    own name for that entry, and falls back to a generic header without one.

    The title is not on image 1 and is not board state: it was said once, at
    the start, and the log is where the page already holds what was said. A
    board seeded straight into the log, or briefed with an empty title, opens
    under the generic header rather than under a blank one.
    """
    assert f'var SESSION_START_KIND = "{SESSION_START_KIND}";' in page_source()
    assert "SESSION_START_KIND" in function_body("briefing")
    named = function_body("sessionTitle")
    assert "briefing().session" in named
    assert '"Grilling session"' in named, "a briefing with no title leaves no header"


def test_a_title_the_briefing_wrote_reaches_the_page_unaltered(
    client: TestClient, log: Any
) -> None:
    """
    Given a briefing whose title carries markup
    When the page reads the log from the start
    Then the title arrives byte for byte, and the page's one sink for it
         escapes.

    The title is authored content: the backend records what it was given and
    does not sanitise it, so every guarantee about it reaching the human as
    words rather than as markup is the page's, at the sink. That the sink holds
    is measured in a browser.
    """
    _opened(log, session={**handoff_doc()["session"], "title": MARKUP_TITLE})

    carried = _opening(client, log.epoch)["session"]["title"]

    assert carried == MARKUP_TITLE
    assert "esc(sessionTitle())" in _intro()


def test_an_empty_title_leaves_the_generic_header(client: TestClient, log: Any) -> None:
    """
    Given a briefing carrying an empty title
    When the page reads it
    Then there is nothing to name the session with, and the page's fallback is
         what decides.

    A briefing written by hand is a whole briefing. The backend does not invent
    a title on the author's behalf, so an empty one reaches the page as empty
    and the header stays generic rather than blank.
    """
    _opened(log, session={**handoff_doc()["session"], "title": ""})

    assert _opening(client, log.epoch)["session"]["title"] == ""
    assert "named ? String(named)" in function_body("sessionTitle")


def test_the_help_control_is_offered_only_when_the_briefing_shipped_the_material(
    client: TestClient, log: Any
) -> None:
    """
    Given a briefing that ships reference material about the board, and one
    that does not
    When each is recorded
    Then the material rides in the opening entry under the field the page
         gates the control on, and is absent from the briefing that shipped
         none.

    The control promises an agent that knows this board. With nothing behind it
    the human would get the guesswork available anywhere else, dressed up as
    the one place that knows.
    """
    assert "help_reference" in Handoff.model_fields
    assert "briefing().help_reference" in function_body("helpOffered")
    assert "helpOffered()" in function_body("renderShell")

    _opened(log, help_reference=REFERENCE)

    assert _opening(client, log.epoch)["help_reference"] == REFERENCE
    assert "help_reference" not in handoff_doc(), "the plain briefing already ships material"


def test_the_help_control_opens_the_one_session_thread_and_creates_nothing() -> None:
    """
    Given the help control's handler
    When its source is read
    Then it opens a thread panel under the session's one name for that thread,
         and sends nothing.

    A control that opened the thread would spend an agent's turn on a click,
    and one that minted a fresh name each time would leave the human a new
    conversation every visit rather than the one they were already having.
    """
    body = function_body("openHelp")
    assert "HELP_THREAD" in body
    assert "send(" not in body, "opening help says something into the log"
    assert f'var HELP_THREAD = "{HELP_THREAD}";' in page_source()
    assert 'case "help": openHelp();' in page_source()


def test_a_thread_with_no_decision_anchor_is_an_ordinary_thread(
    client: TestClient, log: Any
) -> None:
    """
    Given the page's own thread-created shape carrying a null decision
    When it is posted and the board is read back
    Then the thread is on the board, anchored to nothing, and takes turns like
         any other.

    A null anchor is the whole of the extension the thread model needs for a
    session-scoped thread. Nothing else about a thread changes, which is why
    the help thread is an ordinary thread rather than a surface of its own.
    """
    assert 'title: help ? "How this board works"' in function_body("startThread")
    assert "decision: help ? null : id" in function_body("startThread")

    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            HELP_THREAD,
            turns=turns("How do I park a thread?"),
            decision=None,
            kind="help",
            title="How this board works",
            requires_action=False,
        ),
    )
    post(client, log.epoch, page_message("thread-turn", HELP_THREAD, turns=turns("And fold it?")))

    found = thread_of(client, HELP_THREAD)
    assert found["decision"] is None
    assert [one["text"] for one in found["turns"]] == ["How do I park a thread?", "And fold it?"]
    assert found["state"] == "open"


def test_the_session_thread_hangs_off_no_decision_on_the_board(
    client: TestClient, log: Any
) -> None:
    """
    Given a session-scoped thread and a decision's own thread
    When the page asks which threads sit on that decision
    Then only the anchored one does.

    The session thread is reachable from the header and from nowhere else. One
    that turned up on a decision's thread list would be the board offering a
    conversation about the tool as though it were about that question.
    """
    seed_node(client, log.epoch, "n1")
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            HELP_THREAD,
            turns=turns("How do I park a thread?"),
            decision=None,
            kind="help",
            title="How this board works",
            requires_action=False,
        ),
    )
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Why this one?"),
            decision="n1",
            kind="user",
            title="T",
            requires_action=False,
        ),
    )

    board = client.get("/state").json()["image1"]

    assert [one["id"] for one in board["threads"] if one["decision"] == "n1"] == [THREAD]
    assert "t.decision === id" in function_body("threadsOf")


# ---------------------------------------------------------------- GUI-A58


def test_a_finished_board_is_one_the_terminal_result_would_leave_nothing_open_on(
    client: TestClient, log: Any, session_dir: Path
) -> None:
    """
    Given a board carrying one settled decision and one invalidated one
    When the session is captured
    Then the invalidated decision is one of the result's open items.

    The page announces completion off its own reading of the board, and the one
    reading it is allowed is the one the write-up takes: settled, and nothing
    else. A page that counted an invalidated or a stale decision as finished
    would congratulate the human on a board whose own result lists work left to
    do -- so the page's test is pinned to the string, and the string's meaning
    is pinned to the backend here.
    """
    body = function_body("allSettled")
    assert 'd.status === "settled"' in body
    assert "BOARD.decisions.length > 0" in body, "an empty board would read as finished"

    seed_node(client, log.epoch, "n1")
    seed_node(client, log.epoch, "n2")
    post(
        client,
        log.epoch,
        page_message("answer", MAP_CHANNEL, target="n1", answer={"option": "a", "text": None}),
    )
    post(client, log.epoch, event("invalidate", key="kill", target="n2", why="the premise moved"))
    assert apply_all(client, log.epoch, "n2")["status"] == "accepted"
    post(client, log.epoch, page_message(SESSION_END_KIND, MAP_CHANNEL))

    board = client.get("/state").json()["image1"]["decisions"]
    assert sorted(one["status"] for one in board) == ["invalidated", "settled"]

    result = capture(session_dir)
    assert [one.id for one in result.open_items] == ["n2"]


def test_the_completion_overlay_announces_arriving_at_that_state_rather_than_sitting_in_it() -> (
    None
):
    """The re-fire rule, read off the page's own transition.

    An agent may put an open node on the board at any moment, and a board that
    leaves the finished state has nothing to announce. Arming on the crossing is
    what makes the overlay an announcement: it comes down when the board moves
    on, and it comes back only when the board arrives again -- rather than
    lingering over a question that has just been reopened, or re-firing on every
    poll tick that finds the same finished board.
    """
    body = function_body("noteCompletion")
    assert "var done = !sessionOver() && allSettled();" in body
    assert "if (done && !UI.wasDone) { UI.done = true; UI.pulse = false; }" in body
    assert "if (!done) { UI.done = false; UI.pulse = false; }" in body
    assert "UI.wasDone = done;" in body
    assert "noteCompletion();" in function_body("render")
    # Presentation, and page-local: nothing writes it anywhere a reload reads.
    assert "done: false, pulse: false, wasDone: false" in page_source()
    for name in ("UI.done", "UI.pulse", "UI.wasDone"):
        assert f'saveWindow("{name}' not in page_source()


def test_the_overlay_ends_the_session_through_the_control_it_is_offering() -> None:
    """One gesture into ending, reachable from two places.

    A second wire path would be a second set of semantics to keep in step -- and
    the one thing the page must never get wrong is ending a session twice, or
    ending one on terms the top row's control does not use. So the overlay's
    action is that control's own act, and the page has exactly one site that
    builds the ending event.
    """
    source = page_source()
    offer = function_body("completionOffer")
    assert 'data-act="endsession"' in offer, "the overlay does not offer the ending act"
    assert 'data-act="dismiss-completion"' in offer, "the overlay offers no way back"
    assert source.count(f'ev("{SESSION_END_KIND}"') == 1, "a second path builds the ending"
    assert 'case "endsession": endSession(); break;' in source
    # Dismissing writes nothing, so it is not one of the acts an ended board
    # seals -- and it leaves the offer on the control the human was pointed at.
    assert 'case "dismiss-completion": UI.done = false; UI.pulse = true; render();' in source
    assert '"dismiss-completion"' not in function_body("sealSurface")
    assert '(UI.pulse ? " pulsing" : "")' in function_body("renderShell")


def test_the_ending_tries_the_tab_and_says_so_when_the_tab_stays() -> None:
    """The fallback is the path most humans take.

    A browser refuses to close a tab the page did not open, and refuses it
    silently -- so the ended surface is not an edge case, it is the normal
    outcome, and it has to say the thing the human is now waiting to be told.
    The attempt hangs off the accepted receipt rather than off the click,
    because a tab closed before the POST left would end nothing at all.
    """
    sender = function_body("send")
    assert "ENDED = true;" in sender
    close = sender.split("ENDED = true;", 1)[1]
    assert "window.close();" in close, "the ending never tries the tab"
    assert page_source().count("window.close()") == 1, "a second path closes the tab"
    ended = page_source().split('banners += \'<div class="banner">🏁', 1)[1].split("}", 1)[0]
    assert "close this tab" in ended


def test_the_board_is_sized_by_the_window_rather_than_by_a_constant() -> None:
    """Two panes that fill the window they are in, on both axes.

    A pixel height is a guess about a window nobody has opened yet, and it is
    wrong in both directions: it scrolls the whole page on a laptop and wastes
    the bottom half of a tall monitor. The chain is what matters -- the shell
    takes the viewport's height, the surface takes what the header leaves, its
    single row is capped at that, and only the two scrolling panes absorb the
    rest -- so each link is pinned. Whether the panes then move with the window
    is the resize probe's answer; a stylesheet cannot give it.
    """
    source = page_source()
    assert "height: 100vh; height: 100dvh; display: flex; flex-direction: column; }" in source
    assert "grid-template-rows: minmax(0, 1fr);" in source
    assert "flex: 1 1 auto; min-height: 360px; }" in source
    assert "display: flex; flex-direction: column; min-height: 0; }" in source
    for pane in (".mapscroll { position: relative;", ".column { position: relative;"):
        assert f"{pane} flex: 1 1 auto; min-height: 0;" in source, f"{pane} is not window-sized"
    # The chrome around the panes keeps its own size, or it is what shrinks.
    for fixed in (".card > h3 { flex: none;", ".maplegend { flex: none;"):
        assert fixed in source, f"{fixed} does not hold its height"
    assert "640px" not in source, "a fixed pane height is back"


def test_a_decision_block_pins_its_own_header_until_the_block_ends() -> None:
    """The id and title stay in view while any of the decision is.

    An option list runs screens below the question it answers, and a human
    picking an answer down there has nothing on the page naming what they are
    answering. What pins is the block's own header rather than a second copy
    floating over the pane: a copy would cover the first option every time the
    block was read from its top, and it would need code to work out which
    decision it belonged to. Sticky needs three things the page has to keep --
    a scrolling ancestor for the pane, an opaque background under the header,
    and a header whose own box ends where the block does, which is what makes
    it release rather than hand over to a rule. A collapsed block opts out: a
    settled decision has nothing under its header to read.

    Where the pinned header actually lands is the browser probe's answer.
    """
    source = page_source()
    assert ".column { position: relative;" in source, "the pane is not the scrolling ancestor"
    sticky = source.split(".item .head {", 1)[1].split("}", 1)[0]
    assert "position: sticky" in sticky, f"the header is not pinned: {sticky!r}"
    assert "top: 0" in sticky, f"the header pins to nothing: {sticky!r}"
    assert "background: var(--paper)" in sticky, "the pinned header is see-through"
    assert ".item.focused .head { background: var(--accent-soft); }" in source, (
        "a focused block's pinned header shows the wrong colour"
    )
    assert ".item.collapsed .head { position: static; }" in source, "a collapsed block still pins"


# ------------------------------------------------------ GUI-A67, GUI-A68


def test_the_key_an_armed_answer_names_its_thread_by_is_the_backends_own() -> None:
    """One spelling, in the table the page sends by and in the constant it
    writes with.

    Payload content like the tier keys beside it, so nothing validates it in
    passing: a stale spelling settles the decision and silently leaves the
    thread it came from open, which is the one thing the provenance exists to
    prevent.
    """
    assert page_constants()["FROM_THREAD_KEY"] == FROM_THREAD_KEY
    assert FROM_THREAD_KEY in emissions()["answer"]["payload"], (
        "the page's own table refuses the key its answers carry"
    )


def test_an_answer_armed_from_a_thread_is_one_entry_that_settles_and_closes(
    client: TestClient, log: Any
) -> None:
    """The page's own shape, on the wire, against the real backend.

    Measured on the log's length as well as on the board: settling the decision
    and closing its thread is one entry, and a page that sent a second gesture
    to close the thread would leave the human looking at a settled decision
    whose thread asks to be closed again.
    """
    node = seed_node(client, log.epoch)
    post(
        client,
        log.epoch,
        page_message(
            "thread-created",
            THREAD,
            turns=turns("Does (a) really cover the migration?"),
            decision=node,
            kind="user",
            title="On the storage layer",
            requires_action=False,
        ),
    )
    before = len(log_lines(log.directory))

    receipt = post(
        client,
        log.epoch,
        page_message(
            "answer",
            MAP_CHANNEL,
            target=node,
            answer={"option": "a", "text": "Only once the migration is written down."},
            from_thread=THREAD,
        ),
    )[0]
    assert receipt["status"] == "accepted", receipt

    assert len(log_lines(log.directory)) == before + 1, "the answer was not one entry"
    board = client.get("/state").json()["image1"]
    settled = next(one for one in board["decisions"] if one["id"] == node)
    assert settled["status"] == "settled", settled
    assert thread_of(client, THREAD)["state"] == "closed"


def test_only_the_live_offer_carries_a_control() -> None:
    """Which offer is live is position, and the control is the whole difference.

    A retired proposal still renders -- it is a thing the agent put to the human
    -- so the liveness rule cannot be "render it or do not". It has to be the
    control, on the most recent turn of an open thread and on nothing else: a
    parked or closed thread hides it while the offer stays live in the log, and
    reopening the thread shows it again.
    """
    body = balanced_body("renderTurns")
    assert 'var h = "", last = t.turns.length - 1;' in body
    assert 'offerBlock(t, turn.proposal, i === last && t.state === "open")' in body, (
        "the control is not held to the last turn of an open thread"
    )
    offer = balanced_body("offerBlock")
    assert 'live ? armControl(t, offer) : ""' in offer, "a retired offer carries a control"
    assert page_source().count('data-act="arm"') == 1, "the arming control has a second author"
    assert 'data-act="arm"' in balanced_body("armControl")


def test_taking_an_offer_appends_nothing_and_writes_after_the_humans_own_words() -> None:
    """Arming fills the answer controls and touches the log with nothing.

    Both halves matter. An arming that appended would put an answer on the board
    the human has not read, and on a settled decision it would overwrite their
    own on one click. An arming that replaced the draft would discard what the
    human was in the middle of writing in favour of an agent's sentence.
    """
    arming = balanced_body("armAnswer")
    assert not reaches_send(arming), "arming puts something on the wire"
    assert "arm" not in acts_that_write()
    assert 'UI.drafts[id] = draft ? draft + "\\n\\n" + offer.text : offer.text;' in arming, (
        "the offer is not written after what the human already had"
    )
    assert "UI.armed[id] = { thread: tid, option: offer.option || null };" in arming
    # The live offer and no other, even from a window drawn before the last turn
    # arrived: a control the human can still see is not a proposal still on offer.
    assert "t.turns[t.turns.length - 1]" in arming
    assert 'offer.decision !== id || t.state !== "open"' in arming


def test_the_arming_rides_the_next_answer_and_goes_with_the_draft() -> None:
    """Provenance belongs to the answer the human gives next on that decision,
    and to no later one -- so it is cleared where the draft it filled is."""
    answering = balanced_body("answerDecision")
    assert "if (armed) out[FROM_THREAD_KEY] = armed.thread;" in answering
    assert 'UI.drafts[id] = "";\n  delete UI.armed[id];' in answering, (
        "the arming outlives the draft it filled"
    )
    # The option the offer built on is marked as the control that would record
    # it -- marked, not pressed: the answer is still the human's to give.
    assert 'if (armed && armed.option === o.id) cls += " armed";' in balanced_body("optionButton")
    assert ".btn.armed { box-shadow:" in page_source()


def test_a_decision_the_board_will_not_take_an_answer_on_names_what_holds_it() -> None:
    """Inert, and saying why. Arming a box the board will not accept from does
    nothing the human can act on, and a control that looked live would read as a
    press that did nothing.

    Settled is the one state that is not a block: the proposal replaces the
    answer, which is what revisiting a decision does, so the control says that
    rather than refusing.
    """
    block = balanced_body("armBlock")
    for held in (
        "a change is waiting on it",
        "a thread must conclude first",
        "its mandated thread has to conclude first",
        "it is in the fog until",
        "it has left the flow",
        "it is waiting on ",
    ):
        assert held in block, f"no hold reads as {held!r}"
    assert 'if (d.status === "settled") return null;' in block
    control = balanced_body("armControl")
    assert "Cannot take this — " in control
    assert "replaces your answer to" in control
    assert '(block ? " disabled" : "")' in control, "a blocked control is still pressable"
    # Only the armed decision reopens, and only while the arming stands.
    assert 'answerable(id) || !!(UI.armed[id] && d && d.status === "settled")' in balanced_body(
        "takesAnswer"
    )


def test_emptying_an_armed_draft_discards_its_provenance() -> None:
    """GUI-D33: the thread id rides the draft the proposal filled and is
    discarded with it -- a box the human empties by hand carries no proposal,
    so the next answer for that decision must not name the thread."""
    source = page_source()
    handler = source.split('document.addEventListener("input"', 1)[1].split("});", 1)[0]
    assert "delete UI.armed[id]" in handler, "an emptied draft keeps its provenance"
    assert "!e.target.value.trim()" in handler, "provenance is dropped on every keystroke"


@pytest.mark.parametrize(
    "shell",
    ["<style></style><script>//__SCRIPT__</script>", "/*__STYLE__*/ /*__STYLE__*/ //__SCRIPT__"],
)
def test_a_shell_without_exactly_one_of_each_token_is_refused(shell: str) -> None:
    """A token missing or doubled would serve a page without its style or its
    script and nothing downstream would notice; assembly refuses it by name."""
    with pytest.raises(ValueError, match="__STYLE__"):
        assemble_page(shell, PAGE_DIR)
