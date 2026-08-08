"""`work search QUERY` — the corpus, the statuses, and the bound.

Three narrowings, none of them applied unasked: reading titles alone, skipping
closed items, and stopping at the backend's own default page. Each one turns a
match into an empty result that a caller cannot tell from a true negative,
which is how a search for prior art becomes a duplicate filing. The tests here
pin the wide default and the caller's ability to narrow it back down
deliberately.
"""

from __future__ import annotations

import json

from tests.conftest import run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult

_EMPTY = BdResult(returncode=0, stdout="[]", stderr="")


def _raw(
    item_id: str,
    *,
    title: str = "an item",
    status: str = "open",
    description: str = "",
    notes: str = "",
) -> dict[str, object]:
    return {
        "id": item_id,
        "title": title,
        "issue_type": "task",
        "status": status,
        "priority": 2,
        "labels": [],
        "description": description,
        "notes": notes,
        "dependencies": [],
        "dependents": [],
    }


def _found(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _legs(*results: BdResult) -> list[ScriptedStep]:
    """Script one result per corpus leg, in the order the adapter reads them."""
    prefixes = (("search",), ("list",), ("list",))
    return [ScriptedStep(prefix, result) for prefix, result in zip(prefixes, results, strict=True)]


def _ids(envelope: dict[str, object]) -> list[str]:
    data = envelope["data"]
    assert isinstance(data, dict)
    return [item["id"] for item in data["items"]]


def test_search_reads_title_description_and_notes_by_default():
    runner = ScriptedBdRunner(steps=_legs(_EMPTY, _EMPTY, _EMPTY))

    exit_code, _, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    assert runner.calls == [
        ("search", "quarantine", "--json", "--status", "all", "--limit", "0"),
        ("list", "--json", "--desc-contains", "quarantine", "--all", "--limit", "0"),
        ("list", "--json", "--notes-contains", "quarantine", "--all", "--limit", "0"),
    ]


def test_search_returns_an_item_whose_only_match_is_in_its_description():
    # The first narrowing: reading titles alone returns nothing at all for a
    # word that appears only in a description.
    runner = ScriptedBdRunner(
        steps=_legs(
            _EMPTY,
            _found(_raw("x.7", title="unrelated title", description="mentions quarantine")),
            _EMPTY,
        )
    )

    exit_code, envelope, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    assert _ids(envelope) == ["x.7"]


def test_search_returns_an_item_whose_only_match_is_in_its_notes():
    runner = ScriptedBdRunner(
        steps=_legs(
            _EMPTY,
            _EMPTY,
            _found(_raw("x.8", title="unrelated title", notes="measured: quarantine holds")),
        )
    )

    exit_code, envelope, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    assert _ids(envelope) == ["x.8"]


def test_search_returns_a_closed_item():
    # The second narrowing: every leg asks for every status, so a match that
    # was already done and closed still answers "yes, this exists".
    runner = ScriptedBdRunner(
        steps=_legs(_found(_raw("x.9", title="park re-park", status="closed")), _EMPTY, _EMPTY)
    )

    exit_code, envelope, _ = run_cli_with_runner(["search", "park"], runner)

    assert exit_code == 0
    assert _ids(envelope) == ["x.9"]
    assert runner.calls[0] == ("search", "park", "--json", "--status", "all", "--limit", "0")


def test_search_defaults_to_unbounded_and_every_row_surfaces():
    # The third narrowing: the backend's own default page is 50, so deferring
    # to it clips a match set of 60 with nothing to say it was clipped.
    matches = [_raw(f"x.{i}") for i in range(60)]
    runner = ScriptedBdRunner(steps=_legs(_found(*matches), _EMPTY, _EMPTY))

    exit_code, envelope, _ = run_cli_with_runner(["search", "item"], runner)

    assert exit_code == 0
    assert len(_ids(envelope)) == 60
    # The bound is what the backend was actually asked for: a fake returns
    # whatever it was scripted with, so only the argv can prove the page was
    # lifted. `tests/integration/test_search_corpus.py` proves the effect
    # against a real backend holding more than a page of matches.
    assert [call[-2:] for call in runner.calls] == [("--limit", "0")] * 3


def test_search_narrowed_to_titles_reads_one_leg_only():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("search",), _EMPTY)])

    exit_code, _, _ = run_cli_with_runner(["search", "quarantine", "--in", "title"], runner)

    assert exit_code == 0
    assert runner.calls == [("search", "quarantine", "--json", "--status", "all", "--limit", "0")]


def test_search_corpus_narrowing_is_repeatable_and_drops_the_field_not_named():
    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("search",), _EMPTY), ScriptedStep(("list",), _EMPTY)]
    )

    exit_code, _, _ = run_cli_with_runner(
        ["search", "quarantine", "--in", "title", "--in", "notes"], runner
    )

    assert exit_code == 0
    assert runner.calls == [
        ("search", "quarantine", "--json", "--status", "all", "--limit", "0"),
        ("list", "--json", "--notes-contains", "quarantine", "--all", "--limit", "0"),
    ]


def test_search_status_narrowing_reaches_every_leg():
    runner = ScriptedBdRunner(steps=_legs(_EMPTY, _EMPTY, _EMPTY))

    exit_code, _, _ = run_cli_with_runner(["search", "park", "--status", "open"], runner)

    assert exit_code == 0
    assert runner.calls == [
        ("search", "park", "--json", "--status", "open", "--limit", "0"),
        ("list", "--json", "--desc-contains", "park", "--status", "open", "--limit", "0"),
        ("list", "--json", "--notes-contains", "park", "--status", "open", "--limit", "0"),
    ]


def test_search_limit_slices_the_union_and_never_the_legs():
    # A bound applied per leg would truncate each one before the merge and
    # undercount the union -- the same ordering `list --track` already fixes.
    # So every leg is asked unbounded and the cap applies to the merged set.
    runner = ScriptedBdRunner(
        steps=_legs(_found(_raw("x.1")), _found(_raw("x.2")), _found(_raw("x.3")))
    )

    exit_code, envelope, _ = run_cli_with_runner(["search", "item", "--limit", "2"], runner)

    assert exit_code == 0
    assert _ids(envelope) == ["x.1", "x.2"]
    assert [call[-2:] for call in runner.calls] == [("--limit", "0")] * 3


def test_search_unions_by_id_and_reports_a_twice_matched_item_once():
    both = _raw("x.5", title="quarantine the backend", description="quarantine again")
    runner = ScriptedBdRunner(steps=_legs(_found(both), _found(both), _EMPTY))

    exit_code, envelope, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    assert _ids(envelope) == ["x.5"]
    assert len(runner.calls) == 3


def test_search_declares_the_same_relationship_disclosure_whichever_leg_matched():
    # One result set never mixes disclosure levels. The leg that reads titles
    # can report no relationship at all, so that is the floor for all of them
    # -- a consumer reading `unknown_relations` off the first item would
    # otherwise generalize it to the rest and mistake an unknown parent for
    # an absent one.
    from_title = _raw("x.1", title="quarantine")
    from_description = {**_raw("x.2", description="quarantine"), "parent": "x.0"}
    runner = ScriptedBdRunner(steps=_legs(_found(from_title), _found(from_description), _EMPTY))

    exit_code, envelope, _ = run_cli_with_runner(["search", "quarantine"], runner)

    assert exit_code == 0
    data = envelope["data"]
    assert isinstance(data, dict)
    assert _ids(envelope) == ["x.1", "x.2"]
    for item in data["items"]:
        assert item["unknown_relations"] == ["children", "deps", "parent"]
        assert "parent" not in item


def test_search_rejects_a_corpus_field_it_does_not_have():
    exit_code, envelope, _ = run_cli_with_runner(
        ["search", "quarantine", "--in", "acceptance"], ScriptedBdRunner(steps=[])
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == "E_USAGE"
