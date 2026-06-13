"""Phase 6.5: plugin-to-base-asset extensions (F.5).

After the Phase 6 plugin overlay, each active plugin may surgically patch
base markdown assets already staged in the tool's StagingPlan. A patch is
one YAML file in a scope-bearing extensions dir:

    src/plugins/<plugin>/.agents/extensions/*.yaml    shared scope (every tool)
    src/plugins/<plugin>/.<tool>/extensions/*.yaml    tool scope (that tool only)

Schema (all four fields required, all strings): ``target-file`` (relpath
under the tool's install root), ``target-section`` (literal ATX header text
or ``frontmatter``), ``precision`` (replace | insert_before | insert_after |
prepend | append), ``content``. Ordering is deterministic per R6 of the
originating spec (agents-config-phzj.4): plugin name alphabetical, shared
scope before tool scope within a plugin, filename alphabetical within a
scope. Later patches see earlier patches' effects — target resolution always
runs against the CURRENT plan state. Every failure is terminal
(ExtensionError); no partial application.

Unlike the bash-era spec, patches mutate plan state rather than a staging
tree on disk: a FILE item's bytes are replaced on the item; a file inside a
DIR item (skill/agent dirs, ``content=None``) patches into
``plan.dir_overrides`` — the same side channel the F.3 carrier-merge writes,
consumed by the plan-walking sync (Epic E/H).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from installer.core.md_patch import PatchError, Precision, apply_patch
from installer.core.model import FileKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.model import StagingPlan
    from installer.plugins.base import PluginAdapter

_REQUIRED_FIELDS = ("target-file", "target-section", "precision", "content")


class ExtensionError(ValueError):
    """Terminal extension failure. Structured attrs (.yaml_path,
    .target_file, .reason) so callers and tests assert on data, not the
    message string; the message carries the R7 citation."""

    def __init__(self, yaml_path: Path, reason: str, *, target_file: Path | None = None) -> None:
        cite = f"extension {yaml_path}"
        if target_file is not None:
            cite += f" (target-file {target_file})"
        super().__init__(f"{cite}: {reason}")
        self.yaml_path = yaml_path
        self.target_file = target_file
        self.reason = reason


@dataclass(frozen=True, slots=True)
class _Extension:
    """One schema-validated extension patch."""

    yaml_path: Path
    target_file: Path
    target_section: str
    precision: Precision
    content: str


def apply_extensions(plan: StagingPlan, plugins: Sequence[PluginAdapter]) -> StagingPlan:
    """Apply every active plugin's extension patches to ``plan`` (one tool),
    in R6 order, mutating and returning it. Raises ExtensionError on the
    first failure — partial application is acceptable only because the
    caller treats any raise as terminal for the whole install (the plan is
    discarded, nothing syncs)."""
    for plugin in sorted(plugins, key=lambda p: p.name):
        for yaml_path in _extension_files(plugin, plan.tool.value):
            _apply_one(plan, _load_extension(yaml_path))
    return plan


def _extension_files(plugin: PluginAdapter, tool_name: str) -> list[Path]:
    """This plugin's extension yamls for one tool, in R6 scope order:
    shared (``.agents/extensions/``) before tool (``.<tool>/extensions/``),
    filename-alphabetical within each scope."""
    files: list[Path] = []
    for scope_root in (
        plugin.source_path / ".agents" / "extensions",
        plugin.source_path / f".{tool_name}" / "extensions",
    ):
        if scope_root.is_dir():
            files.extend(sorted(scope_root.glob("*.yaml")))
    return files


def _load_extension(yaml_path: Path) -> _Extension:
    """Parse + schema-validate one extension yaml (R2, R7 schema rows)."""
    try:
        raw = yaml_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ExtensionError(yaml_path, f"extension file is not valid UTF-8: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ExtensionError(yaml_path, f"malformed YAML: {exc}") from exc
    if not isinstance(data, dict):
        shape = "list" if isinstance(data, list) else "scalar"
        raise ExtensionError(yaml_path, f"top-level YAML is a {shape}; mapping required")
    fields = {name: _required_str(data, name, yaml_path) for name in _REQUIRED_FIELDS}
    try:
        precision = Precision(fields["precision"])
    except ValueError:
        raise ExtensionError(
            yaml_path,
            f"unknown precision: {fields['precision']}; expected one of: "
            "replace, insert_before, insert_after, prepend, append",
        ) from None
    target_file = Path(fields["target-file"])
    if target_file.is_absolute() or ".." in target_file.parts:
        raise ExtensionError(
            yaml_path, "target-file must be a relative path inside the install root"
        )
    if target_file.suffix != ".md":
        raise ExtensionError(
            yaml_path,
            "target-file must be a markdown asset (.md); the patch engine only "
            "operates on staged markdown",
            target_file=target_file,
        )
    return _Extension(
        yaml_path=yaml_path,
        target_file=target_file,
        target_section=fields["target-section"],
        precision=precision,
        # YAML `|` block scalars terminate with one newline; the precision
        # verbs add their own line separation (R4), so a single terminal
        # newline is normalized away — `|` and `|-` author identically.
        content=fields["content"].removesuffix("\n"),
    )


def _required_str(data: dict[object, object], name: str, yaml_path: Path) -> str:
    if name not in data:
        raise ExtensionError(yaml_path, f"missing required field: {name}")
    value = data[name]
    if not isinstance(value, str):
        raise ExtensionError(yaml_path, f"field {name} must be a string")
    return value


def _apply_one(plan: StagingPlan, ext: _Extension) -> None:
    target = _resolve(plan, ext)
    try:
        text = target.current.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtensionError(
            ext.yaml_path, f"target-file is not valid UTF-8: {exc}", target_file=ext.target_file
        ) from exc
    try:
        patched = apply_patch(
            text, section=ext.target_section, precision=ext.precision, content=ext.content
        )
    except PatchError as exc:
        raise ExtensionError(ext.yaml_path, str(exc), target_file=ext.target_file) from exc
    target.write(plan, patched.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class _FileTarget:
    """Target staged as its own plan item carrying bytes — patched bytes
    replace the item's content."""

    dest: Path
    current: bytes

    def write(self, plan: StagingPlan, data: bytes) -> None:
        plan.items[self.dest] = dc_replace(plan.items[self.dest], content=data)


@dataclass(frozen=True, slots=True)
class _DirTarget:
    """Target is a file inside an opaque DIR item — patched bytes go to the
    dir_overrides side channel (the DIR item's content stays None)."""

    dir_dest: Path
    inner: Path
    current: bytes

    def write(self, plan: StagingPlan, data: bytes) -> None:
        plan.dir_overrides.setdefault(self.dir_dest, {})[self.inner] = data


def _resolve(plan: StagingPlan, ext: _Extension) -> _FileTarget | _DirTarget:
    """Locate ``target-file`` in the CURRENT plan state. Precedence inside a
    DIR item: an earlier patch's (or carrier-merge's) dir_overrides bytes win
    over the source tree — later patches must see earlier effects (R6).

    Namespace opt-outs (e.g. OpenCode skipping shared ``agents/``) need no
    explicit check here: a skipped namespace stages no plan item or DIR
    ancestor, so a patch targeting it falls through to the terminal
    "not found" below. The gating is enforced transitively by plan
    membership, not re-consulted from the adapter."""
    item = plan.items.get(ext.target_file)
    if item is not None and item.kind is not FileKind.DIR and item.content is not None:
        return _FileTarget(dest=ext.target_file, current=item.content)
    for ancestor in ext.target_file.parents:
        dir_item = plan.items.get(ancestor)
        if dir_item is None or dir_item.kind is not FileKind.DIR:
            continue
        inner = ext.target_file.relative_to(ancestor)
        override = plan.dir_overrides.get(ancestor, {}).get(inner)
        if override is not None:
            return _DirTarget(dir_dest=ancestor, inner=inner, current=override)
        source = dir_item.source_path / inner
        if source.is_file():
            return _DirTarget(dir_dest=ancestor, inner=inner, current=source.read_bytes())
        break  # the innermost DIR item owns this subtree; the file is absent
    raise ExtensionError(
        ext.yaml_path, "target-file not found in staging tree", target_file=ext.target_file
    )
