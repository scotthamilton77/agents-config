"""The repo-side content lint over a real ``src/`` tree.

Pins the decisions that make this check different from the deploy gate it
delegates to: it stages every tool regardless of the machine, it reports the
budget numbers whether or not anything breached, and it treats a record-less
artifact as fatal or merely reportable according to which subtree it sits in.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from installer.core.capabilities import models_skill_loading
from installer.core.content_lint import UNGATED_ROOTS, _staged_dirs, _unaccounted_dirs, lint_content
from installer.core.installignore import load_installignore
from installer.core.io_port import ScriptedIO
from installer.core.surface_budget import (
    SKILL_BODY_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
)
from installer.tools.registry import known_tools
from tests.unit.plugin_double import RoutedPluginDouble

_RECORD = "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"

_INSTALLIGNORE = "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nrules-readmes/\n"


def _repo(
    tmp_path: Path,
    *,
    skills: dict[str, str] | None = None,
    rules: dict[str, str] | None = None,
    plugin_rules: dict[str, str] | None = None,
    shared_skill_files: dict[str, dict[str, str]] | None = None,
    plugin_skill_files: dict[str, dict[str, str]] | None = None,
) -> Path:
    """A minimal repo root the lint can stage.

    ``skills`` maps a shared skill name to its full SKILL.md text; ``plugin_rules``
    maps ``<plugin>/<rule>.md`` to a rule's full text. ``shared_skill_files`` and
    ``plugin_skill_files`` write arbitrary file sets into a shared skill dir and a
    plugin's ``.agents/skills/<name>/``, which is how a carrier merge is set up:
    the two file sets must be disjoint, so a plugin supplies the entry file only
    when the shared dir has none.
    """
    (tmp_path / ".installignore").write_text(_INSTALLIGNORE, encoding="utf-8")
    shared = tmp_path / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "AGENTS.md.template").write_text("# laws\n", encoding="utf-8")

    for name, text in (skills or {}).items():
        skill_dir = shared / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")

    for filename, text in (rules or {}).items():
        rules_dir = shared / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / filename).write_text(text, encoding="utf-8")

    for name, files in (shared_skill_files or {}).items():
        skill_dir = shared / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        for filename, text in files.items():
            target = skill_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    for relpath, files in (plugin_skill_files or {}).items():
        plugin, name = relpath.split("/", 1)
        skill_dir = tmp_path / "src" / "plugins" / plugin / ".agents" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        for filename, text in files.items():
            target = skill_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

    for relpath, text in (plugin_rules or {}).items():
        plugin, filename = relpath.split("/", 1)
        rules_dir = tmp_path / "src" / "plugins" / plugin / ".agents" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / filename).write_text(text, encoding="utf-8")

    return tmp_path


def _lint(repo_root: Path):  # ContentLintResult; inferred at every call site
    return lint_content(repo_root, io=ScriptedIO())


@contextmanager
def _exemption(entries: dict[Path, str]) -> Iterator[None]:
    """Run the lint with ``entries`` added to the exemption register.

    The register ships empty, so the mechanism has no live occupant to exercise it
    against. Patching one in is how it stays tested without the repo carrying a
    standing exemption granted for the sake of testing that exemptions work.
    """
    UNGATED_ROOTS.update(entries)
    try:
        yield
    finally:
        for key in entries:
            UNGATED_ROOTS.pop(key, None)


def test_clean_tree_passes_and_still_reports_its_numbers(tmp_path: Path) -> None:
    """The bar's whole value as a trend instrument is that the numbers print on a
    PASS: a check that speaks only at the cliff gives no warning of the approach."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "a short body\n"})
    result = _lint(repo)

    assert result.ok
    assert result.violations == []
    assert [b.tokens for b in result.skills if b.where.endswith("skills/tidy/SKILL.md")]
    assert all(s.tokens > 0 for s in result.surfaces)


def test_every_known_tool_is_staged_regardless_of_the_machine(tmp_path: Path) -> None:
    """The lint asks 'is this content deployable at all', so its answer must not
    depend on which tools the CI runner happens to have installed."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    result = _lint(repo)

    assert {s.tool for s in result.surfaces} == {t.value for t in known_tools()}


def test_over_cap_skill_body_in_real_src_is_a_violation(tmp_path: Path) -> None:
    """The regression this module exists for: an over-cap body reaching main with
    CI green because nothing measured the tree the installer would actually read.

    Reported once for the one file, naming every tool that measured it — a line
    per tool and a count to match would read as several separate defects. Gemini
    is not among them: its skill loading is not modelled, so it weighs no body.
    """
    oversize = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    repo = _repo(tmp_path, skills={"bloated": _RECORD + oversize})
    result = _lint(repo)

    assert not result.ok
    assert len(result.violations) == 1
    assert "skills/bloated" in result.violations[0]
    assert "over the" in result.violations[0]
    for tool in known_tools():
        measured = tool.value in result.violations[0]
        assert measured is models_skill_loading(tool.value)


def test_a_violation_carrying_no_tool_prefix_passes_through_whole() -> None:
    """The conflict audit reports across artifacts, not per tool, so its message has
    no prefix to group on and must survive the grouping untouched."""
    from installer.core.content_lint import _collapse_findings

    audit = "conflicting claim 'x': 'a' (one), 'b' (two)"
    assert _collapse_findings([audit], sources={}, tool_values=frozenset({"claude"})) == [audit]


def test_two_artifacts_sharing_a_destination_stay_two_findings() -> None:
    """Grouping is by source artifact, never by rendered text. Two distinct
    tool-scoped artifacts can stage to the same destination at the same measured
    size — their messages are then identical once the tool prefix comes off, and
    folding them would report one defect where there are two."""
    from installer.core.content_lint import _collapse_findings

    sources = {
        "claude:skills/foo": Path("src/user/.claude/skills/foo"),
        "gemini:skills/foo": Path("src/user/.gemini/skills/foo"),
    }
    same_text = "skill body is 2250 tokens, over the 2000-token cap"
    collapsed = _collapse_findings(
        [f"claude:skills/foo: {same_text}", f"gemini:skills/foo: {same_text}"],
        sources=sources,
        tool_values=frozenset({"claude", "gemini"}),
    )

    assert len(collapsed) == 2
    assert any(".claude/skills/foo" in line for line in collapsed)
    assert any(".gemini/skills/foo" in line for line in collapsed)


def test_one_shared_artifact_folds_across_its_tools_and_names_the_source() -> None:
    """The same source staged into four plans is one defect in one file. The source
    path replaces the destination in the output — that is the file to edit."""
    from installer.core.content_lint import _collapse_findings

    source = Path("src/user/.agents/skills/foo")
    sources = {f"{t}:skills/foo": source for t in ("claude", "codex")}
    collapsed = _collapse_findings(
        ["claude:skills/foo: body too big", "codex:skills/foo: body too big"],
        sources=sources,
        tool_values=frozenset({"claude", "codex"}),
    )

    assert collapsed == [f"[claude, codex] {source}: body too big"]


def test_the_trend_report_folds_a_shared_body_but_not_two_bodies_at_one_destination() -> None:
    """The success path asks the same identity question as the failure path, so it
    gets the same answer. Deduplicating on ``(destination, tokens)`` folded two
    distinct tool-scoped skills that share a destination and happen to weigh the
    same — under-counting the surface silently, on the run nobody is reading
    closely."""
    from installer.core.content_lint import SkillBody, _group_skill_bodies
    from installer.core.surface_budget import SKILL_BODY_TOKEN_CAP, SkillMeasure

    shared = Path("src/user/.agents/skills/foo")
    measures = [
        SkillMeasure(label=f"{t}:skills/foo", tokens=100, cap=SKILL_BODY_TOKEN_CAP)
        for t in ("claude", "codex")
    ]
    folded = _group_skill_bodies(measures, sources={m.label: shared for m in measures})
    assert folded == [
        SkillBody(
            where=str(shared), tokens=100, cap=SKILL_BODY_TOKEN_CAP, tools=("claude", "codex")
        )
    ]

    distinct = _group_skill_bodies(
        measures,
        sources={
            "claude:skills/foo": Path("src/user/.claude/skills/foo"),
            "codex:skills/foo": Path("src/user/.codex/skills/foo"),
        },
    )
    assert len(distinct) == 2


def test_one_source_measuring_two_weights_reports_both() -> None:
    """A per-tool transform can change a shared body's deployed weight. Grouping on
    the source alone would report one of the two numbers and hide the other, which
    is the trend instrument lying about the surface it exists to watch."""
    from installer.core.content_lint import _group_skill_bodies
    from installer.core.surface_budget import SKILL_BODY_TOKEN_CAP, SkillMeasure

    shared = Path("src/user/.agents/skills/foo")
    bodies = _group_skill_bodies(
        [
            SkillMeasure(label="claude:skills/foo", tokens=100, cap=SKILL_BODY_TOKEN_CAP),
            SkillMeasure(label="gemini:skills/foo", tokens=80, cap=SKILL_BODY_TOKEN_CAP),
        ],
        sources={"claude:skills/foo": shared, "gemini:skills/foo": shared},
    )

    assert [(b.tokens, b.tools) for b in bodies] == [(80, ("gemini",)), (100, ("claude",))]


def test_a_label_cannot_claim_a_longer_labels_message() -> None:
    """Prefix matching is longest-first, so ``skills/foo`` never absorbs the finding
    that belongs to ``skills/foobar``."""
    from installer.core.content_lint import _matching_label

    sources = {
        "claude:skills/foo": Path("a"),
        "claude:skills/foobar": Path("b"),
    }
    assert _matching_label("claude:skills/foobar: msg", sources) == "claude:skills/foobar"


def test_findings_of_different_kinds_never_share_a_bucket() -> None:
    """Every gate violation must reach the output. If an ungrouped finding could key
    into a grouped one, the ungrouped one is absorbed and vanishes — a swallowed
    violation is worse than a mis-grouped one, because nothing signals the loss."""
    from installer.core.content_lint import _collapse_findings

    text = "always-on surface is 10001 tokens"
    collapsed = _collapse_findings(
        [f"claude: {text}", text],  # the second carries no tool prefix at all
        sources={},
        tool_values=frozenset({"claude"}),
    )

    assert len(collapsed) == 2
    assert f"[claude] {text}" in collapsed
    assert text in collapsed


def test_always_on_breach_groups_on_its_text_having_no_artifact_behind_it() -> None:
    """The always-on surface is a property of the tool, not of one file, so there is
    no source identity to group on — identical breaches still fold."""
    from installer.core.content_lint import _collapse_findings

    text = "always-on surface is 10001 tokens, over the 10000-token cap"
    collapsed = _collapse_findings(
        [f"claude: {text}", f"codex: {text}"],
        sources={},
        tool_values=frozenset({"claude", "codex"}),
    )

    assert collapsed == [f"[claude, codex] {text}"]


def test_a_directory_no_staging_root_reaches_is_a_violation(tmp_path: Path) -> None:
    """The whole gate is scoped to what staging reaches, so a directory it does not
    reach is content measured by nothing — and it arrives silently, on a green build.

    Asserted alongside the trend numbers because the two reports are independent: an
    unaccounted directory says nothing about the content that WAS staged, and a run
    that answered only one of the two questions would be reporting half a verdict.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "newthing" / "nested").mkdir(parents=True)
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/newthing:")]
    assert not [v for v in result.violations if "nested" in v]  # shallowest only
    assert result.skills  # the staged content is still measured and reported


def test_the_exemption_register_is_empty() -> None:
    """Which directories are exempt from the admission bar is a decision, and this is
    where it is on the record. Empty is the useful state: an exemption is a judgement
    about a body of content, so it belongs to whoever can see that content rather than
    to whoever anticipated it. Widening this must arrive as a reviewed diff."""
    assert UNGATED_ROOTS == {}


def test_an_exempt_directory_is_not_reported_as_unaccounted(tmp_path: Path) -> None:
    """The mechanism, separately from the membership. A directory nothing stages but
    that the register names is a decision already taken, and re-reporting it every run
    would train a reader to skip the one finding that is not a decision already taken.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    exempt = Path("src") / "someday"
    (repo / exempt / "content").mkdir(parents=True)
    with _exemption({exempt: "because the test says so"}):
        result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_namespace_no_adapter_stages_is_a_violation(tmp_path: Path) -> None:
    """The likeliest instance of this defect, and the one root-level accounting misses.

    Codex, Gemini and OpenCode declare no tool-scoped namespaces at all, so a skill
    placed at src/user/.codex/skills/ — a path that looks exactly like the one that
    works for Claude — deploys nowhere and is weighed by nothing. It needs no new tool
    and no registry edit, only a plausible guess, which makes it likelier than the
    unknown-tool-tree case and invisible to a check that stops at the root.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "user" / ".codex" / "skills" / "orphan").mkdir(parents=True)
    (repo / "src" / "user" / ".agents" / "commands" / "orphan").mkdir(parents=True)
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/user/.codex/skills:")]
    # 'commands' is deliberately absent from the shared namespaces (shared content
    # is tool-agnostic; commands are a tool-scoped concept), so the shared tree has
    # the same hole as a tool tree and must answer to the same rule.
    assert [v for v in result.violations if v.startswith("src/user/.agents/commands:")]


def test_a_namespace_interior_is_not_reported(tmp_path: Path) -> None:
    """A namespace stages whole — a skill directory is one DIR item, interior and all.
    Descending past it would report every skill's own scripts/ subdirectory as unread
    content, and a gate that fires on a valid tree is one the next contributor deletes.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "user" / ".agents" / "skills" / "tidy" / "scripts").mkdir(parents=True)
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_tool_tree_the_registry_does_not_know_is_caught_one_level_down(
    tmp_path: Path,
) -> None:
    """src/user holds staging roots without being one, so the check descends into it.
    Stopping at the top level would pass a src/user/.newtool that no adapter reads —
    the same defect as an unstaged src/newthing, one directory deeper."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "user" / ".newtool" / "rules").mkdir(parents=True)
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/user/.newtool:")]


def test_malformed_record_is_a_violation(tmp_path: Path) -> None:
    """A record stating both worth fields aborts a deploy; the lint must fail on it
    here rather than leaving it to be discovered at install time."""
    both = "---\nadmission:\n  prevents: p\n  provides: q\n  cost: c\n  remove_when: r\n---\nbody\n"
    repo = _repo(tmp_path, skills={"confused": _RECORD + "ok\n", "both": both})
    result = _lint(repo)

    assert not result.ok
    assert any("skills/both" in v for v in result.violations)


def test_record_less_artifact_under_src_user_is_fatal(tmp_path: Path) -> None:
    """src/user is declared admitted-content-only, so a record-less file there is a
    mistake rather than a tracked exception — it can never reach an agent."""
    repo = _repo(tmp_path, skills={"orphan": "# no front matter\n"})
    result = _lint(repo)

    assert not result.ok
    assert result.violations == []  # the failure is the omission, not a gate breach
    assert [str(u.source.relative_to(repo)) for u in result.fatal_unadmitted] == [
        "src/user/.agents/skills/orphan/SKILL.md"
    ]


def test_record_less_plugin_rule_is_reported_but_not_fatal(tmp_path: Path) -> None:
    """Plugin rules carrying no record are a known state tracked elsewhere. The lint
    surfaces them on every run so they stay visible, without failing the build for a
    condition this check did not introduce."""
    repo = _repo(tmp_path, plugin_rules={"graphify/graphify.md": "# no record\n"})
    result = _lint(repo)

    assert result.ok
    assert [u.source.name for u in result.unadmitted] == ["graphify.md"]
    assert result.fatal_unadmitted == []


def test_shared_artifact_is_reported_once_naming_every_tool(tmp_path: Path) -> None:
    """A shared artifact stages into every tool's plan, so the gate skips it once per
    tool. Reporting it four times would read as four defects instead of one file."""
    repo = _repo(tmp_path, skills={"orphan": "# no front matter\n"})
    result = _lint(repo)

    assert len(result.unadmitted) == 1
    assert result.unadmitted[0].tools == tuple(sorted(t.value for t in known_tools()))


def test_source_path_outside_the_repo_is_not_treated_as_admitted_only(
    tmp_path: Path,
) -> None:
    """The admitted-only test is a containment question; a path it cannot relativise
    is outside the tree, not a crash."""
    from installer.core.content_lint import _is_admitted_only

    assert not _is_admitted_only(tmp_path / "elsewhere" / "x.md", tmp_path / "repo")


def test_a_parked_plugin_directory_is_not_reported(tmp_path: Path) -> None:
    """`discover` skips `.`/`_`-prefixed directories under src/plugins by documented
    convention, so one of them is a plugin deliberately parked, not a directory nobody
    noticed. Reporting it would make the gate fire on a valid tree, and a gate that
    cries wolf is one the next contributor deletes along with the real check."""
    repo = _repo(tmp_path, plugin_rules={"graphify/graphify.md": _RECORD + "body\n"})
    (repo / "src" / "plugins" / "_parked" / ".agents" / "rules").mkdir(parents=True)
    result = _lint(repo)

    assert result.violations == []


def test_a_plugin_namespace_no_tool_overlays_is_a_violation(tmp_path: Path) -> None:
    """Plugin interiors answer to the same rule as the user tree: the overlay reads
    only PLUGIN_TOOL_SCOPED out of a plugin's tool dir, so a `hooks` directory there
    deploys nowhere. Stopping the descent at the plugin root would bless it."""
    repo = _repo(tmp_path, plugin_rules={"graphify/graphify.md": _RECORD + "body\n"})
    (repo / "src" / "plugins" / "graphify" / ".claude" / "hooks").mkdir(parents=True)
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/plugins/graphify/.claude/hooks:")]


def test_a_symlink_cycle_under_src_does_not_hang_the_walk(tmp_path: Path) -> None:
    """Termination is provable from the current code — descent requires a staging root
    strictly below the child, which bounds depth — but nothing pinned it. A later
    rewrite into rglob or recursion would reintroduce the loop with every other test
    still green, and a gate that hangs is worse than one that misses a directory.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "loop").symlink_to(repo / "src", target_is_directory=True)
    (repo / "src" / "user" / "back").symlink_to(repo / "src", target_is_directory=True)

    result = _lint(repo)  # must return at all; the assertion is that we get here

    assert not [v for v in result.violations if "loop" in v or "back" in v]


def test_a_directory_installignore_declares_unstaged_is_not_reported(tmp_path: Path) -> None:
    """The repo already has a register of deliberately-unstaged source, and this check
    has to read it. `rules-readmes/` is in `.installignore` AND documented in the plugin
    layout table as source-only-not-installed; without this branch the gate fails a
    contributor for following the documentation, and the remedies it offers are all
    wrong. Staging never reads these — silence is the correct verdict, not an oversight.
    """
    repo = _repo(
        tmp_path,
        skills={"tidy": _RECORD + "body\n"},
        plugin_rules={"graphify/graphify.md": _RECORD + "body\n"},
    )
    (repo / "src" / "user" / ".claude" / "rules-readmes").mkdir(parents=True)
    (repo / "src" / "plugins" / "graphify" / ".agents" / "rules-readmes").mkdir(parents=True)
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_plugin_scope_no_overlay_reads_is_a_violation(tmp_path: Path) -> None:
    """A plugin contributes through .agents and one dir per known tool, and nothing
    else inside it is ever opened. A `docs/` directory there deploys nowhere, so it is
    reported — the deliberate call being that plugin repo-side material declares itself
    through .installignore or the register rather than by sitting somewhere unread."""
    repo = _repo(tmp_path, plugin_rules={"graphify/graphify.md": _RECORD + "body\n"})
    (repo / "src" / "plugins" / "graphify" / "docs").mkdir(parents=True)
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/plugins/graphify/docs:")]


def test_an_exemption_naming_a_missing_directory_is_a_violation(tmp_path: Path) -> None:
    """The register fails silent: an exemption matching nothing simply never fires, so a
    stale entry is found only by someone reading the file. That is how src/kits stayed
    exempt after it was archived — caught by a human, which is the check that does not
    run on every build. Retiring the entry without this leaves the mechanism intact.
    """
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    with _exemption({Path("src") / "longgone": "reason that outlived its content"}):
        result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith("src/longgone:")]
    assert [v for v in result.violations if "no such directory exists" in v]


def test_a_plugins_bespoke_routes_are_accounted(tmp_path: Path) -> None:
    """Routes are a third staging channel, and the one a map built from the tool overlay
    cannot see: a specialized adapter can send content to a bespoke destination outside
    every tool tree, as the one this codebase used to ship did. Missing them did not
    under-report, it inverted the claim — the gate called correctly-wired content "content
    that deploys nowhere" and offered three remedies that would each break it.

    No specialized adapter ships in production today (``_SPECIALIZED`` is empty), so this
    drives ``_staged_dirs``/``_unaccounted_dirs`` directly with an injected
    ``RoutedPluginDouble`` rather than going through ``discover()``/``lint_content()`` —
    the completeness algorithm under test does not care where its ``PluginAdapter`` came
    from, only that its declared routes get accounted for.
    """
    repo = _repo(tmp_path)
    plugins_root = repo / "src" / "plugins"
    source_path = plugins_root / "widget"
    (source_path / ".widget" / "formulas").mkdir(parents=True)
    (source_path / ".widget" / "scripts").mkdir(parents=True)
    plugin = RoutedPluginDouble(name="widget", source_path=source_path)

    staged = _staged_dirs(repo, plugins_root=plugins_root, plugins=[plugin])
    ignore = load_installignore(repo / ".installignore")

    assert _unaccounted_dirs(repo, staged=staged, ignore=ignore) == []


def test_a_directory_beside_a_route_that_no_route_names_is_a_violation(tmp_path: Path) -> None:
    """Accounting for a route's own source must not bless its siblings. ``.widget`` is
    reached because routes point into it, not because it is wholly covered — the same
    distinction between "a root is on the path" and "staging reads this" that the tool
    trees answer. Same injected-double approach as
    ``test_a_plugins_bespoke_routes_are_accounted`` — see its docstring for why."""
    repo = _repo(tmp_path)
    plugins_root = repo / "src" / "plugins"
    source_path = plugins_root / "widget"
    (source_path / ".widget" / "formulas").mkdir(parents=True)
    (source_path / ".widget" / "notaroute").mkdir(parents=True)
    plugin = RoutedPluginDouble(name="widget", source_path=source_path)

    staged = _staged_dirs(repo, plugins_root=plugins_root, plugins=[plugin])
    ignore = load_installignore(repo / ".installignore")

    unaccounted = _unaccounted_dirs(repo, staged=staged, ignore=ignore)
    assert [p for p in unaccounted if p == Path("src/plugins/widget/.widget/notaroute")]


def test_a_build_directory_is_not_reported(tmp_path: Path) -> None:
    """content-tests refuses to walk these; content-lint must not fail the build over one.
    Two gates disagreeing about what is out of scope is the defect class both exist to
    close, so the set is read from content_tests rather than restated here."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "user" / ".claude" / "node_modules").mkdir(parents=True)
    (repo / "src" / "user" / ".agents" / ".venv").mkdir(parents=True)
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_every_specialized_adapters_routes_are_accounted(tmp_path: Path) -> None:
    """The completeness check, generalised over the registry rather than over one adapter.

    Three review rounds each found the same shape: a staging channel the accounting map did
    not model, reported as content that deploys nowhere. This iterates whatever
    ``_SPECIALIZED`` holds and fails if the map does not reach a registered adapter's
    declared routes, so registering one cannot silently reintroduce that defect.

    ``_SPECIALIZED`` is empty today, so this body iterates nothing: the guard is dormant,
    not dead, and arms itself the moment the extension point is used. It deliberately does
    NOT assert the registry is non-empty — that assertion is what an empty extension point
    breaks, and it would have to be deleted on every green run. The sibling tests above pin
    the accounting algorithm itself through an injected double; this one exists for the
    registry-mediated path they cannot reach, because ``lint_content`` discovers plugins
    internally and offers no seam to inject through.
    """
    from installer.plugins.registry import _SPECIALIZED

    for name, factory in _SPECIALIZED.items():
        root = tmp_path / name
        root.mkdir()
        repo = _repo(root, plugin_rules={f"{name}/{name}.md": _RECORD + "body\n"})
        source_path = repo / "src" / "plugins" / name
        for route in factory(name, source_path).routes(Path("/nonexistent-home")):
            route.source_dir.mkdir(parents=True, exist_ok=True)
        result = _lint(repo)

        assert result.violations == [], f"{name}: {result.violations}"


def test_a_record_less_contributor_to_a_merged_rule_is_named_by_itself(tmp_path: Path) -> None:
    """A shared rule and a plugin rule of one name land at one destination. Judged
    as a single artifact the pair is classified off whichever file leads the merged
    bytes, so a record-less contributor behind an admitted one is never reported at
    all — and its bytes deploy anyway, which is what the bar exists to stop."""
    repo = _repo(
        tmp_path,
        rules={"x.md": _RECORD + "shared rule body\n"},
        plugin_rules={"p/x.md": "# no record\n"},
    )
    result = _lint(repo)

    assert [u.source for u in result.unadmitted] == [repo / "src/plugins/p/.agents/rules/x.md"]
    assert result.fatal_unadmitted == []  # src/plugins is reported, not fatal


def test_a_carrier_supplied_entry_file_is_blamed_on_the_plugin_that_supplied_it(
    tmp_path: Path,
) -> None:
    """A carrier merge puts a plugin's SKILL.md into a shared skill dir whose own
    source tree has none. Blaming the carrier would fail the build under the
    admitted-content-only rule against a directory that contributed nothing; the
    old answer — blame nobody, and never let it be fatal — let a record-less
    contributor through in silence."""
    repo = _repo(
        tmp_path,
        shared_skill_files={"foo": {"reference.md": "notes\n"}},
        plugin_skill_files={"p/foo": {"SKILL.md": "# no record\n"}},
    )
    result = _lint(repo)

    supplier = repo / "src/plugins/p/.agents/skills/foo/SKILL.md"
    assert [u.source for u in result.unadmitted] == [supplier]
    assert result.fatal_unadmitted == []  # src/plugins is reported, not fatal


def test_a_finding_on_an_ordinary_skill_names_its_entry_file(tmp_path: Path) -> None:
    """The bar reads a directory item's record out of its entry file, so that file
    is what a finding has to name: it is the one the reader edits, and it is the
    one whose bytes were judged. Naming the directory reports at a coarser grain
    than the plan knows — and disagrees with the entry file arriving through the
    override channel, which names the contributing file exactly.

    """
    both = "---\nadmission:\n  prevents: p\n  provides: q\n  cost: c\n  remove_when: r\n---\nb\n"
    repo = _repo(tmp_path, skills={"confused": both})
    result = _lint(repo)

    assert len(result.violations) == 1
    assert str(repo / "src/user/.agents/skills/confused/SKILL.md") in result.violations[0]


def test_an_admitted_skill_is_weighed_under_the_file_that_was_weighed(
    tmp_path: Path,
) -> None:
    """The trend report answers the same identity question as the findings, so it
    gets the same answer: the number is the entry file's body, so the entry file is
    what the line names."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "a short body\n"})
    result = _lint(repo)

    assert [b.where for b in result.skills] == [str(repo / "src/user/.agents/skills/tidy/SKILL.md")]


def test_the_payload_report_prints_on_a_pass_and_fails_nothing(tmp_path: Path) -> None:
    """The number with no ceiling. A reader cannot otherwise see what a skill costs
    when they follow one of its pointers, and the unit they pay is one file — so the
    report names the largest and the verdict is untouched by it."""
    repo = _repo(
        tmp_path,
        skills={"heavy": _RECORD + "short\n"},
        shared_skill_files={
            "heavy": {
                "references/long.md": "p" * 4_000,
                "references/short.md": "p" * 40,
                "scripts/run.py": "c" * 8_000,
            }
        },
    )
    result = _lint(repo)

    assert result.ok
    assert [(p.prose_files, p.largest_file, p.largest_tokens) for p in result.payloads] == [
        (2, "references/long.md", 1_000)
    ]
    # Executed code is counted apart and costed at nothing: it never enters a
    # context window, and charging it would price code-over-prose as a cost.
    assert [p.prose_tokens for p in result.payloads] == [1_010]
    assert [p.other_tokens for p in result.payloads] == [2_000]


def test_the_payload_walk_counts_what_deploys_not_what_is_authored(tmp_path: Path) -> None:
    """A file the manifest prunes never reaches a user, so weighing it would report
    a cost nobody pays. The manifest's own path rule answers this, rather than a
    second copy of it here."""
    repo = _repo(
        tmp_path,
        skills={"heavy": _RECORD + "short\n"},
        shared_skill_files={"heavy": {"references/keep.md": "p" * 40, "README.md": "p" * 4_000}},
    )
    result = _lint(repo)

    assert result.ok
    assert [(p.prose_files, p.largest_file) for p in result.payloads] == [(1, "references/keep.md")]


def test_a_skill_entry_file_is_not_charged_to_its_own_payload(tmp_path: Path) -> None:
    """The body is already weighed against the skill body cap; counting it here
    would charge one artifact's bytes to two different numbers."""
    repo = _repo(
        tmp_path,
        skills={"lonely": _RECORD + "x" * 400},
        shared_skill_files={"lonely": {"references/tiny.md": "p" * 4}},
    )
    result = _lint(repo)

    assert [(p.prose_files, p.prose_tokens) for p in result.payloads] == [(1, 1)]


def test_a_user_invoked_shared_skill_reports_one_line_per_ceiling(tmp_path: Path) -> None:
    """Grouping folds a repeated finding into one line naming its tools, but the
    ceiling now varies by target — so folding on the token count alone would print
    whichever cap arrived first and hide the tools it does not apply to."""
    flagged = _RECORD.replace("---\n", "---\ndisable-model-invocation: true\n", 1)
    repo = _repo(tmp_path, skills={"quiet": flagged + "short\n"})
    result = _lint(repo)

    assert result.ok
    assert [(body.cap, body.tools) for body in result.skills] == [
        (SKILL_BODY_TOKEN_CAP, ("codex", "opencode")),
        (USER_INVOKED_SKILL_BODY_TOKEN_CAP, ("claude",)),
    ]


def _costed(cost: str) -> str:
    """A complete record whose ``cost`` is ``cost``, plus a one-line body."""
    return f"---\nadmission:\n  prevents: p\n  cost: {cost}\n  remove_when: r\n---\nbody\n"


def test_a_cost_mentioning_tokens_is_a_violation_with_or_without_a_number(
    tmp_path: Path,
) -> None:
    """The gate prints every token number that exists, at the moment it is true, so a
    record restating one is a hand-copy at a location nothing updates — three of the
    six that lived in this tree had already drifted from what they claimed. The rule
    bans the word rather than the number: a value that means money can say money, and
    a second heuristic telling the two apart would be free to drift from the first."""
    repo = _repo(
        tmp_path,
        skills={
            "priced": _costed("68 always-on tokens, measured"),
            "wordy": _costed("the tokens a reader spends on it"),
        },
    )
    result = _lint(repo)

    assert not result.ok
    assert len([v for v in result.violations if "cost mentions tokens" in v]) == 2


def test_a_vacuous_cost_is_a_violation_however_it_is_cased(tmp_path: Path) -> None:
    """The deploy-time check tests only that the field is non-empty, so ``cost:
    None`` cleared it while violating a rule this repo had already written down.
    Capitalisation is the author's, not the claim's."""
    repo = _repo(tmp_path, skills={"bare": _costed("None"), "shouty": _costed("NEGLIGIBLE")})
    result = _lint(repo)

    assert not result.ok
    assert len([v for v in result.violations if "cost is vacuous" in v]) == 2


def test_a_cost_naming_what_no_gate_measures_passes(tmp_path: Path) -> None:
    """Both conforming shapes: a cost that falls outside every measurement, and the
    sentinel an artifact carries when its only cost is its own footprint. The
    sentinel needs no exemption from the token rule — it is written not to want one."""
    repo = _repo(
        tmp_path,
        skills={
            "external": _costed("An API key the user must supply and pay against."),
            "plain": _costed("Context footprint only, bounded by the caps content-lint enforces."),
        },
    )
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_one_shared_artifact_reports_its_cost_defect_once(tmp_path: Path) -> None:
    """A shared skill stages into every tool's plan, so keying on the label would
    report one authored line as four defects in four places. The value is a
    property of the file, which is also the only thing a reader can edit."""
    repo = _repo(tmp_path, skills={"spread": _costed("a 900 token body")})
    result = _lint(repo)

    assert len([v for v in result.violations if "cost mentions tokens" in v]) == 1
