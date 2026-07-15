"""Guarded lifecycle transitions on real bd state (happy path — no faults)."""

from __future__ import annotations


def test_create_claim_deliver_trivial_then_reconcile_noop(driver):
    # `create feat` mints a shape-feat leaf (not a container); claimable once ready.
    # `--orphan` is required alongside `--parent` (create.py: exactly one of the two).
    item_id = driver(["create", "feat", "--title", "lc-leaf", "--priority", "2", "--orphan"])[
        "data"
    ]["id"]
    assert driver(["claim", item_id])["ok"] is True
    # A leaf delivery with trivial evidence closes it.
    delivered = driver(["deliver", item_id, "--trivial"])
    assert delivered["ok"] is True
    assert driver(["show", item_id])["data"]["status"] == "closed"  # single-id show
    # reconcile with nothing recoverable is a clean no-op.
    swept = driver(["reconcile"])
    assert swept["ok"] is True


def test_plan_add_then_done(driver):
    # `plan` requires exactly one of --done/--undo on every call
    # (transitions.py::plan: `args.done == args.undo` raises E_USAGE) -- there is
    # no separate "add to queue" step distinct from --done. An epic IS a container
    # (nouns.py: is_container=True), so --done needs no --force (plan's guard:
    # `not is_container(item) and not args.force`).
    item_id = driver(["create", "epic", "--title", "lc-epic", "--priority", "2", "--orphan"])[
        "data"
    ]["id"]
    added = driver(["plan", item_id, "--done"])
    assert added["ok"] is True
    assert added["data"]["planned"] is True
    assert "planned" in driver(["show", item_id])["data"]["labels"]
    # Idempotent replay: PLANNED_LABEL already present short-circuits to the
    # same result rather than erroring or double-adding the label.
    replayed = driver(["plan", item_id, "--done"])
    assert replayed["ok"] is True
    assert replayed["data"]["planned"] is True


def test_promote_leaf_to_spec_container(driver):
    # promote requires a shape-feat leaf (transitions.py::promote); `create feat`
    # provides exactly that. Result: the leaf becomes a shape-spec container.
    leaf = driver(["create", "feat", "--title", "lc-promote", "--priority", "2", "--orphan"])[
        "data"
    ]["id"]
    promoted = driver(["promote", leaf])
    assert promoted["ok"] is True
    assert promoted["data"]["promoted"] == "spec"
    assert "shape-spec" in driver(["show", leaf])["data"]["labels"]  # single-id show
