"""Behavioural tests for the Gemini frontmatter transform.

Each test pins a coded decision (which keys are stripped, the tools
string->sequence rule, the no-frontmatter passthrough, byte-identity when
there is nothing to change, body preservation), never YAML/stdlib behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from installer.core.io_port import ScriptedIO
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.tools.gemini import GeminiAdapter, transform_agent_frontmatter

_PROV = Provenance(kind="tool", name="gemini")


def _agent_item(relname: str, content: bytes) -> StagedItem:
    return StagedItem(
        source_path=Path("src") / relname,
        dest_relpath=Path("agents") / relname,
        kind=FileKind.NAMESPACED_MD,
        namespace="agents",
        provenance=_PROV,
        content=content,
    )


def _frontmatter(content: bytes) -> dict[str, object]:
    """Parse the YAML frontmatter out of a transformed agent file, for
    asserting on the resulting mapping."""
    parsed = yaml.safe_load(content.decode("utf-8").split("---\n", 2)[1])
    assert isinstance(parsed, dict)
    return parsed


def test_strips_claude_only_keys() -> None:
    src = b"---\nname: a\nskills: x\ncolor: purple\nmemory: y\ntools: Read\n---\nbody\n"
    fm = _frontmatter(transform_agent_frontmatter(src))
    assert "skills" not in fm
    assert "color" not in fm
    assert "memory" not in fm
    assert fm["name"] == "a"


def test_converts_csv_tools_to_sequence() -> None:
    src = b"---\nname: a\ntools: Read, Grep, Glob\n---\nbody\n"
    assert _frontmatter(transform_agent_frontmatter(src))["tools"] == ["Read", "Grep", "Glob"]


def test_single_tool_becomes_one_element_sequence() -> None:
    src = b"---\nname: a\ntools: Read\n---\nbody\n"
    assert _frontmatter(transform_agent_frontmatter(src))["tools"] == ["Read"]


def test_already_sequence_tools_not_double_wrapped() -> None:
    src = b"---\nname: a\ntools:\n  - Read\n  - Grep\n---\nbody\n"
    assert _frontmatter(transform_agent_frontmatter(src))["tools"] == ["Read", "Grep"]


def test_strips_key_with_indented_block() -> None:
    src = b"---\nname: a\nskills:\n  - one\n  - two\ntools: Read\n---\nbody\n"
    fm = _frontmatter(transform_agent_frontmatter(src))
    assert "skills" not in fm
    assert fm["name"] == "a"


def test_no_frontmatter_passes_through_byte_identical() -> None:
    src = b"# Just a markdown agent\nNo frontmatter here.\n"
    assert transform_agent_frontmatter(src) == src


def test_unterminated_frontmatter_passes_through() -> None:
    src = b"---\nname: a\ntools: Read\n(no closing fence)\n"
    assert transform_agent_frontmatter(src) == src


def test_unchanged_frontmatter_returns_byte_identical() -> None:
    # Quoted scalar + already-list tools: nothing to strip or convert, so the
    # original bytes must survive verbatim (no gratuitous pyyaml reformatting
    # such as dropping the quotes).
    src = b'---\nname: a\ndescription: "keep quotes"\ntools:\n- Read\n---\nbody\n'
    assert transform_agent_frontmatter(src) == src


def test_body_after_frontmatter_is_preserved() -> None:
    body = "# Title\n\nLine with --- dashes\nclosing\n"
    src = ("---\nname: a\ncolor: red\ntools: Read\n---\n" + body).encode("utf-8")
    assert transform_agent_frontmatter(src).decode("utf-8").endswith(body)


def test_real_source_agent_is_gemini_clean() -> None:
    """Real-source coverage: the actually-shipped quality-reviewer agent loses
    its Claude-only keys and gains a tools sequence."""
    repo_root = Path(__file__).resolve().parents[4]
    agent = repo_root / "src" / "user" / ".agents" / "agents" / "quality-reviewer.md"
    if not agent.is_file():  # pragma: no cover  # defensive: real tree may move
        pytest.skip(f"real agent source not found at {agent}")
    fm = _frontmatter(transform_agent_frontmatter(agent.read_bytes()))
    assert "color" not in fm
    assert "skills" not in fm
    assert "memory" not in fm
    assert isinstance(fm["tools"], list)


def test_invalid_utf8_passes_through_unchanged() -> None:
    # A non-UTF-8 (e.g. binary) staged file must not crash the install.
    src = b"\xff\xfe\x00not utf-8"
    assert transform_agent_frontmatter(src) == src


def test_malformed_yaml_frontmatter_passes_through_unchanged() -> None:
    # A YAML typo in one agent file must not abort the whole install — it is
    # left verbatim rather than raised.
    src = b'---\nkey: "unterminated\n---\nbody\n'
    assert transform_agent_frontmatter(src) == src


def test_non_mapping_frontmatter_passes_through_unchanged() -> None:
    # Frontmatter that parses to a sequence/scalar (not a mapping) is left as-is.
    src = b"---\n- a\n- b\n---\nbody\n"
    assert transform_agent_frontmatter(src) == src


def test_empty_tools_string_is_not_converted() -> None:
    # An empty tools value yields no sequence items, so it is left untouched
    # (mirrors the bash length>0 guard); other keys still transform.
    src = b'---\nname: a\ncolor: red\ntools: ""\n---\nbody\n'
    fm = _frontmatter(transform_agent_frontmatter(src))
    assert "color" not in fm
    assert fm["tools"] == ""


def test_post_staging_transforms_rewrites_agent_items() -> None:
    item = _agent_item("a.md", b"---\nname: a\ncolor: red\ntools: Read, Grep\n---\nbody\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.GEMINI)
    out = GeminiAdapter().post_staging_transforms(plan, ScriptedIO())
    new_content = out.items[item.dest_relpath].content
    assert new_content is not None
    assert b"color:" not in new_content
    assert _frontmatter(new_content)["tools"] == ["Read", "Grep"]


def test_post_staging_transforms_logs_phase_when_agents_present() -> None:
    item = _agent_item("a.md", b"---\nname: a\ncolor: red\ntools: Read\n---\nbody\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.GEMINI)
    io = ScriptedIO()
    GeminiAdapter().post_staging_transforms(plan, io)
    assert any("frontmatter" in e.message.lower() for e in io.transcript)


def test_post_staging_transforms_leaves_non_agent_items_untouched() -> None:
    item = StagedItem(
        source_path=Path("src/GEMINI.md"),
        dest_relpath=Path("GEMINI.md"),
        kind=FileKind.OTHER,
        namespace=None,
        provenance=_PROV,
        content=b"---\ncolor: red\ntools: Read\n---\nx\n",
    )
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.GEMINI)
    io = ScriptedIO()
    out = GeminiAdapter().post_staging_transforms(plan, io)
    assert out.items[item.dest_relpath].content == item.content
    assert not any("frontmatter" in e.message.lower() for e in io.transcript)


def test_post_staging_transforms_returns_same_plan_when_no_agents() -> None:
    plan = StagingPlan(items={}, tool=Tool.GEMINI)
    assert GeminiAdapter().post_staging_transforms(plan, ScriptedIO()) is plan


def test_post_staging_transforms_logs_phase_once_for_multiple_agents() -> None:
    a = _agent_item("a.md", b"---\nname: a\ncolor: red\ntools: Read\n---\nx\n")
    b = _agent_item("b.md", b"---\nname: b\ncolor: blue\ntools: Grep\n---\ny\n")
    plan = StagingPlan(items={a.dest_relpath: a, b.dest_relpath: b}, tool=Tool.GEMINI)
    io = ScriptedIO()
    GeminiAdapter().post_staging_transforms(plan, io)
    assert sum("frontmatter" in e.message.lower() for e in io.transcript) == 1


def test_post_staging_transforms_keeps_already_clean_agent_item() -> None:
    # An agent already in Gemini form is not re-wrapped in a new StagedItem.
    item = _agent_item("a.md", b"---\nname: a\ntools:\n- Read\n---\nbody\n")
    plan = StagingPlan(items={item.dest_relpath: item}, tool=Tool.GEMINI)
    out = GeminiAdapter().post_staging_transforms(plan, ScriptedIO())
    assert out.items[item.dest_relpath] is item
