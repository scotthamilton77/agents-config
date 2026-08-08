"""`work create <noun>` accepts the same noun aliases and priority notations
`work discover --noun` already does -- 9k9.169, the residual of 9k9.99 for
the `create` surface.

`create`'s NOUN positional used to be an argparse `choices=` list built
straight off the `Noun` enum, which bypassed `resolve_noun` (and its
`NOUN_ALIASES`) entirely and rejected before the handler -- and hence before
`discover`-style combined-error reporting -- ever ran. These tests pin: the
alias resolves to the identical mint discover's does, the bare-priority-digit
form normalizes the same way, an invalid NOUN is rejected by the handler (not
argparse) with zero backend calls, and an invalid NOUN + an invalid --priority
together fold into one envelope.
"""

from __future__ import annotations

import dataclasses
import json
from argparse import Namespace

import pytest

from tests.conftest import run_cli_with_runner
from tests.fake_backend import FakeBackend, ReadOnlyFakeBackend
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, WorkError
from workcli.lifecycle.create import create_noun


def _not_found_config_loader(_explicit_path: str | None = None) -> TrackLayerConfig:
    # Byte-identical to pre-track-layer behavior: NOT_CONFIGURED/"not-found"
    # makes the track gate a no-op, same convention as test_create_noun.py.
    raise WorkError(
        ErrorCode.NOT_CONFIGURED,
        "track layer not configured: no project-config.toml",
        detail={"reason": "not-found"},
    )


def _search_result(*raw_items: dict[str, object]) -> BdResult:
    return BdResult(returncode=0, stdout=json.dumps(list(raw_items)), stderr="")


def _create_result(new_id: str) -> BdResult:
    return BdResult(
        returncode=0,
        stdout=json.dumps({"id": new_id, "schema_version": 3, "title": "T"}),
        stderr="",
    )


def _create_args(
    *,
    noun: str = "chore",
    priority: str | None = None,
    parent: str | None = "P",
) -> Namespace:
    return Namespace(
        noun=noun,
        raw=False,
        title="T",
        description=None,
        type=None,
        priority=priority,
        parent=parent,
        label=[],
        orphan=parent is None,
        spec=None,
        trivial=False,
        acceptance=None,
        track=None,
        load_config=_not_found_config_loader,
    )


# --- AC1: 'bug' mints the identical item 'bugfix' would ---


def test_create_bug_alias_sends_the_identical_bd_call_as_bugfix() -> None:
    runner_alias = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )
    runner_canon = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_alias, envelope_alias, _ = run_cli_with_runner(
        ["create", "bug", "--title", "T", "--parent", "P"],
        runner_alias,
        config_loader=_not_found_config_loader,
    )
    exit_canon, envelope_canon, _ = run_cli_with_runner(
        ["create", "bugfix", "--title", "T", "--parent", "P"],
        runner_canon,
        config_loader=_not_found_config_loader,
    )

    assert exit_alias == 0 and exit_canon == 0
    assert envelope_alias["data"] == envelope_canon["data"]
    assert runner_alias.calls == runner_canon.calls
    assert runner_canon.calls == [
        ("search", "T", "--json", "--status", "all", "--limit", "0"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "bug",
            "--parent",
            "P",
            "--no-inherit-labels",
            "--labels",
            "shape-bugfix",
        ),
    ]


def test_create_bug_alias_and_canonical_form_produce_byte_identical_items() -> None:
    backend_alias = FakeBackend()
    backend_canon = FakeBackend()

    data_alias = create_noun(backend_alias, _create_args(noun="bug"))
    data_canon = create_noun(backend_canon, _create_args(noun="bugfix"))

    assert isinstance(data_alias, dict)
    assert isinstance(data_canon, dict)
    item_alias = backend_alias.get(str(data_alias["id"]))
    item_canon = backend_canon.get(str(data_canon["id"]))

    assert dataclasses.replace(item_alias, id="") == dataclasses.replace(item_canon, id="")


# --- AC2: bare-digit --priority accepted on the same terms discover accepts it ---


def test_create_bare_priority_digit_normalizes_to_canonical_p_notation() -> None:
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("search",), _search_result()),
            ScriptedStep(("create",), _create_result("x.1")),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "chore", "--title", "T", "--parent", "P", "--priority", "2"],
        runner,
        config_loader=_not_found_config_loader,
    )

    assert exit_code == 0
    assert envelope["data"] == {"id": "x.1"}
    assert runner.calls == [
        ("search", "T", "--json", "--status", "all", "--limit", "0"),
        (
            "create",
            "--json",
            "--title",
            "T",
            "--type",
            "chore",
            "--priority",
            "P2",
            "--parent",
            "P",
            "--no-inherit-labels",
            "--labels",
            "shape-chore",
        ),
    ]


def test_create_priority_omitted_still_creates_without_a_priority_flag() -> None:
    """Regression guard: --priority stays optional for `create` -- unlike
    `discover`, which requires it. Every noun that worked before this change
    (no --priority at all) must keep working."""
    backend = FakeBackend()

    data = create_noun(backend, _create_args(priority=None))

    assert isinstance(data, dict)
    assert backend.get(str(data["id"])).priority == "P2"  # FakeBackend's create() default


def test_create_invalid_priority_alone_raises_its_own_usage_error() -> None:
    """A valid noun with a malformed --priority still raises that field's own
    (non-combined) error unchanged -- mirrors discover's
    `test_priority_only_failure_still_returns_triage_incomplete_alone`, but
    `create` has no triage concept, so the code stays plain `E_USAGE`."""
    backend = ReadOnlyFakeBackend()

    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(priority="P9"))

    assert exc_info.value.code is ErrorCode.USAGE
    assert exc_info.value.message == "priority must be one of P0-P4, got 'P9'"
    assert exc_info.value.detail == {"field": "priority"}


# --- AC4: an invalid NOUN is rejected by the handler, not argparse, with zero backend calls ---


def test_invalid_noun_rejected_by_handler_not_argparse_with_zero_backend_calls() -> None:
    runner = ScriptedBdRunner(steps=[])

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "widget", "--title", "T", "--parent", "P"],
        runner,
        config_loader=_not_found_config_loader,
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    assert error["code"] == str(ErrorCode.USAGE)
    # argparse's own choices-rejection message is prefixed "argument NOUN: ";
    # the handler's own message (validate.validate_noun) carries no such
    # prefix -- this is the mechanical proof the rejection moved surfaces.
    assert error["message"] == (
        "invalid choice: 'widget' (choose from spike, chore, decision, feat, "
        "bugfix, spec, epic, milestone)"
    )
    assert error["detail"] == {"field": "noun"}
    assert runner.calls == []


def test_invalid_noun_alone_touches_no_backend_mutation() -> None:
    """Handler-level mirror of the CLI proof above, using `ReadOnlyFakeBackend`
    (raises on every mutator) -- same proof shape as
    `test_discover.test_unknown_noun_alone_touches_no_backend_mutation`."""
    backend = ReadOnlyFakeBackend()

    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(noun="widget"))

    assert exc_info.value.code is ErrorCode.USAGE


# --- AC3: an invalid NOUN and an invalid --priority together, one envelope ---


def test_invalid_noun_and_invalid_priority_together_reported_in_one_envelope() -> None:
    runner = ScriptedBdRunner(steps=[])

    exit_code, envelope, _ = run_cli_with_runner(
        ["create", "widget", "--title", "T", "--parent", "P", "--priority", "P9"],
        runner,
        config_loader=_not_found_config_loader,
    )

    assert exit_code == 1
    error = envelope["error"]
    assert isinstance(error, dict)
    # Neither folded failure is triage-semantic in create's context (create has
    # no triage concept) -- the top-level code stays E_USAGE, unlike discover's
    # equivalent aggregate, which surfaces E_TRIAGE_INCOMPLETE.
    assert error["code"] == str(ErrorCode.USAGE)
    errors = error["detail"]["errors"]
    assert isinstance(errors, list)
    fields = {entry["field"] for entry in errors}
    assert fields == {"noun", "priority"}
    codes_by_field = {entry["field"]: entry["code"] for entry in errors}
    assert codes_by_field == {"noun": str(ErrorCode.USAGE), "priority": str(ErrorCode.USAGE)}
    assert runner.calls == []


def test_invalid_noun_and_invalid_priority_together_touches_no_backend_mutation() -> None:
    backend = ReadOnlyFakeBackend()

    with pytest.raises(WorkError) as exc_info:
        create_noun(backend, _create_args(noun="widget", priority="P9"))

    assert exc_info.value.code is ErrorCode.USAGE
    errors = exc_info.value.detail["errors"]
    assert isinstance(errors, list)
    fields = {entry["field"] for entry in errors}  # type: ignore[union-attr]
    assert fields == {"noun", "priority"}
