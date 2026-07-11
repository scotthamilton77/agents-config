"""Finding 3: `--help`/`-h` is a documented, pinned exemption from the
"stdout is always exactly one envelope" invariant (spec §4).

argparse's built-in help action prints human-oriented usage text to the
*real* `sys.stdout` and raises `SystemExit(0)` -- it never routes through
`main()`'s injected `out`/`err` TextIO parameters, so these tests capture
with pytest's `capsys` rather than the `run_cli` helper.
"""

from __future__ import annotations

import pytest

from workcli.cli import main


def test_root_help_exits_zero_and_prints_usage_to_stdout(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out


def test_verb_help_exits_zero_and_prints_usage_to_stdout(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc_info:
        main(["show", "--help"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
