# Plugin Architecture Design

**Date:** 2026-04-17
**Status:** Approved — amended 2026-04-17 (fresh-eyes pass)
**Goal:** Partially isolate beads-related content into a `src/plugins/` namespace and feature-flag it in `install.sh`. This is *partial* isolation — beads skills in `src/user/.agents/skills/` are deferred to a separate agent's work and remain installed unconditionally until that work lands.

---

## Problem

Beads-related content is currently scattered across shared and tool-specific source directories:

- `src/user/.beads/` — formulas and AGENTS.md (already partially isolated)
- `src/user/.agents/skills/beads/{create-bead,start-bead,implement-bead,run-queue}/` — beads skills grouped under a `beads/` subdirectory within the shared skills dir, installed unconditionally (**not addressed in this spec**). Note: these were relocated from flat `src/user/.agents/skills/{name}/` paths to `src/user/.agents/skills/beads/{name}/` by a prior agent; the spec treats this as WIP, not yet committed.
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

**Plugin content is subdirectory-based only.** Plugins install content into tool subdirs (e.g., `rules/`, `commands/`, `skills/`, `agents/`) and the `.beads/formulas/` target. Plugins **may** provide `settings.json.template` in a tool subdir to inject MCP servers, hooks, permissions, or other settings — these are union-merged into the assembled settings during staging. Plugins do **not** install:
- Root-level tool identity templates (`AGENTS.md.template`, `CLAUDE.md.template`, etc.)
- Any non-settings `.template` file (template rendering for identity files is base-content only)

Settings injection is explicit and composable: plugin settings are union-merged on top of base settings, plugins alphabetically.

### What Moves

| From | To |
|------|----|
| `src/user/.beads/` (entire directory, including `AGENTS.md` and `formulas/`) | `src/plugins/beads/.beads/` |
| `src/user/.claude/rules/beads.md` | `src/plugins/beads/.claude/rules/beads.md` |
| `src/user/.claude/commands/implement-bead.md` | `src/plugins/beads/.claude/commands/implement-bead.md` |

### What Stays (Untouched)

- `src/user/.agents/skills/beads/{create-bead,start-bead,implement-bead,run-queue}/` — WIP from a separate agent (currently untracked, grouped under a `beads/` subdir); will migrate to `src/plugins/beads/.agents/skills/` in that agent's work. No changes here.

### What Changes in Shared Content

- `INSTRUCTIONS.md.template` line 37: remove "or bead" — stripped to "Write specs in the plan file for small-context specs." The instruction is **relocated** (not deleted) — `src/plugins/beads/.claude/rules/beads.md` should include explicit guidance that specs for beads work can be written into the bead itself.

---

## install.sh Changes

### New Path Variable

Add alongside the existing path declarations near the top of install.sh:

```sh
SRC_PLUGINS="$PROJECT_ROOT/src/plugins"
ALL_PLUGINS=(beads)
PLUGINS=()
PLUGINS_OVERRIDE=""
```

### New Flag: `--plugins=`

Mirrors the existing `--tools=` flag parser exactly. Add to the `for arg in "$@"` loop:

```sh
--plugins=*)   PLUGINS_OVERRIDE="${arg#--plugins=}" ;;
```

Add to the `--help` output:

```
  --plugins=PLUGINS  Comma-separated plugins: beads
                     Default: auto-detect (enabled if bd is on PATH or ~/.beads/ exists)
```

**Parser semantics** (same as `--tools=`, runs after arg parsing):
- If `PLUGINS_OVERRIDE` is set (even empty), use it as the explicit list — replaces auto-detection entirely
- Unknown plugin names are a fatal error with a clear message
- Duplicates are silently deduplicated
- `--plugins=` with empty value means no plugins installed
- Summary output: active plugins listed; skipped plugins shown with `(not detected, skipped)` in the same DIM format used for tools

**Auto-detection (when `--plugins=` is absent):**
- If `bd` is on PATH **or** `~/.beads/` exists → beads auto-enabled
- Same pattern as Codex/Gemini auto-detection today

**Plugin disable warning:** When a previously-detected plugin is now not detected and `--plugins=` is absent (i.e., auto-detection produces no match), emit:

```
warn "Plugin 'beads' not detected (bd not on PATH and ~/.beads/ not found) — skipping. Files already installed are not removed."
```

### Staging + Sync Flow

The install.sh is refactored around a **staging pattern**: content is assembled into a tmp tree before any comparison or copy to the target `~/.<tool>/` directories. This requires new staging helpers in addition to the existing sync functions.

**Cleanup:** The staging directory is always removed via a `trap` registered at script start, ensuring cleanup on both normal exit and error:
```sh
STAGING_DIR="$(mktemp -d /tmp/agents-config-install-XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT
```

**Per-tool install flow (replacing the current per-tool loop):**

```
for each active tool:
  1. Create tool staging dir: $STAGING_DIR/<tool>/
  2. Stage base content:
     a. Render shared templates (.agents/*.md.template → staging/)
     b. Copy shared skills  (.agents/skills/ → staging/skills/)
     c. Copy shared agents  (.agents/agents/ → staging/agents/)
     d. Render tool templates (.<tool>/*.md.template → staging/)
     e. Copy tool subdirs   (.<tool>/{commands,skills,agents,rules}/ → staging/)
  3. Overlay active plugins (alphabetical plugin order):
     a. For each plugin, if .<tool>/ subdir exists in plugin:
        - Copy plugin's .<tool>/{rules,commands,skills,agents}/ into staging
        - On file/dir collision, apply collision resolution (see below)
        - If plugin has .<tool>/settings.json.template: union-merge into staged settings.json
     b. For each plugin, if .agents/ subdir exists in plugin:
        - Copy plugin's .agents/{skills,agents}/ into staging (for this tool)
        - On file/dir collision, apply collision resolution (see below)
  4. Sync $STAGING_DIR/<tool>/ → ~/.<tool>/ using existing compute_hash + sync logic
```

The existing `compute_hash()`, `sync_directory()`, `sync_settings_file()`, and `sync_templates()` functions remain reusable for the final staging→target sync step. **New helpers are required** for the staging assembly phase: a `stage_file()` function that copies a file into the staging tree and a `resolve_collision()` function that applies the collision table below.

**Confirmation flow:** The staging phase itself is **silent** — no interactive prompts. All `confirm()` prompts happen only in the final staging→target sync step (step 4 above), which reuses `sync_directory()` / `sync_templates()` unchanged. The staging phase aborts via `err + exit 1` only on fatal collision errors.

**`.beads/` content — separate staging path:**

The `.beads/` target (`~/.beads/formulas/`) has a fundamentally different structure from tool directories (formulas-only, flat, no subdir hierarchy). It is staged and synced separately:

```
if beads plugin is active:
  Stage formulas: $STAGING_DIR/.beads/formulas/
  For each plugin with .beads/formulas/:
    Copy *.toml into staging, applying TOML collision resolution
  Sync $STAGING_DIR/.beads/formulas/ → ~/.beads/formulas/
  using existing compute_hash + sync logic
```

This is implemented as `stage_and_install_beads()` — a parallel to `stage_and_install_tool()` but scoped to the formulas-only target. The staging and sync primitives are reused; only the source/target paths differ.

### Collision Resolution

Plugin subdirectory files should use unique names by convention (see `src/plugins/AGENTS.md`). When collisions occur in the staging tree:

| File type | Resolution |
|-----------|-----------|
| `.md` in `rules/` only | Base first, plugins alphabetically — **append** with `\n---\n` separator |
| `.md` in `commands/`, `agents/`, `skills/` | **Fatal error** — must use unique names |
| `settings.json.template` | **Union-merge** — base first, plugins alphabetically; same jq logic as existing `sync_settings_file()` |
| `.toml` (formulas) | Last-wins alphabetically + **warn** |
| Directories (skill dirs, agent dirs) | **Fatal error** — same-named directories between a plugin and base content, or across plugins, is a bug |

### When a Plugin Is Disabled

When auto-detection stops matching (e.g., `bd` is removed) or a user passes `--plugins=` without listing a previously-enabled plugin, the install.sh **does not remove** previously installed plugin files. Removal is risky (user may have customized them).

Behavior:
- install.sh emits the warning described in the `--plugins=` section above (auto-detection miss) **or**, if explicitly excluded via `--plugins=`, warns: `"Plugin 'beads' excluded via --plugins= but files may still be installed in ~/.<tool>/. Remove them manually if no longer needed."`
- Files are left in place in both cases
- A future `--prune-plugins` flag may automate removal (out of scope here)

### New Functions

**`stage_and_install_tool(tool)`** — replaces `install_tool()`. Creates staging for one tool, assembles base + plugin content, resolves collisions, then syncs staging to `~/.<tool>/`.

**`stage_and_install_beads()`** — replaces `install_beads()`. Stages beads formula files, then syncs to `~/.beads/formulas/`. Separate from the per-tool loop because the target structure is formulas-only.

**`stage_file(src, staging_dir)`** — copies a single file into staging, applying `resolve_collision()` if the target already exists.

**`resolve_collision(existing, incoming, file_type)`** — applies the collision table. `file_type` is a composite string encoding both the file extension and the parent directory context, e.g. `rules.md`, `commands.md`, `skills.md`, `agents.md`, `toml`, `dir`. This disambiguates `.md` files in `rules/` (append) from `.md` files in `commands/` or `skills/` (fatal). Callers must pass the appropriate string — the function does a simple switch/case match, not path inspection.

**`plugin_enabled(plugin_name)`** — returns true if the named plugin is in the active `PLUGINS` array.

### Main Loop (Revised)

```sh
# Register staging cleanup trap
STAGING_DIR="$(mktemp -d /tmp/agents-config-install-XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT

# For each tool: stage base + plugins, then sync to target
for tool in "${TOOLS[@]}"; do
    stage_and_install_tool "$tool"
done

# For beads: stage formulas, sync to ~/.beads/
if plugin_enabled "beads"; then
    stage_and_install_beads
fi

# Summary...
```

Summary counters extended to include active plugins, same pattern as tools today.

---

## src/plugins/AGENTS.md Contract

Documents for agents and plugin authors:

1. **Unique filenames are required** for commands, skills, agents, and non-rules markdown. Name plugin files `<plugin>-<thing>.md` or place them in plugin-owned subdirs. Accidental collisions are a fatal install error.
2. **Rule file collisions are intentional-append only.** Two plugins (or a plugin + base) may both provide `rules/some-rule.md` only when the intent is to extend shared behavior. Alphabetical plugin order determines append sequence.
3. **Plugin scope is subdirectory content only.** Supported targets: `.<tool>/rules/`, `.<tool>/commands/`, `.<tool>/skills/`, `.<tool>/agents/`, `.<tool>/settings.json.template` (union-merged), `.agents/skills/`, `.agents/agents/`, `.beads/formulas/`. Explicitly forbidden: identity template files (`AGENTS.md.template`, `CLAUDE.md.template`, etc.) and any non-settings `.template` file.
4. **Directory collisions are fatal** — a plugin may not define a skill or agent directory whose name matches an existing base skill/agent or another plugin's skill/agent.
5. **`.beads/AGENTS.md` is repository documentation only** — it is not installed to any target directory.
6. **Detection:** `install.sh` auto-detects a plugin if its sentinel condition is met (e.g., `bd` on PATH or `~/.beads/` exists for beads). Override with `--plugins=`. An explicit `--plugins=` list disables auto-detection entirely.

---

## Out of Scope

- Moving beads skills (`create-bead`, `start-bead`, `implement-bead`, `run-queue`) — handled by a separate agent's work; they currently sit in `src/user/.agents/skills/beads/` (untracked) and will be committed to `src/plugins/beads/.agents/skills/` in that agent's work
- Any plugin beyond beads — architecture supports it, implementation deferred
- Plugin versioning or dependency resolution between plugins
- Automated removal of previously-installed plugin files (`--prune-plugins`)
