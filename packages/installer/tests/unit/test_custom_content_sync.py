"""Installing an instruction file that carries the custom-content heading.

The merge itself is pinned in ``test_custom_content.py``; these tests pin the
wiring around it — that the install refuses the whole run when a managed part was
edited, that it refuses it under a dry run too, and that an ordinary re-install
preserves the user's tail through the consent gate, the backup, and the
hash-equal skip on the run after.

Each test drives the real engine through ``ScriptedIO`` and the real filesystem
under ``tmp_path``, with the minimal identity adapter of ``test_sync_outcomes.py``
so a test controls the dest root via ``home``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from installer.core.custom_content import HEADING, CustomContentConflictError
from installer.core.io_port import IOPort, ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.run import install_pipeline
from installer.core.sync import sync_plan

_FIXED_TS = "20260613-120000"

# The managed part is every byte above the heading line, blank separator
# included — the template's own shape, and what the digest covers.
_MANAGED = "# Instructions\n\nrule one\n\n"
_INCOMING = f"{_MANAGED}{HEADING}\n".encode()
_INSTRUCTION = Path("AGENTS.md")


class _IdentityAdapter:
    """Minimal ToolAdapter double whose ``dest_dir`` is an identity pass-through,
    so a test controls the real dest root via ``home``. ``name`` is settable so
    two of them can stand for two tools in one run."""

    detection_signal: str = ".fake"

    def __init__(self, name: str = "claude", subdir: str = "") -> None:
        self.name = name
        self._subdir = subdir

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root

    def dest_dir(self, home: Path) -> Path:
        return home / self._subdir if self._subdir else home

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert stub
        return True

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ()

    def should_install_namespace(
        self,
        namespace: str,  # noqa: ARG002  # inert stub
        source: str,  # noqa: ARG002  # inert stub
    ) -> bool:
        return True

    def post_staging_transforms(
        self,
        plan: StagingPlan,
        io: IOPort,  # noqa: ARG002  # inert stub
    ) -> StagingPlan:
        return plan


def _plan(tool: Tool, content: bytes = _INCOMING) -> StagingPlan:
    item = StagedItem(
        source_path=Path("/unused/for/file/items") / _INSTRUCTION,
        dest_relpath=_INSTRUCTION,
        kind=FileKind.OTHER,
        namespace=None,
        provenance=Provenance(kind="tool", name=tool.value),
        content=content,
    )
    return StagingPlan(items={_INSTRUCTION: item}, tool=tool)


def _stamped(managed: str) -> str:
    return (
        f"{HEADING} <!-- the installer rewrites everything above this line "
        f"and nothing below it; "
        f"digest {hashlib.sha256(managed.encode('utf-8')).hexdigest()[:12]} -->\n"
    )


def _tampered_file(path: Path) -> None:
    """Write a destination whose managed part gained a line after the installer
    stamped its heading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _MANAGED + "hand-typed\n" + _stamped(_MANAGED) + "\nmine\n",
        encoding="utf-8",
    )


def _two_tool_run(tmp_path: Path) -> tuple[list[_IdentityAdapter], dict[Tool, StagingPlan], Path]:
    """Two adapters installing into two subdirectories of one home, the first
    tool's destination tampered with and the second's untouched."""
    home = tmp_path / "home"
    adapters = [
        _IdentityAdapter(name="claude", subdir=".claude"),
        _IdentityAdapter(name="codex", subdir=".codex"),
    ]
    plans = {Tool.CLAUDE: _plan(Tool.CLAUDE), Tool.CODEX: _plan(Tool.CODEX)}
    _tampered_file(home / ".claude" / _INSTRUCTION)
    return adapters, plans, home


def test_a_tampered_file_leaves_every_tool_in_the_run_unwritten(tmp_path: Path) -> None:
    """
    Given a two-tool run where one tool's destination was edited above the heading
    When the install pipeline runs
    Then it raises before the first write, the offending absolute path is named,
    and the OTHER tool's destination is never created — the verdict spans the run
    rather than stopping at the tool that tripped.
    """
    adapters, plans, home = _two_tool_run(tmp_path)
    before = (home / ".claude" / _INSTRUCTION).read_bytes()
    io = ScriptedIO()

    with pytest.raises(CustomContentConflictError) as raised:
        install_pipeline(adapters, plans=plans, home=home, io=io, auto_yes=True)

    assert raised.value.paths == (home / ".claude" / _INSTRUCTION,)
    assert str(home / ".claude" / _INSTRUCTION) in "".join(
        entry.message for entry in io.transcript if entry.channel == "err"
    )
    assert (home / ".claude" / _INSTRUCTION).read_bytes() == before
    assert not (home / ".codex").exists()


def test_a_tampered_file_fails_a_dry_run_too(tmp_path: Path) -> None:
    """
    Given the same two-tool run
    When it is previewed with dry_run
    Then it fails identically. A preview that reported a clean install the real
    run would refuse is worse than no preview.
    """
    adapters, plans, home = _two_tool_run(tmp_path)

    with pytest.raises(CustomContentConflictError):
        install_pipeline(adapters, plans=plans, home=home, io=ScriptedIO(), dry_run=True)

    assert not (home / ".codex").exists()


def test_reinstall_preserves_the_user_tail_and_restamps_the_heading(tmp_path: Path) -> None:
    """
    Given an installed instruction file with the user's own tail below the heading
    When a changed managed part is installed over it and the overwrite is confirmed
    Then the old file is backed up, the tail survives byte-for-byte, and the heading
    is re-stamped for the new managed part.
    """
    home = tmp_path / "home"
    home.mkdir()
    dest = home / _INSTRUCTION
    old_managed = "# Instructions\n\nolder rule\n\n"
    tail = "\n## my notes\n\nkeep me\n"
    dest.write_text(old_managed + _stamped(old_managed) + tail, encoding="utf-8")
    io = ScriptedIO(confirms=[True])  # the consent gate on a changed dest

    counters = sync_plan(
        _IdentityAdapter(), _plan(Tool.CLAUDE), home=home, io=io, timestamp=_FIXED_TS
    )

    assert counters.updated == 1
    assert counters.backed_up == 1
    assert dest.read_text(encoding="utf-8") == _MANAGED + _stamped(_MANAGED) + tail
    assert any(entry.channel == "confirm" for entry in io.transcript)


def test_a_second_install_of_the_same_template_is_a_hash_equal_skip(tmp_path: Path) -> None:
    """
    Given a destination the installer just wrote, tail and all
    When the same plan is installed again
    Then it is skipped as unchanged: the re-stamped heading reproduces the same
    digest, so a steady-state re-install prompts for nothing and backs up nothing.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / _INSTRUCTION).write_text(_MANAGED + _stamped(_MANAGED) + "\nmine\n", encoding="utf-8")

    counters = sync_plan(
        _IdentityAdapter(), _plan(Tool.CLAUDE), home=home, io=ScriptedIO(), timestamp=_FIXED_TS
    )

    assert counters.skipped == 1
    assert counters.updated == 0
    assert counters.backed_up == 0


def test_a_first_install_over_a_pre_heading_file_carries_it_down_and_says_so(
    tmp_path: Path,
) -> None:
    """
    Given a destination written before the heading existed, holding the user's own text
    When the instruction file is installed over it
    Then that text lands below the new heading and the move is reported, because the
    user has to review where it went.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / _INSTRUCTION).write_text("# Instructions\n\nmy own note\n", encoding="utf-8")
    io = ScriptedIO(confirms=[True])

    sync_plan(_IdentityAdapter(), _plan(Tool.CLAUDE), home=home, io=io, timestamp=_FIXED_TS)

    assert (home / _INSTRUCTION).read_text(encoding="utf-8") == (
        _MANAGED + _stamped(_MANAGED) + "\nmy own note\n"
    )
    assert any(entry.channel == "info" and HEADING in entry.message for entry in io.transcript)


def test_a_file_without_the_heading_is_installed_exactly_as_before(tmp_path: Path) -> None:
    """
    Given staged content that carries no heading
    When it is installed over an existing file
    Then the bytes are written through unchanged — the heading is the whole
    selector, so every other file's behaviour is untouched by this feature.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "notes.md").write_text("old\n", encoding="utf-8")
    plan = _plan(Tool.CLAUDE)
    item = plan.items[_INSTRUCTION]
    plan = StagingPlan(
        items={
            Path("notes.md"): StagedItem(
                source_path=item.source_path,
                dest_relpath=Path("notes.md"),
                kind=FileKind.OTHER,
                namespace=None,
                provenance=item.provenance,
                content=b"new\n",
            )
        },
        tool=Tool.CLAUDE,
    )

    sync_plan(
        _IdentityAdapter(), plan, home=home, io=ScriptedIO(confirms=[True]), timestamp=_FIXED_TS
    )

    assert (home / "notes.md").read_bytes() == b"new\n"
