"""Typed error envelopes against real bd, within reason."""

from __future__ import annotations

import json

from tests.integration.conftest import _bd_env
from workcli.adapters.bd.runner import SubprocessBdRunner


def test_show_bogus_id_is_not_found(driver):
    env = driver(["show", "itest-nope-xyz"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_NOT_FOUND"  # reaches bd, no pre-check → real drift coverage


def test_bad_flag_is_usage_error(driver):
    env = driver(["show", "--bogus-flag"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_USAGE"


def test_deliver_without_evidence_is_refused(driver):
    item_id = driver(["create", "feat", "--title", "ep-noevidence", "--priority", "2", "--orphan"])[
        "data"
    ]["id"]
    driver(["claim", item_id])
    env = driver(["deliver", item_id])  # no --pr/--items/--trivial
    assert env["ok"] is False
    assert env["error"]["code"] == "E_EVIDENCE"


def test_type_wall_verb_envelope(driver):
    # (a) The verb-layer pre-check raises E_TYPE_WALL before bd is called.
    epic = driver(["create", "epic", "--title", "ep-epic", "--priority", "2", "--orphan"])["data"][
        "id"
    ]
    task = driver(["create", "feat", "--title", "ep-task", "--priority", "2", "--orphan"])["data"][
        "id"
    ]
    env = driver(["dep", "add", epic, task, "--type", "blocks"])
    assert env["ok"] is False
    assert env["error"]["code"] == "E_TYPE_WALL"


def test_type_wall_raw_bd_marker_drift(fresh_install, bd_binary):
    # (b) DRIFT COVERAGE: drive bd's own `dep add` directly (bypassing the verb
    # pre-check) and assert bd still emits the marker map_bd_failure keys on
    # ("can only block"). This is the assertion that actually fails if bd changes
    # its wall wording — the verb-envelope test above cannot see that.
    runner = SubprocessBdRunner(
        bd_binary=bd_binary, cwd=str(fresh_install), env=_bd_env(fresh_install)
    )
    epic = _create_raw(runner, "rw-epic", "epic")
    task = _create_raw(runner, "rw-task", "task")
    result = runner.run(["dep", "add", epic, task, "--type", "blocks"])
    assert result.returncode != 0
    assert "can only block" in result.stderr.lower()


def _create_raw(runner, title, bd_type):
    r = runner.run(["create", "--json", "--title", title, "--type", bd_type, "--priority", "2"])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["id"]
