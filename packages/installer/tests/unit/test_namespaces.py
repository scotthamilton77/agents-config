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
        frozenset({"commands", "skills", "agents", "rules", "hooks", "workflows", "formulas"})
        == namespaces.ALL
    )


def test_tool_scoped_view() -> None:
    # Namespaces a tool stages into its own config tree (staging Phase 4);
    # ClaudeAdapter.scoped_namespaces() returns exactly this. formulas excluded —
    # it is plugin-routed to a non-tool root, never a tool-tree dir.
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
    # test_hooks_is_staged_and_pruned_and_backed_up. formulas absent: it is
    # plugin-routed and tracked via the plugin-route receipt path, not this set.
    assert namespaces.PRUNE == ("commands", "skills", "agents", "rules", "hooks", "workflows")


def test_backup_view() -> None:
    # Namespaces whose backups route to a sibling <ns>-backup/ dir (else an
    # in-place suffix). formulas included — overwritten plugin-route content still
    # gets a sibling-dir backup; hooks included — an overwritten hook is backed up
    # too, not lost.
    assert (
        frozenset({"commands", "skills", "agents", "rules", "hooks", "formulas", "workflows"})
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


def test_formulas_is_plugin_routed_backup_only() -> None:
    """formulas is a plugin-routed namespace (beads -> ~/.beads/formulas), never a
    tool-tree dir: absent from TOOL_SCOPED and PRUNE, present in BACKUP so an
    overwritten route file still gets a sibling-dir backup.
    """
    assert "formulas" not in namespaces.TOOL_SCOPED
    assert "formulas" not in namespaces.PRUNE
    assert "formulas" in namespaces.BACKUP


def test_claude_scoped_namespaces_consumes_canonical_tool_scoped() -> None:
    # The consolidation's whole point: the Claude adapter's tool-scope list is the
    # canonical object, not a re-declared copy.
    from installer.tools.claude import ClaudeAdapter

    assert ClaudeAdapter().scoped_namespaces() is namespaces.TOOL_SCOPED


def test_ownership_prune_namespaces_consumes_canonical_prune() -> None:
    from installer.core import ownership

    assert ownership.PRUNE_NAMESPACES is namespaces.PRUNE
