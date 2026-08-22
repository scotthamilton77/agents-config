"""The Codex skill-policy sidecar.

A skill whose front matter declares it user-invoked deploys to Codex with a
generated ``agents/openai.yaml`` beside its ``SKILL.md``, carrying the vendor's
own declaration (``policy.allow_implicit_invocation: false``) — so Codex keeps
the skill out of implicit invocation the way Claude does through the front
matter key. Each test pins one decision of that emission: who gets the file,
what its bytes parse to, which entry text decides, and how the deployed copy is
receipt-tracked so a prune removes it with the rest of the skill.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.core.installignore import InstallIgnore
from installer.core.io_port import ScriptedIO
from installer.core.model import Contribution, FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.orchestrator import stage_and_transform
from installer.core.receipt import dir_content_digest
from installer.core.receipt_build import entries_from_outcomes
from installer.core.sync import sync_plan
from installer.tools.claude import ClaudeAdapter
from installer.tools.codex import SIDECAR_RELPATH, CodexAdapter
from installer.tools.gemini import GeminiAdapter
from installer.tools.opencode import OpenCodeAdapter

_PROV = Provenance(kind="tool", name="codex")
_FIXED_TS = "20260101-000000"

_USER_INVOKED = b"---\nname: s\ndescription: d\ndisable-model-invocation: true\n---\nbody\n"
_MODEL_INVOKED = b"---\nname: s\ndescription: d\n---\nbody\n"


def _skill_src(tmp_path: Path, entry: bytes) -> Path:
    src = tmp_path / "skill_src"
    src.mkdir(exist_ok=True)
    (src / "SKILL.md").write_bytes(entry)
    return src


def _skill_plan(src: Path, tool: Tool) -> StagingPlan:
    item = StagedItem(
        source_path=src,
        dest_relpath=Path("skills/s"),
        kind=FileKind.DIR,
        namespace="skills",
        provenance=_PROV,
    )
    return StagingPlan(items={item.dest_relpath: item}, tool=tool)


def _sidecar_of(plan: StagingPlan) -> Contribution | None:
    return plan.dir_overrides.get(Path("skills/s"), {}).get(SIDECAR_RELPATH)


def test_user_invoked_skill_gains_the_sidecar_with_exact_policy_yaml(tmp_path: Path) -> None:
    """
    Given a DIR skill whose SKILL.md declares disable-model-invocation: true
    When the Codex adapter's post-staging transform runs
    Then the plan carries an agents/openai.yaml override for that skill whose
    parsed YAML is exactly {"policy": {"allow_implicit_invocation": False}},
    with a real YAML boolean — Codex's loader type-validates the field, so a
    string "false" would be rejected (and would read as truthy anywhere that
    didn't).
    """
    plan = _skill_plan(_skill_src(tmp_path, _USER_INVOKED), Tool.CODEX)
    out = CodexAdapter().post_staging_transforms(plan, ScriptedIO())
    sidecar = _sidecar_of(out)
    assert sidecar is not None
    parsed = yaml.safe_load(sidecar.content)
    assert parsed == {"policy": {"allow_implicit_invocation": False}}
    assert parsed["policy"]["allow_implicit_invocation"] is False


def test_skill_without_the_key_gets_no_sidecar(tmp_path: Path) -> None:
    """
    Given a DIR skill whose SKILL.md carries no disable-model-invocation key
    When the Codex adapter's post-staging transform runs
    Then no sidecar override is added — a model-invoked skill keeps Codex's
    default (implicit invocation allowed) without a generated file saying so.
    """
    plan = _skill_plan(_skill_src(tmp_path, _MODEL_INVOKED), Tool.CODEX)
    out = CodexAdapter().post_staging_transforms(plan, ScriptedIO())
    assert _sidecar_of(out) is None


def test_explicit_false_gets_no_sidecar(tmp_path: Path) -> None:
    """
    Given a SKILL.md declaring disable-model-invocation: false
    When the Codex adapter's post-staging transform runs
    Then no sidecar is emitted — the declaration reads through the same
    strict-True test the budget uses, so an explicit false and a stray string
    both mean model-invoked.
    """
    entry = b"---\nname: s\ndescription: d\ndisable-model-invocation: false\n---\nbody\n"
    plan = _skill_plan(_skill_src(tmp_path, entry), Tool.CODEX)
    out = CodexAdapter().post_staging_transforms(plan, ScriptedIO())
    assert _sidecar_of(out) is None


def test_other_adapters_emit_no_sidecar(tmp_path: Path) -> None:
    """
    Given the same user-invoked DIR skill staged for Claude, Gemini and OpenCode
    When each adapter's post-staging transform runs
    Then none of them adds the sidecar — the file is Codex's declaration form,
    meaningless bytes anywhere else.
    """
    src = _skill_src(tmp_path, _USER_INVOKED)
    for adapter, tool in (
        (ClaudeAdapter(), Tool.CLAUDE),
        (GeminiAdapter(), Tool.GEMINI),
        (OpenCodeAdapter(), Tool.OPENCODE),
    ):
        out = adapter.post_staging_transforms(_skill_plan(src, tool), ScriptedIO())
        assert _sidecar_of(out) is None, tool


def test_stage_and_transform_yields_sidecar_for_codex_only(
    tmp_path: Path, ignore: InstallIgnore
) -> None:
    """
    Given a shared skill carrying the key, staged end-to-end for every tool
    When stage_and_transform builds each tool's plan
    Then only the Codex plan carries the agents/openai.yaml override — the
    emission rides the per-tool transform pass, so no other tool's staged tree
    ever contains it.
    """
    repo = tmp_path / "repo"
    skill = repo / "src" / "user" / ".agents" / "skills" / "s"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(_USER_INVOKED)
    for tool in ("claude", "codex", "gemini", "opencode"):
        (repo / "src" / "user" / f".{tool}").mkdir(parents=True)

    plans = stage_and_transform(
        [Tool.CLAUDE, Tool.CODEX, Tool.GEMINI, Tool.OPENCODE],
        repo_root=repo,
        io=ScriptedIO(),
        ignore=ignore,
    )

    assert _sidecar_of(plans[Tool.CODEX]) is not None
    for tool in (Tool.CLAUDE, Tool.GEMINI, Tool.OPENCODE):
        if Path("skills/s") in plans[tool].items:
            assert _sidecar_of(plans[tool]) is None, tool


def test_overridden_entry_file_decides_not_the_source_tree(tmp_path: Path) -> None:
    """
    Given a skill whose source-tree SKILL.md is model-invoked but whose
    dir_overrides already carry a SKILL.md declaring the key (the bytes a
    carrier merge or extension patch will actually deploy)
    When the Codex adapter's post-staging transform runs
    Then the sidecar is emitted — the declaration is read from the bytes that
    reach disk, not from the tree they replaced. And with the two swapped
    (source declares, override does not), nothing is emitted.
    """
    src = _skill_src(tmp_path, _MODEL_INVOKED)
    plan = _skill_plan(src, Tool.CODEX)
    plan.dir_overrides[Path("skills/s")] = {
        Path("SKILL.md"): Contribution(source_path=src / "SKILL.md", content=_USER_INVOKED)
    }
    assert _sidecar_of(CodexAdapter().post_staging_transforms(plan, ScriptedIO())) is not None

    swapped_src = tmp_path / "swapped"
    swapped_src.mkdir()
    (swapped_src / "SKILL.md").write_bytes(_USER_INVOKED)
    swapped = _skill_plan(swapped_src, Tool.CODEX)
    swapped.dir_overrides[Path("skills/s")] = {
        Path("SKILL.md"): Contribution(source_path=swapped_src / "SKILL.md", content=_MODEL_INVOKED)
    }
    assert _sidecar_of(CodexAdapter().post_staging_transforms(swapped, ScriptedIO())) is None


def test_contradictory_authored_sidecar_aborts_staging(tmp_path: Path) -> None:
    """
    Given a user-invoked skill whose source tree ships its own
    agents/openai.yaml that does NOT declare allow_implicit_invocation: false
    When the Codex adapter's post-staging transform runs
    Then staging aborts — the front matter says never fire unprompted, the
    authored sidecar would deploy Codex the opposite, and neither file may
    silently win over the other.
    """
    src = _skill_src(tmp_path, _USER_INVOKED)
    (src / "agents").mkdir()
    (src / "agents" / "openai.yaml").write_bytes(b"policy:\n  allow_implicit_invocation: true\n")
    with pytest.raises(ValueError, match="disable-model-invocation"):
        CodexAdapter().post_staging_transforms(_skill_plan(src, Tool.CODEX), ScriptedIO())


def test_contradictory_override_sidecar_aborts_staging(tmp_path: Path) -> None:
    """
    Given a user-invoked skill whose dir_overrides already carry an
    agents/openai.yaml (a carrier merge or extension patch) without the policy
    When the Codex adapter's post-staging transform runs
    Then staging aborts — override bytes are the ones that reach disk, so they
    are judged by the same rule as an authored source file.
    """
    src = _skill_src(tmp_path, _USER_INVOKED)
    plan = _skill_plan(src, Tool.CODEX)
    plan.dir_overrides[Path("skills/s")] = {
        SIDECAR_RELPATH: Contribution(
            source_path=src / "agents" / "openai.yaml", content=b"interface: {}\n"
        )
    }
    with pytest.raises(ValueError, match="disable-model-invocation"):
        CodexAdapter().post_staging_transforms(plan, ScriptedIO())


def test_consistent_authored_sidecar_is_left_alone(tmp_path: Path) -> None:
    """
    Given a user-invoked skill whose source tree already ships an
    agents/openai.yaml declaring allow_implicit_invocation: false
    When the Codex adapter's post-staging transform runs
    Then no override is added — the authored file is the author's declaration,
    and a generated one silently replacing it would ship bytes nobody wrote.
    """
    src = _skill_src(tmp_path, _USER_INVOKED)
    (src / "agents").mkdir()
    (src / "agents" / "openai.yaml").write_bytes(
        b"interface:\n  display_name: S\npolicy:\n  allow_implicit_invocation: false\n"
    )
    out = CodexAdapter().post_staging_transforms(_skill_plan(src, Tool.CODEX), ScriptedIO())
    assert _sidecar_of(out) is None


class _IdentityAdapter:
    """Adapter double whose dest tree is ``home`` itself."""

    name = "codex"

    def dest_dir(self, home: Path) -> Path:
        return home


def test_sidecar_deploys_inside_the_skill_and_the_receipt_digest_covers_it(
    tmp_path: Path,
) -> None:
    """
    Given a user-invoked skill transformed for Codex
    When sync_plan materialises it and the install outcomes become receipt entries
    Then the sidecar is on disk inside the deployed skill, and the skill dir's
    receipt entry records a dir_digest that matches the tree WITH the sidecar —
    and stops matching without it. That digest is the owned-state record the
    prune path compares before deleting, so the sidecar is removed with the
    skill on uninstall rather than surviving as an orphan.
    """
    plan = CodexAdapter().post_staging_transforms(
        _skill_plan(_skill_src(tmp_path, _USER_INVOKED), Tool.CODEX), ScriptedIO()
    )
    home = tmp_path / "home"
    outcomes: list = []
    sync_plan(
        _IdentityAdapter(),  # type: ignore[arg-type]  # sync_plan only calls dest_dir
        plan,
        home=home,
        io=ScriptedIO(),
        timestamp=_FIXED_TS,
        outcomes=outcomes,
    )

    dest = home / "skills" / "s"
    sidecar = dest / "agents" / "openai.yaml"
    assert yaml.safe_load(sidecar.read_bytes()) == {"policy": {"allow_implicit_invocation": False}}

    entries = entries_from_outcomes(outcomes, tool="codex", dest_root=home, home=home)
    entry = next(e for e in entries if e.path == Path("skills/s"))
    assert entry.kind == "dir"
    assert entry.dir_digest == dir_content_digest(dest)

    sidecar.unlink()
    assert dir_content_digest(dest) != entry.dir_digest
