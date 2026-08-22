"""The repo-side content lint over a real ``src/`` tree.

Pins the decisions that make this check different from the deploy gate it
delegates to: it stages every tool regardless of the machine, it reports the
budget numbers whether or not anything breached, and it treats a record-less
artifact as fatal or merely reportable according to which subtree it sits in.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from pathlib import Path

import pytest

from installer.core.capabilities import models_skill_loading
from installer.core.content_lint import (
    CH_BUILD,
    CH_GIT,
    CH_INSTALLIGNORE,
    CH_NAMESPACE,
    CH_STAGED,
    CH_UNGATED,
    UNGATED_ROOTS,
    _staged_dirs,
    _unaccounted_dirs,
    lint_content,
)
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
    every tool tree. Missing them does not under-report, it inverts the claim — the gate
    calls correctly-wired content "content that deploys nowhere" and offers three
    remedies that would each break it.

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

    walk = _unaccounted_dirs(repo, staged=staged, ignore=ignore, git_ignored=frozenset())

    assert walk.unaccounted == []


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

    walk = _unaccounted_dirs(repo, staged=staged, ignore=ignore, git_ignored=frozenset())
    assert [p for p in walk.unaccounted if p == Path("src/plugins/widget/.widget/notaroute")]


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

    The defect has one shape: a staging channel the accounting map does not model,
    reported as content that deploys nowhere. This iterates whatever
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


# --- The provenance header rule ------------------------------------------------
# Fixtures are real content, not invented shapes: the failing cases are the headers
# that actually drifted into the tree, and the passing ones are the headers that
# legitimately live there. An invented fixture would pin whatever the check happens
# to do rather than what the tree contains.

# Verbatim from the four artifacts that carried them until the sweep at cc3e76c9 —
# a rule, two skills and a plugin skill. Each recorded its own authoring date, which
# is history git already holds, and each passed human review; the last was written
# one day after this defect was filed and measured.
_SELF_AUTHORED_HEADERS = (
    "<!--\nSource: authored 2026-07-26.\n-->",
    "<!--\nSource: authored 2026-07-31, replacing dispatching-subagents (archived).\n-->",
    "<!--\nSource: authored 2026-08-01.\n-->",
    "<!--\nSource: authored 2026-08-02.\n-->",
)

# The genuinely-mixed case, two lines verbatim from explain-diff's header: an
# in-repo authoring line naming the files with no upstream, and the upstream for
# the ones that have it. This is what a partly-derived artifact is supposed to look
# like, so it is the case a check must not break.
_MIXED_HEADER = (
    "<!--\n"
    "Source: authored in-repo 2026-07-10 — SKILL.md, assets/theme.css, assets/quiz.js "
    "and assets/palette.md have no upstream.\n"
    "Upstream: https://github.com/scotthamilton77/claude-code-sidekick @ "
    "44e57b67beceb29825fb7be95b07520ec5445ad9\n"
    "-->"
)

# Indented keys, from writing-skills: its keys sit inside the comment rather than at
# column zero, and three artifacts in the tree are written this way.
_INDENTED_HEADER = (
    "<!--\n"
    "Amalgam of three upstreams, one Source/Upstream pair each.\n\n"
    "  Source: skills/writing-skills/\n"
    "  Upstream: https://github.com/obra/superpowers @ "
    "f2cbfbefebbfef77321e4c9abc9e949826bea9d7 (v5.1.0)\n"
    "-->"
)

# The two shapes above crossed: indentation with nothing derived. Constructed, since
# the tree has never carried one — it is the gap between the two real shapes, and the
# one a column-anchored pattern passes without a word.
_INDENTED_SELF_AUTHORED = "<!--\nAuthored here.\n\n  Source: authored 2026-08-02.\n-->"


def _skill_carrying(header: str) -> str:
    """An admitted skill whose body opens with ``header``, laid out as the real
    artifacts are: the header one blank line below the fence, the body below it."""
    return _RECORD + "\n" + header + "\n\nbody\n"


@pytest.mark.parametrize("header", _SELF_AUTHORED_HEADERS)
def test_a_self_authored_provenance_header_is_a_violation(header: str, tmp_path: Path) -> None:
    """The drift that made this mechanical rather than reviewed. A provenance header
    asserts that an outside party exists at a known commit whose changes could collide
    with ours; a header recording only our own authoring date makes that assertion
    falsely, and a reader has to open the upstream to find out there is none.

    Reported once for the one file, naming every tool it would have deployed to — four
    lines and a count of four would read as four separate defects.
    """
    repo = _repo(tmp_path, skills={"drifted": _skill_carrying(header)})
    result = _lint(repo)

    assert not result.ok
    assert len(result.violations) == 1
    assert "skills/drifted" in result.violations[0]
    assert "naming no upstream" in result.violations[0]
    for tool in known_tools():
        assert tool.value in result.violations[0]


@pytest.mark.parametrize("header", [_MIXED_HEADER, _INDENTED_HEADER])
def test_a_header_naming_an_upstream_passes(header: str, tmp_path: Path) -> None:
    """An outside party at a known commit is what the header is for, so the check has
    to leave one alone — including the mixed case, where the artifact is partly ours
    and the header scopes itself to the files that are derived. Failing that case would
    push authors to delete a header doing exactly its job."""
    repo = _repo(tmp_path, skills={"derived": _skill_carrying(header)})
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_an_indented_key_is_seen_where_it_sits(tmp_path: Path) -> None:
    """A key-at-column-zero pattern reads an indented key as no key at all, so it
    passes this artifact in silence — the same miss that undercounted the tree's
    legitimate headers by three when the census was taken by hand. The recognizer's
    leading-whitespace tolerance is what the deploy strips by, and this is the
    direction in which getting it wrong is invisible."""
    repo = _repo(tmp_path, skills={"drifted": _skill_carrying(_INDENTED_SELF_AUTHORED)})
    result = _lint(repo)

    assert not result.ok
    assert "naming no upstream" in result.violations[0]


def test_a_leading_comment_that_is_not_provenance_is_left_alone(tmp_path: Path) -> None:
    """Only a header carrying provenance keys is bookkeeping; any other leading comment
    is content. A check that fired on every leading comment would fail artifacts that
    never claimed provenance at all."""
    repo = _repo(tmp_path, skills={"noted": _skill_carrying("<!--\nTODO: rewrite this.\n-->")})
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_provenance_key_below_prose_is_not_a_header(tmp_path: Path) -> None:
    """Where the header may sit is the sanitizer's decision, and this check inherits it
    rather than scanning the file for a key. A comment below prose is content the deploy
    ships untouched, so failing the build over it would report a defect in bytes that
    were never bookkeeping — which is what a whole-file search for a Source: line
    without an Upstream: line would do."""
    body = _RECORD + "\nprose first.\n\n<!--\nSource: authored 2026-08-02.\n-->\n"
    repo = _repo(tmp_path, skills={"prosefirst": body})
    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_plugin_artifact_gets_no_location_exemption(tmp_path: Path) -> None:
    """One of the four drifted artifacts was a plugin skill, so the rule cannot stop at
    src/user. It is also independent of the admission verdict: a record-less plugin rule
    is reported without failing the build, and the header it carries fails it anyway —
    an artifact can be wrong in both ways at once and should hear about both."""
    repo = _repo(
        tmp_path,
        plugin_rules={"graphify/graphify.md": "<!--\nSource: authored 2026-08-01.\n-->\n\nbody\n"},
    )
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if "naming no upstream" in v]
    assert [u.source.name for u in result.unadmitted] == ["graphify.md"]
    assert result.fatal_unadmitted == []


def test_a_directory_with_no_entry_file_is_not_a_provenance_question(tmp_path: Path) -> None:
    """A skill directory carrying no SKILL.md has no front matter and no header to
    judge, so the provenance check has nothing to ask of it. The gate already reports
    it as record-less; asking a header question of bytes that do not exist would turn a
    reported omission into a crash."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    (repo / "src" / "user" / ".agents" / "skills" / "empty").mkdir()
    result = _lint(repo)

    assert result.violations == []
    assert [u.source.name for u in result.fatal_unadmitted] == ["empty"]


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


def test_a_header_on_a_trailing_contributor_is_seen(tmp_path: Path) -> None:
    """A shared rule and a plugin rule of one name append-merge into one destination,
    and the header question is per contributor exactly as the admission record is.
    Asked of the assembled bytes it would read the leading contributor's header and
    no other, so a trailing self-authored one would ship its claim unchallenged —
    the same half-blindness the bar stopped having, one check over."""
    repo = _repo(
        tmp_path,
        rules={"x.md": _RECORD + "leading body, no header\n"},
        plugin_rules={"p/x.md": _RECORD + "\n<!--\nSource: authored 2026-08-01.\n-->\n\nbody\n"},
    )
    result = _lint(repo)

    assert not result.ok
    flagged = [v for v in result.violations if "naming no upstream" in v]
    assert len(flagged) == 1
    assert str(repo / "src/plugins/p/.agents/rules/x.md") in flagged[0]


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


def test_a_user_invoked_shared_skill_reports_one_ceiling_for_every_tool(tmp_path: Path) -> None:
    """The ceiling follows the author's declaration, so the report names one cap
    and every tool measured against it. A reader deciding whether a body has room
    gets one number, not a per-target lottery over the same bytes."""
    flagged = _RECORD.replace("---\n", "---\ndisable-model-invocation: true\n", 1)
    repo = _repo(tmp_path, skills={"quiet": flagged + "short\n"})
    result = _lint(repo)

    assert result.ok
    assert [(body.cap, body.tools) for body in result.skills] == [
        (USER_INVOKED_SKILL_BODY_TOKEN_CAP, ("claude", "codex", "opencode")),
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


def _git_tracked_repo(repo: Path, ignore_lines: str) -> Path:
    """Turn a fixture root into a git repository whose ``.gitignore`` is ``ignore_lines``.

    No commit is needed: the question the lint asks is which *untracked* paths git
    would refuse, which an empty index answers as well as a full one.
    """
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)  # noqa: S603, S607
    (repo / ".gitignore").write_text(ignore_lines, encoding="utf-8")
    return repo


def test_a_git_ignored_file_beside_a_skill_is_not_content(tmp_path: Path) -> None:
    """The verdict has to be a property of the committed tree. A Finder ``.DS_Store``
    dropped into a namespace directory reaches no clone and no runner, so holding it
    to the admission bar makes the gate red on one machine and green on every other —
    which teaches its readers to stop reading its exit code."""
    repo = _git_tracked_repo(_repo(tmp_path, skills={"tidy": _RECORD + "body\n"}), ".DS_Store\n")
    (repo / "src" / "user" / ".agents" / "skills" / ".DS_Store").write_bytes(b"Bud1\x00")

    result = _lint(repo)

    assert result.ok
    assert result.violations == []
    assert result.unadmitted == []


def test_an_untracked_file_git_keeps_is_still_held_to_the_bar(tmp_path: Path) -> None:
    """The floor under the skip. Asking git is not a licence to stop looking at
    uncommitted work: a new artifact is untracked right up to the moment it is
    staged, and a gate that waited for the commit would pass every artifact on the
    run that introduces it."""
    repo = _git_tracked_repo(_repo(tmp_path, skills={"tidy": _RECORD + "body\n"}), ".DS_Store\n")
    (repo / "src" / "user" / ".agents" / "skills" / "stray.md").write_text("no record\n")

    result = _lint(repo)

    assert not result.ok
    assert [u for u in result.unadmitted if u.source.name == "stray.md"]


def test_a_git_ignored_file_inside_a_skill_is_not_weighed(tmp_path: Path) -> None:
    """The same file one level deeper is no longer an artifact of its own — it is
    payload the skill would be charged for, and a number that moves with whoever
    opened the directory in Finder is a budget nobody can hold."""
    repo = _git_tracked_repo(
        _repo(
            tmp_path,
            skills={"tidy": _RECORD + "body\n"},
            shared_skill_files={"tidy": {"references/notes.md": "x" * 400}},
        ),
        ".DS_Store\n",
    )
    skill = repo / "src" / "user" / ".agents" / "skills" / "tidy"
    before = [m.other_tokens + m.prose_tokens for m in _lint(repo).payloads]
    (skill / "references" / ".DS_Store").write_bytes(b"Bud1\x00" * 200)

    result = _lint(repo)

    assert result.ok
    assert [m.other_tokens + m.prose_tokens for m in result.payloads] == before


def test_a_git_ignored_directory_under_src_is_not_unaccounted(tmp_path: Path) -> None:
    """Staging never reads a directory git refuses either, and the accounting walk
    must not call that a wiring defect — otherwise a stray local build directory
    fails the build for its owner alone."""
    repo = _git_tracked_repo(_repo(tmp_path, skills={"tidy": _RECORD + "body\n"}), "scratch/\n")
    (repo / "src" / "scratch" / "deep").mkdir(parents=True)

    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_git_ignored_markdown_inside_a_skill_carries_no_verdict(tmp_path: Path) -> None:
    """The interior scan walks a skill directory from disk rather than from the plan,
    so a stray markdown file is read wherever it came from. A local note git refuses
    to track is not an authoring defect in this repository, and failing the build over
    one puts the verdict back on the working directory."""
    repo = _git_tracked_repo(
        _repo(
            tmp_path,
            skills={"tidy": _RECORD + "body\n"},
            shared_skill_files={"tidy": {"references/keep.md": "plain prose\n"}},
        ),
        "scratch.md\n",
    )
    skill = repo / "src" / "user" / ".agents" / "skills" / "tidy"
    (skill / "references" / "scratch.md").write_text(_RECORD + "notes\n", encoding="utf-8")

    result = _lint(repo)

    assert result.ok
    assert result.violations == []


def test_a_tracked_markdown_inside_a_skill_is_still_judged(tmp_path: Path) -> None:
    """The floor under the interior skip: the same file under no ignore rule still
    reports, so the filter never becomes a way to stop scanning skill interiors."""
    repo = _git_tracked_repo(
        _repo(
            tmp_path,
            skills={"tidy": _RECORD + "body\n"},
            shared_skill_files={"tidy": {"references/scratch.md": _RECORD + "notes\n"}},
        ),
        "nothing-here\n",
    )

    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if "carries deploy-time metadata" in v]


# ---------------------------------------------------------------------------
# The silencing channels, as a set rather than one at a time. Each is
# individually justified and each is a way for part of the check to vanish while
# the findings that survive keep printing — which is why the fixture carries one
# fail-open shape per place the walk can go quiet, and every channel is asked
# what it took.
# ---------------------------------------------------------------------------
_FAIL_OPEN_SHAPES = (
    Path("src/newtree"),  # nothing under src/ reaches it
    Path("src/plugins/demo/.claude/hooks"),  # a plugin namespace no tool overlays
    Path("src/plugins/demo/docs"),  # a plugin scope no overlay reads
    Path("src/user/.agents/prompts"),  # a namespace no adapter stages
    Path("src/user/.newtool"),  # a tool tree the registry does not know
)

# The one dot-directory in the fixture, which is what makes '.*/' measurable:
# every other shape keeps firing under it, so the run still reads healthy.
_DOTTED_SHAPE = Path("src/user/.newtool")


def _fail_open_repo(tmp_path: Path, *, ignore_text: str = _INSTALLIGNORE) -> Path:
    """A repo that stages cleanly and carries one directory per fail-open shape."""
    repo = _repo(
        tmp_path,
        skills={"tidy": _RECORD + "body\n"},
        plugin_rules={"demo/demo.md": _RECORD + "body\n"},
    )
    (repo / ".installignore").write_text(ignore_text, encoding="utf-8")
    for shape in _FAIL_OPEN_SHAPES:
        (repo / shape).mkdir(parents=True, exist_ok=True)
    return repo


def _walk_inputs(repo: Path) -> dict:
    """The accounting walk's inputs, built the way ``lint_content`` builds them.

    Driven directly rather than through ``lint_content`` because two of the six
    channels — the namespace names and the staging roots themselves — are
    answers the registry gives, and arranging one through the registry would mean
    inventing a tool or an adapter to test a branch that is three lines long.
    Handing the map in is the same seam the route tests use.
    """
    from installer.plugins.registry import discover

    plugins_root = repo / "src" / "plugins"
    return {
        "staged": _staged_dirs(
            repo, plugins_root=plugins_root, plugins=tuple(discover(plugins_root).values())
        ),
        "ignore": load_installignore(repo / ".installignore"),
        "git_ignored": frozenset(),
    }


def test_every_fail_open_shape_fires_on_the_bare_fixture(tmp_path: Path) -> None:
    """The control. A fixture that silences a shape it was never reporting proves
    nothing about the channel that silenced it, so the shapes are pinned firing
    before any channel is asked to remove one."""
    repo = _fail_open_repo(tmp_path)
    result = _lint(repo)

    assert not result.ok
    for shape in _FAIL_OPEN_SHAPES:
        assert [v for v in result.violations if v.startswith(f"{shape}:")], shape
    assert _unaccounted_dirs(repo, **_walk_inputs(repo)).unaccounted == sorted(_FAIL_OPEN_SHAPES)


_Arranger = Callable[[Path, dict, pytest.MonkeyPatch], AbstractContextManager[None]]


def _silence_ungated(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    return _exemption({Path("src/newtree"): "a reason the test supplies"})


def _silence_git(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    inputs["git_ignored"] = frozenset({repo / "src" / "newtree"})
    return nullcontext()


def _silence_staged(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    inputs["staged"][repo / "src" / "newtree" / "rules"] = frozenset()
    return nullcontext()


def _silence_namespace(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    root = repo / "src" / "user" / ".agents"
    inputs["staged"][root] = inputs["staged"][root] | {"prompts"}
    return nullcontext()


def _silence_build(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    monkeypatch.setattr("installer.core.content_lint.BUILD_DIRS", frozenset({"newtree"}))
    return nullcontext()


def _silence_installignore(repo: Path, inputs: dict, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    (repo / ".installignore").write_text(_INSTALLIGNORE + "newtree/\n", encoding="utf-8")
    inputs["ignore"] = load_installignore(repo / ".installignore")
    return nullcontext()


@pytest.mark.parametrize(
    ("channel", "target", "arrange"),
    [
        (CH_UNGATED, Path("src/newtree"), _silence_ungated),
        (CH_GIT, Path("src/newtree"), _silence_git),
        (CH_STAGED, Path("src/newtree"), _silence_staged),
        (CH_NAMESPACE, Path("src/user/.agents/prompts"), _silence_namespace),
        (CH_BUILD, Path("src/newtree"), _silence_build),
        (CH_INSTALLIGNORE, Path("src/newtree"), _silence_installignore),
    ],
    ids=["ungated", "git", "staged-root", "namespace", "build-dirs", "installignore"],
)
def test_a_channel_that_removes_a_finding_says_so_and_says_how_much(
    channel: str,
    target: Path,
    arrange: _Arranger,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both halves of the same fact, per channel: the finding is gone, and the run
    still says a directory went unreported and which channel answered for it.

    Without the second half a green run cannot be read — every channel here is
    legitimate, so the only thing distinguishing "the tree got tidier" from "a
    channel got wider" is the count. The other four shapes are asserted still
    firing because that is the shape of the defect: silence that leaves the rest
    of the report intact looks like health."""
    repo = _fail_open_repo(tmp_path)
    before = len(_unaccounted_dirs(repo, **_walk_inputs(repo)).silenced.get(channel, []))

    inputs = _walk_inputs(repo)
    with arrange(repo, inputs, monkeypatch):
        walk = _unaccounted_dirs(repo, **inputs)

    assert walk.unaccounted == sorted(s for s in _FAIL_OPEN_SHAPES if s != target)
    assert target in walk.silenced[channel]
    assert len(walk.silenced[channel]) == before + 1


_EndToEnd = Callable[[Path, pytest.MonkeyPatch], AbstractContextManager[None]]


def _already_firing(repo: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    """The two channels the fixture exercises without being asked to: it holds
    staging roots, and one of them declares namespaces."""
    return nullcontext()


def _live_ungated(repo: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    return _exemption({Path("src/newtree"): "a reason the test supplies"})


def _live_git(repo: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    _git_tracked_repo(repo, "newtree/\n")
    return nullcontext()


def _live_build(repo: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    monkeypatch.setattr("installer.core.content_lint.BUILD_DIRS", frozenset({"newtree"}))
    return nullcontext()


def _live_installignore(repo: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ARG001
    (repo / ".installignore").write_text(_INSTALLIGNORE + "newtree/\n", encoding="utf-8")
    return nullcontext()


@pytest.mark.parametrize(
    ("channel", "arrange"),
    [
        (CH_UNGATED, _live_ungated),
        (CH_GIT, _live_git),
        (CH_STAGED, _already_firing),
        (CH_NAMESPACE, _already_firing),
        (CH_BUILD, _live_build),
        (CH_INSTALLIGNORE, _live_installignore),
    ],
    ids=["ungated", "git", "staged-root", "namespace", "build-dirs", "installignore"],
)
def test_every_channels_count_reaches_the_lints_own_report(
    channel: str, arrange: _EndToEnd, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each channel again, end to end this time. The walk knowing what it took is
    only half the floor: the count has to survive out to the result a caller reads,
    or the report exists where nobody looks at it."""
    repo = _fail_open_repo(tmp_path)

    with arrange(repo, monkeypatch):
        result = _lint(repo)

    assert result.silenced.get(channel, 0) >= 1


def test_a_channel_that_took_nothing_is_absent_from_the_report(tmp_path: Path) -> None:
    """A channel prints because it did something. A standing row of zeroes is a
    block a reader learns to skip, which is the failure mode the whole report is
    meant to avoid."""
    repo = _fail_open_repo(tmp_path)
    result = _lint(repo)

    assert CH_INSTALLIGNORE not in result.silenced  # nothing in the fixture matches one
    assert CH_UNGATED not in result.silenced  # the register ships empty


@pytest.mark.parametrize("pattern", ["*/", ".*/"])
def test_a_directory_pattern_naming_nothing_fails_the_run(pattern: str, tmp_path: Path) -> None:
    """The two measured over-broad patterns. ``*/`` takes every shape in the fixture
    and ``.*/`` takes the one dot-directory — the unregistered-tool-tree class this
    gate exists to catch — and under either the surviving output reads healthy. The
    manifest declares directories by name, so a directory pattern with no name in it
    is the violation, whatever it happened to match in this tree."""
    repo = _fail_open_repo(tmp_path, ignore_text=_INSTALLIGNORE + pattern + "\n")
    result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith(f".installignore: {pattern}")]


def test_the_widest_pattern_still_fails_after_it_has_silenced_everything(
    tmp_path: Path,
) -> None:
    """``*/`` is the fail-open in its pure form: every finding gone, nothing left to
    report, and before this the run was green. The pattern check is what stands in
    for the findings it removed."""
    repo = _fail_open_repo(tmp_path, ignore_text=_INSTALLIGNORE + "*/\n")
    result = _lint(repo)

    assert not [v for v in result.violations if "staging never reads" in v]
    assert not result.ok


def test_a_dotted_pattern_leaves_the_other_shapes_firing(tmp_path: Path) -> None:
    """Why the pattern check is not a threshold on the count: ``.*/`` removes one
    finding out of five, so any measure of "how much was silenced" reads this as
    ordinary while the class it silenced is the one that matters."""
    repo = _fail_open_repo(tmp_path, ignore_text=_INSTALLIGNORE + ".*/\n")
    result = _lint(repo)

    assert not [v for v in result.violations if v.startswith(f"{_DOTTED_SHAPE}:")]
    assert len([v for v in result.violations if "staging never reads" in v]) == 4
    assert [v for v in result.violations if v.startswith(".installignore: .*/")]


def test_a_glob_that_still_names_something_is_left_alone(tmp_path: Path) -> None:
    """The rule asks for a name, not for a literal. A pattern bounded by something a
    reader can search for is a declaration about known content, which is what the
    manifest is for."""
    repo = _fail_open_repo(tmp_path, ignore_text=_INSTALLIGNORE + "*cache*/\n")
    result = _lint(repo)

    assert not [v for v in result.violations if v.startswith(".installignore:")]


def test_an_exemption_the_walk_cannot_reach_is_reported_stale(tmp_path: Path) -> None:
    """Existence is only half of "this exemption does nothing". The walk stops at a
    directory staging reads whole, so an entry naming a path inside a namespace is
    exempting a directory from a question it was never going to be asked — it exists,
    it has never fired, and to a check that asks only whether the path is there it is
    indistinguishable from a live exemption."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "body\n"})
    unreachable = Path("src/user/.agents/skills/tidy/scripts")
    (repo / unreachable).mkdir(parents=True)

    with _exemption({unreachable: "an entry that has never silenced anything"}):
        result = _lint(repo)

    assert not result.ok
    assert [v for v in result.violations if v.startswith(f"{unreachable}: ")]
    assert [v for v in result.violations if "never reaches" in v]
