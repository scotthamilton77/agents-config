# Plugin Architecture Design

**Date:** 2026-04-17
**Status:** Approved
**Goal:** Partially isolate beads-related content into a `src/plugins/` namespace and feature-flag it in `install.sh`. This is *partial* isolation — beads skills in `src/user/.agents/skills/` are deferred to a separate agent's work and remain installed unconditionally until that work lands.

---

## Problem

Beads-related content is currently scattered across shared and tool-specific source directories:

- `src/user/.beads/` — formulas and AGENTS.md (already partially isolated)
- `src/user/.agents/skills/{create-bead,start-bead,implement-bead,run-queue}/` — beads skills in the *shared* skills dir, installed unconditionally (**not addressed in this spec**)
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
      AGENTS.md                          ← repo-only documentation; NOT installed
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

**Plugin content is subdirectory-based only.** Plugins do not install root-level tool templates (e.g., `AGENTS.md.template`) or settings files (`.json.template`, `.toml.template`). That scope is reserved for `src/user/.<tool>/` content. This keeps plugin content composable without requiring template-merge logic.

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

Mirrors the existing `--tools=` flag parser exactly:

```sh
--plugins=beads,foo    # explicit list; replaces auto-detection entirely
                       # --plugins= (empty) means no plugins
```

**Parser semantics** (same as `--tools=`):
- Explicit list replaces auto-detection entirely
- Unknown plugin names are a fatal error with a clear message
- Duplicates are silently deduplicated
- `--plugins=` with empty value means no plugins installed
- Summary output reports both enabled and skipped plugins

**Auto-detection (when `--plugins=` is absent):**
- If `bd` is on PATH **or** `~/.beads/` exists → beads auto-enabled
- Same pattern as Codex/Gemini auto-detection today

### Staging + Sync Flow

The install.sh is refactored around a **staging pattern**: content is assembled into a tmp tree before any comparison or copy to the target `~/.<tool>/` directories. This requires new staging helpers in addition to the existing sync functions.

**Per-tool install flow (replacing the current per-tool loop):**

```
for each active tool:
  1. Create staging dir: /tmp/agents-config-install-<timestamp>/<tool>/
  2. Stage base content:
     a. Render shared templates (.agents/*.md.template → staging/)
     b. Copy shared skills  (.agents/skills/ → staging/skills/)
     c. Copy shared agents  (.agents/agents/ → staging/agents/)
     d. Render tool templates (.<tool>/*.md.template → staging/)
     e. Copy tool subdirs   (.<tool>/{commands,skills,agents,rules}/ → staging/)
  3. Overlay active plugins (alphabetical plugin order):
     a. For each plugin, if .<tool>/ subdir exists in plugin:
        - Copy plugin's .<tool>/{rules,commands,skills,agents}/ into staging
        - On file collision, apply collision resolution (see below)
     b. For each plugin, if .agents/ subdir exists in plugin:
        - Copy plugin's .agents/{skills,agents}/ into staging (for this tool)
  4. Sync staging/<tool>/ → ~/.<tool>/ using existing compute_hash + sync logic
  5. Clean up staging dir
```

**For `.beads/` plugin content** (separate from tool staging):
```
for each active plugin with a .beads/ subdir:
  Stage formulas: plugin/.beads/formulas/*.toml → /tmp/.beads/formulas/
  After all plugins: sync /tmp/.beads/formulas/ → ~/.beads/formulas/
```

The existing `compute_hash()`, `sync_directory()`, `sync_settings_file()`, and `sync_templates()` functions remain reusable for the final staging→target sync step. **New helpers are required** for the staging assembly phase: a `stage_file()` function that copies a file into the staging tree and a `resolve_collision()` function that applies the collision table below.

### Collision Resolution

Plugin subdirectory files should use unique names by convention (see `src/plugins/AGENTS.md`). When collisions occur in the staging tree:

| File type | Resolution |
|-----------|-----------|
| `.md` in `rules/` only | Base first, plugins alphabetically — **append** with `\n---\n` separator |
| `.md` in `commands/`, `agents/`, `skills/` | **Fatal error** — commands and skill files must use unique names |
| `.json` (settings) | **Union-merge** — existing logic, unchanged |
| `.toml` (formulas) | Last-wins alphabetically + **warn** |
| Directories (skill dirs, agent dirs) | **Fatal error** — same-named directories across plugins is a bug |

### When a Plugin Is Disabled

When auto-detection stops matching (e.g., `bd` is removed) or a user passes `--plugins=` without listing a previously-enabled plugin, the install.sh **does not remove** previously installed plugin files. Removal is risky (user may have customized them).

Behavior:
- install.sh warns: `"Plugin 'beads' is not enabled but files may still be installed in ~/.<tool>/. Remove them manually if no longer needed."`
- Files are left in place
- A future `--prune-plugins` flag may automate removal (out of scope here)

### New Function: `install_plugin(plugin_name)`

Replaces the current `install_beads()`. Called inside the per-tool loop to overlay plugin content into the staging tree.

Responsibilities:
- For each tool subdir (`.claude/`, `.codex/`, `.gemini/`) present in the plugin, copies its subdirs (`rules/`, `commands/`, `skills/`, `agents/`) into the staging tree with collision resolution applied
- **Only for tools currently being installed** — if user runs `--tools=claude`, plugin codex/gemini content is ignored
- For `.agents/` subdir: copies shared skills/agents into staging for each active tool
- Does NOT handle root-level templates or settings files (those are base content only)

**`.beads/` content is handled separately** (not inside `install_plugin()`): a dedicated `install_plugin_beads_formulas()` step assembles formula files into a tmp `.beads/` staging dir and syncs to `~/.beads/formulas/` after all tools complete.

### Main Loop (Revised)

```sh
# For each tool: stage base + plugins, then sync to target
for tool in "${TOOLS[@]}"; do
    stage_and_install_tool "$tool"   # new function replacing install_tool()
done

# For beads: stage formulas, sync to ~/.beads/
if plugin_enabled "beads"; then
    install_plugin_beads_formulas
fi

# Summary...
```

`stage_and_install_tool()` handles phases 1–5 from the staging flow above, including overlaying all active plugins for that tool.

Summary counters extended to include active plugins, same pattern as tools today.

---

## src/plugins/AGENTS.md Contract

Documents for agents and plugin authors:

1. **Unique filenames are required** for commands, skills, agents, and templates. Name plugin files `<plugin>-<thing>.md` or place them in plugin-owned subdirs. Accidental collisions are a fatal install error.
2. **Rule file collisions are intentional-append only.** Two plugins (or a plugin + base) may both provide `rules/some-rule.md` only when the intent is to extend shared behavior. Alphabetical plugin order determines append sequence.
3. **Plugin scope is subdirectory content only.** Supported: `.<tool>/rules/`, `.<tool>/commands/`, `.<tool>/skills/`, `.<tool>/agents/`, `.agents/skills/`, `.agents/agents/`, `.beads/formulas/`. Not supported: root-level `*.md.template`, `*.json.template`, `*.toml.template`.
4. **Skills/agent directory collisions are fatal** — two plugins may not define the same skill or agent directory name.
5. **`.beads/AGENTS.md` is repository documentation only** — it is not installed to any target directory.
6. **Detection:** `install.sh` auto-detects a plugin if its sentinel condition is met (e.g., `bd` on PATH or `~/.beads/` exists for beads). Override with `--plugins=`. An explicit `--plugins=` list disables auto-detection entirely.

---

## Out of Scope

- Moving beads skills (`create-bead`, `start-bead`, `implement-bead`, `run-queue`) — handled by a separate agent's work; they remain in `src/user/.agents/skills/` until that work lands
- Any plugin beyond beads — architecture supports it, implementation deferred
- Plugin versioning or dependency resolution between plugins
- Automated removal of previously-installed plugin files (`--prune-plugins`)
