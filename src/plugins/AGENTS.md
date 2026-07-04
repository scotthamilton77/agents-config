# src/plugins/ — Optional Plugin Content

This directory contains optional integrations that may not apply to all users.
The Python installer (`packages/installer/`) **discovers** plugins by scanning
the direct subdirectories of `src/plugins/` (dot/underscore-prefixed dirs and
loose files like this `AGENTS.md` are skipped). Which discovered plugins are
**activated** is resolved per run: by default each plugin's adapter
auto-detects against `$HOME` (`is_detected`); `--plugins=<names>` overrides the
set (naming an undiscovered plugin is a fast-fail error), and `--plugins=`
(empty) installs none. A plugin's rules deploy only into the tools that are
themselves detected.

## Plugin Structure

Each plugin directory follows this layout (all subdirs are optional):

    src/plugins/<name>/
      .<tool>/                    Tool-specific content (.claude/, .codex/, .gemini/)
        rules/                    Rule files — appended on collision (unique names preferred)
        commands/                 Slash commands — unique names required (fatal on collision)
        skills/                   Skill directories — unique names required (fatal on collision)
        agents/                   Agent definitions — unique names required (fatal on collision)
        settings.json.template    Settings injection (MCP servers, hooks, permissions) — union-merged
      .agents/                    Shared content installed to all active tools
        rules/                    Rule files (same collision rules as .<tool>/rules/)
        rules-readmes/            Source-only rationale docs — NOT installed
        skills/
        agents/

## Naming Convention

- **Commands, skills, agents:** pick names that are unambiguous in the global skill namespace. Same-named items across plugins (or plugin vs base) are a fatal install error. A `<plugin>-<name>` prefix is a safe fallback when a shorter name would collide or read ambiguously; prefer domain-obvious names (e.g. `start-work`) when they are self-describing.
- **Rules:** collisions are allowed — content is appended with a `---` separator, base first then plugins alphabetically.
- **Settings:** always union-merged (base first, plugins alphabetically). Use for MCP, hooks, permissions.
- **`.template` files:** only `settings.json.template` is supported and processed. Other `.template` files in plugin directories are not installed (the installer ignores them).

## Collision Resolution

| File type | Resolution |
|-----------|-----------|
| `.md` in `rules/` | Append (base first, plugins alphabetically) |
| `.md` in `commands/`, `skills/`, `agents/` | **Fatal error** |
| `settings.json.template` | Union-merge (base first, plugins alphabetically) |
| `.toml` (formulas) | Last-wins alphabetically + warn |
| Directories | **Fatal error** (plugin vs base OR plugin vs plugin) |

## Adding a New Plugin

1. Create `src/plugins/<name>/` with the content subdirs you need. That alone
   makes it discoverable — the installer scans this directory; there is no
   registration list to edit.
2. By default it auto-detects via the `GenericPluginAdapter`, whose footprint
   check is `~/.<name>/` present *or* `<name>` on PATH. If that footprint isn't
   the right signal, or the plugin needs to install outside the tool config
   dirs (e.g. beads routing `~/.beads/`), add a specialized adapter under
   `packages/installer/src/installer/plugins/` and register it in
   `registry.py`'s `_SPECIALIZED` map.

## Current Plugins

| Plugin | Auto-detect footprint | Adapter | What it installs |
|--------|----------------------|---------|-----------------|
| `beads` | `bd` on PATH or `~/.beads/` exists | specialized (`BeadsPlugin`) | `beads.md` + `discovered-work.md` rules; also routes `~/.beads/` (e.g. formulas/scripts when present) |
| `graphify` | `~/.graphify/` or `graphify` on PATH | generic | graphify discipline rule (shared) |
| `codex` | `~/.codex/` or `codex` on PATH | generic | Codex routing rule (Claude-only) |
