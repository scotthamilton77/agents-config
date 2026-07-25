"""The repo-side content lint over a real ``src/`` tree.

Pins the decisions that make this check different from the deploy gate it
delegates to: it stages every tool regardless of the machine, it reports the
budget numbers whether or not anything breached, and it treats a record-less
artifact as fatal or merely reportable according to which subtree it sits in.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.content_lint import lint_content
from installer.core.io_port import ScriptedIO
from installer.core.surface_budget import SKILL_BODY_TOKEN_CAP
from installer.tools.registry import known_tools

_RECORD = "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"

_INSTALLIGNORE = "AGENTS.md\nCLAUDE.md\nGEMINI.md\nREADME.md\nrules-readmes/\n"


def _repo(
    tmp_path: Path,
    *,
    skills: dict[str, str] | None = None,
    plugin_rules: dict[str, str] | None = None,
) -> Path:
    """A minimal repo root the lint can stage.

    ``skills`` maps a shared skill name to its full SKILL.md text; ``plugin_rules``
    maps ``<plugin>/<rule>.md`` to a rule's full text.
    """
    (tmp_path / ".installignore").write_text(_INSTALLIGNORE, encoding="utf-8")
    shared = tmp_path / "src" / "user" / ".agents"
    shared.mkdir(parents=True)
    (shared / "AGENTS.md.template").write_text("# laws\n", encoding="utf-8")

    for name, text in (skills or {}).items():
        skill_dir = shared / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")

    for relpath, text in (plugin_rules or {}).items():
        plugin, filename = relpath.split("/", 1)
        rules_dir = tmp_path / "src" / "plugins" / plugin / ".agents" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / filename).write_text(text, encoding="utf-8")

    return tmp_path


def _lint(repo_root: Path):  # ContentLintResult; inferred at every call site
    return lint_content(repo_root, io=ScriptedIO())


def test_clean_tree_passes_and_still_reports_its_numbers(tmp_path: Path) -> None:
    """The bar's whole value as a trend instrument is that the numbers print on a
    PASS: a check that speaks only at the cliff gives no warning of the approach."""
    repo = _repo(tmp_path, skills={"tidy": _RECORD + "a short body\n"})
    result = _lint(repo)

    assert result.ok
    assert result.violations == []
    assert [m.tokens for m in result.skills if m.label.endswith("skills/tidy")]
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

    Reported once for the one file, naming every tool it would have deployed to —
    four lines and a count of four would read as four separate defects.
    """
    oversize = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    repo = _repo(tmp_path, skills={"bloated": _RECORD + oversize})
    result = _lint(repo)

    assert not result.ok
    assert len(result.violations) == 1
    assert "skills/bloated" in result.violations[0]
    assert "over the" in result.violations[0]
    for tool in known_tools():
        assert tool.value in result.violations[0]


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
    assert [u.source.name for u in result.fatal_unadmitted] == ["orphan"]


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
