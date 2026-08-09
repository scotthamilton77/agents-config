# Python Installer — HLD Artifact Index

> **Source item**: `agents-config-w1qls.9` — archive-era, resolvable in the private archive repository and not through `work`
> **Subsystem**: the Python installer (`packages/installer`)
> **Companion spec**: [`installer-design.md`](installer-design.md) — the design these artifacts visualise
> **Glossary**: per-artifact short glossaries appear at the top of each file

## Glossary (subsystem-wide terms used across this artifact set)

| Term | Meaning |
|---|---|
| HLD | High-Level Design — evergreen reference material describing how a subsystem is meant to be structured and behave. This folder *is* the HLD set for the installer. |
| C4 | A model for visualising software architecture in four levels (Context, Container, Component, Code); see [c4model.com](https://c4model.com). This folder uses **L2** and **L3** only — see "Why no L1 / Deployment" below. |
| Installer | The Python package at `packages/installer/`, reached through `scripts/install.sh` — a thin `exec` stub that delegates to it. A short-lived CLI: parse argv → stage in memory → merge → admission gate (user-home path) → sync to disk → CLI-deploy (user-home path) → optional prune → exit. |
| Tool | One of the four supported AI coding assistants — **Claude Code**, **Codex CLI**, **Gemini CLI**, **OpenCode** — each with its own destination store and its own `ToolAdapter`. |
| `ToolAdapter` | The protocol abstracting everything the engine needs to know about a tool: source dir, dest dir, detection, scoped namespaces, project-scoped namespaces, namespace filtering, post-staging transforms. Per-tool adapters live in `tools/`. |
| `PluginAdapter` | The protocol for an optional plugin that overlays extra content onto the staging plan. Discovered dynamically by scanning `src/plugins/<name>/`; string-keyed (NOT enumerated). |
| `StagingPlan` | The **in-memory** staging structure: a `dict[Path, StagedItem]` plus provenance. Built per tool, mutated by plugin overlay + transforms, then flushed to disk by `sync`. Never an on-disk container in the operational path (`--dump-stage` materialises it for debugging only). |
| `StagedItem` | One planned destination entry — a file, or, when `kind == DIR`, a directory: its content, `FileKind`, namespace, and `Provenance`. The unit the merge + sync engines operate on. |
| `MergeStrategy` | A collision-resolution class (append-rules, JSON-union, fatal, last-wins-warn, last-wins-silent), each in its own module, dispatched by the registry on `(FileKind, namespace)`. |
| `FileKind` | The enum classifying a staged file (`NAMESPACED_MD`, `SETTINGS_JSON`, `JSONC`, `TOML`, `OTHER`, `DIR`) — the primary merge-dispatch key. |
| `Provenance` | `(kind: "tool" \| "plugin", name: str)` on each `StagedItem` — preserves tool-vs-plugin origin through the plan. |
| `IOPort` | The single injectable I/O abstraction (`info`/`warn`/`show_diff`/`confirm`/…). `TerminalIO` is real (via `rich`); `ScriptedIO` is the test fake. No module calls `print`/`input` directly. |
| DYNAMIC-INCLUDE | The directive form (`<!-- DYNAMIC-INCLUDE: path -->` and the ALL-RULES variant) that flattens shared template fragments into assembled per-tool instruction files at staging time. |
| Namespace | The managed sub-directory a file belongs to (`commands` / `skills` / `agents` / `rules` / `hooks` / `workflows`) — second component of the merge-dispatch key for `.md` content. Only `rules` (append) and `commands`/`skills`/`agents` (fatal) change the merge strategy; see [`data-view.md`](data-view.md) for the full dispatch table, including `hooks`' OTHER-classified exception. |

Each artifact file in this folder carries its **own short glossary** at the top, listing the terms used in that specific file.

## Purpose

This folder is the **high-level design (HLD) artifact set** for the Python installer. It exists to fix the big-picture architecture in pictures — boundary, internals, runtime flow, data model — so that anyone changing the installer works from one mental model of the system rather than re-deriving it from the design prose.

These artifacts are **evergreen reference material**: they describe how the installer is meant to be structured and behave, and are amended in place as the design evolves. They are NOT point-in-time proposals — those live in `docs/specs/` with date-prefixed filenames. The companion design here, `installer-design.md`, is itself the design-of-record — undated, because it is the living installer design, not a snapshot.

## Scope and non-scope

**In scope** for this artifact set:

- The installer's place among its persistent stores: the read-only source tree, `installer.toml`, the N per-tool destination stores, and the AI tools that consume those stores at their own runtime.
- The installer's internal components: the tool-agnostic `core/` engine, the per-tool `tools/` adapters, the per-plugin `plugins/` adapters, and the `cli`/`config`/`orchestrator` top layer.
- The installer's runtime behaviour: one install invocation's traversal through detect → stage → overlay → merge → admission gate (user-home path) → sync → CLI-deploy (user-home path) → (optional) prune, plus the collision-merge, per-item sync-decision, and prune sub-flows.
- The installer's data model: `StagingPlan` / `StagedItem` / `Provenance` / `FileKind` / `IncludeDirective` / `Orphan` / `Counters` / `Config`, the `(FileKind, namespace)` merge-dispatch table, the `installer.toml` shape, and the data-ownership boundaries.

**Out of scope** for this artifact set:

- **Code-level (C4 L4) diagrams** — C4 itself recommends against drawing this level; the package layout in `installer-design.md` is sufficient at code granularity.
- **The agent-config *content* itself** — what the skills/agents/rules/commands *say* is the subject of the rest of the repo, not of the installer's architecture.
- **The test architecture** — specified in `installer-design.md` §"Test architecture"; not re-drawn here.

### Why no L1 (Context) or Deployment artifact

Both are **deliberately skipped**, not forgotten:

- **C4 L1 (System Context)** would show one box (the installer) talking to a developer and a filesystem. The ecosystem is obvious and singular; an L1 page would carry no information the L2 container view doesn't already make plain. L2 is the natural entry point here.
- **C4 Deployment** would show the installer running on the developer's own workstation, reading and writing the same local filesystem. There is no multi-host topology, no service, no scheduler — the deployment is "run a script in your repo." Nothing to diagram.

Either level earns its place in a subsystem with a genuinely non-trivial ecosystem (external services, schedulers, agent subprocesses) or a real topology. The installer has neither.

## Reading order

Newcomers should read in this order; deep contributors may navigate freely.

1. **[C4 L2 — Container](c4-l2-container.md)** — what runs, what it reads, what it writes, who consumes the output.
2. **[Sequences](sequences.md)** — how one install invocation runs: the end-to-end flow plus collision-merge, sync-decision, and prune sub-flows.
3. **[C4 L3 — Engine](c4-l3-engine.md)** — the components inside the installer process: `core/` engine, `tools/` + `plugins/` adapters, and the protocol seams.
4. **[Data View](data-view.md)** — the in-memory data model, the merge-dispatch table, the `installer.toml` schema, and the data-ownership boundaries.

## Artifact synopsis

| File | Synopsis |
|---|---|
| [`c4-l2-container.md`](c4-l2-container.md) | **C4 Level 2** — the `installer` process, its read-only source tree + `installer.toml` inputs, its N destination stores + backup-dir outputs, and the four AI assistants that consume the deployed stores at their own runtime. The in-memory `StagingPlan` is explicitly NOT a container (it lives at L3 / data-view). |
| [`c4-l3-engine.md`](c4-l3-engine.md) | **C4 Level 3** — components inside the installer process, grouped by sub-package: the tool-agnostic `core/` engine (`model`, `io_port`, `templates`, `staging`, `installignore`, `overlay`, `sync`, `consent`, `prune`, `merge/*`), the `tools/` adapters, the `plugins/` adapters, and the `cli`/`config`/`orchestrator` top layer — with the four protocol seams (`ToolAdapter`, `PluginAdapter`, `MergeStrategy`, `IOPort`) as the test-substitution points. `cli.py` is the real top-level driver (staging then sync as two separate whole-fleet passes); `orchestrator.py` covers staging only. |
| [`sequences.md`](sequences.md) | **Four sequence diagrams**: (1) end-to-end install — detect → stage → overlay → merge → admission gate (user-home path) → sync → CLI-deploy (user-home path); (2) collision-merge dispatch — `(FileKind, namespace)` → strategy; (3) sync per-item decision — hash-skip vs diff → confirm → backup → write; (4) prune flow — orphan scan → interactive prune → backup + remove. |
| [`data-view.md`](data-view.md) | **Data model**: ER for `Config` / `StagingPlan` / `StagedItem` / `Provenance` / `FileKind` / `IncludeDirective` / `Orphan` / `Counters`; the `(FileKind, namespace)` → `MergeStrategy` dispatch table; the `installer.toml` schema; and the source-vs-plan-vs-destination ownership boundaries. |

## Conventions

- **Diagram notation**: Mermaid throughout, for native GitHub rendering. No SVG artifacts — `.md` files are the deliverable.
  - C4 set uses `C4Container` / `C4Component` syntax.
  - Sequences use `sequenceDiagram`.
  - Data view uses `erDiagram` for entities, `flowchart` + markdown tables for ownership boundaries, fenced TOML/JSON for flat config/contract shapes.
- **C4 L4 (code) is intentionally absent.** The package layout in `installer-design.md` documents code granularity; C4 itself advises against an L4 diagram for self-documenting code.
- **L1 + Deployment are intentionally absent** — see "Why no L1 / Deployment" above.
- **File-path citations are permitted here.** Unlike installed assets (which flatten into user-space config where paths are dead-ends), these `docs/architecture/` artifacts are project-internal and never installed, so they cite `installer-design.md`, `src/…`, and `scripts/…` directly.

## Source-spec coupling

Diagrams in this folder are **derived artifacts**. The source of truth is [`installer-design.md`](installer-design.md). Diagrams cite the spec section they visualise (each file does so in its header / cross-references) and are amended in place when the spec changes. If the implementation diverges from these diagrams without a paired amendment, that is a drift signal — update both as one commit.
