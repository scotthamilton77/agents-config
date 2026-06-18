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


def test_csv_tools_wrapped_inline_preserving_raw_spacing() -> None:
    # Bash awk wraps the RAW value string in brackets (printf "tools: [%s]"), so
    # the source comma-space spacing survives byte-for-byte. A pyyaml round-trip
    # would instead emit a block sequence — the exact divergence this fixes.
    src = b"---\nname: a\ntools: Read, Edit, Write, Grep, Glob, Bash\n---\nbody\n"
    out = transform_agent_frontmatter(src)
    assert b"\ntools: [Read, Edit, Write, Grep, Glob, Bash]\n" in out
    assert b"\n- Read\n" not in out  # never a block sequence


def test_single_tool_becomes_one_element_sequence() -> None:
    src = b"---\nname: a\ntools: Read\n---\nbody\n"
    assert _frontmatter(transform_agent_frontmatter(src))["tools"] == ["Read"]


def test_already_inline_tools_not_double_wrapped() -> None:
    # A value already starting with `[` (inline flow sequence) fails the bash
    # `val !~ /^\[/` guard, so it is left verbatim — never `[[...]]`.
    src = b"---\nname: a\ntools: [Read, Grep]\n---\nbody\n"
    out = transform_agent_frontmatter(src)
    assert b"\ntools: [Read, Grep]\n" in out
    assert b"[[" not in out


def test_already_sequence_tools_not_double_wrapped() -> None:
    src = b"---\nname: a\ntools:\n  - Read\n  - Grep\n---\nbody\n"
    assert _frontmatter(transform_agent_frontmatter(src))["tools"] == ["Read", "Grep"]


def test_description_block_scalar_preserved_while_stripping_and_wrapping() -> None:
    # The headline parity guarantee: a `description: |-` block scalar survives
    # byte-for-byte even as color: is stripped and tools: is wrapped. The pyyaml
    # round-trip reflowed the block (quoting/spacing/style); the line port leaves
    # every untouched line verbatim. Mirrors install.sh transform_gemini_agent_
    # frontmatter (the surgical awk).
    block = "description: |-\n  Line one.\n\n  Line two with: a colon and  weird   spacing.\n"
    src = ("---\nname: a\n" + block + "tools: Read, Grep\ncolor: purple\n---\nbody\n").encode()
    out = transform_agent_frontmatter(src).decode("utf-8")
    assert block in out  # block scalar byte-identical
    assert "\ntools: [Read, Grep]\n" in out  # tools wrapped inline
    assert "color:" not in out  # claude-only key stripped
    assert out.startswith("---\nname: a\n")


def test_strips_key_with_indented_block() -> None:
    src = b"---\nname: a\nskills:\n  - one\n  - two\ntools: Read\n---\nbody\n"
    fm = _frontmatter(transform_agent_frontmatter(src))
    assert "skills" not in fm
    assert fm["name"] == "a"


def test_no_frontmatter_passes_through_byte_identical() -> None:
    src = b"# Just a markdown agent\nNo frontmatter here.\n"
    assert transform_agent_frontmatter(src) == src


def test_missing_trailing_newline_is_normalized_like_awk() -> None:
    # awk terminates every record with \n, so a file lacking a final newline
    # gains one (matching bash). Pins the record-reconstruction decision.
    src = b"# no frontmatter, no trailing newline"
    assert transform_agent_frontmatter(src) == src + b"\n"


def test_empty_content_returns_empty_like_awk() -> None:
    # A 0-byte file never enters awk's main loop, so bash emits nothing. Without
    # the empty guard, record reconstruction would add a stray newline.
    assert transform_agent_frontmatter(b"") == b""


def test_unterminated_frontmatter_still_transforms_like_bash() -> None:
    # Bash awk has no closing-fence guard: once the opening --- is seen it keeps
    # transforming every subsequent line. Mirror that — tools: is wrapped even
    # with no closing ---, and the trailing non-frontmatter line is preserved.
    src = b"---\nname: a\ntools: Read\n(no closing fence)\n"
    out = transform_agent_frontmatter(src)
    assert b"\ntools: [Read]\n" in out
    assert b"(no closing fence)\n" in out


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
    # The line port never parses YAML, so a typo can't abort the install: no line
    # is a Claude-only key or a `tools:` line, so nothing matches and the bytes
    # survive verbatim.
    src = b'---\nkey: "unterminated\n---\nbody\n'
    assert transform_agent_frontmatter(src) == src


def test_non_mapping_frontmatter_passes_through_unchanged() -> None:
    # Sequence/scalar frontmatter has no key=value line to match either, so the
    # line port leaves it byte-identical (no structural validation happens).
    src = b"---\n- a\n- b\n---\nbody\n"
    assert transform_agent_frontmatter(src) == src


def test_quoted_empty_tools_string_is_bracket_wrapped_like_bash() -> None:
    # Bash's length>0 guard is on the RAW substring after `tools:`, not on parsed
    # items — so a quoted empty string (`tools: ""`, length 2) is non-empty and
    # gets wrapped to `tools: [""]`. Only a truly empty value (`tools:` with
    # nothing after) is left alone. color: is still stripped.
    src = b'---\nname: a\ncolor: red\ntools: ""\n---\nbody\n'
    out = transform_agent_frontmatter(src)
    assert b'\ntools: [""]\n' in out
    assert b"color:" not in out


def test_bare_empty_tools_value_left_untouched() -> None:
    # `tools:` with nothing after it (raw value length 0) fails the bash length>0
    # guard, so the line is printed verbatim — no `[]` wrapping.
    src = b"---\nname: a\ntools:\n---\nbody\n"
    out = transform_agent_frontmatter(src)
    assert b"\ntools:\n" in out
    assert b"tools: [" not in out


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
