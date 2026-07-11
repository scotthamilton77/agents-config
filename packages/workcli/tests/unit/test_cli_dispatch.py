"""cli.py dispatch: subparser E_USAGE propagation and lazy backend construction.

Task 1 left an open question: does a bad flag *inside* a known subcommand
(`work show --bogus`) reach the same `E_USAGE` envelope path as an unknown
top-level verb, or does argparse's default subparser dump straight to
stderr? Task 3 replaces the placeholder `nargs='?'` verb positional with
real subparsers built with `parser_class=_EnvelopeArgumentParser`, closing
that question: both cases raise into `main()`'s `WorkError` handling.
"""

from __future__ import annotations

import json
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
