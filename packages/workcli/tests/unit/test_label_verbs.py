"""`label add`/`remove`/`list` — one bd invocation per label (bd needs it).

bd's own `label add`/`label remove` accept only one label per call; the
facade's `work label add ID a b c` fans that out into three ordered bd
invocations behind a single envelope. `label list` normalizes to
the golden `bd label list --json` shape: a flat `string[]`.
"""

from __future__ import annotations

from tests.conftest import run_cli, run_cli_with_runner
from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.envelope import ErrorCode

_OK = BdResult(returncode=0, stdout="", stderr="")


def test_label_add_sends_one_bd_call_per_label_in_order():
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(("label", "add"), _OK),
            ScriptedStep(("label", "add"), _OK),
            ScriptedStep(("label", "add"), _OK),
        ]
    )

    exit_code, envelope, _ = run_cli_with_runner(["label", "add", "x.1", "a", "b", "c"], runner)

    assert exit_code == 0
    assert envelope["ok"] is True
    assert runner.calls == [
        ("label", "add", "x.1", "a"),
        ("label", "add", "x.1", "b"),
        ("label", "add", "x.1", "c"),
    ]


def test_label_remove_sends_exactly_one_bd_call():
    runner = ScriptedBdRunner(steps=[ScriptedStep(("label", "remove"), _OK)])

    exit_code, _, _ = run_cli_with_runner(["label", "remove", "x.1", "stale"], runner)

    assert exit_code == 0
    assert runner.calls == [("label", "remove", "x.1", "stale")]


def test_label_add_with_no_labels_yields_usage_envelope():
    exit_code, envelope, _ = run_cli(["label", "add", "x.1"], steps=[])

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.USAGE)


def test_label_list_returns_the_flat_string_array_from_the_golden_fixture_shape():
    import json
    from pathlib import Path

    fixture = (
        Path(__file__).resolve().parent.parent / "fixtures" / "bd_label_list_wgclw9.1.json"
    ).read_text()

    runner = ScriptedBdRunner(
        steps=[ScriptedStep(("label", "list"), BdResult(returncode=0, stdout=fixture, stderr=""))]
    )

    exit_code, envelope, _ = run_cli_with_runner(["label", "list", "x.1"], runner)

    assert exit_code == 0
    assert envelope["data"] == json.loads(fixture)
    assert runner.calls == [("label", "list", "x.1", "--json")]


def test_label_not_found_maps_to_not_found_envelope():
    exit_code, envelope, _ = run_cli(
        ["label", "add", "bogus-id", "a"],
        steps=[
            ScriptedStep(
                ("label", "add"),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "bogus-id"\n'),
            )
        ],
    )

    assert exit_code == 1
    assert envelope["error"]["code"] == str(ErrorCode.NOT_FOUND)
