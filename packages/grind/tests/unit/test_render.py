"""`grind.render`: `State -> dashboard.html` -- PR-link derivation order,
unknown-status degradation, empty-state edges, and the pure-function
(determinism) guarantee. The CI smoke test over a rich fixture lives in
`test_render_dashboard_smoke.py`."""

from __future__ import annotations

from typing import cast

from grind.fold import fold
from grind.model import Item, ItemStatus, Lane, PrRef, State
from grind.render import render_dashboard

from .builders import event, seed_event


def _state_with_item(item: Item) -> State:
    """A minimally-seeded `State` with `item` filed under one lane -- the
    renderer only projects items reachable via `lane.item_ids` (mirroring the
    fold), so a bare `state.items[...]` assignment with no lane membership
    would silently never appear on the board."""
    state = State(seeded=True, title="t", repo="acme/widgets")
    state.lanes["lane-a"] = Lane(id="lane-a", name="Lane A", item_ids=[item.id])
    state.items[item.id] = item
    return state


def _state_json_blob(html: str) -> str:
    """The literal JSON payload text between `var STATE = ` and the next
    statement -- the exact substring the serialization contract governs."""
    start = html.index("var STATE = ") + len("var STATE = ")
    end = html.index(";\n\nvar KNOWN_STATUSES", start)
    return html[start:end]


# -- determinism ---------------------------------------------------------


def test_render_is_a_pure_function_of_state():
    events = [seed_event(), event("item_started", item="wgclw.1")]

    html_a = render_dashboard(fold(events))
    html_b = render_dashboard(fold(events))

    assert html_a == html_b


# -- PR-link derivation order ---------------------------------------------


def _item_with_pr(pr: PrRef | None) -> Item:
    return Item(id="wgclw.1", lane="lane-a", title="Item", status="pr-open", pr=pr)


def test_pr_link_prefers_explicit_url_over_repo_derivation():
    item = _item_with_pr(PrRef(number=7, url="https://example.com/pr/7"))
    html = render_dashboard(_state_with_item(item))

    blob = _state_json_blob(html)
    assert '"url": "https://example.com/pr/7"' in blob
    assert '"number": 7' in blob


def test_pr_link_falls_back_to_repo_slug_when_no_explicit_url():
    item = _item_with_pr(PrRef(number=9, url=None))
    html = render_dashboard(_state_with_item(item))

    blob = _state_json_blob(html)
    assert '"url": null' in blob
    assert '"number": 9' in blob
    # The renderer emits the raw PR fields; repo-slug derivation is a
    # client-side concern (`prUrl` in the inlined script) -- assert the
    # function that performs it ships in the page.
    assert "function prUrl(pr, repo)" in html
    assert 'repo) return "https://github.com/" + repo + "/pull/" + pr.number;' in html


def test_pr_absent_when_item_has_no_pr():
    item = _item_with_pr(None)
    html = render_dashboard(_state_with_item(item))

    blob = _state_json_blob(html)
    assert '"pr": null' in blob


# -- unknown-status degradation --------------------------------------------


def test_unknown_item_status_passes_through_without_raising():
    item = Item(
        id="wgclw.1",
        lane="lane-a",
        title="Weird",
        status=cast("ItemStatus", "totally-unrecognized"),
    )
    state = _state_with_item(item)

    html = render_dashboard(state)  # must not raise

    blob = _state_json_blob(html)
    assert "totally-unrecognized" in blob
    # The client-side fallback path exists so an unrecognized value still
    # renders neutrally rather than breaking the board.
    assert "st-unknown" in html
    assert "ICONS.unknown" in html


# -- empty-state edges ------------------------------------------------------


def test_renders_with_no_lanes_no_attention_no_lessons():
    state = State(seeded=True, title="Empty grind", repo="acme/widgets")

    html = render_dashboard(state)

    blob = _state_json_blob(html)
    assert '"lanes": []' in blob
    assert '"attention": []' in blob
    assert '"lessons": []' in blob
    assert '"parking_lot": []' in blob


def test_review_omitted_when_item_has_never_been_reviewed():
    item = Item(id="wgclw.1", lane="lane-a", title="Fresh", status="queued")
    html = render_dashboard(_state_with_item(item))

    blob = _state_json_blob(html)
    assert '"review": null' in blob
