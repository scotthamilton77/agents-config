"""`dep add`'s two pre-checks: the closed type vocabulary, and parent arity.

Both refuse before `dep_mutate` is reached, so a rejected call costs zero
mutating bd invocations -- the same property `test_dep_type_wall.py` holds for
the `blocks` wall, asserted the same way, off the fake's call log.

The parent-arity check is the one that matters most. bd accepts a second
`parent-child` edge silently, and the item is then described by two sources
that disagree: the `parent` scalar is bd's own field, `children` is derived
from reverse edges. A caller who runs the add and verifies with `show` reads
one parent and concludes nothing happened, while the tree still walks the item
from both parents.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode
from workcli.verbs.relations import DEP_TYPES

_OK = BdResult(returncode=0, stdout="", stderr="")

# The two types whose pre-check reads bd; every other type reaches
# `dep add` with no read at all.
_READS_BOTH_ENDS = "blocks"
_READS_THE_CHILD = "parent-child"


def _show_result(item_id: str, *, parent: str | None = None, issue_type: str = "task") -> BdResult:
    """A `bd show ID --json` response, with or without a parent."""
    payload = [
        {
            "id": item_id,
            "title": "t",
            "issue_type": issue_type,
            "status": "open",
            "priority": 2,
            "labels": [],
            "parent": parent,
            "dependencies": [],
            "dependents": [],
        }
    ]
    return BdResult(returncode=0, stdout=json.dumps(payload), stderr="")


# ---- parent arity ----


def test_dep_add_parent_child_onto_an_item_that_already_has_a_parent_never_mutates():
    # The reproduction: on the unguarded code this call succeeded silently and
    # left `child.1` carrying two parent-child edges against one parent scalar.
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("show", "child.1", "--json"), _show_result("child.1", parent="old.1"))]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "child.1", "new.1", "--type", "parent-child"], runner
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.FIELD_CLOBBER_GUARD)
    assert runner.calls == [("show", "child.1", "--json")]
    assert not any(call[:2] == ("dep", "add") for call in runner.calls)


def test_dep_add_parent_child_refusal_names_the_existing_parent_and_the_move_command():
    # The recovery has to be discoverable from the error itself: the previous
    # behaviour raised nothing at all, so nothing ever pointed at the fix.
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("show", "child.1", "--json"), _show_result("child.1", parent="old.1"))]
    )

    _, envelope, _ = run_cli_with_runner(
        ["dep", "add", "child.1", "new.1", "--type", "parent-child"], runner
    )

    error = envelope["error"]
    assert "old.1" in error["message"]
    assert "work update child.1 --set-parent new.1" in error["message"]
    assert error["detail"] == {
        "id": "child.1",
        "parent": "old.1",
        "requested_parent": "new.1",
    }


def test_dep_add_parent_child_onto_a_parentless_item_passes_through():
    # Attaching a first parent is how a child is created; only a SECOND one is
    # the violation.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show", "orphan.1", "--json"), _show_result("orphan.1", parent=None)),
            ScriptedStep(("dep", "add"), _OK),
        ]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["dep", "add", "orphan.1", "new.1", "--type", "parent-child"], runner
    )

    assert exit_code == 0
    assert runner.calls[-1] == ("dep", "add", "orphan.1", "new.1", "--type", "parent-child")


def test_dep_add_re_adding_the_parent_an_item_already_has_stays_a_success():
    # Judgment call, recorded: a re-add is a silent success, not an error. The
    # postcondition the caller asked for already holds, bd treats the repeat as
    # a no-op, and erroring here would fail a correct request -- and would make
    # a retry after a timeout report failure on a call that had succeeded.
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("show", "child.1", "--json"), _show_result("child.1", parent="same.1")),
            ScriptedStep(("dep", "add"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["dep", "add", "child.1", "same.1", "--type", "parent-child"], runner
    )

    assert exit_code == 0
    assert envelope["error"] is None


# ---- closed type vocabulary ----


def test_dep_add_with_an_unrecognized_type_is_refused_without_calling_bd_at_all():
    # Measured on the unguarded code: bd stored `bogus-type-probe` as a real
    # edge. Nothing reads it, nothing acts on it, and it renders like any other
    # edge -- a typo that produces a silently inert relationship.
    exit_code, envelope, _ = run_cli(
        ["dep", "add", "a.1", "b.1", "--type", "bogus-type-probe"], steps=[]
    )

    assert exit_code == 1
    error = envelope["error"]
    assert error["code"] == str(ErrorCode.USAGE)
    assert error["detail"] == {"field": "type", "dep_type": "bogus-type-probe"}
    # The accepted vocabulary is in the message, so the caller learns the set
    # from the rejection rather than from bd's help.
    assert "relates-to" in error["message"]


def test_dep_add_refuses_the_near_miss_this_package_invented():
    # `related-to` appeared in this package's own model comment and its tests
    # and is in no bd vocabulary; `relates-to` and `related` are the real ones.
    # The facade documenting a type its backend does not know is exactly the
    # typo class the closed set exists to catch.
    exit_code, envelope, _ = run_cli(["dep", "add", "a.1", "b.1", "--type", "related-to"], steps=[])

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.USAGE)


def test_every_type_in_the_closed_set_is_still_accepted():
    for dep_type in sorted(DEP_TYPES):
        if dep_type == _READS_BOTH_ENDS:
            steps = [
                ScriptedStep(
                    ("show", "a.1", "b.1", "--json"),
                    BdResult(
                        returncode=0,
                        stdout=json.dumps(
                            [
                                json.loads(_show_result("a.1").stdout)[0],
                                json.loads(_show_result("b.1").stdout)[0],
                            ]
                        ),
                        stderr="",
                    ),
                ),
                ScriptedStep(("dep", "add"), _OK),
            ]
        elif dep_type == _READS_THE_CHILD:
            steps = [
                ScriptedStep(("show", "a.1", "--json"), _show_result("a.1", parent=None)),
                ScriptedStep(("dep", "add"), _OK),
            ]
        else:
            steps = [ScriptedStep(("dep", "add"), _OK)]
        runner = ScriptedBdRunner(steps=steps)

        exit_code, envelope, _ = run_cli_with_runner(
            ["dep", "add", "a.1", "b.1", "--type", dep_type], runner
        )

        assert exit_code == 0, f"{dep_type} was rejected: {envelope['error']}"
        assert runner.calls[-1] == ("dep", "add", "a.1", "b.1", "--type", dep_type)


def test_dep_remove_still_accepts_a_type_outside_the_closed_set():
    # Deliberate asymmetry. Edges with an unsanctioned type already exist,
    # written before this check landed; closing the set on removal too would
    # strand precisely the edges that need cleaning up.
    runner = ScriptedBdRunner(steps=[ScriptedStep(("dep", "remove"), _OK)])

    exit_code, _, _ = run_cli_with_runner(
        ["dep", "remove", "a.1", "b.1", "--type", "bogus-type-probe"], runner
    )

    assert exit_code == 0
    assert runner.calls == [("dep", "remove", "a.1", "b.1")]
