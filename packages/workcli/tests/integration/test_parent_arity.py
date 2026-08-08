"""Parent arity and dep-type validation, against a real bd.

This is the suite that matters for these two defects, because both are about
what bd itself does with the calls the facade makes -- neither is visible
against a fake that models an item's parent as one field and therefore cannot
represent the corrupt state at all.

Every assertion here reads BOTH descriptions of an item's place in the tree
and requires them to agree: the `parent` scalar (bd's own field) and the
`parent-child` edges from `dep list` (derived from edge rows). The defect was
precisely that those two can disagree, so checking either alone proves nothing.
"""

from __future__ import annotations


def _mk(driver, title: str, item_type: str = "task") -> str:
    return driver(["create", "--raw", "--title", title, "--type", item_type, "--priority", "2"])[
        "data"
    ]["id"]


def _parent_edges(driver, item_id: str) -> list[str]:
    """The ids this item points at with a `parent-child` edge, from `dep list`."""
    listing = driver(["dep", "list", item_id])
    return [e["id"] for e in listing["data"]["depends_on"] if e["type"] == "parent-child"]


def _children_edges(driver, item_id: str) -> list[str]:
    """The ids pointing AT this item with a `parent-child` edge (the reverse side)."""
    listing = driver(["dep", "list", item_id])
    return [e["id"] for e in listing["data"]["dependents"] if e["type"] == "parent-child"]


def _assert_parent_is(driver, item_id: str, expected: str) -> None:
    """The scalar and the edges must agree, and there must be exactly one edge."""
    assert driver(["show", item_id])["data"]["items"][0]["parent"] == expected
    assert _parent_edges(driver, item_id) == [expected]


def test_dep_add_second_parent_is_refused_and_leaves_the_tree_untouched(driver):
    old_parent = _mk(driver, "pa-old", "epic")
    new_parent = _mk(driver, "pa-new", "epic")
    child = _mk(driver, "pa-child")
    driver(["dep", "add", child, old_parent, "--type", "parent-child"])
    _assert_parent_is(driver, child, old_parent)

    env = driver(["dep", "add", child, new_parent, "--type", "parent-child"])

    assert env["ok"] is False
    assert env["error"]["code"] == "E_FIELD_CLOBBER_GUARD"
    assert old_parent in env["error"]["message"]
    assert "--set-parent" in env["error"]["message"]
    # Nothing moved and nothing was added: this is the state the unguarded
    # code left holding TWO parent-child edges against one scalar.
    _assert_parent_is(driver, child, old_parent)
    assert _children_edges(driver, new_parent) == []


def test_dep_add_first_parent_leaves_the_scalar_and_the_edges_agreeing(driver):
    parent = _mk(driver, "pa-first-parent", "epic")
    child = _mk(driver, "pa-first-child")

    assert driver(["dep", "add", child, parent, "--type", "parent-child"])["ok"] is True

    _assert_parent_is(driver, child, parent)
    assert _children_edges(driver, parent) == [child]


def test_re_adding_the_parent_an_item_already_has_succeeds_and_adds_no_second_edge(driver):
    parent = _mk(driver, "pa-idem-parent", "epic")
    child = _mk(driver, "pa-idem-child")
    driver(["dep", "add", child, parent, "--type", "parent-child"])

    env = driver(["dep", "add", child, parent, "--type", "parent-child"])

    assert env["ok"] is True
    _assert_parent_is(driver, child, parent)


def test_set_parent_moves_the_item_and_the_old_parent_child_edge_is_gone(driver):
    old_parent = _mk(driver, "sp-old", "epic")
    new_parent = _mk(driver, "sp-new", "epic")
    child = _mk(driver, "sp-child")
    driver(["dep", "add", child, old_parent, "--type", "parent-child"])
    _assert_parent_is(driver, child, old_parent)

    env = driver(["update", child, "--set-parent", new_parent])

    assert env["ok"] is True
    # The whole point of routing the move through bd's own `--parent`: the old
    # edge is REPLACED. Asserting the scalar alone would pass even if the old
    # edge survived, which is the exact failure being ruled out.
    _assert_parent_is(driver, child, new_parent)
    assert _children_edges(driver, old_parent) == []
    assert _children_edges(driver, new_parent) == [child]


def test_set_parent_to_a_missing_item_reports_not_found_and_changes_nothing(driver):
    parent = _mk(driver, "sp-missing-parent", "epic")
    child = _mk(driver, "sp-missing-child")
    driver(["dep", "add", child, parent, "--type", "parent-child"])

    env = driver(["update", child, "--set-parent", "itest-nosuchid"])

    assert env["ok"] is False
    # bd's reparent path words this differently from every other command; the
    # facade must still call it what it is rather than E_BACKEND_DRIFT.
    assert env["error"]["code"] == "E_NOT_FOUND"
    _assert_parent_is(driver, child, parent)


def test_an_unrecognized_dep_type_writes_no_edge_at_all(driver):
    source = _mk(driver, "dt-source")
    target = _mk(driver, "dt-target")

    env = driver(["dep", "add", source, target, "--type", "bogus-type-probe"])

    assert env["ok"] is False
    assert env["error"]["code"] == "E_USAGE"
    # Measured on the unguarded code, this stored a real edge typed
    # `bogus-type-probe`. bd validates nothing here; the facade is the only
    # layer that can refuse it.
    assert driver(["dep", "list", source])["data"]["depends_on"] == []


def test_every_type_in_the_closed_set_is_one_bd_accepts(driver):
    # The set is transcribed from bd's own `dep add --help`. If bd's vocabulary
    # drifts, this fails against the real binary rather than silently letting
    # the facade advertise a type bd no longer honours.
    from workcli.verbs.relations import DEP_TYPES

    target = _mk(driver, "cs-target")
    for index, dep_type in enumerate(sorted(DEP_TYPES)):
        source = _mk(driver, f"cs-source-{index}", "epic" if dep_type == "blocks" else "task")
        if dep_type == "blocks":
            # The blocks wall needs both ends the same class; use two epics.
            target_for_type = _mk(driver, f"cs-target-epic-{index}", "epic")
        else:
            target_for_type = target

        env = driver(["dep", "add", source, target_for_type, "--type", dep_type])

        assert env["ok"] is True, f"{dep_type} rejected: {env['error']}"
        stored = [e["type"] for e in driver(["dep", "list", source])["data"]["depends_on"]]
        assert stored == [dep_type], f"{dep_type} stored as {stored}"
