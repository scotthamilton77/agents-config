"""Materialiser for the ``--dump-stage`` debug mode (G.6).

``dump_plan`` writes the in-memory ``StagingPlan`` per tool to a real directory
tree at ``<target>/<tool>/<dest_relpath>`` and exits — no destination writes.
These tests pin the coded write decisions: where bytes come from for FILE vs DIR
items, how ``dir_overrides`` overlays a carrier/extension DIR, per-tool layout,
the io-routed path print, and the path-traversal guard on both the item key and
the override inner key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.dump import dump_plan
from installer.core.io_port import ScriptedIO
from installer.core.model import (
    FileKind,
    Provenance,
    StagedItem,
    StagingPlan,
    Tool,
)

_TOOL_PROV = Provenance(kind="tool", name="claude")


def _file_item(dest: str, content: bytes) -> StagedItem:
    return StagedItem(
        source_path=Path("unused-for-file-items"),
        dest_relpath=Path(dest),
        kind=FileKind.OTHER,
        namespace=None,
        provenance=_TOOL_PROV,
        content=content,
    )


def _dir_item(source_path: Path, dest: str) -> StagedItem:
    return StagedItem(
        source_path=source_path,
        dest_relpath=Path(dest),
        kind=FileKind.DIR,
        namespace=dest.split("/")[0],
        provenance=_TOOL_PROV,
        content=None,
    )


def test_file_item_materialises_content_bytes_under_tool_dir(tmp_path: Path) -> None:
    """A FILE item's ``content`` bytes land verbatim at
    ``<target>/<tool>/<dest_relpath>``."""
    target = tmp_path / "dump"
    plan = StagingPlan(
        items={Path("AGENTS.md"): _file_item("AGENTS.md", b"laws\n")}, tool=Tool.CLAUDE
    )

    dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())

    assert (target / "claude" / "AGENTS.md").read_bytes() == b"laws\n"


def test_dir_item_copies_source_tree_recursively(tmp_path: Path) -> None:
    """A DIR item (``content is None``) materialises by copying its
    ``source_path`` tree — nested files included — to the dest dir."""
    src = tmp_path / "src" / "skills" / "demo"
    (src / "nested").mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"skill body\n")
    (src / "nested" / "helper.py").write_bytes(b"print('hi')\n")
    target = tmp_path / "dump"
    dest = Path("skills/demo")
    plan = StagingPlan(items={dest: _dir_item(src, "skills/demo")}, tool=Tool.CLAUDE)

    dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())

    base = target / "claude" / "skills" / "demo"
    assert (base / "SKILL.md").read_bytes() == b"skill body\n"
    assert (base / "nested" / "helper.py").read_bytes() == b"print('hi')\n"


def test_dir_overrides_overlay_on_top_of_source_tree(tmp_path: Path) -> None:
    """``dir_overrides`` for a DIR item are written after the source-tree copy:
    a new carrier/extension file appears, and an override for an existing inner
    path wins over the copied source bytes (sync-time overlay semantics)."""
    src = tmp_path / "src" / "skills" / "demo"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"base body\n")
    target = tmp_path / "dump"
    dest = Path("skills/demo")
    plan = StagingPlan(
        items={dest: _dir_item(src, "skills/demo")},
        tool=Tool.CLAUDE,
        dir_overrides={
            dest: {
                Path("SKILL.md"): b"patched body\n",  # override wins over source
                Path("carried/extra.md"): b"from plugin\n",  # net-new file
            }
        },
    )

    dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())

    base = target / "claude" / "skills" / "demo"
    assert (base / "SKILL.md").read_bytes() == b"patched body\n"
    assert (base / "carried" / "extra.md").read_bytes() == b"from plugin\n"


def test_each_tool_gets_its_own_subtree(tmp_path: Path) -> None:
    """Two tools in one dump land under distinct ``<target>/<tool>/`` roots."""
    target = tmp_path / "dump"
    claude_plan = StagingPlan(
        items={Path("AGENTS.md"): _file_item("AGENTS.md", b"claude\n")}, tool=Tool.CLAUDE
    )
    gemini_plan = StagingPlan(
        items={Path("GEMINI.md"): _file_item("GEMINI.md", b"gemini\n")}, tool=Tool.GEMINI
    )

    dump_plan({Tool.CLAUDE: claude_plan, Tool.GEMINI: gemini_plan}, target, io=ScriptedIO())

    assert (target / "claude" / "AGENTS.md").read_bytes() == b"claude\n"
    assert (target / "gemini" / "GEMINI.md").read_bytes() == b"gemini\n"


def test_dump_path_is_printed_through_io(tmp_path: Path) -> None:
    """The dump path is surfaced through ``IOPort`` (never a bare ``print``)."""
    target = tmp_path / "dump"
    plan = StagingPlan(items={Path("AGENTS.md"): _file_item("AGENTS.md", b"x\n")}, tool=Tool.CLAUDE)
    io = ScriptedIO()

    dump_plan({Tool.CLAUDE: plan}, target, io=io)

    assert any(str(target) in e.message for e in io.transcript)


def test_dest_relpath_escaping_tool_tree_is_rejected(tmp_path: Path) -> None:
    """A ``dest_relpath`` with a ``..`` component is refused before any write —
    the materialiser must not let a plan write outside ``<target>/<tool>/``."""
    target = tmp_path / "dump"
    escaping = _file_item("../escape.md", b"nope\n")
    plan = StagingPlan(items={escaping.dest_relpath: escaping}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="escapes the tool tree"):
        dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())


def test_dir_override_inner_relpath_escaping_dir_is_rejected(tmp_path: Path) -> None:
    """An override keyed by a ``..`` inner relpath is refused — a carrier/
    extension byte map must not escape its own DIR destination."""
    src = tmp_path / "src" / "skills" / "demo"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_bytes(b"base\n")
    target = tmp_path / "dump"
    dest = Path("skills/demo")
    plan = StagingPlan(
        items={dest: _dir_item(src, "skills/demo")},
        tool=Tool.CLAUDE,
        dir_overrides={dest: {Path("../escape.md"): b"nope\n"}},
    )

    with pytest.raises(ValueError, match="escapes the dir"):
        dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())


def test_non_empty_target_is_refused(tmp_path: Path) -> None:
    """A pre-existing, non-empty ``target`` is refused before any write — the
    dump must faithfully equal the plan, so stale files from a prior run (which
    ``copytree(dirs_exist_ok=True)`` would silently merge under) cannot be left
    to misrepresent it."""
    target = tmp_path / "dump"
    target.mkdir()
    (target / "leftover.txt").write_bytes(b"stale\n")
    plan = StagingPlan(items={Path("AGENTS.md"): _file_item("AGENTS.md", b"x\n")}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="not empty"):
        dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())


def test_file_target_is_refused_as_value_error(tmp_path: Path) -> None:
    """A ``target`` that exists but is a *file* (or symlink to one) is refused as
    a ``ValueError`` — not the ``NotADirectoryError`` that an unguarded
    ``iterdir()`` would raise. The CLI only catches ``ValueError``, so this is
    what keeps a ``--dump-stage <file>`` invocation a clean exit 2 instead of an
    uncaught traceback."""
    target = tmp_path / "dump"
    target.write_bytes(b"i am a file, not a dir\n")
    plan = StagingPlan(items={Path("AGENTS.md"): _file_item("AGENTS.md", b"x\n")}, tool=Tool.CLAUDE)

    with pytest.raises(ValueError, match="not a directory"):
        dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())


def test_empty_existing_target_is_accepted(tmp_path: Path) -> None:
    """An existing but empty ``target`` is fine — only non-empty is refused, so
    an operator can pre-create the directory."""
    target = tmp_path / "dump"
    target.mkdir()
    plan = StagingPlan(items={Path("AGENTS.md"): _file_item("AGENTS.md", b"x\n")}, tool=Tool.CLAUDE)

    dump_plan({Tool.CLAUDE: plan}, target, io=ScriptedIO())

    assert (target / "claude" / "AGENTS.md").read_bytes() == b"x\n"
