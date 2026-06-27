"""Unit tests for the per-item ``InstallOutcome`` stream threaded through
``sync_plan`` (Task 8 — outcome plumbing).

``Counters.skipped`` conflates a hash-equal skip with a consent-declined
overwrite; the receipt must tell them apart (a DECLINED item holds the user's
bytes and must never be recorded). ``sync_plan`` grows an optional ``outcomes``
collector that records one ``InstallOutcome`` per item, distinguishing WRITTEN /
SKIPPED_IDENTICAL / DECLINED while leaving the ``Counters`` tallies unchanged.

Each test pins a coded decision and drives the engine through ``ScriptedIO`` +
the real filesystem under ``tmp_path``. The adapter is a minimal identity double
so a test controls the dest root directly via ``home`` — mirroring
``test_sync_plan.py`` and independent of any real tool's path layout.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from installer.core.io_port import IOPort, ScriptedIO
from installer.core.model import (
    FileKind,
    InstallOutcome,
    Outcome,
    Provenance,
    StagedItem,
    StagingPlan,
    Tool,
)
from installer.core.sync import sync_plan

_FIXED_TS = "20260613-120000"


class _IdentityAdapter:
    """Minimal ToolAdapter double. ``dest_dir`` is an identity pass-through so a
    test controls the real dest root via ``sync_plan``'s ``home`` argument. The
    remaining protocol members are inert — ``sync_plan`` consults only
    ``dest_dir``."""

    name: str = "claude"
    detection_signal: str = ".fake"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root

    def dest_dir(self, home: Path) -> Path:
        return home

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


def _file_item(relpath: Path, content: bytes) -> StagedItem:
    """A FILE ``StagedItem`` carrying eager ``content`` (``source_path`` unused
    for file items — bytes are in memory, not re-read from disk)."""
    return StagedItem(
        source_path=Path("/unused/for/file/items") / relpath,
        dest_relpath=relpath,
        kind=FileKind.OTHER,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def _one_file_plan(relpath: Path, content: bytes) -> StagingPlan:
    return StagingPlan(items={relpath: _file_item(relpath, content)}, tool=Tool.CLAUDE)


def test_created_file_yields_written_outcome_with_sha256(tmp_path: Path) -> None:
    """
    Given a FILE item whose dest is absent (a first install)
    When sync_plan walks it with an outcomes collector
    Then exactly one Outcome.WRITTEN is recorded, naming the absolute dest and
    carrying the file's hex sha256.
    """
    home = tmp_path / "home"  # absent — first install
    plan = _one_file_plan(Path("rules/a.md"), b"alpha\n")
    outcomes: list[InstallOutcome] = []

    sync_plan(
        _IdentityAdapter(),
        plan,
        home=home,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
        outcomes=outcomes,
    )

    assert outcomes == [
        InstallOutcome(
            home / "rules" / "a.md",
            Outcome.WRITTEN,
            hashlib.sha256(b"alpha\n").hexdigest(),
        )
    ]


def test_identical_rerun_yields_skipped_identical_with_sha256(tmp_path: Path) -> None:
    """
    Given a dest already holding the item's bytes (a hash-equal skip)
    When sync_plan walks it with an outcomes collector
    Then exactly one Outcome.SKIPPED_IDENTICAL is recorded with the file's hex
    sha256 — distinct from a DECLINED skip even though both bump Counters.skipped.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.md").write_bytes(b"same\n")
    plan = _one_file_plan(Path("f.md"), b"same\n")
    outcomes: list[InstallOutcome] = []

    sync_plan(
        _IdentityAdapter(),
        plan,
        home=home,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
        outcomes=outcomes,
    )

    assert outcomes == [
        InstallOutcome(
            home / "f.md", Outcome.SKIPPED_IDENTICAL, hashlib.sha256(b"same\n").hexdigest()
        )
    ]


def test_declined_overwrite_yields_declined_and_keeps_user_bytes(tmp_path: Path) -> None:
    """
    Given an existing dest whose bytes differ from the staged item
    When the interactive overwrite confirm is declined
    Then exactly one Outcome.DECLINED (sha256 None) is recorded AND the dest
    keeps the user's bytes — the receipt must never record a file the user chose
    to keep.
    """
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.md").write_bytes(b"user-edited\n")
    plan = _one_file_plan(Path("f.md"), b"incoming\n")
    outcomes: list[InstallOutcome] = []
    io = ScriptedIO(confirms=[False])  # decline the overwrite

    sync_plan(
        _IdentityAdapter(),
        plan,
        home=home,
        io=io,
        timestamp=_FIXED_TS,
        outcomes=outcomes,
    )

    assert outcomes == [InstallOutcome(home / "f.md", Outcome.DECLINED, None)]
    assert (home / "f.md").read_bytes() == b"user-edited\n"


def test_counters_identical_with_outcomes_none_and_empty_list(tmp_path: Path) -> None:
    """
    Given the same mixed scenario (a create, a skip, and a declined overwrite)
    When sync_plan runs once with outcomes=None and once with outcomes=[]
    Then the returned Counters are equal — the outcomes stream is purely
    additive and never perturbs the existing tallies.
    """

    def _scenario(home: Path) -> StagingPlan:
        home.mkdir()
        (home / "identical.md").write_bytes(b"same\n")  # -> SKIPPED_IDENTICAL
        (home / "changed.md").write_bytes(b"user\n")  # -> DECLINED
        return StagingPlan(
            items={
                Path("new.md"): _file_item(Path("new.md"), b"fresh\n"),  # -> WRITTEN
                Path("identical.md"): _file_item(Path("identical.md"), b"same\n"),
                Path("changed.md"): _file_item(Path("changed.md"), b"incoming\n"),
            },
            tool=Tool.CLAUDE,
        )

    home_none = tmp_path / "none"
    counters_none = sync_plan(
        _IdentityAdapter(),
        _scenario(home_none),
        home=home_none,
        io=ScriptedIO(confirms=[False]),
        timestamp=_FIXED_TS,
        outcomes=None,
    )

    home_list = tmp_path / "list"
    counters_list = sync_plan(
        _IdentityAdapter(),
        _scenario(home_list),
        home=home_list,
        io=ScriptedIO(confirms=[False]),
        timestamp=_FIXED_TS,
        outcomes=[],
    )

    assert counters_none == counters_list
