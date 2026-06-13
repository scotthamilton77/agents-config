"""Unit tests for installer.core.prune (G.3 — orphan scan).

Each test pins a coded decision in ``scan_orphans``, the port of the bash
orphan scan (``scripts/install.sh:1505-1543``):
- a dest entry absent from the plan AND matching a prune glob is an orphan,
- a dest entry absent from the plan but matching NO glob is left alone,
- a dest entry present in the plan is never an orphan (even if a glob matches),
- ``*.backup-*`` legacy entries are skipped,
- dir vs file kind is classified from the filesystem entry,
- a ``*/...`` glob matches across tools; a ``claude/...`` glob is tool-scoped,
- ``~/.beads/formulas`` is scanned even with no beads plan present (strict mode).

The fnmatch semantics themselves are stdlib and not under test; what is pinned
is the key shape (``tool/namespace/basename``), the plan-membership exclusion,
the backup skip, and the kind classification.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.installer_toml import InstallerToml
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.prune import scan_orphans


class _ClaudeLikeAdapter:
    """Minimal ToolAdapter double: dest_dir is ``home/.claude`` and the scoped
    namespaces match Claude. The scan only consults ``name``, ``dest_dir``, and
    ``scoped_namespaces``; the rest are inert."""

    name: str = "claude"
    detection_signal: str = ".claude/settings.json"

    def source_dir(self, repo_root: Path) -> Path:
        return repo_root

    def dest_dir(self, home: Path) -> Path:
        return home / ".claude"

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert stub
        return True

    def scoped_namespaces(self) -> tuple[str, ...]:
        return ("commands", "skills", "agents", "rules")

    def should_install_namespace(self, namespace: str, source: str) -> bool:  # noqa: ARG002
        return True

    def post_staging_transforms(self, plan: StagingPlan, io: object) -> StagingPlan:  # noqa: ARG002
        return plan


def _empty_plan() -> StagingPlan:
    return StagingPlan(items={}, tool=Tool.CLAUDE)


def _staged_dir(namespace: str, name: str) -> StagedItem:
    return StagedItem(
        source_path=Path("/src") / namespace / name,
        dest_relpath=Path(namespace) / name,
        kind=FileKind.DIR,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
    )


def _make_dest_dir(home: Path, namespace: str, name: str) -> Path:
    d = home / ".claude" / namespace / name
    d.mkdir(parents=True)
    return d


def test_unstaged_entry_matching_glob_is_orphan(tmp_path: Path) -> None:
    """
    Given a dest skills/ entry absent from the plan and matching a prune glob
    When scan_orphans runs
    Then exactly that entry is returned as a dir orphan tagged claude/skills.
    """
    _make_dest_dir(tmp_path, "skills", "retired-skill")
    config = InstallerToml(prune_globs=["*/skills/retired-skill"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: _empty_plan()}, home=tmp_path, config=config
    )

    assert [(o.tool, o.namespace, o.path.name, o.kind) for o in orphans] == [
        ("claude", "skills", "retired-skill", "dir")
    ]


def test_unstaged_entry_not_matching_any_glob_is_not_orphan(tmp_path: Path) -> None:
    """
    Given a dest entry absent from the plan but matching no prune glob
    When scan_orphans runs
    Then it is not reported (a non-listed extra is left in place).
    """
    _make_dest_dir(tmp_path, "skills", "some-other-skill")
    config = InstallerToml(prune_globs=["*/skills/retired-skill"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: _empty_plan()}, home=tmp_path, config=config
    )

    assert orphans == []


def test_staged_entry_is_never_orphan_even_when_glob_matches(tmp_path: Path) -> None:
    """
    Given a dest entry that IS in the plan and would match a glob
    When scan_orphans runs
    Then it is not reported — plan membership wins over the glob.
    """
    _make_dest_dir(tmp_path, "skills", "kept-skill")
    plan = _empty_plan()
    plan.items[Path("skills/kept-skill")] = _staged_dir("skills", "kept-skill")
    config = InstallerToml(prune_globs=["*/skills/kept-skill"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: plan}, home=tmp_path, config=config
    )

    assert orphans == []


def test_legacy_backup_entry_is_skipped(tmp_path: Path) -> None:
    """
    Given a dest entry whose name carries the legacy .backup- marker
    When scan_orphans runs
    Then it is skipped even though it is unstaged and would match a glob.
    """
    _make_dest_dir(tmp_path, "skills", "old-skill.backup-20250101-000000")
    config = InstallerToml(prune_globs=["*/skills/*"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: _empty_plan()}, home=tmp_path, config=config
    )

    assert orphans == []


def test_file_entry_classified_as_file_kind(tmp_path: Path) -> None:
    """
    Given an unstaged dest rules/ FILE matching a glob
    When scan_orphans runs
    Then the orphan's kind is "file", not "dir".
    """
    (tmp_path / ".claude" / "rules").mkdir(parents=True)
    (tmp_path / ".claude" / "rules" / "git-commits.md").write_text("x")
    config = InstallerToml(prune_globs=["claude/rules/git-commits.md"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: _empty_plan()}, home=tmp_path, config=config
    )

    assert [o.kind for o in orphans] == ["file"]


def test_tool_scoped_glob_does_not_match_other_tool(tmp_path: Path) -> None:
    """
    Given a claude/-prefixed glob and a dest entry under the claude tree
    When scan_orphans runs for an adapter whose name is NOT claude
    Then the entry is not matched (the glob is tool-scoped by its first segment).
    """

    class _CodexLikeAdapter(_ClaudeLikeAdapter):
        name: str = "codex"

        def dest_dir(self, home: Path) -> Path:
            return home / ".codex"

    (tmp_path / ".codex" / "rules").mkdir(parents=True)
    (tmp_path / ".codex" / "rules" / "git-commits.md").write_text("x")
    config = InstallerToml(prune_globs=["claude/rules/git-commits.md"])

    orphans = scan_orphans(
        [_CodexLikeAdapter()], plans={Tool.CODEX: _empty_plan()}, home=tmp_path, config=config
    )

    assert orphans == []


def test_beads_formulas_scanned_with_no_beads_plan(tmp_path: Path) -> None:
    """
    Given a ~/.beads/formulas entry and no beads content in any plan
    When scan_orphans runs
    Then the formula is flagged as a beads/formulas orphan (strict mode):
    nothing staged it, so it is an orphan if a glob matches.
    """
    (tmp_path / ".beads" / "formulas").mkdir(parents=True)
    (tmp_path / ".beads" / "formulas" / "stale.toml").write_text("x")
    config = InstallerToml(prune_globs=["beads/formulas/*"])

    orphans = scan_orphans(
        [_ClaudeLikeAdapter()], plans={Tool.CLAUDE: _empty_plan()}, home=tmp_path, config=config
    )

    assert [(o.tool, o.namespace, o.path.name) for o in orphans] == [
        ("beads", "formulas", "stale.toml")
    ]
