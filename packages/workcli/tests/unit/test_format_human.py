"""`--format human`.

Human rendering is opt-in and goes to **stderr only** — stdout must remain
byte-identical to the same invocation without the flag, so the "stdout is
always exactly one JSON envelope" invariant holds for every consumer
regardless of `--format`. The default (`--format json`, or the flag
omitted) must never invoke the renderer at all.
"""

from __future__ import annotations

from io import StringIO

from tests.fakes import ScriptedBdRunner, ScriptedStep
from workcli.adapters.bd.runner import BdResult
from workcli.cli import main

_SHOW_OK = BdResult(
    returncode=0,
    stdout='[{"id": "x.1", "title": "T", "issue_type": "task", "status": "open", '
    '"priority": 2, "labels": [], "dependencies": [], "dependents": []}]',
    stderr="",
)


def _run(argv: list[str]) -> tuple[int, str, str]:
    out = StringIO()
    err = StringIO()
    runner = ScriptedBdRunner(steps=[ScriptedStep(("show",), _SHOW_OK)])
    exit_code = main(argv, runner=runner, out=out, err=err)
    return exit_code, out.getvalue(), err.getvalue()


def test_format_human_stdout_is_byte_identical_to_json_default_and_stderr_is_nonempty() -> None:
    json_exit, json_stdout, json_stderr = _run(["show", "x.1"])
    human_exit, human_stdout, human_stderr = _run(["--format", "human", "show", "x.1"])

    assert human_exit == json_exit
    assert human_stdout == json_stdout
    assert json_stderr == ""
    assert human_stderr != ""


def test_a_one_id_show_renders_through_the_same_items_list_as_any_read() -> None:
    # The renderer is deliberately generic: it walks whatever `data` holds and
    # knows no verb names. So `show` moving to `{"items": [...]}` moves the
    # human view with it, and a one-id show now reads like the listing verbs
    # rather than like a special case. Teaching the renderer that `show` with
    # one row should be flattened would put a verb's identity into a module
    # that has none, and would make the human view disagree with the JSON
    # envelope printed beside it.
    _, _, stderr_text = _run(["--format", "human", "show", "x.1"])

    assert stderr_text.splitlines()[:3] == ["ok", "items:", "  -"]
    assert "    id: x.1" in stderr_text


def test_format_json_default_never_writes_to_stderr() -> None:
    _, _, stderr_text = _run(["show", "x.1"])

    assert stderr_text == ""


def test_format_json_explicit_never_writes_to_stderr() -> None:
    _, _, stderr_text = _run(["--format", "json", "show", "x.1"])

    assert stderr_text == ""


def test_format_human_on_a_usage_error_still_renders_to_stderr() -> None:
    # A parse/usage failure raises before the verb dispatches, but the
    # "human view to stderr" invariant still applies: --format human must be
    # recovered from argv even though full parsing never completed.
    out = StringIO()
    err = StringIO()

    exit_code = main(["--format", "human", "bogus-verb"], out=out, err=err)

    assert exit_code == 1
    assert '"ok": false' in out.getvalue()
    assert "E_USAGE" in out.getvalue()
    assert "error\n" in err.getvalue()
    assert "E_USAGE" in err.getvalue()


def test_format_human_on_a_failure_case_renders_the_error_to_stderr() -> None:
    out = StringIO()
    err = StringIO()
    runner = ScriptedBdRunner(
        steps=[
            ScriptedStep(
                ("show",),
                BdResult(returncode=1, stdout="", stderr='no issue found matching "x.1"\n'),
            )
        ]
    )

    exit_code = main(["--format", "human", "show", "x.1"], runner=runner, out=out, err=err)

    assert exit_code == 1
    assert '"ok": false' in out.getvalue()
    assert "error\n" in err.getvalue()
    assert "E_NOT_FOUND" in err.getvalue()
