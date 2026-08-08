"""The canonical namespace vocabulary (core/namespaces.py) and its per-concern
views.

Each assertion pins a divergence-adjudication decision from the vocabulary
consolidation: which namespaces belong to each view, and — for the deliberate
exclusions — that the exclusion holds. The *behavioral* consequences
(staging/prune/backup) are pinned by those modules' own tests; here we pin the
vocabulary itself, the coherence invariants across views, and that the public
call sites consume the canonical object rather than re-declaring their own list.
"""

from __future__ import annotations

from installer.core import namespaces


def test_all_is_the_full_namespace_universe() -> None:
    assert (
        frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows"}) == namespaces.ALL
    )


def test_tool_scoped_view() -> None:
    # Namespaces a tool stages into its own config tree (staging Phase 4);
    # ClaudeAdapter.scoped_namespaces() returns exactly this.
    assert namespaces.TOOL_SCOPED == (
        "commands",
        "skills",
        "agents",
        "rules",
        "hooks",
        "workflows",
    )


def test_shared_view() -> None:
    # Shared namespaces staged from src/user/.agents (Phase 2) and overlaid from
    # each plugin's .agents. commands excluded — shared content is tool-agnostic
    # and there are no shared commands.
    assert namespaces.SHARED == ("skills", "agents", "rules")


def test_shared_carrier_view() -> None:
    # The shared namespaces whose DIR units can carrier-merge. rules excluded: it
    # holds files, not dirs, so it never carrier-merges.
    assert frozenset({"skills", "agents"}) == namespaces.SHARED_CARRIER


def test_plugin_tool_scoped_view() -> None:
    # Plugin tool-scope overlay namespaces. v1 plugins ship only rules; hooks and
    # workflows are intentionally not overlaid from plugins (plugin-authored
    # executables/workflows are a deferred expansion).
    assert namespaces.PLUGIN_TOOL_SCOPED == ("commands", "skills", "agents", "rules")


def test_prune_view() -> None:
    # Receipt-recorded, prune-eligible tool-tree namespaces. hooks included — see
    # test_hooks_is_staged_and_pruned_and_backed_up. Routed content is tracked via
    # the plugin-route receipt path, which never consults this set.
    assert namespaces.PRUNE == ("commands", "skills", "agents", "rules", "hooks", "workflows")


def test_backup_view() -> None:
    # Namespaces whose backups route to a sibling <ns>-backup/ dir (else an
    # in-place suffix). hooks included — an overwritten hook is backed up too, not
    # lost.
    assert (
        frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows"})
        == namespaces.BACKUP
    )


def test_every_view_is_a_subset_of_the_vocabulary() -> None:
    for view in (
        namespaces.TOOL_SCOPED,
        namespaces.SHARED,
        namespaces.SHARED_CARRIER,
        namespaces.PLUGIN_TOOL_SCOPED,
        namespaces.PRUNE,
        namespaces.BACKUP,
    ):
        assert set(view) <= namespaces.ALL


def test_shared_carrier_is_a_subset_of_shared() -> None:
    assert set(namespaces.SHARED) >= namespaces.SHARED_CARRIER


def test_hooks_is_staged_and_pruned_and_backed_up() -> None:
    """hooks is a tool-scoped, deployed namespace (src/user/.claude/hooks/ ->
    ~/.claude/hooks/) that IS receipt-tracked and sibling-backed-up: a
    removed-source hook is pruned on the next install, and an overwritten hook
    is backed up to a sibling ``hooks-backup/`` dir rather than lost — the
    identical fix already applied to ``workflows`` (see test_workflows_namespace).
    The full prune/backup behavior is pinned end-to-end in
    test_hooks_prune_and_backup.py; this pins the vocabulary membership only.
    """
    assert "hooks" in namespaces.TOOL_SCOPED
    assert "hooks" in namespaces.PRUNE
    assert "hooks" in namespaces.BACKUP


def test_backup_carries_no_namespace_the_installer_does_not_stage() -> None:
    """Every backup-routed namespace is one this installer actually stages.

    ``core/backup.py`` matches BACKUP by the target's parent DIRECTORY NAME, so a
    member with no staged namespace behind it silently relocates the backup of any
    file that happens to sit under a directory of that name — for a directory this
    installer never creates. The vocabulary held exactly one such member (a
    namespace a since-deleted plugin adapter routed to a non-tool root); nothing
    replaced it, and this pins that BACKUP does not re-acquire an unstaged member
    without the reasoning being restated.

    What removes this guard: a route producer whose ``dest_dir`` names a directory
    that genuinely wants sibling-dir backups rather than in-place ones. Then this
    assertion is the wrong shape, not merely failing.
    """
    assert set(namespaces.TOOL_SCOPED) == namespaces.BACKUP


def test_claude_scoped_namespaces_consumes_canonical_tool_scoped() -> None:
    # The consolidation's whole point: the Claude adapter's tool-scope list is the
    # canonical object, not a re-declared copy.
    from installer.tools.claude import ClaudeAdapter

    assert ClaudeAdapter().scoped_namespaces() is namespaces.TOOL_SCOPED


def test_ownership_prune_namespaces_consumes_canonical_prune() -> None:
    from installer.core import ownership

    assert ownership.PRUNE_NAMESPACES is namespaces.PRUNE
