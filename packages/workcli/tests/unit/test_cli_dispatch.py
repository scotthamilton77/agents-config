"""cli.py dispatch: subparser E_USAGE propagation and lazy backend construction.

An open question: does a bad flag *inside* a known subcommand
(`work show --bogus`) reach the same `E_USAGE` envelope path as an unknown
top-level verb, or does argparse's default subparser dump straight to
stderr? Real subparsers built with `parser_class=_EnvelopeArgumentParser`
replace the placeholder `nargs='?'` verb positional, closing that question:
both cases raise into `main()`'s `WorkError` handling.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from io import StringIO

from workcli.adapters.bd.runner import BdResult
from workcli.cli import main


class _ExplodingRunner:
    """A `BdRunner` that fails the test the instant it's asked to do anything.

    Proves `--protocol-version` never constructs a `Backend` over this
    runner -- if dispatch's lazy-construction discipline regresses and a
    `Backend` gets built (or, worse, called) for the handshake path, this
    raises instead of silently succeeding.
    """

    def run(self, args: Sequence[str]) -> BdResult:
        raise AssertionError(f"protocol-version handshake must never call bd, got: {args!r}")


def test_unknown_verb_yields_usage_envelope_not_argparse_stderr_dump():
    out = StringIO()
    err = StringIO()

    exit_code = main(["bogus-verb"], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""

    envelope = json.loads(out.getvalue())
    assert envelope["error"]["code"] == "E_USAGE"


def test_unknown_flag_inside_a_known_subcommand_yields_usage_envelope():
    out = StringIO()
    err = StringIO()

    exit_code = main(["show", "--bogus-flag"], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""

    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"


def test_missing_verb_yields_usage_envelope():
    out = StringIO()
    err = StringIO()

    exit_code = main([], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"
    # A missing verb must read as missing, not as the confusing "unknown verb: None".
    assert "no verb given" in envelope["error"]["message"]
    assert "None" not in envelope["error"]["message"]


def test_invalid_format_value_yields_usage_envelope_with_clean_stderr():
    # An invalid --format value fails the main parse; the lenient format peek
    # also can't resolve it and falls back to json, so nothing renders to stderr.
    out = StringIO()
    err = StringIO()

    exit_code = main(["--format", "bogus"], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 1
    assert err.getvalue() == ""
    envelope = json.loads(out.getvalue())
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "E_USAGE"


def test_protocol_version_never_constructs_a_backend_or_touches_the_runner():
    out = StringIO()
    err = StringIO()

    exit_code = main(["--protocol-version"], runner=_ExplodingRunner(), out=out, err=err)

    assert exit_code == 0
    assert err.getvalue() == ""


class _AlwaysTimingOutRunner:
    """A `BdRunner` whose every call hits the subprocess deadline."""

    def run(self, args: Sequence[str]) -> BdResult:
        raise subprocess.TimeoutExpired(cmd=list(args), timeout=60)


def test_a_timeout_envelope_names_the_verb_that_resolves_it():
    # A half-applied mutation is only actionable if the caller learns what to
    # run about it. The adapter that detects the timeout may not say -- `work
    # reconcile` is this layer's word, and this layer is where it gets added,
    # so the advice has to survive the trip out or the caller is left holding
    # a fact with no next step.
    out = StringIO()
    err = StringIO()

    exit_code = main(
        ["note", "x.1", "hello"],
        runner=_AlwaysTimingOutRunner(),
        out=out,
        err=err,
        sleep=lambda _: None,
    )

    assert exit_code == 1
    envelope = json.loads(out.getvalue())
    assert envelope["error"]["code"] == "E_TIMEOUT"
    assert "may have partially applied" in envelope["error"]["message"]
    assert "work reconcile" in envelope["error"]["message"]


def test_the_readme_counts_the_verbs_the_cli_actually_dispatches() -> None:
    # The README's verb table opened with a hand-written count that said
    # "Twelve" while `VERBS` held 31 -- nineteen verbs' worth of drift in the
    # one sentence a reader meets before the table. A number nobody recomputes
    # decays silently, and the sentence is worse than no sentence once it does,
    # because it reads as a deliberate statement of scope.
    import re
    from pathlib import Path

    from workcli.verbs import VERBS

    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    match = re.search(r"^(\d+) verbs; each is a subcommand", readme, re.MULTILINE)

    assert match, "the README's verb table states no count; this check has nothing to hold"
    assert int(match.group(1)) == len(VERBS), (
        f"README says {match.group(1)} verbs, the CLI dispatches {len(VERBS)}"
    )
