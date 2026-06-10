"""Pure data model for the installer engine.

No behaviour beyond construction, equality, and immutability where called
for. Every type here is consumed by later engine modules (`staging`,
`sync`, `merge`, `prune`, `templates`); this module imports only from
the standard library so it remains the foundation, not a consumer.

See `docs/specs/2026-05-17-w1qls.1.2-model-design.md` for the rationale
behind every design decision in this file.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypeAlias


class Tool(StrEnum):
    """Tools the installer can target. Closed set — adding a tool requires
    a new adapter, so the enum is the right shape."""

    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    OPENCODE = "opencode"


class FileKind(StrEnum):
    """Merge-dispatch discriminator. Mirrors the bash `classify_file()` at
    `scripts/install.sh:486-505`. Namespace context for `NAMESPACED_MD`
    lives on `StagedItem.namespace`, not in the enum, so merge dispatch
    keys on (kind, namespace) cleanly."""

    DIR = "dir"
    SETTINGS_JSON = "settings.json"
    JSONC = "jsonc"
    TOML = "toml"
    NAMESPACED_MD = "namespaced_md"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Tagged origin marker on every `StagedItem`. Tool and plugin
    adapters live in separate registries (Tool-enum-keyed vs string-keyed),
    but the `name` field on Provenance is a flat string — a hypothetical
    plugin named after a tool would be indistinguishable in logs and
    StagedItem comparisons without the `kind` discriminator. The
    discriminator disambiguates the flat name field, not the registries."""

    kind: Literal["tool", "plugin"]
    name: str


@dataclass(frozen=True, slots=True)
class FileInclude:
    """DYNAMIC-INCLUDE form — verbatim file substitution."""

    path: Path


@dataclass(frozen=True, slots=True)
class AllRulesInclude:
    """DYNAMIC-INCLUDE form — glob rules from the staged tree, sort
    lexicographically, join with ``\\n---\\n``. Marker dataclass; the
    behaviour lives in `core/templates.py`."""


IncludeDirective: TypeAlias = FileInclude | AllRulesInclude
"""Discriminated union of the DYNAMIC-INCLUDE directive forms.

Consumers should `match` on this union and use `typing.assert_never` in
the default arm so that adding a third variant fails type-checking at
every call site rather than silently passing through."""


@dataclass(frozen=True, slots=True)
class StagedItem:
    """In-memory record of one entry destined for a tool's install root.

    `content` is `None` when `kind == FileKind.DIR` (the bash installer
    treats top-level skill / agent directories as single staged units;
    their bytes are derived from `source_path` at sync time, not carried
    in the data model). For every other `kind`, `content` is the file's
    bytes (eager — read at staging time so the sync-phase hash-compare
    has no extra I/O).

    `executable` is a sync-phase write attribute (mode bit 0o755 vs 0o644),
    not a merge-dispatch concern — see design doc §3.6. Directories
    ignore `executable`; the sync engine preserves the source tree's
    mode bits for recursive copies.

    `shared_carrier` is the in-memory replacement for the bash
    `.carrier-from-user-shared` sentinel file (`scripts/install.sh:517-529`).
    It is set `True` only on `skills/` and `agents/` `kind==DIR` items first
    staged from the shared carrier tree (`build_plan` Phase 2). The Phase 6
    plugin overlay reads it to allow a carrier-merge (a plugin overlaying a
    disjoint file set into a shared skill/agent dir) while keeping plugin-vs-
    plugin directory collisions fatal. The overlay clears it after a merge —
    mirroring the bash `rm -f sentinel` — so a second plugin colliding on the
    same dir is a true plugin-plugin collision (fatal)."""

    source_path: Path
    dest_relpath: Path
    kind: FileKind
    namespace: str | None
    provenance: Provenance
    content: bytes | None = None
    executable: bool = False
    shared_carrier: bool = False


@dataclass(slots=True)
class StagingPlan:
    """The in-memory replacement for the bash installer's temp-dir staging.

    Built incrementally during the staging phase; consumed by sync and
    prune. `items` is a plain `dict` and therefore **silently overwrites**
    on a duplicate `dest_relpath` — it does not by itself surface
    collisions. Callers (staging.py) MUST check `dest_relpath in items`
    before assigning and route through the merge registry when the key is
    already present; this dataclass is bare storage, not a collision
    detector. A future helper may absorb the check, but A.2 deliberately
    holds the engine behaviour out of the data layer."""

    items: dict[Path, StagedItem]
    tool: Tool


@dataclass(frozen=True, slots=True)
class Orphan:
    """One destination-side entry not present in this run's staging plan.

    Replaces the four parallel arrays at `scripts/install.sh:1456-1467`
    with a single record per orphan. `tool` is `str` rather than `Tool`
    because the orphan bucket includes plugin namespaces (e.g. ``beads``)
    that are not tools."""

    tool: str
    namespace: str
    path: Path
    kind: Literal["dir", "file"]


@dataclass(slots=True)
class Counters:
    """Run-level totals reported at install completion. Mutable; the run
    increments these directly."""

    staged: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    pruned: int = 0
    backed_up: int = 0
