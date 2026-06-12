"""Phase 6.5 plugin extensions (plugins/extensions.py).

Behavioural tests for YAML schema validation, scope discovery + R6 ordering,
StagingPlan target resolution/writeback, and the apply_extensions composition
loop. Fixture style mirrors test_overlay.py: tmp_path plugin trees and a
minimal frozen _Plugin standing in for PluginAdapter; assertions are on
returned plan state and structured ExtensionError attrs — never call counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.plugins.extensions import ExtensionError, apply_extensions


@dataclass(frozen=True, slots=True)
class _Plugin:
    name: str
    source_path: Path

    def is_detected(self, home: Path) -> bool:  # noqa: ARG002  # inert  # pragma: no cover
        return True


def _plugin(tmp_path: Path, name: str) -> _Plugin:
    root = tmp_path / "plugins" / name
    root.mkdir(parents=True, exist_ok=True)
    return _Plugin(name=name, source_path=root)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ext_yaml(
    target_file: str = "agents/reviewer.md",
    target_section: str = "Boundaries",
    precision: str = "append",
    content: str = "patched",
) -> str:
    return (
        f"target-file: {target_file}\n"
        f"target-section: {target_section}\n"
        f"precision: {precision}\n"
        f"content: |\n  {content}\n"
    )


def _plan_with_agent_md(text: str = "# Reviewer\n\n## Boundaries\nbase\n") -> StagingPlan:
    item = StagedItem(
        source_path=Path("/base/agents/reviewer.md"),
        dest_relpath=Path("agents/reviewer.md"),
        kind=FileKind.NAMESPACED_MD,
        namespace="agents",
        provenance=Provenance(kind="tool", name="claude"),
        content=text.encode(),
    )
    return StagingPlan(items={item.dest_relpath: item}, tool=Tool.CLAUDE)


@pytest.mark.parametrize(
    ("yaml_text", "reason_match"),
    [
        ("target-file: [unclosed", "malformed YAML"),
        ("- a\n- b\n", "top-level YAML is a list; mapping required"),
        ("just a string\n", "top-level YAML is a scalar; mapping required"),
        (
            "target-section: S\nprecision: append\ncontent: c\n",
            "missing required field: target-file",
        ),
        (
            "target-file: f.md\nprecision: append\ncontent: c\n",
            "missing required field: target-section",
        ),
        (
            "target-file: f.md\ntarget-section: S\ncontent: c\n",
            "missing required field: precision",
        ),
        (
            "target-file: f.md\ntarget-section: S\nprecision: append\n",
            "missing required field: content",
        ),
        (_ext_yaml(precision="upsert"), "unknown precision: upsert"),
        (_ext_yaml(target_file="/etc/passwd"), "must be a relative path"),
        (_ext_yaml(target_file="../escape.md"), "must be a relative path"),
        (
            "target-file: f.md\ntarget-section: 7\nprecision: append\ncontent: c\n",
            "field target-section must be a string",
        ),
    ],
)
def test_schema_validation_is_terminal_with_cited_reason(
    tmp_path: Path, yaml_text: str, reason_match: str
) -> None:
    plugin = _plugin(tmp_path, "p")
    yaml_path = plugin.source_path / ".agents" / "extensions" / "00-bad.yaml"
    _write(yaml_path, yaml_text)

    with pytest.raises(ExtensionError, match=reason_match) as exc_info:
        apply_extensions(_plan_with_agent_md(), [plugin])
    assert exc_info.value.yaml_path == yaml_path


def test_unknown_precision_error_lists_the_valid_verbs(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path, "p")
    _write(plugin.source_path / ".agents" / "extensions" / "00.yaml", _ext_yaml(precision="bogus"))
    with pytest.raises(
        ExtensionError,
        match="expected one of: replace, insert_before, insert_after, prepend, append",
    ):
        apply_extensions(_plan_with_agent_md(), [plugin])
