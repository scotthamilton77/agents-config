"""Shared `subprocess.run` helper for the git/gh adapter ports.

Every git/gh call site duplicated the same `capture_output`/`timeout`/`check`
boilerplate; centralizing it here means a future adapter cannot silently drop
`text=True` (or any other flag) by copy-paste. `text` defaults to `True` — the
common case, since both CLIs emit UTF-8 text output the adapters parse as
`str`. Binary output (`git archive`) opts out explicitly with `text=False`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Literal, overload


@overload
def run(
    argv: Sequence[str],
    *,
    cwd: str,
    timeout: float,
    check: bool = False,
    text: Literal[True] = True,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run(
    argv: Sequence[str], *, cwd: str, timeout: float, check: bool, text: Literal[False]
) -> subprocess.CompletedProcess[bytes]: ...


def run(
    argv: Sequence[str], *, cwd: str, timeout: float, check: bool = False, text: bool = True
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603
        list(argv), cwd=cwd, capture_output=True, text=text, timeout=timeout, check=check
    )
