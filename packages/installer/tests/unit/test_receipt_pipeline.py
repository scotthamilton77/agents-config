"""End-to-end tracer for receipt-based pruning via prune_pipeline.

Proves the architecture: a prior receipt plus a staging plan that drops one
entry -> the dropped entry is pruned and the returned PruneOutcome names it.
prune_pipeline is pure prune: it RECEIVES the prior receipt and RETURNS a
PruneOutcome (no receipt read, no receipt write). The receipt is the sole prune
authority (no globs); the caller writes it via record_receipt.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.receipt import Receipt, ReceiptEntry
from installer.core.receipt_store import read_receipt, write_receipt
from installer.core.run import prune_pipeline, record_receipt
from installer.tools.registry import get_adapter

_TS = "20250101-120000"


def _receipt_path(home: Path) -> Path:
    return home / ".config" / "agents-config" / "install-receipt.json"


def _claude_home(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    return tmp_path


def _skill_item(name: str) -> StagedItem:
    rel = Path("skills") / name
    return StagedItem(
        source_path=Path("/src") / rel,
        dest_relpath=rel,
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )


def _entry(relpath: str) -> ReceiptEntry:
    return ReceiptEntry(Path(relpath), "claude", Path(".claude"), "dir", None)


def test_dropped_entry_is_pruned_and_outcome_names_it(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    drop = home / ".claude" / "skills" / "drop"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(_entry(".claude/skills/keep"), _entry(".claude/skills/drop")),
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert keep.exists()
    assert not drop.exists()
    assert outcome.counters["claude"].pruned == 1
    assert outcome.pruned_paths == {Path(".claude/skills/drop")}


def test_missing_receipt_prunes_nothing(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    stray = home / ".claude" / "skills" / "stray"
    stray.mkdir(parents=True)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=Receipt(),
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert stray.exists()  # empty prior => nothing is an orphan
    assert outcome.counters == {}
    assert outcome.pruned_paths == set()


def test_no_orphans_clean_noop(tmp_path: Path) -> None:
    home = _claude_home(tmp_path)
    keep = home / ".claude" / "skills" / "keep"
    keep.mkdir(parents=True)
    prior = Receipt(roots=(Path(".claude"),), entries=(_entry(".claude/skills/keep"),))
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=True),
        timestamp=_TS,
    )

    assert keep.exists()
    assert outcome.counters == {}
    assert outcome.pruned_paths == set()


def test_retired_plugin_formula_pruned_via_receipt(tmp_path: Path) -> None:
    """Spec safety scenario 1: a fully-retired plugin's recorded formula is pruned.

    Beads was dropped from this run (``plugins=()``, ``discovered_plugin_names``
    empty), but the prior receipt records ``.beads/formulas/old.toml`` owned by
    ``beads`` with a sha matching the on-disk bytes. ``scope_owners`` pulls the
    retired ``beads`` owner back into scope; the ``.beads`` root must be in
    ``prior.roots`` so ``validate_entry``'s allowlist check passes for an owner with
    no live root this run. The orphan's bytes match the recorded sha, so it is
    deleted, not relinquished.

    Pins: a plugin we stopped shipping still gets its routed files pruned via the
    receipt — the persisted-roots allowlist is what authorizes the delete.
    """
    home = _claude_home(tmp_path)
    formula = home / ".beads" / "formulas" / "old.toml"
    formula.parent.mkdir(parents=True)
    formula_bytes = b"old = 1\n"
    formula.write_bytes(formula_bytes)
    prior = Receipt(
        roots=(Path(".claude"), Path(".beads")),
        entries=(
            ReceiptEntry(
                Path(".beads/formulas/old.toml"),
                "beads",
                Path(".beads"),
                "file",
                hashlib.sha256(formula_bytes).hexdigest(),
            ),
        ),
    )
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plugins=(),
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),  # fully retired
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not formula.exists()
    assert outcome.pruned_paths == {Path(".beads/formulas/old.toml")}
    assert outcome.relinquished_paths == set()


def test_active_plugin_shipped_formula_survives_retired_pruned(tmp_path: Path) -> None:
    import hashlib

    from installer.plugins.beads import BeadsPlugin

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # plugin source ships ONLY current.toml
    src = tmp_path / "src" / "plugins" / "beads"
    (src / ".beads" / "formulas").mkdir(parents=True)
    (src / ".beads" / "formulas" / "current.toml").write_bytes(b"shipped\n")
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)
    # on-disk dest holds current.toml AND a retired.toml
    formulas = home / ".beads" / "formulas"
    formulas.mkdir(parents=True)
    (formulas / "current.toml").write_bytes(b"shipped\n")
    (formulas / "retired.toml").write_bytes(b"stale\n")
    cur_sha = hashlib.sha256(b"shipped\n").hexdigest()
    ret_sha = hashlib.sha256(b"stale\n").hexdigest()
    rpath = _receipt_path(home)
    write_receipt(
        rpath,
        Receipt(
            roots=(Path(".beads"),),
            entries=(
                ReceiptEntry(
                    Path(".beads/formulas/current.toml"), "beads", Path(".beads"), "file", cur_sha
                ),
                ReceiptEntry(
                    Path(".beads/formulas/retired.toml"), "beads", Path(".beads"), "file", ret_sha
                ),
            ),
        ),
    )
    prior = read_receipt(rpath).receipt
    assert prior is not None
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plugins=[beads],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names={"beads"},
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert (formulas / "current.toml").exists()  # active formula spared
    assert not (formulas / "retired.toml").exists()  # no-longer-shipped formula pruned
    assert outcome.pruned_paths == {Path(".beads/formulas/retired.toml")}


def test_active_plugin_missing_route_source_preserves_recorded_files(tmp_path: Path) -> None:
    """An ACTIVE plugin whose route source dir is missing must NOT have its
    previously-installed files pruned: a missing source is a packaging/checkout
    anomaly, not a retirement. ``desired_route_keys`` contributes no keys for the
    missing route, so without the guard the prior entry would orphan and — bytes
    still matching the recorded sha — be deleted under ``--yes``.

    Pins the fail-closed guard: active plugin + missing route source => preserve the
    recorded files. Distinct from a fully *retired* plugin (``plugins=()``), which IS
    pruned via prior-receipt scope (test_retired_plugin_formula_pruned_via_receipt).
    """
    from installer.plugins.beads import BeadsPlugin

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # Plugin is ACTIVE / discovered, but its source tree has no formulas dir at all
    # (source_path exists; the .beads/formulas route source does not).
    src = tmp_path / "src" / "plugins" / "beads"
    src.mkdir(parents=True)
    beads = BeadsPlugin(name="beads", source_path=src, which=lambda _c: None)
    # On-disk dest still holds a file we installed on a prior run, with our bytes.
    formulas = home / ".beads" / "formulas"
    formulas.mkdir(parents=True)
    installed = formulas / "current.toml"
    installed.write_bytes(b"shipped\n")
    sha = hashlib.sha256(b"shipped\n").hexdigest()
    prior = Receipt(
        roots=(Path(".beads"),),
        entries=(
            ReceiptEntry(
                Path(".beads/formulas/current.toml"), "beads", Path(".beads"), "file", sha
            ),
        ),
    )
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plugins=[beads],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names={"beads"},  # ACTIVE, not retired
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert installed.exists()  # preserved despite matching sha — source skew is not retirement
    assert outcome.pruned_paths == set()


def test_plugin_named_like_tool_does_not_prune_untargeted_tool_entry(tmp_path: Path) -> None:
    """Regression for the codex tool/plugin name collision: a Claude-only prune with
    the codex plugin discovered (but the codex tool untargeted) must NOT delete a
    recorded ``.codex/...`` tool entry.

    The plain-string owner model unioned raw discovered plugin names into scope, so
    the codex plugin's discovery pulled the codex *tool*'s entries into scope; with
    ``.codex`` in the persisted roots allowlist, ``validate_entry`` then authorized
    their deletion. Pins the scoped-run safety invariant against the name collision.
    """
    home = _claude_home(tmp_path)
    cx = home / ".codex" / "skills" / "cx"
    cx.mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".claude"), Path(".codex")),  # .codex in allowlist (would validate)
        entries=(ReceiptEntry(Path(".codex/skills/cx"), "codex", Path(".codex"), "dir", None),),
    )
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plugins=(),  # codex plugin excluded via --plugins=
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names={"codex"},  # ...but the codex plugin is still DISCOVERED
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert cx.exists()  # untargeted codex TOOL entry preserved despite the name collision
    assert outcome.pruned_paths == set()


def test_codex_tool_entry_pruned_with_codex_plugin_active(tmp_path: Path) -> None:
    """The codex tool/plugin name collision must not DISABLE pruning of the codex
    TOOL's own entries. With the codex tool targeted AND the generic (route-less)
    codex plugin active, `live_roots_by_owner['codex']` must keep the tool's `.codex`
    root rather than be clobbered to the plugin's empty route set — otherwise a
    retired codex tool entry fails validation and survives as litter.

    Companion to test_plugin_named_like_tool_does_not_prune_untargeted_tool_entry
    (the *untargeted* half): there the collision must not over-prune; here it must
    not under-prune.
    """
    from installer.plugins.generic import GenericPluginAdapter

    home = tmp_path
    (home / ".codex").mkdir()
    old = home / ".codex" / "skills" / "old"
    old.mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".codex"),),
        entries=(ReceiptEntry(Path(".codex/skills/old"), "codex", Path(".codex"), "dir", None),),
    )
    plans = {Tool.CODEX: StagingPlan(items={}, tool=Tool.CODEX)}  # 'old' is retired (not staged)
    codex_plugin = GenericPluginAdapter(name="codex", source_path=tmp_path / "src")

    outcome = prune_pipeline(
        [get_adapter(Tool.CODEX)],
        plugins=[codex_plugin],  # codex PLUGIN active alongside the codex TOOL
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names={"codex"},
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not old.exists()  # codex tool entry pruned despite the plugin name collision
    assert outcome.pruned_paths == {Path(".codex/skills/old")}


def test_prune_pipeline_accepts_one_shot_adapters_iterator(tmp_path: Path) -> None:
    # The body iterates `adapters` several times; a one-shot generator must not be
    # exhausted after the first pass (that would silently disable pruning).
    home = _claude_home(tmp_path)
    drop = home / ".claude" / "skills" / "drop"
    drop.mkdir(parents=True)
    rpath = _receipt_path(home)
    write_receipt(
        rpath, Receipt(roots=(Path(".claude"),), entries=(_entry(".claude/skills/drop"),))
    )
    prior = read_receipt(rpath).receipt
    assert prior is not None
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}
    adapters = (a for a in [get_adapter(Tool.CLAUDE)])  # one-shot generator

    outcome = prune_pipeline(
        adapters,
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert not drop.exists()
    assert outcome.pruned_paths == {Path(".claude/skills/drop")}


def test_symlinked_root_escape_is_not_pruned(tmp_path: Path) -> None:
    """Spec safety scenario 3: a recorded entry that escapes its root via a
    symlinked parent survives the prune end-to-end.

    ``home/.claude/link`` symlinks outside home; a recorded entry under
    ``.claude/link/x`` resolves outside ``.claude``. ``validate_entry``'s
    symlink-aware containment rejects it, so ``diff_orphans`` skips it — it never
    reaches the delete step. The real target file outside home is untouched.

    Pins: the containment check is enforced in the full pipeline, not only the
    ``validate_entry`` unit — a forged symlink cannot weaponize the pruner into
    deleting outside the install roots.
    """
    home = _claude_home(tmp_path)
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    victim = outside / "x"
    victim.write_bytes(b"not ours\n")
    (home / ".claude" / "link").symlink_to(outside, target_is_directory=True)

    prior = Receipt(
        roots=(Path(".claude"),),
        entries=(ReceiptEntry(Path(".claude/link/x"), "claude", Path(".claude"), "file", None),),
    )
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert victim.exists()  # the escaping target is never deleted
    assert outcome.pruned_paths == set()


def test_corrupt_prior_modeled_as_empty_prunes_nothing(tmp_path: Path) -> None:
    """Spec safety scenario 5 (pipeline level): a corrupt receipt prunes nothing.

    A CORRUPT receipt read collapses to an empty ``Receipt`` before reaching
    ``prune_pipeline`` (fail closed). With an empty prior, an on-disk dir that WOULD
    be an orphan if a real receipt recorded it is left untouched — nothing is an
    orphan without a recorded baseline.

    Pins the fail-closed contract at the pipeline boundary: no recorded entries =>
    no deletions, regardless of what is on disk. The cli-level corrupt-digest path
    is pinned separately in test_cli_smoke.
    """
    home = _claude_home(tmp_path)
    would_be_orphan = home / ".claude" / "skills" / "stray"
    would_be_orphan.mkdir(parents=True)
    plans = {Tool.CLAUDE: StagingPlan(items={}, tool=Tool.CLAUDE)}

    outcome = prune_pipeline(
        [get_adapter(Tool.CLAUDE)],
        plans=plans,
        prior=Receipt(),  # the CORRUPT -> empty fallback
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert would_be_orphan.exists()
    assert outcome.pruned_paths == set()


def test_targeted_run_preserves_untargeted_tool_entry(tmp_path: Path) -> None:
    """A claude-only prune+record never erases an untargeted codex entry.

    prune_pipeline returns the pruned set; record_receipt then writes the
    mirrors-disk receipt. The untargeted ``.codex/skills/cx`` entry — neither
    in this run's scope nor pruned — survives in the written receipt.
    """
    home = _claude_home(tmp_path)
    (home / ".claude" / "skills" / "keep").mkdir(parents=True)
    prior = Receipt(
        roots=(Path(".claude"), Path(".codex")),
        entries=(
            _entry(".claude/skills/keep"),
            ReceiptEntry(Path(".codex/skills/cx"), "codex", Path(".codex"), "dir", None),
        ),
    )
    plans = {
        Tool.CLAUDE: StagingPlan(items={Path("skills/keep"): _skill_item("keep")}, tool=Tool.CLAUDE)
    }
    adapter = get_adapter(Tool.CLAUDE)
    outcome = prune_pipeline(
        [adapter],
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    receipt_path = _receipt_path(home)
    record_receipt(
        receipt_path,
        prior=prior,
        dest_roots={"claude": adapter.dest_dir(home)},
        home=home,
        tool_outcomes={},
        plugin_outcomes={},
        pruned_paths=outcome.pruned_paths,
        relinquished_paths=outcome.relinquished_paths,
    )

    after = read_receipt(receipt_path).receipt
    assert after is not None
    paths = {e.path for e in after.entries}
    assert Path(".codex/skills/cx") in paths  # untargeted tool preserved (mass-delete trap fixed)
    assert Path(".claude/skills/keep") in paths


def test_cross_tree_relocation_prunes_stale_fanout_copies(tmp_path: Path) -> None:
    """A shared skill narrowed to Claude-only prunes its stale per-tool fan-out copies.

    ``zoom-out`` first installs from shared ``.agents/`` content, fanning out to all
    four tools — the prior receipt records one entry per tool owner. The source then
    relocates to Claude-only ``.claude/`` content: this run stages ``zoom-out`` only
    under ``claude``, and the codex/gemini/opencode plans no longer contain it. Each of
    the three non-Claude copies is in scope (its tool is resolved), absent from its
    owner's desired keys, and root-valid, so all three are pruned; Claude's copy matches
    its desired key and is kept.

    Pins the per-owner ``(owner, path)`` diff against a cross-tree relocation — the
    receipt model's structural answer to the bash-era merged-source orphan gap (design
    relocation scenario, case c). A regression here would mean a relocated-and-narrowed
    skill leaves stale copies littering the tools it no longer ships to.
    """
    home = tmp_path
    claude = home / ".claude" / "skills" / "zoom-out"
    codex = home / ".codex" / "skills" / "zoom-out"
    gemini = home / ".gemini" / "skills" / "zoom-out"
    opencode = home / ".config" / "opencode" / "skills" / "zoom-out"
    for d in (claude, codex, gemini, opencode):
        d.mkdir(parents=True)

    prior = Receipt(
        roots=(Path(".claude"), Path(".codex"), Path(".gemini"), Path(".config/opencode")),
        entries=(
            _entry(".claude/skills/zoom-out"),
            ReceiptEntry(Path(".codex/skills/zoom-out"), "codex", Path(".codex"), "dir", None),
            ReceiptEntry(Path(".gemini/skills/zoom-out"), "gemini", Path(".gemini"), "dir", None),
            ReceiptEntry(
                Path(".config/opencode/skills/zoom-out"),
                "opencode",
                Path(".config/opencode"),
                "dir",
                None,
            ),
        ),
    )
    # Relocated to Claude-only: claude still stages it; the other three plans drop it.
    plans = {
        Tool.CLAUDE: StagingPlan(
            items={Path("skills/zoom-out"): _skill_item("zoom-out")}, tool=Tool.CLAUDE
        ),
        Tool.CODEX: StagingPlan(items={}, tool=Tool.CODEX),
        Tool.GEMINI: StagingPlan(items={}, tool=Tool.GEMINI),
        Tool.OPENCODE: StagingPlan(items={}, tool=Tool.OPENCODE),
    }
    adapters = [get_adapter(t) for t in (Tool.CLAUDE, Tool.CODEX, Tool.GEMINI, Tool.OPENCODE)]

    outcome = prune_pipeline(
        adapters,
        plans=plans,
        prior=prior,
        home=home,
        discovered_plugin_names=set(),
        io=ScriptedIO(interactive=False),
        auto_yes=True,
        timestamp=_TS,
    )

    assert claude.exists()  # still desired -> kept
    assert not codex.exists()  # stale fan-out copy -> pruned
    assert not gemini.exists()
    assert not opencode.exists()
    assert outcome.pruned_paths == {
        Path(".codex/skills/zoom-out"),
        Path(".gemini/skills/zoom-out"),
        Path(".config/opencode/skills/zoom-out"),
    }
    assert "claude" not in outcome.counters  # nothing pruned for the still-desired owner
