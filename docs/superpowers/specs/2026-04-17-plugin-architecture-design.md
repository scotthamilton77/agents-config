# Plugin Architecture Design

**Date:** 2026-04-17
**Status:** Approved
**Goal:** Isolate optional tool integrations (starting with beads) into a `src/plugins/` namespace, feature-flagged in `install.sh`, so users without those tools are not polluted with irrelevant instructions.

---

## Problem

Beads-related content is currently scattered across shared and tool-specific source directories:

- `src/user/.beads/` — formulas and AGENTS.md (already partially isolated)
- `src/user/.agents/skills/{create-bead,start-bead,implement-bead,run-queue}/` — beads skills in the *shared* skills dir, installed unconditionally
- `src/user/.claude/rules/beads.md` — Claude-specific, but not gated
- `src/user/.claude/commands/implement-bead.md` — Claude-specific, but not gated
- `src/user/.agents/INSTRUCTIONS.md.template` line 37 — "or bead" reference in shared content

`install_beads()` in `install.sh` is called unconditionally regardless of whether the user has beads installed.

---

## Solution: Generic Plugin Architecture

### Directory Layout

```
src/plugins/
  AGENTS.md                              ← plugin system docs + conventions
  beads/
    .beads/                              ← moved from src/user/.beads/
      AGENTS.md
      formulas/
        brainstorm-bead.formula.toml
        implement-feature.formula.toml
        fix-bug.formula.toml
        merge-and-cleanup.formula.toml
    .claude/
      rules/
        beads.md                         ← moved from src/user/.claude/rules/
      commands/
        implement-bead.md                ← moved from src/user/.claude/commands/
    .agents/
      skills/                            ← FUTURE: beads skills land here (separate agent's work)
```

### What Moves

| From | To |
|------|----|
| `src/user/.beads/` | `src/plugins/beads/.beads/` |
| `src/user/.claude/rules/beads.md` | `src/plugins/beads/.claude/rules/beads.md` |
| `src/user/.claude/commands/implement-bead.md` | `src/plugins/beads/.claude/commands/implement-bead.md` |

### What Stays (Untouched)

- `src/user/.agents/skills/{create-bead,start-bead,implement-bead,run-queue}/` — WIP from a separate agent; will migrate to `src/plugins/beads/.agents/skills/` in that agent's work. No changes here.

### What Changes in Shared Content

- `INSTRUCTIONS.md.template` line 37: remove "or bead" — stripped to "Write specs in the plan file for small-context specs." The beads rule file absorbs any beads-specific orchestration guidance.

---

## install.sh Changes

### New Flag: `--plugins=`

Mirrors the existing `--tools=` flag:

```sh
--plugins=beads,foo    # explicit list
                       # default: auto-detect
```

**Auto-detection:** if `bd` is on PATH **or** `~/.beads/` exists → beads auto-enabled. Same pattern as Codex/Gemini auto-detection today.

### Tmp-Assembly Pattern

Before any comparison or install, all content (base + plugins) is assembled into a staging directory:

```
/tmp/agents-config-install-<timestamp>/<tool>/
```

Assembly order:
1. Base content (`src/user/.agents/`, `src/user/.<tool>/`) written first
2. Plugin content layered on top, plugins processed alphabetically

This means the existing `compute_hash` + diff logic runs unchanged — it compares the assembled tmp tree against `~/.<tool>/`. No special-case logic for composite files. Dry-run diffs are accurate by default.

The tmp directory is cleaned up at the end of the run.

### Collision Resolution

Plugin filenames should be unique by convention (documented in `src/plugins/AGENTS.md`). When collisions occur:

| File type | Resolution |
|-----------|-----------|
| `.md` (rules, commands, templates) | Base first, plugins alphabetically — **append** with `\n---\n` separator |
| `.json` (settings) | **Union-merge** — existing logic, unchanged |
| `.toml` (formulas) | Last-wins alphabetically + **warn** |
| Directories / scripts | **Fatal error** — same-named skill or agent directories across plugins is a bug |

### New Function: `install_plugin(plugin_name)`

Replaces the current `install_beads()`. Processes `src/plugins/<plugin-name>/`:

- For each tool subdir (`.claude/`, `.codex/`, `.gemini/`) present in the plugin, syncs its subdirs (`rules/`, `commands/`, `skills/`, `agents/`) into the assembled tmp tree — but **only for tools currently being installed**
- For `.beads/` subdir: assembles formulas into the tmp `.beads/` staging area → installs to `~/.beads/formulas/`
- For `.agents/` subdir: assembles shared skills/agents into tmp tree for each active tool
- Uses existing `sync_directory()` and `sync_settings_file()` — no new sync primitives

### Main Loop

```sh
# After per-tool phases:
for plugin in "${PLUGINS[@]}"; do
    install_plugin "$plugin"
done
```

Summary counters extended to include active plugins, same pattern as tools today.

---

## src/plugins/AGENTS.md Contract

Documents for agents and plugin authors:

1. **Unique filenames are required.** Name plugin files `<plugin>-<thing>.md` or place them in plugin-owned subdirs. Accidental collisions are a bug.
2. **Intentional collisions (markdown append)** are supported for extending shared rule files. Alphabetical plugin order determines append sequence.
3. **Supported subdirs per plugin:** `.beads/`, `.claude/`, `.codex/`, `.gemini/`, `.agents/`
4. **Skills/agent directory collisions are fatal** — two plugins may not define the same skill or agent directory name.
5. **Detection:** `install.sh` auto-detects a plugin if its sentinel condition is met (e.g., `bd` on PATH for beads). Override with `--plugins=`.

---

## Out of Scope

- Moving beads skills (`create-bead`, etc.) — handled by separate agent's work
- Any plugin beyond beads — architecture supports it, implementation deferred
- Plugin versioning or dependency resolution between plugins
