# Python Installer — Data View

> **Up**: [index](index.md)
> **Previous (reading order)**: [C4 L3 — Engine](c4-l3-engine.md)
> **Source bead**: `agents-config-w1qls.9`
> **Source spec**: [`installer-design.md`](installer-design.md) — §"Data model highlights", §"Configuration — installer.toml"

## Glossary

| Term | Meaning |
|---|---|
| `StagingPlan` | The aggregate root of the in-memory model: a `dict[Path, StagedItem]` (plus the target `Tool`). One is built per detected tool. **In-memory only** — it has no on-disk form in the operational path. |
| `StagedItem` | One planned destination file. The unit the merge + sync engines operate on. |
| `Provenance` | `(kind: "tool" | "plugin", name: str)` — preserves whether a `StagedItem` came from a tool's source tree or a plugin overlay, through the tool-vs-plugin registry asymmetry. |
| `FileKind` | The enum classifying a staged file. The **primary** merge-dispatch key. |
| Namespace | The managed sub-dir (`commands` / `skills` / `agents` / `rules` / `formulas`) or `""`. The **secondary** merge-dispatch key. |
| `IncludeDirective` | A discriminated union (`FileInclude` | `AllRulesInclude`) produced **transiently** while flattening DYNAMIC-INCLUDE markers; consumed during staging, not persisted on the `StagedItem`. |
| `Orphan` | A prune candidate: on disk, absent from the plan, matching a retired glob. |
| `Counters` | The per-run tally (`staged` / `created` / `updated` / `skipped` / `pruned` / `backed_up`) surfaced in the exit summary. |
| Canonical ownership | Which actor is the source of truth for a piece of data: the human (source tree), the installer (plan + writes), or the tool (deployed store at runtime). |

## Purpose

Three complementary data views in one file:

1. **The in-memory model** (`Config`, `StagingPlan`, `StagedItem`, `Provenance`, `IncludeDirective`, `Orphan`, `Counters`) as an ER diagram — the shapes the engine builds and passes around. None of these persist; they live and die within one process invocation.
2. **The merge-dispatch table** — the `(FileKind, namespace)` → `MergeStrategy` lookup that the collision matrix is built on.
3. **The config + ownership boundaries** — the `installer.toml` schema, and which actor owns which data as it flows source → memory → disk → runtime.

The data view answers: *what shapes does the installer build in memory, what drives collision resolution, and who owns each piece of data along the way?*

## In-memory model ER diagram

Field names below mirror the **implemented** dataclasses in `packages/installer/src/installer/core/model.py` verbatim (snake_case). Where a type is not yet built, the row is marked *design-forward* and traces to `installer-design.md`, not to current code.

```mermaid
erDiagram
    Config      ||--o{ StagingPlan      : "one built per detected Tool"
    StagingPlan ||--o{ StagedItem       : "items: dict keyed by dest_relpath"
    StagedItem  ||--|| Provenance        : "has 1 (origin)"
    StagedItem  ||--o{ FileInclude       : "content flattened from 0..N (transient)"
    StagedItem  ||--o| AllRulesInclude   : "content flattened from ALL-RULES marker (transient; no fields)"
    Config      ||--|| Counters          : "one run tally"
    Config      ||--o{ Orphan            : "prune scan yields 0..N"

    Config {
        Path      home           "destination root (per-tool dest via adapter) — implemented (B.1)"
        ToolTuple tools          "resolved tool set (claude auto-detected; forced via --tools) — implemented (B.1)"
        StrList   plugins        "design-forward: discovered by scanning src/plugins/"
        bool      dry_run        "design-forward: --dry-run preview, no writes"
        PruneMode prune          "design-forward: none | prune | prune_only"
        Path      dump_stage     "design-forward: --dump-stage target (debug)"
        StrList   retired_globs  "design-forward: installer.toml [prune].retired"
        Map       tool_overrides "design-forward: installer.toml [tools]"
    }

    StagingPlan {
        Map  items  "dict[Path, StagedItem] — IN-MEMORY; silently overwrites on dup dest_relpath (caller routes to merge)"
        Tool tool   "which tool this plan targets"
    }

    StagedItem {
        Path     source_path   "source file the bytes derive from"
        Path     dest_relpath  "destination path, relative to the tool's install root (dict key)"
        FileKind kind          "DIR | SETTINGS_JSON | JSONC | TOML | NAMESPACED_MD | OTHER"
        string   namespace     "managed namespace or null — 2nd merge-dispatch key"
        bytes    content       "post-flatten bytes; null when kind == DIR (derived at sync)"
        bool     executable    "sync-phase mode bit 0o755 vs 0o644 (e.g. beads scripts)"
    }

    Provenance {
        string kind  "Literal[tool | plugin] — disambiguates the flat name field"
        string name  "Tool enum value (tool) or plugin name string (plugin)"
    }

    FileInclude {
        Path path  "DYNAMIC-INCLUDE file form — verbatim file substitution"
    }

    Orphan {
        string tool       "destination bucket — str, NOT Tool (includes plugin namespaces like beads)"
        string namespace  "managed namespace or ''"
        Path   path       "destination path on disk"
        string kind       "Literal[dir | file] — NOT FileKind"
    }

    Counters {
        int staged     "items staged into the plan"
        int created    "new files written"
        int updated    "existing files overwritten"
        int skipped    "hash-equal (unchanged)"
        int pruned     "orphans removed"
        int backed_up  "files copied to backup before overwrite/prune"
    }
```

### Cardinality + shape notes

- **`StagingPlan` is the aggregate root of the install path; `Config` is the run root.** One `Config` per invocation drives one `StagingPlan` per detected tool, one `Counters` tally, and (with `--prune`) a list of `Orphan`s. There are no cross-plan relationships — each tool's plan is independent.
- **`Config` is built incrementally.** Only `home` + `tools` exist today (tool-selection scope); `plugins`, `dry_run`, `prune`, `dump_stage`, `retired_globs`, and `tool_overrides` are *design-forward* — they land in later stories (the `installer.toml` loader, prune, `--dump-stage`). The ER shows the target shape and tags each row accordingly.
- **`items` is a `dict[Path, StagedItem]`, not a list.** The `dest_relpath` is the key, which is exactly why collisions are detectable: a second item mapping to a key already present triggers the merge dispatch (Sequence 2). The dict is **in-memory** — the single most load-bearing fact in this model. `install.sh` materialised this as a temp directory tree; the Python rewrite keeps it in process memory and only `sync` writes individual files. (The bare dict silently overwrites on a duplicate key; the staging caller checks `dest_relpath in items` and routes to the merge registry — collision detection is the caller's job, not the dataclass's.)
- **`Provenance` carries the tool-vs-plugin asymmetry.** Tools are enum-keyed (`Tool` enum + adapter registry); plugins are string-keyed (dynamic discovery, no enum). `Provenance(kind, name)` lets a single `StagedItem` record either origin uniformly — the `kind` discriminator disambiguates the flat `name` (a plugin named after a tool would otherwise be ambiguous), so the merge engine can reason about "base asset vs plugin overlay" without caring which registry the item came from.
- **`IncludeDirective` is a transient `TypeAlias` union.** `FileInclude | AllRulesInclude`, produced while `templates.py` flattens a `<!-- DYNAMIC-INCLUDE: … -->` marker (file form) or the ALL-RULES marker, then consumed immediately — the flattened text lands in `StagedItem.content`; the directive objects do not survive on the `StagedItem`. `FileInclude` carries the fragment `path`; `AllRulesInclude` carries no fields — it expands the plan's already-staged rules collection, sorted and joined with a `---` separator.
- **`FileKind` is an enum, not an entity.** Its six values are shown inline on `StagedItem.kind`. It is the primary merge-dispatch key; `namespace` is the secondary key (see the dispatch table). Note `Orphan.kind` is a *different*, coarser `Literal["dir", "file"]` — orphan classification only needs dir-vs-file, not the full merge taxonomy — and `Orphan.tool` is a plain `str` (not the `Tool` enum) because the orphan bucket includes plugin namespaces like `beads` that are not tools.

## Merge-dispatch table — `(FileKind, namespace)` → `MergeStrategy`

The collision matrix — the dispatch contract `core/merge/registry.py` will implement (Epic E; **not yet built**, so this table is the design intent from `installer-design.md`, not a description of current code). It keys on `(FileKind, namespace)`: `NAMESPACED_MD` is the only kind whose namespace changes the strategy; for every other kind the namespace component is unused and the lookup degenerates to a `FileKind`-only key. The strategy names below are the design's; the modules land in Epic E.

| FileKind | Namespace | Strategy | Behaviour on collision |
|---|---|---|---|
| `NAMESPACED_MD` | `rules` | `append_rules` | Join `existing + "\n---\n" + incoming` — rules compose. |
| `NAMESPACED_MD` | `commands` / `skills` / `agents` | `fatal` | **Raise** — two items with the same name is an authoring error; the message names both files. |
| `SETTINGS_JSON` | — | `json_union` | Deep union: nested-dict precedence, array union + sort, type-mismatch surfaced. |
| `JSONC` | — | `last_wins_warn` | Replace, with a warning that an existing file was overwritten. |
| `TOML` | — | `last_wins_warn` | Replace, with a warning. |
| `OTHER` | — | `last_wins_silent` | Replace silently. |
| `DIR` | — | (n/a) | Directories are created, not merged. |

> Formula files are `.toml`, so they classify as `FileKind.TOML` and route via `(TOML, —) → last_wins_warn`. `formulas` is a managed namespace for **backup / prune** routing (it is in the path-aware namespace set), NOT a `NAMESPACED_MD` merge namespace — the only `NAMESPACED_MD` namespaces that change the strategy are `rules` (append) and `commands`/`skills`/`agents` (fatal). The dispatch is data: adding a `(FileKind, namespace)` row is a registry change, not an engine change.

## `installer.toml` schema

Structured config at `packages/installer/installer.toml`, replacing the legacy `scripts/prune-list` text file at the parity gate. Read once at `Config` build (read-only to the install path).

```toml
[prune]
# Retired paths (one glob per line) — matched against destination files during
# the prune scan. A destination file is an orphan only if it ALSO matches here.
retired = [
  "*/skills/condition-based-waiting",
  "claude/rules/git-commits.md",
]

[tools]
# Optional per-tool overrides — leave commented to use the built-in adapters.
# claude.dest = "~/.claude"
```

| Key | Type | Drives | Notes |
|---|---|---|---|
| `[prune].retired` | list[str] (globs) | `Config.retired_globs` → `prune.py` *(design-forward)* | The orphan gate. A dest file absent from the plan is pruned **only** if it also matches one of these globs. |
| `[tools].<tool>.dest` | str (path) | `Config.tool_overrides` → tool adapter *(design-forward)* | Override a tool's destination dir; commented out = built-in adapter default. |

## Canonical-ownership boundaries

Data flows source → memory → disk → runtime, and ownership hands off at each arrow. The installer never writes the source; the tools never read the plan; backups are write-only recovery.

```mermaid
flowchart LR
    subgraph HUMAN["Human-canonical (read-only to installer)"]
        S1[src/user/ + src/plugins/ source tree]
        S2[installer.toml config]
    end

    subgraph MEM["Installer-owned (in-memory, ephemeral)"]
        M1[StagingPlan = dict Path to StagedItem]
        M2[Counters + Orphan list]
    end

    subgraph DISK["Installer-written, then tool-owned"]
        D1[~/.claude ~/.codex ~/.gemini ~/.config/opencode ~/.beads]
    end

    subgraph BAK["Installer-written (recovery only)"]
        B1[namespace-backup/ dirs + in-place backups]
    end

    subgraph TOOLS["Tool-owned at runtime"]
        T1[AI assistants + bd CLI]
    end

    S1 -->|"staging reads"| M1
    S2 -->|"config reads"| M1
    M1 -->|"sync writes (hash-gated)"| D1
    D1 -->|"backup before overwrite/prune"| B1
    D1 -->|"runtime read (async)"| T1
```

### Ownership rules (worth memorising)

| Data | Owner | Lifetime | Notes |
|---|---|---|---|
| Source tree (`src/user/`, `src/plugins/`) | **Human** (via repo) | Permanent | Installer reads, NEVER writes. The "always edit source" guarantee. |
| `installer.toml` | **Human** | Permanent | Read-only to the install path. |
| `StagingPlan` / `StagedItem` | **Installer** | One invocation | In-memory; gone when the process exits. `--dump-stage` materialises a throwaway copy. |
| `Counters` / `Orphan` list | **Installer** | One invocation | Surfaced in the exit summary; not persisted. |
| Destination stores | **Installer** writes → **Tool** reads | Permanent on disk | Single writer at install time; consumed asynchronously at each tool's runtime. |
| Backups | **Installer** | Permanent on disk | Write-only recovery; never read back by the installer. |

### Explicit non-ownership

- The installer does **not** own source content — it copies and flattens it, but the human authoring the repo is canonical. A `StagedItem.Content` is a *derived* artifact (post-flatten, post-transform), not a source of truth.
- The installer does **not** own a tool's runtime interpretation of its store. It deposits files matching each tool's path + shape contract; how the tool loads them is the tool's concern.
- The installer does **not** persist any of its own state between runs. There is no installer database, no manifest, no lockfile of "what I installed last time" — the destination store *is* the record, and hash-compare is how the next run reconciles.

## What this diagram does NOT show

- **The components that build / read these shapes** — see [`c4-l3-engine.md`](c4-l3-engine.md).
- **The order** in which the shapes are built and flushed — see [`sequences.md`](sequences.md).
- **The per-strategy merge mechanics** (deep-union algorithm, append separator placement) — specified per-strategy in the E.* stories and `installer-design.md` §"Test architecture".
- **The golden-master / fixture data shapes** — test artifacts; see `installer-design.md` §"Fixture strategy".

## Cross-references

- **Previous (reading order)**: [C4 L3 — Engine](c4-l3-engine.md) — the components that read / build / write this data
- **Companion structural views**: [`c4-l2-container.md`](c4-l2-container.md), [`c4-l3-engine.md`](c4-l3-engine.md)
- **Companion flow view**: [`sequences.md`](sequences.md)
- **Source spec**: [`installer-design.md`](installer-design.md) §"Data model highlights", §"Configuration — installer.toml", §"--dump-stage flag"
