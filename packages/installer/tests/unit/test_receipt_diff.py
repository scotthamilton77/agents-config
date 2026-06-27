from pathlib import Path

import pytest

from installer.core.model import Orphan
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_diff import diff_orphans, scope_owners, validate_entry


def _entry(path: str, owner: str, root: str, kind: str = "file") -> ReceiptEntry:
    return ReceiptEntry(Path(path), owner, Path(root), kind, None)  # type: ignore[arg-type]


def test_dropped_entry_becomes_orphan() -> None:
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(
            _entry(".claude/skills/keep", "claude", ".claude", "dir"),
            _entry(".claude/skills/drop", "claude", ".claude", "dir"),
        ),
    )
    desired = {("claude", Path(".claude/skills/keep"))}
    orphans = diff_orphans(
        prior,
        desired_keys=desired,
        scope_owners={"claude"},
        home=Path("/home/u"),
        live_roots_by_owner={"claude": {Path(".claude")}},
        allowlist=set(),
    )
    assert [o.path for o in orphans] == [Path("/home/u/.claude/skills/drop")]
    assert orphans[0].tool == "claude"
    assert orphans[0].namespace == "skills"  # single-segment root: first seg after root
    assert isinstance(orphans[0], Orphan)


def test_orphan_namespace_relative_to_multi_segment_root() -> None:
    """An owner whose root has multiple path segments (OpenCode installs under
    ``.config/opencode``) groups orphans under the real namespace (``skills``),
    not the root's tail (``opencode``). Pins the namespace derivation relative
    to the recorded root, not the fixed ``path.parts[1]`` index.
    """
    prior = Receipt(
        roots=(Path(".config/opencode"),),
        entries=(_entry(".config/opencode/skills/x", "opencode", ".config/opencode", "dir"),),
    )
    orphans = diff_orphans(
        prior,
        desired_keys=set(),
        scope_owners={"opencode"},
        home=Path("/home/u"),
        live_roots_by_owner={"opencode": {Path(".config/opencode")}},
        allowlist=set(),
    )
    assert [o.path for o in orphans] == [Path("/home/u/.config/opencode/skills/x")]
    assert orphans[0].namespace == "skills"


def test_untargeted_owner_is_untouched() -> None:
    prior = Receipt(
        roots=(Path(".codex"),),
        entries=(_entry(".codex/skills/x", "codex", ".codex", "dir"),),
    )
    orphans = diff_orphans(
        prior,
        desired_keys=set(),
        scope_owners={"claude"},
        home=Path("/home/u"),
        live_roots_by_owner={},
        allowlist=set(),
    )
    assert orphans == []


def test_scope_includes_retired_plugin_excludes_untargeted_tool() -> None:
    prior = Receipt(
        entries=(
            _entry(".beads/formulas/old.toml", "beads", ".beads"),
            _entry(".codex/skills/x", "codex", ".codex", "dir"),
        )
    )
    owners = scope_owners({"claude"}, set(), prior)
    assert "claude" in owners  # resolved tool
    assert "beads" in owners  # retired plugin owner (not a tool name)
    assert "codex" not in owners  # untargeted tool -> preserved


def test_scope_includes_discovered_plugin() -> None:
    assert scope_owners({"claude"}, {"beads"}, Receipt()) == {"claude", "beads"}


def test_scope_excludes_discovered_plugin_colliding_with_tool_name() -> None:
    """A discovered plugin whose name collides with a tool (the repo ships both a
    ``codex`` tool and a ``src/plugins/codex`` plugin) must not pull the codex TOOL's
    recorded entries into scope on a run that did not target the codex tool. Tool
    owners are scoped only by ``resolved_tools``; the generic plugin overlays into
    the tool tree and owns nothing under that name itself, so dropping the collision
    loses no prune target while keeping an untargeted tool's entries out of scope.
    """
    prior = Receipt(entries=(_entry(".codex/skills/x", "codex", ".codex", "dir"),))
    # codex plugin discovered, codex tool NOT targeted (only claude resolved)
    owners = scope_owners({"claude"}, {"codex"}, prior)
    assert "claude" in owners
    assert "codex" not in owners  # collision: codex tool entry stays out of scope -> preserved


def test_retired_plugin_entry_is_orphaned_when_in_scope() -> None:
    prior = Receipt(entries=(_entry(".beads/formulas/old.toml", "beads", ".beads"),))
    owners = scope_owners(set(), {"beads"}, prior)
    orphans = diff_orphans(
        prior,
        desired_keys=set(),
        scope_owners=owners,
        home=Path("/home/u"),
        live_roots_by_owner={},
        allowlist={Path(".beads")},
    )
    assert [o.path for o in orphans] == [Path("/home/u/.beads/formulas/old.toml")]
    assert orphans[0].tool == "beads"


def test_diff_skips_invalid_entry_when_validation_supplied() -> None:
    """A recorded entry that fails validate_entry (here: claude forging codex's
    root) is skipped, not orphaned, when diff_orphans is given the validation
    inputs. Pins the validate-gated continue: an unsafe recorded entry is never
    handed to the prune step, even though it is in scope and not in desired_keys.
    """
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(_entry(".codex/skills/x", "claude", ".codex", "dir"),),  # forged root
    )
    orphans = diff_orphans(
        prior,
        desired_keys=set(),
        scope_owners={"claude"},
        home=Path("/home/u"),
        live_roots_by_owner={"claude": {Path(".claude")}},
        allowlist={Path(".claude")},
    )
    assert orphans == []


def test_validate_accepts_legit_tool_entry() -> None:
    e = _entry(".claude/skills/x", "claude", ".claude", "dir")
    assert validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )


def test_validate_rejects_dotdot_path() -> None:
    e = _entry("../evil", "claude", ".claude", "file")
    assert not validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )


def test_validate_rejects_dotdot_root() -> None:
    """A structurally unsafe ROOT (a ``..`` component) is rejected before any
    filesystem resolution — the path can look fine while the root escapes home.
    """
    e = _entry(".claude/skills/x", "claude", "../.claude", "dir")
    assert not validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )


def test_validate_rejects_forged_tool_root() -> None:
    e = _entry(".codex/skills/x", "claude", ".codex", "dir")  # claude claiming codex's root
    assert not validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )


def test_validate_accepts_retired_root_in_allowlist() -> None:
    e = _entry(".beads/formulas/x", "beads", ".beads", "file")
    assert validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={}, allowlist={Path(".beads")}
    )


def test_validate_rejects_retired_root_not_in_allowlist() -> None:
    e = _entry(".beads/formulas/x", "beads", ".beads", "file")
    assert not validate_entry(e, home=Path("/home/u"), live_roots_by_owner={}, allowlist=set())


def test_validate_active_plugin_retired_route_root_via_allowlist() -> None:
    """An ACTIVE plugin (present in live_roots_by_owner) that has dropped/relocated a
    route root still has its old recorded root validated via the integrity-gated
    allowlist — so previously-routed files are pruned, not stranded. Pins the
    plugin-owner allowlist fallback even when the owner HAS a live (non-None) root set
    that no longer contains the retired root.
    """
    e = _entry(".beads/scripts/old.sh", "beads", ".beads", "file")
    assert validate_entry(
        e,
        home=Path("/home/u"),
        live_roots_by_owner={"beads": {Path(".beadsv2")}},  # active, but .beads route dropped
        allowlist={Path(".beads")},  # prior recorded root persists
    )


def test_validate_tool_root_not_laundered_via_allowlist() -> None:
    """A TOOL owner's root is NEVER validated against the allowlist: even if a forged
    `.ssh` root sits in the (integrity-gated) allowlist, claude's live root is `.claude`,
    so the entry is rejected. Pins the asymmetry with the plugin-owner fallback — the
    tool security boundary (round-4) must not be weakened by the new fallback.
    """
    e = _entry(".ssh/x", "claude", ".ssh", "file")
    assert not validate_entry(
        e,
        home=Path("/home/u"),
        live_roots_by_owner={"claude": {Path(".claude")}},
        allowlist={Path(".ssh")},  # present in allowlist, but tools ignore it
    )


def test_validate_rejects_symlink_escape(tmp_path: Path) -> None:
    # home/.claude/link -> outside; an entry under .claude/link escapes .claude once resolved
    home = tmp_path
    (home / ".claude").mkdir()
    outside = tmp_path.parent / "outside_target"
    outside.mkdir()
    (home / ".claude" / "link").symlink_to(outside, target_is_directory=True)
    e = _entry(".claude/link/x", "claude", ".claude", "file")
    assert not validate_entry(
        e, home=home, live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )


def test_validate_entry_fails_closed_on_resolve_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # .resolve() can raise OSError (symlink loops / permission / transient FS
    # errors). The entry must be skipped (return False), never crash the prune.
    def boom(*_args: object, **_kwargs: object) -> Path:  # matches Path.resolve
        raise OSError

    monkeypatch.setattr(Path, "resolve", boom)
    e = _entry(".claude/skills/x", "claude", ".claude", "dir")
    assert not validate_entry(
        e, home=Path("/home/u"), live_roots_by_owner={"claude": {Path(".claude")}}, allowlist=set()
    )
