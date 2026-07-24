"""CI smoke test for `grind render` (renderer spec, "Testing"): a State built
from a rich event log exercising every status, every park reason, an active
review, a stalemate, and a paused grind -- the same scenario shape as
`docs/prototypes/grind-dashboard/fixture-state.json`, adapted into a real
folded `State` rather than a hand-authored display blob (the renderer's only
legal input, per its contract, is `State`; it never reads `events.jsonl` or a
display-shaped fixture directly).

Asserts (per spec): byte-stable output across two folds of the same log, no
unescaped `<` inside the inlined state block, and every status icon / park
chip / required panel is present -- string/DOM-level, not a screenshot.
"""

from __future__ import annotations

from grind.fold import fold
from grind.model import PARK_REASONS, JsonValue, RawEvent
from grind.render import render_dashboard

_SCRIPT_PROBE_TITLE = 'Serializer probe: "</script>" must render as inert text, never execute'
_LONG_TITLE = "A very long work-item title that keeps going " * 4  # >100 chars, exercises overflow

_SEED: RawEvent = {
    "title": "Discipline-Layer Grind — smoke",
    "repo": "acme/widgets",
    "mission": {"goal": "Ship the grind dashboard", "out_of_scope": "Nothing else this round"},
    "protocols": {},
    "lanes": [
        {
            "id": "lane-flow",
            "name": "Lane One — mainline flow",
            "agent": "lt-one",
            "model": "opus",
            "effort": "high",
            "queue": [
                {"id": "item-queued", "title": "Queued item"},
                {"id": "item-inprogress", "title": "In progress item"},
                {"id": "item-pr-open", "title": "PR open item"},
                {"id": "item-in-review", "title": "In review item"},
                {"id": "item-merged", "title": "Merged item"},
                {"id": "item-done", "title": "Done item"},
            ],
        },
        {
            "id": "lane-blockers",
            "name": "Lane Two — blockers & human gates",
            "agent": "lt-two",
            "model": "sonnet",
            "effort": "medium",
            "queue": [
                {"id": "item-blocked", "title": "Blocked item", "on": ["item-queued"]},
                {"id": "item-waiting", "title": "Waiting on human item"},
                {"id": "item-stalemate", "title": "Stalemate item"},
            ],
        },
        {
            "id": "lane-parking-source",
            "name": "Lane Three — parking source",
            "agent": "lt-three",
            "queue": [
                {"id": "park-ci-failure", "title": "CI-failure candidate"},
                {"id": "park-merge-conflict", "title": "Merge-conflict candidate"},
                {"id": "park-approval", "title": "Approval-required candidate"},
                {"id": "park-bot-declined", "title": "Bot-declined candidate"},
                {"id": "park-budget", "title": "Budget-exhausted candidate"},
                {"id": "park-discovered", "title": "Discovered work candidate"},
                {"id": "park-later", "title": "Later-wave candidate"},
                {"id": "park-deferred", "title": "Deferred candidate"},
                {"id": "park-untyped", "title": "Untyped park candidate"},
            ],
        },
        {"id": "lane-standing-down", "name": "Lane Four — standing down", "agent": "lt-four"},
        {"id": "lane-idle", "name": "Lane Five — idle", "agent": "lt-five"},
        {
            "id": "lane-edges",
            "name": "Lane Six — edge-case titles",
            "agent": "lt-six",
            "queue": [
                {"id": "item-long-title", "title": _LONG_TITLE},
                {"id": "item-script-probe", "title": _SCRIPT_PROBE_TITLE},
            ],
        },
    ],
}


def _events() -> list[RawEvent]:
    def e(evt_type: str, **fields: JsonValue) -> RawEvent:
        return {"ts": "2026-07-19T00:00:00Z", "type": evt_type, **fields}

    return [
        {"ts": "2026-07-19T00:00:00Z", "type": "grind_created", **_SEED},
        e("item_started", item="item-inprogress"),
        e("item_started", item="item-pr-open"),
        e("pr_opened", item="item-pr-open", pr=101),
        e("item_started", item="item-in-review"),
        e("pr_opened", item="item-in-review", pr=102),
        e(
            "review_verdict",
            item="item-in-review",
            kind="codex",
            round=2,
            head_sha="abc123",
            verdict="findings",
            detail="round 2: one deferred, one wont-fix",
            findings=[
                {"severity": "medium", "summary": "needs a follow-up", "disposition": "deferred"},
                {"severity": "low", "summary": "tolerated by design", "disposition": "wont-fix"},
            ],
        ),
        e("item_started", item="item-merged"),
        e("pr_opened", item="item-merged", pr=103),
        e("item_merged", item="item-merged", pr=103, sha="deadbeef"),
        e("item_started", item="item-done"),
        e("pr_opened", item="item-done", pr=104),
        e("item_merged", item="item-done", pr=104, sha="cafebabe"),
        e("item_done", item="item-done"),
        e("item_blocked", item="item-blocked", on=["item-queued"], note="waiting on item-queued"),
        e("item_started", item="item-waiting"),
        e("item_waiting_human", item="item-waiting", why="need a merge ruling"),
        e("item_started", item="item-stalemate"),
        e("pr_opened", item="item-stalemate", pr=105),
        e(
            "review_verdict",
            item="item-stalemate",
            kind="codex",
            round=4,
            head_sha="xyz789",
            verdict="stalemate",
            detail="round 4 re-raised on an unchanged head",
        ),
        e("lane_standing_down", lane="lane-standing-down"),
        e("item_parked", item="park-ci-failure", reason="ci-failure", note="CI red after 2 fixes"),
        e("item_parked", item="park-merge-conflict", reason="merge-conflict", note="rebase failed"),
        e("item_parked", item="park-approval", reason="approval-required", note="ruleset gate"),
        e("item_parked", item="park-bot-declined", reason="bot-declined", note="reviewer declined"),
        e("item_parked", item="park-budget", reason="budget-exhausted", note="attempts spent"),
        e(
            "item_parked",
            item="park-discovered",
            reason="discovered-work",
            note="surfaced during review",
        ),
        e("item_parked", item="park-later", reason="later-wave", note="wave 2"),
        e("item_parked", item="park-deferred", reason="deferred", note="revisit later"),
        # The untyped park: `pr_closed`'s `next: parked` path carries no reason
        # field, so it renders the unknown chip -- the fourth branch.
        e("item_started", item="park-untyped"),
        e("pr_opened", item="park-untyped", pr=106),
        e("pr_closed", item="park-untyped", pr=106, reason="superseded", next="parked"),
        e(
            "grind_paused",
            reason="Human decision needed before lanes resume",
            resume_checklist=["Pick a call", "grind log grind_resumed"],
        ),
        e("observation", level="INFO", message="informational note", item="item-inprogress"),
        e("observation", level="WARN", message="staleness warning", lane="lane-idle"),
        e("observation", level="ERROR", message="synthetic anomaly for the smoke test"),
        e("observation", level="LESSON", message="a lesson worth keeping", item="item-done"),
        e("attention_raised", text="General ops note not tied to any item"),
    ]


_ALL_ITEM_STATUSES = (
    "queued",
    "in-progress",
    "pr-open",
    "in-review",
    "merged",
    "done",
    "blocked",
    "waiting-human",
)
# Read off the vocabulary itself: a reason added to `PARK_REASONS` without a
# fixture park fails here rather than shipping unexercised through the renderer.
_ALL_PARK_REASONS = frozenset(PARK_REASONS)
# The renderer colours by axis + category, not per reason, so these four -- not
# the eight reasons -- are the branches its chip function can take.
_ALL_PARK_CHIP_CLASSES = ("park-machine", "park-human", "park-scheduling", "park-unknown")


def _state_json_blob(html: str) -> str:
    start = html.index("var STATE = ") + len("var STATE = ")
    end = html.index(";\n\nvar KNOWN_STATUSES", start)
    return html[start:end]


def test_fixture_state_is_a_valid_rich_scenario():
    """Sanity-check the fixture itself before trusting the renderer
    assertions below: every status/park reason this test claims to cover must
    actually be present in the folded state, and folding must not have
    silently anomalied any of the crafted events."""
    state = fold(_events())

    assert state.anomalies == []
    statuses = {item.status for item in state.items.values()}
    assert statuses == set(_ALL_ITEM_STATUSES)
    assert state.lanes["lane-standing-down"].standing_down is True
    parked = [item.parked for item in state.parking_lot().values() if item.parked]
    assert {p.reason for p in parked} == _ALL_PARK_REASONS | {None}
    assert {p.axis for p in parked} == {"failure", "scheduling", None}
    assert {p.category for p in parked} == {"machine", "human", None}
    assert state.items["item-stalemate"].review.stalemate is True
    assert state.paused is True


def test_render_is_byte_stable_across_two_folds_of_the_same_log():
    events = _events()

    html_a = render_dashboard(fold(events))
    html_b = render_dashboard(fold(events))

    assert html_a == html_b


def test_state_block_has_no_unescaped_angle_bracket():
    html = render_dashboard(fold(_events()))
    blob = _state_json_blob(html)

    assert "<" not in blob
    # The escape actually landed on the probe title, proving the round trip
    # (not merely that the title was absent from the payload). Only `<` is
    # escaped per the contract; the trailing `>` is untouched and harmless.
    assert "\\u003c/script>" in blob
    assert "</script>" not in blob


def test_renders_every_status_icon_and_park_chip():
    html = render_dashboard(fold(_events()))
    blob = _state_json_blob(html)

    for status in (*_ALL_ITEM_STATUSES, "standing-down"):
        assert f'"{status}"' in blob, f"status {status!r} missing from the state payload"
        assert f".st-{status}" in html, f"no status palette entry for {status!r}"
        assert f'"{status}":' in html, f"no ICONS entry for {status!r}"

    for reason in _ALL_PARK_REASONS:
        assert f'"{reason}"' in blob, f"park reason {reason!r} missing from the state payload"

    for chip_class in _ALL_PARK_CHIP_CLASSES:
        assert f".{chip_class} " in html, f"no chip CSS entry for {chip_class!r}"
        assert f'"{chip_class}"' in html, f"chip class {chip_class!r} unreachable in the renderer"


def test_renders_required_panels_and_no_merged_or_closed_panels():
    html = render_dashboard(fold(_events()))

    assert 'id="board"' in html
    assert 'id="obs-list"' in html and "Observations" in html
    assert 'id="parking-list"' in html and "Parking lot" in html
    assert 'id="lesson-list"' in html and "Lessons learned" in html
    assert 'id="attention-banner"' in html
    assert 'id="pause-banner"' in html
    assert 'id="mission"' in html

    # The event log is the ledger now -- no Merged/Closed panels (renderer
    # spec, UX #6).
    assert "merged_ledger" not in html
    assert "closed_ledger" not in html
    assert "Merged</h2>" not in html
    assert "Closed</h2>" not in html


def test_review_pill_data_present_for_open_threads_wontfix_and_stalemate():
    html = render_dashboard(fold(_events()))
    blob = _state_json_blob(html)

    assert '"open_threads": 1' in blob
    assert '"wont_fix_count": 1' in blob
    assert '"stalemate": true' in blob


def test_pause_and_mission_data_present():
    html = render_dashboard(fold(_events()))
    blob = _state_json_blob(html)

    assert '"paused": true' in blob
    assert "Human decision needed before lanes resume" in blob
    assert "Ship the grind dashboard" in blob


def test_at_least_six_lanes_present():
    html = render_dashboard(fold(_events()))
    blob = _state_json_blob(html)

    assert blob.count('"agent":') >= 6


def test_script_elements_survive_html_parsing_intact():
    # HTML terminates a <script> element at the FIRST literal "</script"
    # sequence, even inside a JS // comment -- parse the page the way a
    # browser does and assert the dashboard script still carries both the
    # state payload and the renderer code past every inline comment.
    from html.parser import HTMLParser

    html = render_dashboard(fold(_events()))

    class _ScriptCollector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._in_script = False
            self.scripts: list[str] = []

        def handle_starttag(self, tag: str, attrs: object) -> None:  # noqa: ARG002 -- HTMLParser API
            if tag == "script":
                self._in_script = True
                self.scripts.append("")

        def handle_endtag(self, tag: str) -> None:
            if tag == "script":
                self._in_script = False

        def handle_data(self, data: str) -> None:
            if self._in_script:
                self.scripts[-1] += data

    parser = _ScriptCollector()
    parser.feed(html)

    dashboard = [s for s in parser.scripts if "grind" in s or "STATE" in s]
    assert dashboard, "dashboard script parsed as empty -- early </script> termination"
    content = max(dashboard, key=len)
    assert "var STATE" in content or "STATE =" in content
    assert "function renderBoard" in content  # renderer code is INSIDE the script element
