"""Materialise an in-memory StagingPlan to a real directory tree (G.6).

Backs the ``--dump-stage <path>`` debug mode: write every active tool's
``StagingPlan`` to ``<target>/<tool>/<dest_relpath>`` and return, touching no
install destination. A dump is a read-only stage — it consumes the same plans
``core.orchestrator.stage_and_transform`` already produces and writes them
somewhere harmless for inspection.

Two item shapes, mirroring the data model (see ``model.StagedItem``):

- A FILE item carries eager ``content`` bytes; they are written verbatim.
- A DIR item carries ``content is None``; its bytes derive from its
  ``source_path`` tree (copied recursively), then the carrier/extension bytes in
  ``StagingPlan.dir_overrides[dest_relpath]`` are overlaid on top (override wins
  on a name collision, matching sync-time semantics).

All user-facing output (the printed dump path) routes through ``IOPort``; this
module never calls ``print``.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from installer.core.paths import is_safe_relpath

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from installer.core.io_port import IOPort
    from installer.core.model import StagedItem, StagingPlan, Tool


def dump_plan(plans: Mapping[Tool, StagingPlan], target: Path, *, io: IOPort) -> None:
    """Write every plan in ``plans`` under ``target/<tool>/`` and print the path.

    Each tool's items land at ``target / tool.value / item.dest_relpath``. FILE
    items write their ``content`` bytes; DIR items copy their ``source_path``
    tree then overlay ``plan.dir_overrides`` on top. Returns nothing — the
    caller owns the process exit code.

    Refuses a pre-existing **non-empty** ``target`` with `ValueError`: the dump's
    contract is that it equals the plan, but DIR materialisation uses
    ``copytree(dirs_exist_ok=True)`` which would silently merge new files over
    whatever already sits there — leaving stale files from a prior run to
    misrepresent the plan. An empty or absent ``target`` is fine (the operator
    may pre-create it).

    Refuses a ``target`` that exists but is **not a directory** (a file, or a
    symlink to a file — ``is_dir()`` follows symlinks) with `ValueError` too:
    otherwise ``iterdir()`` would raise ``NotADirectoryError`` (an ``OSError``,
    not ``ValueError``), bypassing the CLI's ``ValueError`` handling and dying
    with an uncaught traceback instead of a clean ``installer: …`` / exit 2.
    """
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"dump target is not a directory: {target}")  # noqa: TRY003  # debug-only guard; subclass not justified
        if any(target.iterdir()):
            raise ValueError(f"dump target is not empty: {target}")  # noqa: TRY003  # single call-site; debug-only guard
    for tool, plan in plans.items():
        tool_root = target / tool.value
        for item in plan.items.values():
            overrides = plan.dir_overrides.get(item.dest_relpath, {})
            _write_item(tool_root, item, overrides)
    io.info(f"staging plan written to {target}")


def _write_item(
    tool_root: Path,
    item: StagedItem,
    overrides: Mapping[Path, bytes],
) -> None:
    if not is_safe_relpath(item.dest_relpath):
        raise ValueError(f"dump dest_relpath escapes the tool tree: {item.dest_relpath}")  # noqa: TRY003  # debug-only guard; subclass not justified
    dest = tool_root / item.dest_relpath
    if item.content is not None:
        _write_bytes(dest, item.content)
        return
    # DIR item: copy the source tree, then overlay carrier/extension bytes.
    shutil.copytree(item.source_path, dest, dirs_exist_ok=True)
    for inner, content in overrides.items():
        if not is_safe_relpath(inner):
            raise ValueError(f"dump override relpath escapes the dir: {inner}")  # noqa: TRY003  # debug-only guard; subclass not justified
        _write_bytes(dest / inner, content)


def _write_bytes(dest: Path, content: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
