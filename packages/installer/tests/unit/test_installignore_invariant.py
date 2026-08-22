"""Invariant guard: the known confirmed dev-doc leakers never appear in the
Python installer's staged output, using the REAL repo-root .installignore.

The leaker paths are HARDCODED here, deliberately NOT sourced from .installignore:
a manifest-sourced check would go blind to the exact regression it must catch —
someone deleting an entry from .installignore. This test goes red on a manifest
mis-edit OR a staging-logic regression."""

from __future__ import annotations

from pathlib import Path

from installer.core.installignore import InstallIgnore, load_installignore
from installer.core.model import Tool
from installer.core.staging import build_plan
from installer.tools.registry import get_adapter

_REPO_ROOT = Path(__file__).resolve().parents[4]

# Confirmed live leakers (design spec audit table). Their relpaths must never
# survive base staging into any tool's plan.
_FORBIDDEN_RELPATHS = (
    Path("rules/AGENTS.md"),
    Path("skills/AGENTS.md"),
)
_NAMESPACE_DIRS = {"skills", "agents", "rules", "commands", "hooks"}
_MARKER_BASENAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md"}


def test_known_dead_docs_are_never_staged() -> None:
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    for tool in Tool:
        adapter = get_adapter(tool)
        plan = build_plan(adapter, repo_root=_REPO_ROOT, ignore=ignore)

        for forbidden in _FORBIDDEN_RELPATHS:
            assert forbidden not in plan.items, f"{forbidden} leaked into {tool} plan"
        # No namespace-level AGENTS.md/CLAUDE.md/GEMINI.md under a staged subdir.
        for dest in plan.items:
            parts = dest.parts
            if len(parts) >= 2 and parts[-1] in _MARKER_BASENAMES:
                assert parts[-2] not in _NAMESPACE_DIRS, (
                    f"namespace dead-doc {dest} leaked into {tool} plan"
                )


def test_marker_docs_are_excluded_at_every_depth_not_just_the_namespace_level() -> None:
    """The three marker names must stay UNANCHORED in the real manifest.

    Staging sees only a namespace dir's direct children; a skill stages as one
    DIR item whose interior the copy walks separately. An anchored marker entry
    would therefore leave ``skills/<skill>/AGENTS.md`` deploying — and in this
    repo a skill's own AGENTS.md is guidance for whoever maintains its scripts,
    so it would ship to every install carrying repo-internal vocabulary.

    This pins the manifest's policy, not the matcher's mechanism (that is
    test_installignore.py's job): re-anchoring any of the three turns it red."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    for marker in sorted(_MARKER_BASENAMES):
        for rel in (Path(f"some-skill/{marker}"), Path(f"some-skill/references/{marker}")):
            assert ignore.excludes_path(rel), (
                f"{rel} would deploy — {marker} is anchored in .installignore and must not be"
            )


def test_readme_stays_anchored_so_a_skill_can_ship_one() -> None:
    """README.md is the deliberate exception to the rule above.

    Unlike the marker names it is genuinely ambiguous — a skill's own
    references/README.md may be content it means to ship — so it stays anchored
    to the namespace level. Unanchoring it would silently stop deploying that
    file, which is the failure mode the anchoring rule exists to prevent."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")

    assert not ignore.excludes_path(Path("some-skill/references/README.md"))
    assert ignore.excludes("README.md", is_dir=False, at_root=True)


def test_shell_test_suites_are_excluded_by_class_not_by_name() -> None:
    """A hook's own ``*_test.sh`` suite must never deploy, using the REAL repo
    ``.installignore`` and the REAL Claude hooks/ staging (hooks are Claude-only).

    ``ruff-postedit_test.sh`` was once carried as a single named entry; a second
    shell suite (``codex-broker-reaper_test.sh``) shipped anyway because nothing
    excluded the class. Both must be caught the same way ``*_test.py`` catches
    every Python suite, so a third hook's own suite needs no new manifest line."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")
    plan = build_plan(get_adapter(Tool.CLAUDE), repo_root=_REPO_ROOT, ignore=ignore)

    for leaker in ("ruff-postedit_test.sh", "codex-broker-reaper_test.sh"):
        assert Path("hooks") / leaker not in plan.items, f"{leaker} leaked into the Claude plan"
        assert ignore.excludes(leaker, is_dir=False, at_root=True)


def _deployed_relpaths(source: Path, ignore: InstallIgnore) -> set[Path]:
    """What a DIR item's interior actually places at dest, derived the way the
    sync derives it — the source tree filtered through ``excludes_path``."""
    return {
        rel
        for rel in (p.relative_to(source) for p in source.rglob("*") if p.is_file())
        if not ignore.excludes_path(rel)
    }


def _staged_skills_carrying_evals(ignore: InstallIgnore) -> dict[Tool, dict[Path, Path]]:
    """Per tool, the dest relpath -> source dir of every staged skill that has an
    ``evals/`` directory in source."""
    found: dict[Tool, dict[Path, Path]] = {}
    for tool in Tool:
        plan = build_plan(get_adapter(tool), repo_root=_REPO_ROOT, ignore=ignore)
        found[tool] = {
            dest: item.source_path
            for dest, item in plan.items.items()
            if item.namespace == "skills"
            and item.content is None
            and (item.source_path / "evals").is_dir()
        }
    return found


def test_eval_corpora_never_deploy_for_any_tool() -> None:
    """A skill's ``evals/`` holds the trigger-eval corpus the author grades the
    skill against — repo-side verification data of the same class as a
    ``*_test.py`` suite, and excluded on the same rule: a file the repo gate
    consumes as verification is never a file the installer ships.

    Keyed on the directory, not on a filename: the corpora are split between
    ``trigger-eval.json`` and ``evals.json``, so a name-keyed entry would catch
    most of them and leave the rest shipping, which reads as an enforced rule
    while being a partial one."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")
    carriers = _staged_skills_carrying_evals(ignore)

    for tool, skills in carriers.items():
        # Per tool, not once globally: a tool whose plan happens to carry no
        # eval-bearing skill would otherwise run no assertion at all and report
        # as covered. One shared skill carries a corpus, so every tool has one.
        assert skills, f"no staged skill carries an evals/ directory for {tool}"
        for dest, source in skills.items():
            deployed = _deployed_relpaths(source, ignore)
            leaked = sorted(rel for rel in deployed if "evals" in rel.parts)
            assert not leaked, f"{dest}: {leaked} would deploy to {tool}"

    # Base staging is not the whole deployed surface — a plugin skill reaches a
    # tool through the overlay phase, out of a source tree no plan above names.
    # The manifest is what prunes a DIR item's interior either way, so every
    # corpus in the tree is checked against it directly.
    # Discovery is depth-agnostic, matching the unanchored entry it checks: the
    # question is asked of the corpora the tree actually holds, wherever they
    # sit, rather than of one depth the glob was shaped to expect. Paths are
    # taken relative to the corpus's own parent, which is enough — the copy
    # filter prunes at the ``evals`` component whatever ancestor it counts from.
    corpora = sorted(_REPO_ROOT.glob("src/**/evals"))
    assert corpora, "no evals/ directory under src/ — this guard proves nothing"
    for corpus in corpora:
        assert not _deployed_relpaths(corpus.parent, ignore) & {
            path.relative_to(corpus.parent) for path in corpus.rglob("*") if path.is_file()
        }, f"{corpus.relative_to(_REPO_ROOT)} would deploy"


def test_excluding_evals_does_not_take_the_rest_of_the_skill_with_it() -> None:
    """The pattern is a directory name, and a directory pattern prunes a whole
    subtree — so the guard that matters beside the exclusion is that the
    subtrees a skill means to ship still arrive. ``openrouter-claude-subagent``
    is the one carrier holding all three kinds at once."""
    ignore = load_installignore(_REPO_ROOT / ".installignore")
    source = _REPO_ROOT / "src/user/.claude/skills/openrouter-claude-subagent"
    assert (source / "evals").is_dir(), "fixture skill no longer carries evals/"

    deployed = _deployed_relpaths(source, ignore)
    for kept in (Path("SKILL.md"), Path("references/model-routing.md"), Path("scripts/run.js")):
        assert kept in deployed, f"{kept} stopped deploying"
