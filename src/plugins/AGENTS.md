# src/plugins/ — Optional Plugin Content

This directory contains optional integrations that may not apply to all users. Plugins are
feature-flagged in `install.sh` via the `--plugins=` flag and auto-detected by a sentinel condition.

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
        skills/
        agents/
      .beads/                     Beads-specific content
        formulas/                 Formula TOML files → ~/.beads/formulas/
        AGENTS.md                 Repo-only documentation; NOT installed

## Naming Convention

- **Commands, skills, agents:** pick names that are unambiguous in the global skill namespace. Same-named items across plugins (or plugin vs base) are a fatal install error. A `<plugin>-<name>` prefix is a safe fallback when a shorter name would collide or read ambiguously; prefer domain-obvious names (e.g. `start-bead`) when they are self-describing.
- **Rules:** collisions are allowed — content is appended with a `---` separator, base first then plugins alphabetically.
- **Settings:** always union-merged (base first, plugins alphabetically). Use for MCP, hooks, permissions.
- **`.template` files:** only `settings.json.template` is supported and processed. Other `.template` files in plugin directories are not installed (install.sh ignores them).

## Collision Resolution

| File type | Resolution |
|-----------|-----------|
| `.md` in `rules/` | Append (base first, plugins alphabetically) |
| `.md` in `commands/`, `skills/`, `agents/` | **Fatal error** |
| `settings.json.template` | Union-merge (base first, plugins alphabetically) |
| `.toml` (formulas) | Last-wins alphabetically + warn |
| Directories | **Fatal error** (plugin vs base OR plugin vs plugin) |

## Adding a New Plugin

1. Create `src/plugins/<name>/` with the content subdirs you need
2. Add `<name>` to `ALL_PLUGINS` in `scripts/install.sh`
3. Add an auto-detection condition to the plugin detection block in `install.sh`

## Current Plugins

| Plugin | Auto-detect sentinel | What it installs |
|--------|---------------------|-----------------|
| `beads` | `bd` on PATH OR `~/.beads/` exists | Claude rules, commands, and beads formulas |
