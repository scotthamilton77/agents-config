"""`work list` against a real backend: a default listing hides nothing.

Only a real backend shows this. A scripted runner replays the rows it was
scripted with, so it cannot drop a closed one -- which is how the narrow
default survived so long: every hermetic test agreed with the facade's own
model of the answer while the backend applied a filter nobody had asked for.

One install, three listings: the default, one narrowed by status, and one
narrowed on another axis. The contrast is the point -- what a caller can
tell apart is a listing they narrowed from one that was narrowed for them.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

_MARK = "ls-marked"


def _create(driver: Callable[[Sequence[str]], dict], title: str, *label: str) -> str:
    argv = ["create", "--raw", "--title", title, "--type", "task", "--priority", "2"]
    for name in label:
        argv += ["--label", name]
    created = driver(argv)
    assert created["ok"] is True, created
    return created["data"]["id"]


def _ids(envelope: dict) -> set[str]:
    assert envelope["ok"] is True, envelope
    return {item["id"] for item in envelope["data"]["items"]}


def test_a_default_listing_carries_closed_work_and_a_narrowed_one_carries_what_was_asked(
    driver,
):
    open_id = _create(driver, "ls-still-open")
    closed_id = _create(driver, "ls-already-finished", _MARK)
    assert driver(["close", closed_id])["ok"] is True

    everything = driver(["list"])
    by_status = driver(["list", "--status", "open"])
    by_label = driver(["list", "--label", _MARK])

    # A fresh install holds exactly these two items, so this is the whole
    # database and not merely a superset check.
    assert _ids(everything) == {open_id, closed_id}
    closed = next(i for i in everything["data"]["items"] if i["id"] == closed_id)
    assert closed["status"] == "closed"
    # The only narrowing in a listing is the one the caller typed...
    assert _ids(by_status) == {open_id}
    # ...and narrowing on one axis does not quietly re-apply a status filter
    # on another: this item matches the label and is closed.
    assert _ids(by_label) == {closed_id}
