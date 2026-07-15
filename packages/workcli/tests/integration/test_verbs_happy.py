"""Every verb once against real bd, asserting VALUE-LEVEL, not just ok=True.

Read verbs use the shared read_only corpus; mutating verbs use a fresh install."""

from __future__ import annotations

# ---- read verbs (shared corpus) ----

# NOTE (envelope shape, verified against verbs/read.py): a SINGLE-id `show`
# returns the item object DIRECTLY as `data` (not wrapped in {"items":[...]});
# only a 2+-id `show`, and every `list`/`ready`/`search`, wraps as
# `{"items": [...]}`. `label list` returns a BARE string[] as `data`.
# `Item.priority` is a STRING ("P0".."P4"), `Item.type` (not "issue_type").


def test_show_returns_exact_seeded_fields(read_only_driver):
    listing = read_only_driver(["list"])
    alpha_id = next(i["id"] for i in listing["data"]["items"] if i["title"] == "seed-alpha")
    env = read_only_driver(["show", alpha_id])
    assert env["ok"] is True
    item = env["data"]  # single-id show → item object directly
    assert item["id"] == alpha_id
    assert item["title"] == "seed-alpha"
    assert item["status"] == "open"
    assert item["priority"] == "P2"  # priority is a string, not int
    assert "seed" in item["labels"]  # value-level: label round-trips


def test_list_filter_by_label(read_only_driver):
    env = read_only_driver(["list", "--label", "seed"])
    assert env["ok"] is True
    assert {i["title"] for i in env["data"]["items"]} == {"seed-alpha"}


def test_show_child_reports_seeded_parent(read_only_driver):
    listing = read_only_driver(["list"])
    child_id = next(i["id"] for i in listing["data"]["items"] if i["title"] == "seed-child")
    item = read_only_driver(["show", child_id])["data"]  # single-id show → item directly
    assert item["parent"] is not None  # value-level: parent edge survives


def test_ready_lists_unblocked(read_only_driver):
    env = read_only_driver(["ready"])
    assert env["ok"] is True
    assert isinstance(env["data"]["items"], list)


def test_search_finds_seeded(read_only_driver):
    env = read_only_driver(["search", "seed-beta"])
    assert env["ok"] is True
    assert any(i["title"] == "seed-beta" for i in env["data"]["items"])


# ---- write/relation/transition verbs (fresh install) ----


def test_create_raw_update_note_close_reopen_roundtrip(driver):
    created = driver(["create", "--raw", "--title", "wv-one", "--type", "task", "--priority", "2"])
    assert created["ok"] is True
    item_id = created["data"]["id"]  # create → {"id": ...}

    driver(["update", item_id, "--set-title", "wv-one-renamed"])
    assert driver(["show", item_id])["data"]["title"] == "wv-one-renamed"  # value-level

    driver(["note", item_id, "a durable note"])
    assert "a durable note" in driver(["show", item_id])["data"]["notes"]

    assert driver(["close", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "closed"

    assert driver(["reopen", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "open"


def test_label_add_list_remove(driver):
    item_id = driver(["create", "--raw", "--title", "wv-lbl", "--type", "task", "--priority", "2"])[
        "data"
    ]["id"]
    driver(["label", "add", item_id, "alpha", "beta"])
    labels = driver(["label", "list", item_id])["data"]  # label list → bare string[]
    assert {"alpha", "beta"} <= set(labels)
    driver(["label", "remove", item_id, "alpha"])
    assert "alpha" not in driver(["label", "list", item_id])["data"]


def test_dep_add_list_remove(driver):
    a = driver(["create", "--raw", "--title", "wv-dep-a", "--type", "task", "--priority", "2"])[
        "data"
    ]["id"]
    b = driver(["create", "--raw", "--title", "wv-dep-b", "--type", "task", "--priority", "2"])[
        "data"
    ]["id"]
    driver(["dep", "add", a, b, "--type", "blocks"])
    listing = driver(["dep", "list", a])
    assert listing["ok"] is True
    driver(["dep", "remove", a, b])


def test_claim_and_release(driver):
    item_id = driver(
        ["create", "--raw", "--title", "wv-claim", "--type", "task", "--priority", "2"]
    )["data"]["id"]
    assert driver(["claim", item_id])["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "in_progress"
    assert driver(["release", item_id])["ok"] is True
