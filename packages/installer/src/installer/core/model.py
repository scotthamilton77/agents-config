"""Pure data model for the installer engine.

No behaviour beyond construction, equality, immutability where called for,
and the one derivation that states what an empty `contributions` tuple means
— which belongs with the field it interprets, not in whichever consumer
happened to need it first. Every type here is consumed by later engine modules (`staging`,
`sync`, `merge`, `prune`, `templates`); this module imports only from
the standard library so it remains the foundation, not a consumer.

See `docs/specs/2026-05-17-w1qls.1.2-model-design.md` for the rationale
behind every design decision in this file.
"""

from dataclasses import dataclass, field
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
    """Merge-dispatch discriminator. Namespace context for `NAMESPACED_MD`
    lives on `StagedItem.namespace`, not in the enum, so merge dispatch
    keys on (kind, namespace) cleanly."""

    DIR = "dir"
    SETTINGS_JSON = "settings.json"
    JSONC = "jsonc"
    TOML = "toml"
    NAMESPACED_MD = "namespaced_md"
    OTHER = "other"


class Outcome(StrEnum):
    """What actually happened to one install item — finer than ``Counters``.

    ``Counters.skipped`` conflates a hash-equal skip with a consent-declined
    overwrite; the receipt must tell them apart (a declined file holds the user's
    bytes and must never be recorded)."""

    WRITTEN = "written"  # created, updated, or merged
    SKIPPED_IDENTICAL = "skipped_identical"
    DECLINED = "declined"  # consent declined / unmergeable -> user's bytes kept


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


@dataclass(frozen=True, slots=True)
class NamedRulesInclude:
    """DYNAMIC-INCLUDE form — inline a comma-separated *subset* of rules, by
    name, **in the order listed**, joined with ``\\n---\\n``. Unlike
    `AllRulesInclude` (staged tree, lexicographic) the named subset resolves
    from the fixed ``src/user/.claude/rules/`` source dir and preserves the
    author's ordering. ``names`` holds the verbatim sed capture (the raw
    comma-list text); splitting, trimming, and empty-entry skipping happen at
    flatten time in `core/templates.py` (split on comma, trim each name, skip
    empties)."""

    names: str


IncludeDirective: TypeAlias = FileInclude | AllRulesInclude | NamedRulesInclude
"""Discriminated union of the DYNAMIC-INCLUDE directive forms.

Consumers should `match` on this union and use `typing.assert_never` in
the default arm so that adding a fourth variant fails type-checking at
every call site rather than silently passing through."""


@dataclass(frozen=True, slots=True)
class Contribution:
    """One source file's bytes inside a staged item's content.

    A destination is not always one file. Two rules of the same name append-merge
    into a single item, and the deploy gate has to judge each of them on its own
    record: a destination judged as one artifact either ships a contributor's
    governance metadata it never read, or drops an admitted contributor because
    something it merged with carried none. Carrying `(source_path, content)` per
    side is what makes both questions answerable at the gate — the alternative is
    reconstructing, downstream, an origin the merge already destroyed.

    Also the value type of `StagingPlan.dir_overrides`, where the same problem
    appears one level down: bytes destined for a file inside an opaque directory
    item, arriving from a source the directory's own `source_path` does not name.
    """

    source_path: Path
    content: bytes


@dataclass(frozen=True, slots=True)
class StagedItem:
    """In-memory record of one entry destined for a tool's install root.

    `content` is `None` when `kind == FileKind.DIR` — top-level skill /
    agent directories are staged as single units; their bytes are derived
    from `source_path` at sync time, not carried in the data model. For
    every other `kind`, `content` is the file's bytes (eager — read at
    staging time so the sync-phase hash-compare has no extra I/O).

    `executable` is a sync-phase write attribute (mode bit 0o755 vs 0o644),
    not a merge-dispatch concern — see design doc §3.6. Directories
    ignore `executable`; the sync engine preserves the source tree's
    mode bits for recursive copies.

    `shared_carrier` is the in-memory carrier flag (replaces the on-disk
    `.carrier-from-user-shared` sentinel). It is set `True` only on `skills/`
    and `agents/` `kind==DIR` items first
    staged from the shared carrier tree (`build_plan` Phase 2). The Phase 6
    plugin overlay reads it to allow a carrier-merge (a plugin overlaying a
    disjoint file set into a shared skill/agent dir) while keeping plugin-vs-
    plugin directory collisions fatal. The overlay clears it after a merge so
    a second plugin colliding on the same dir is a true plugin-plugin collision
    (fatal).

    `contributions` names the source of every byte in `content`, in the order
    those bytes appear, and is set by any producer that makes `content` stop
    being one file's bytes: the rule append-merge, and a plugin extension patch.
    Empty — the common case — means the item is its own sole contributor, so
    `contributions_of` reads it as `(source_path, content)` rather than making
    every construction site restate what the two fields already say.

    The invariant is that the contributions rejoin to `content`. It is not
    checked anywhere, and it is load-bearing: the admission gate reassembles a
    gated file item out of its contributions, so an item whose `content` was
    rewritten without restating them deploys the pre-rewrite bytes — the later
    edit is silently undone rather than rejected. Any producer that rewrites
    `content` therefore owns `contributions` too.
    """

    source_path: Path
    dest_relpath: Path
    kind: FileKind
    namespace: str | None
    provenance: Provenance
    content: bytes | None = None
    executable: bool = False
    shared_carrier: bool = False
    contributions: tuple[Contribution, ...] = ()


def contributions_of(item: StagedItem) -> tuple[Contribution, ...]:
    """Every source whose bytes are in `item.content`, in the order they appear.

    An item with no recorded contributions is its own: the pair `(source_path,
    content)` says the same thing, and defaulting to it keeps every producer that
    never merges anything from having to restate it. A directory item carries no
    bytes of its own, so it contributes none — its interior is attributed through
    `StagingPlan.dir_overrides` and its own source tree instead.
    """
    if item.contributions:
        return item.contributions
    if item.content is None:
        return ()
    return (Contribution(source_path=item.source_path, content=item.content),)


@dataclass(slots=True)
class StagingPlan:
    """The in-memory staging plan.

    Built incrementally during the staging phase; consumed by sync and
    prune. `items` is a plain `dict` and therefore **silently overwrites**
    on a duplicate `dest_relpath` — it does not by itself surface
    collisions. Callers (staging.py) MUST check `dest_relpath in items`
    before assigning and route through the merge registry when the key is
    already present; this dataclass is bare storage, not a collision
    detector. A future helper may absorb the check, but A.2 deliberately
    holds the engine behaviour out of the data layer.

    `dir_overrides` is the side channel for bytes that cannot be expressed
    through a single-`source_path` DIR `StagedItem`. It is keyed by the DIR
    item's `dest_relpath`, then by each inner file's relpath (relative to the
    dir), to that file's `Contribution` — the bytes and the file they came from,
    since the DIR item's own `source_path` names a tree that does not contain
    them. Two producers write here, both targeting an existing DIR item rather
    than replacing it:

    - the Phase 6 plugin carrier-merge (overlay) records the plugin's disjoint
      added files, since a DIR item has only one `source_path` and two source
      dirs land at one destination;
    - `apply_extensions` (F.5) records YAML-patched file bytes for a skill/agent
      dir whose opaque DIR item it cannot mutate (`content` stays `None`).

    The plan-walking DIR-sync (`sync.sync_plan`) emits each carrier DIR's own
    `source_path` tree first, then overlays `dir_overrides[dest]` on top —
    an override wins on a name collision.
    Empty by default — the common case stages no override bytes."""

    items: dict[Path, StagedItem]
    tool: Tool
    dir_overrides: dict[Path, dict[Path, Contribution]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Orphan:
    """One destination-side entry not present in this run's staging plan.

    One record per orphan. `tool` is `str` rather than `Tool`
    because the orphan bucket includes plugin namespaces (e.g. a kit's own
    routed-file root) that are not tools."""

    tool: str
    namespace: str
    path: Path
    kind: Literal["dir", "file"]


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    """One item's install result. ``dest`` is absolute; ``sha256`` is the hex
    digest for a file (WRITTEN/SKIPPED_IDENTICAL), ``None`` for a directory or a
    DECLINED item."""

    dest: Path
    outcome: Outcome
    sha256: str | None


@dataclass(slots=True)
class Counters:
    """Run-level totals reported at install completion. Mutable; the run
    increments these directly."""

    staged: int = 0
    created: int = 0
    updated: int = 0
    merged: int = 0
    skipped: int = 0
    pruned: int = 0
    backed_up: int = 0
