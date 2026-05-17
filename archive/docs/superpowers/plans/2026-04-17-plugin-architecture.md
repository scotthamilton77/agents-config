# Plugin Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move beads-related content into `src/plugins/beads/`, add a `--plugins=` flag to `install.sh` with staging-based assembly, so beads instructions are isolated and only installed when beads is detected.

**Architecture:** A staging pattern replaces direct-sync — base and plugin content is assembled into a tmp directory tree, then existing `sync_*` functions compare the staged tree against the installed target. New `stage_item()`, `resolve_collision()`, and `classify_file()` helpers drive assembly. `--plugins=` mirrors `--tools=` exactly.

**Tech Stack:** Bash/zsh shell script, jq (already required by `install.sh`), standard POSIX utilities. No build system. Verification via `--dry-run` output inspection.

**Spec:** `docs/superpowers/specs/2026-04-17-plugin-architecture-design.md`

---

## File Map

**Created:**
- `src/plugins/AGENTS.md` — plugin system documentation and conventions
- `src/plugins/beads/.beads/AGENTS.md` — moved from `src/user/.beads/AGENTS.md`
- `src/plugins/beads/.beads/formulas/*.toml` — moved from `src/user/.beads/formulas/`
- `src/plugins/beads/.claude/rules/beads.md` — moved from `src/user/.claude/rules/beads.md`
- `src/plugins/beads/.claude/commands/implement-bead.md` — moved from `src/user/.claude/commands/implement-bead.md`
- `src/plugins/beads/.agents/skills/` — empty placeholder for future beads skills migration

**Modified:**
- `src/user/.agents/INSTRUCTIONS.md.template` — strip "or bead" from line 37
- `src/plugins/beads/.claude/rules/beads.md` — add relocated "or bead" guidance (after move)
- `scripts/install.sh` — major refactor: variables, flag, staging functions, new main loop

**Deleted (via move):**
- `src/user/.beads/` (entire directory)
- `src/user/.claude/rules/beads.md`
- `src/user/.claude/commands/implement-bead.md`

---

### Task 1: Create src/plugins/ structure and move beads content

**Files:**
- Create: `src/plugins/AGENTS.md`
- Create: `src/plugins/beads/` directory tree
- Delete/move: `src/user/.beads/`, `src/user/.claude/rules/beads.md`, `src/user/.claude/commands/implement-bead.md`

- [ ] **Step 1: Check for WIP skills directory — do not touch it**

```bash
ls src/user/.agents/skills/
```

If you see a `beads/` subdirectory, that is untracked WIP from a separate agent. Leave it completely alone throughout this entire plan.

- [ ] **Step 2: Create directory structure**

```bash
mkdir -p src/plugins/beads/.beads/formulas
mkdir -p src/plugins/beads/.claude/rules
mkdir -p src/plugins/beads/.claude/commands
mkdir -p src/plugins/beads/.agents/skills
```

- [ ] **Step 3: Move .beads/ content**

```bash
mv src/user/.beads/AGENTS.md src/plugins/beads/.beads/AGENTS.md
mv src/user/.beads/formulas/brainstorm-bead.formula.toml src/plugins/beads/.beads/formulas/
mv src/user/.beads/formulas/implement-feature.formula.toml src/plugins/beads/.beads/formulas/
mv src/user/.beads/formulas/fix-bug.formula.toml src/plugins/beads/.beads/formulas/
mv src/user/.beads/formulas/merge-and-cleanup.formula.toml src/plugins/beads/.beads/formulas/
rmdir src/user/.beads/formulas src/user/.beads
```

- [ ] **Step 4: Move Claude-specific beads files**

```bash
mv src/user/.claude/rules/beads.md src/plugins/beads/.claude/rules/beads.md
mv src/user/.claude/commands/implement-bead.md src/plugins/beads/.claude/commands/implement-bead.md
```

- [ ] **Step 5: Create src/plugins/AGENTS.md**

Write the following content to `src/plugins/AGENTS.md`:

```markdown
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

- **Commands, skills, agents:** use a `<plugin>-<name>` prefix. Same-named items are a fatal install error.
- **Rules:** collisions are allowed — content is appended with a `---` separator, base first then plugins alphabetically.
- **Settings:** always union-merged (base first, plugins alphabetically). Use for MCP, hooks, permissions.
- **`.template` files:** only `settings.json.template` is supported. Identity templates (AGENTS.md.template, etc.) are forbidden in plugins.

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
```

- [ ] **Step 6: Verify directory structure**

```bash
find src/plugins -not -path "*/\.git/*" | sort
```

Expected output:
```
src/plugins
src/plugins/AGENTS.md
src/plugins/beads
src/plugins/beads/.agents
src/plugins/beads/.agents/skills
src/plugins/beads/.beads
src/plugins/beads/.beads/AGENTS.md
src/plugins/beads/.beads/formulas
src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml
src/plugins/beads/.beads/formulas/fix-bug.formula.toml
src/plugins/beads/.beads/formulas/implement-feature.formula.toml
src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml
src/plugins/beads/.claude
src/plugins/beads/.claude/commands
src/plugins/beads/.claude/commands/implement-bead.md
src/plugins/beads/.claude/rules
src/plugins/beads/.claude/rules/beads.md
```

- [ ] **Step 7: Verify old locations are gone**

```bash
ls src/user/.beads 2>/dev/null && echo "FAIL: .beads still exists" || echo "OK"
ls src/user/.claude/rules/beads.md 2>/dev/null && echo "FAIL: beads.md still in rules/" || echo "OK"
ls src/user/.claude/commands/implement-bead.md 2>/dev/null && echo "FAIL: implement-bead.md still in commands/" || echo "OK"
```

Expected: all three print `OK`.

- [ ] **Step 8: Commit**

```bash
git add src/plugins/ && git add -u src/user/.beads/ src/user/.claude/rules/beads.md src/user/.claude/commands/implement-bead.md
git commit -m "feat(plugins): create src/plugins/ structure and move beads content"
```

---

### Task 2: Update INSTRUCTIONS.md.template and relocate guidance

**Files:**
- Modify: `src/user/.agents/INSTRUCTIONS.md.template` (line 37)
- Modify: `src/plugins/beads/.claude/rules/beads.md`

- [ ] **Step 1: Strip "or bead" from INSTRUCTIONS.md.template**

Open `src/user/.agents/INSTRUCTIONS.md.template`. Find this line (around line 37):

```
- **Plan first**: Plan mode for multi-step tasks or architectural decisions. Re-plan immediately when blocked. Write specs in the plan file or bead for small-context specs.
```

Change it to:

```
- **Plan first**: Plan mode for multi-step tasks or architectural decisions. Re-plan immediately when blocked. Write specs in the plan file for small-context specs.
```

- [ ] **Step 2: Add relocated guidance to beads.md rule**

Open `src/plugins/beads/.claude/rules/beads.md`. Find the `**Rules**:` block and add this bullet:

```
- For bead-tracked work, specs may be written directly into the bead description (`bd update <id> --description "..."`) — the bead is the plan file
```

- [ ] **Step 3: Verify**

```bash
grep -n "or bead" src/user/.agents/INSTRUCTIONS.md.template
```

Expected: no output (the phrase is gone).

- [ ] **Step 4: Commit**

```bash
git add src/user/.agents/INSTRUCTIONS.md.template src/plugins/beads/.claude/rules/beads.md
git commit -m "feat(plugins): relocate 'or bead' guidance from shared template to beads rule"
```

---

### Task 3: Add plugin variables and --plugins= flag to install.sh

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: Add PLUGINS_OVERRIDE to flag variables**

Find the block around line 69 (`DRY_RUN=false`):

```sh
DRY_RUN=false
AUTO_YES=false
TOOLS_OVERRIDE=""
```

Add `PLUGINS_OVERRIDE=""` after `TOOLS_OVERRIDE`:

```sh
DRY_RUN=false
AUTO_YES=false
TOOLS_OVERRIDE=""
PLUGINS_OVERRIDE=""
```

- [ ] **Step 2: Add --plugins= to arg parser**

In the `for arg in "$@"` loop, after the `--tools=*)` case, add:

```sh
        --plugins=*)   PLUGINS_OVERRIDE="${arg#--plugins=}" ;;
```

- [ ] **Step 3: Add --plugins= to --help output**

In the `--help` case, after the `--tools=TOOLS` help line, add:

```sh
            echo "  --plugins=PLUGINS  Comma-separated plugins: beads"
            echo "                     Default: auto-detect (enabled if bd is on PATH or ~/.beads/ exists)"
```

- [ ] **Step 4: Add SRC_PLUGINS variable**

In the `# ── Paths ─────` section, after the `SRC_SHARED=` line, add:

```sh
SRC_PLUGINS="$PROJECT_ROOT/src/plugins"
```

- [ ] **Step 5: Add ALL_PLUGINS and PLUGINS arrays**

In the `# ── Tool detection ────` section, after `ALL_TOOLS=(claude codex gemini)` and `TOOLS=()`, add:

```sh
ALL_PLUGINS=(beads)
PLUGINS=()
```

- [ ] **Step 6: Add plugin detection block after tool detection**

After the `info "Tools: ${TOOLS[*]}"` line, add the plugin detection block:

```sh
# ── Plugin detection ─────────────────────────────────────────────────────────

if [[ -n "$PLUGINS_OVERRIDE" ]]; then
    if [ -n "${BASH_VERSION:-}" ]; then
        IFS=',' read -ra PLUGINS <<< "$PLUGINS_OVERRIDE"
    else
        IFS=',' read -rA PLUGINS <<< "$PLUGINS_OVERRIDE"
    fi
    # Validate each requested plugin
    for plugin in "${PLUGINS[@]}"; do
        local_valid=false
        for valid in "${ALL_PLUGINS[@]}"; do
            if [[ "$plugin" == "$valid" ]]; then
                local_valid=true
                break
            fi
        done
        if [[ "$local_valid" != true ]]; then
            err "Unknown plugin: $plugin (valid: ${ALL_PLUGINS[*]})"
            exit 1
        fi
    done
    # Warn about explicitly excluded plugins
    for plugin in "${ALL_PLUGINS[@]}"; do
        in_list=false
        for p in "${PLUGINS[@]}"; do
            [[ "$p" == "$plugin" ]] && in_list=true && break
        done
        if [[ "$in_list" == false ]]; then
            warn "Plugin '$plugin' excluded via --plugins= — files already installed are not removed."
        fi
    done
else
    # Auto-detect: enable beads if bd is on PATH or ~/.beads/ exists
    if command -v bd &>/dev/null || [[ -d "$HOME/.beads" ]]; then
        PLUGINS+=(beads)
    fi
fi

info "Plugins: ${PLUGINS[*]:-none}"
```

- [ ] **Step 7: Extend counter declarations to include all plugins**

Find the counter initialization loop (around line 186):

```sh
for tool in "${ALL_TOOLS[@]}" beads; do
```

Change to:

```sh
for tool in "${ALL_TOOLS[@]}" "${ALL_PLUGINS[@]}"; do
```

- [ ] **Step 8: Add plugin_enabled() helper**

After the `backup()` function, add:

```sh
# ── Utility: check if a plugin is in the active PLUGINS array ─────────────────

plugin_enabled() {
    local name="$1"
    for p in "${PLUGINS[@]}"; do
        [[ "$p" == "$name" ]] && return 0
    done
    return 1
}
```

- [ ] **Step 9: Verify syntax**

```bash
bash -n scripts/install.sh && echo "PASS: no syntax errors" || echo "FAIL"
```

Expected: `PASS: no syntax errors`

- [ ] **Step 10: Smoke test flag parsing**

```bash
./scripts/install.sh --dry-run --plugins= 2>&1 | grep "Plugins:"
```
Expected: `Plugins: none` (or empty after colon)

```bash
./scripts/install.sh --dry-run --plugins=beads 2>&1 | grep "Plugins:"
```
Expected: `Plugins: beads`

```bash
./scripts/install.sh --dry-run --plugins=bogus 2>&1; echo "exit: $?"
```
Expected: error message containing "Unknown plugin: bogus", exit code non-zero.

- [ ] **Step 11: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): add --plugins= flag with beads auto-detection and plugin_enabled()"
```

---

### Task 4: Add staging infrastructure helpers

**Files:**
- Modify: `scripts/install.sh`

These are pure helper functions. They do not change any existing behavior yet.

- [ ] **Step 1: Add resolve_collision() function**

After `backup()`, add the following function. Note the `other` case for identity templates (which are overwritten by tool-specific versions without conflict):

```sh
# ── Utility: resolve a staging collision ──────────────────────────────────────
#
# file_type composite strings:
#   rules.md      → append with --- separator
#   commands.md, skills.md, agents.md → fatal (unique names required)
#   settings.json → union-merge (same jq logic as sync_settings_file)
#   toml          → last-wins + warn
#   dir           → fatal (unique directory names required)
#   other         → last-wins silently (tool templates overwrite shared)

resolve_collision() {
    local existing="$1"
    local incoming="$2"
    local file_type="$3"

    case "$file_type" in
        rules.md)
            printf '\n---\n' >> "$existing"
            cat "$incoming" >> "$existing"
            ;;
        commands.md|skills.md|agents.md)
            err "Fatal collision: $(basename "$incoming") exists in both base and plugin content. Files in commands/, skills/, and agents/ must use unique names."
            exit 1
            ;;
        settings.json)
            local merged_json
            merged_json="$(jq -s '
                def union_arrays: [.[0], .[1]] | add | unique;
                def deep_merge:
                    if (.[0] | type) == "object" and (.[1] | type) == "object" then
                        .[0] as $a | .[1] as $b |
                        ($a | keys) + ($b | keys) | unique | map(. as $k |
                            if ($a | has($k)) and ($b | has($k)) then
                                if ($a[$k] | type) == "array" and ($b[$k] | type) == "array" then
                                    {($k): ([$a[$k], $b[$k]] | union_arrays)}
                                elif ($a[$k] | type) == "object" and ($b[$k] | type) == "object" then
                                    {($k): ([$a[$k], $b[$k]] | deep_merge)}
                                else
                                    {($k): $a[$k]}
                                end
                            elif ($a | has($k)) then
                                {($k): $a[$k]}
                            else
                                {($k): $b[$k]}
                            end
                        ) | add
                    else
                        .[0]
                    end;
                [.[0], .[1]] | deep_merge
            ' "$existing" "$incoming")"
            printf '%s\n' "$merged_json" | jq . > "$existing"
            ;;
        toml)
            warn "TOML collision: $(basename "$incoming") — plugin overwrites base (alphabetical order)"
            cp "$incoming" "$existing"
            ;;
        dir)
            err "Fatal collision: directory $(basename "$incoming") exists in both base and plugin content (or two plugins). Skill and agent directories must use unique names."
            exit 1
            ;;
        other)
            cp "$incoming" "$existing"
            ;;
        *)
            err "resolve_collision: unknown file_type '$file_type'"
            exit 1
            ;;
    esac
}
```

- [ ] **Step 2: Add classify_file() function**

After `resolve_collision()`, add:

```sh
# ── Utility: classify a file for collision resolution ─────────────────────────
#
# Returns the file_type string expected by resolve_collision().
# parent_dir is the name of the containing directory (e.g., "rules", "commands").
# Pass "" for files that are not inside a named subdir (e.g., top-level templates).

classify_file() {
    local filepath="$1"
    local parent_dir="$2"
    local basename
    basename="$(basename "$filepath")"

    if [[ -d "$filepath" ]]; then
        echo "dir"
    elif [[ "$basename" == settings.json.template ]]; then
        echo "settings.json"
    elif [[ "$basename" == *.toml.template || "$basename" == *.toml ]]; then
        echo "toml"
    elif [[ "$basename" == *.md && -n "$parent_dir" ]]; then
        echo "${parent_dir}.md"
    else
        echo "other"
    fi
}
```

- [ ] **Step 3: Add stage_item() function**

After `classify_file()`, add:

```sh
# ── Utility: copy one item (file or dir) into staging, resolving collisions ───

stage_item() {
    local src="$1"
    local dest="$2"
    local file_type="$3"

    if [[ ! -e "$dest" ]]; then
        if [[ -d "$src" ]]; then
            cp -R "$src" "$dest"
        else
            cp "$src" "$dest"
        fi
    else
        resolve_collision "$dest" "$src" "$file_type"
    fi
}
```

- [ ] **Step 4: Add stage_content_from_dir() function**

After `stage_item()`, add:

```sh
# ── Utility: stage all items from one source subdir into a staging subdir ─────

stage_content_from_dir() {
    local src_parent="$1"   # parent containing the named subdir
    local staging_parent="$2"  # staging parent to copy into
    local dir_name="$3"        # subdir name: skills, rules, commands, agents

    local src_dir="$src_parent/$dir_name"
    local staging_dir="$staging_parent/$dir_name"

    [[ -d "$src_dir" ]] || return

    mkdir -p "$staging_dir"

    for item in "$src_dir"/*; do
        [[ -e "$item" ]] || continue
        local item_name file_type
        item_name="$(basename "$item")"
        file_type="$(classify_file "$item" "$dir_name")"
        stage_item "$item" "$staging_dir/$item_name" "$file_type"
    done
}
```

- [ ] **Step 5: Verify syntax**

```bash
bash -n scripts/install.sh && echo "PASS: no syntax errors" || echo "FAIL"
```

Expected: `PASS: no syntax errors`

- [ ] **Step 6: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): add staging helpers (resolve_collision, classify_file, stage_item, stage_content_from_dir)"
```

---

### Task 5: Implement stage_and_install_tool()

**Files:**
- Modify: `scripts/install.sh`

Replaces `install_tool()`. The staging phase is silent — all `confirm()` prompts happen only in the final sync step via the existing `sync_*` functions.

- [ ] **Step 1: Add STAGING_DIR and trap just before the main loop**

Find the `# ── Main loop ─────` section. Just before the `for tool in "${TOOLS[@]}"` loop, add:

```sh
# ── Staging directory (cleaned up on exit) ────────────────────────────────────

STAGING_DIR="$(mktemp -d /tmp/agents-config-install-XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT
```

- [ ] **Step 2: Add stage_and_install_tool() function**

Add after `stage_content_from_dir()`. This function assembles staging then syncs to target:

```sh
# ── Install one tool via staging ──────────────────────────────────────────────

stage_and_install_tool() {
    local tool="$1"
    local dest_dir="$HOME/.$tool"
    local src_tool="$SRC_USER/.$tool"
    local staging="$STAGING_DIR/$tool"

    CURRENT_TOOL="$tool"
    header "$tool"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_dir"
    mkdir -p "$staging"

    # ── Phase 1: Stage shared templates (.agents/*.md.template → staging/) ───
    info "Phase 1: Shared templates"
    for template in "$SRC_SHARED"/*.md.template; do
        [[ -f "$template" ]] || continue
        stage_item "$template" "$staging/$(basename "$template")" "other"
    done

    # ── Phase 2: Stage shared skills and agents ───────────────────────────────
    stage_content_from_dir "$SRC_SHARED" "$staging" "skills"
    stage_content_from_dir "$SRC_SHARED" "$staging" "agents"

    # ── Phase 3: Stage tool-specific templates ────────────────────────────────
    if [[ -d "$src_tool" ]]; then
        info "Phase 3: Tool-specific templates"
        for template in "$src_tool"/*.md.template; do
            [[ -f "$template" ]] || continue
            stage_item "$template" "$staging/$(basename "$template")" "other"
        done
    fi

    # ── Phase 4: Stage tool-specific subdirs ──────────────────────────────────
    if [[ -d "$src_tool" ]]; then
        for subdir in commands skills agents rules; do
            stage_content_from_dir "$src_tool" "$staging" "$subdir"
        done
    fi

    # ── Phase 5: Stage tool-specific settings ────────────────────────────────
    if [[ -d "$src_tool" ]]; then
        for settings_file in "$src_tool"/*.json.template "$src_tool"/*.toml.template; do
            [[ -f "$settings_file" ]] || continue
            local file_type
            file_type="$(classify_file "$settings_file" "")"
            stage_item "$settings_file" "$staging/$(basename "$settings_file")" "$file_type"
        done
    fi

    # ── Phase 6: Overlay active plugins (alphabetical order) ─────────────────
    for plugin in "${PLUGINS[@]}"; do
        local plugin_tool_dir="$SRC_PLUGINS/$plugin/.$tool"
        local plugin_agents_dir="$SRC_PLUGINS/$plugin/.agents"

        if [[ -d "$plugin_tool_dir" ]]; then
            for subdir in rules commands skills agents; do
                stage_content_from_dir "$plugin_tool_dir" "$staging" "$subdir"
            done
            # Plugin settings injection (MCP servers, hooks, permissions)
            for settings_file in "$plugin_tool_dir"/*.json.template; do
                [[ -f "$settings_file" ]] || continue
                stage_item "$settings_file" "$staging/$(basename "$settings_file")" "settings.json"
            done
        fi

        if [[ -d "$plugin_agents_dir" ]]; then
            for subdir in skills agents; do
                stage_content_from_dir "$plugin_agents_dir" "$staging" "$subdir"
            done
        fi
    done

    # ── Phase 7: Sync staging → ~/.<tool>/ (reusing existing sync functions) ──
    info "Phase 7: Sync to $dest_dir"

    # Sync templates: staging has *.md.template; sync_templates strips the suffix
    sync_templates "$staging" "$dest_dir" "staged"

    # Sync subdirectories
    for subdir in rules commands skills agents; do
        [[ -d "$staging/$subdir" ]] || continue
        sync_directory "$subdir" "$staging" "$dest_dir" "staged"
    done

    # Sync settings files (union-merges staged template with installed settings)
    for settings_file in "$staging"/*.json.template "$staging"/*.toml.template; do
        [[ -f "$settings_file" ]] || continue
        sync_settings_file "$settings_file" "$dest_dir" "staged"
    done
}
```

- [ ] **Step 3: Replace install_tool() call in main loop**

Find:
```sh
for tool in "${TOOLS[@]}"; do
    install_tool "$tool"
done
```

Change to:
```sh
for tool in "${TOOLS[@]}"; do
    stage_and_install_tool "$tool"
done
```

Do NOT delete `install_tool()` yet — keep it until smoke tests pass.

- [ ] **Step 4: Verify syntax**

```bash
bash -n scripts/install.sh && echo "PASS" || echo "FAIL"
```

Expected: `PASS`

- [ ] **Step 5: Dry-run smoke test**

```bash
./scripts/install.sh --dry-run 2>&1 | head -80
```

Expected: phases 1–7 visible for the claude tool; no error output; staged content shown as "up to date" or "Would install/update".

- [ ] **Step 6: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): implement stage_and_install_tool() replacing install_tool()"
```

---

### Task 6: Implement stage_and_install_beads()

**Files:**
- Modify: `scripts/install.sh`

Replaces `install_beads()`. Only runs when beads plugin is enabled.

- [ ] **Step 1: Add stage_and_install_beads() function**

Add after `stage_and_install_tool()`:

```sh
# ── Install beads formulas via staging ───────────────────────────────────────

stage_and_install_beads() {
    local dest_formulas="$HOME/.beads/formulas"
    local staging_formulas="$STAGING_DIR/.beads/formulas"

    header "beads formulas"
    CURRENT_TOOL="beads"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_formulas"
    mkdir -p "$staging_formulas"

    # Stage formulas from all active plugins with a .beads/formulas/ subdir
    for plugin in "${PLUGINS[@]}"; do
        local plugin_formulas="$SRC_PLUGINS/$plugin/.beads/formulas"
        [[ -d "$plugin_formulas" ]] || continue

        for formula in "$plugin_formulas"/*.toml; do
            [[ -f "$formula" ]] || continue
            local name
            name="$(basename "$formula")"
            stage_item "$formula" "$staging_formulas/$name" "toml"
        done
    done

    # Sync staged formulas → ~/.beads/formulas/
    local found_any=false
    for formula in "$staging_formulas"/*.toml; do
        [[ -f "$formula" ]] || continue
        found_any=true
        local name dest_file src_hash dst_hash
        name="$(basename "$formula")"
        dest_file="$dest_formulas/$name"

        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                ok "Would install formulas/$name (new)"
            else
                cp "$formula" "$dest_file"
                ok "Installed formulas/$name (new)"
            fi
            (( tool_installed[beads]++ )) || true
        else
            src_hash="$(compute_hash "$formula")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                ok "formulas/$name is up to date"
                (( tool_skipped[beads]++ )) || true
            else
                info "formulas/$name differs:"
                diff --color=auto -u "$dest_file" "$formula" || true
                echo
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would update formulas/$name"
                    (( tool_updated[beads]++ )) || true
                elif confirm "Overwrite ~/.beads/formulas/$name?"; then
                    backup "$dest_file"
                    cp "$formula" "$dest_file"
                    ok "Updated formulas/$name"
                    (( tool_updated[beads]++ )) || true
                else
                    warn "Skipped formulas/$name"
                    (( tool_skipped[beads]++ )) || true
                fi
            fi
        fi
    done

    [[ "$found_any" == false ]] && info "No formula files staged"

    # Warn about formulas in dest that aren't in staged source
    for dest_file in "$dest_formulas"/*.toml; do
        [[ -f "$dest_file" ]] || continue
        local name
        name="$(basename "$dest_file")"
        if [[ ! -f "$staging_formulas/$name" ]]; then
            warn "formulas/$name exists in ~/.beads/formulas but not in plugin source (keeping)"
        fi
    done
}
```

- [ ] **Step 2: Verify syntax**

```bash
bash -n scripts/install.sh && echo "PASS" || echo "FAIL"
```

Expected: `PASS`

- [ ] **Step 3: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): implement stage_and_install_beads() replacing install_beads()"
```

---

### Task 7: Wire up main loop, summary, and remove old functions

**Files:**
- Modify: `scripts/install.sh`

- [ ] **Step 1: Replace install_beads() call with conditional stage_and_install_beads()**

Find:
```sh
install_beads
```

Replace with:
```sh
if plugin_enabled "beads"; then
    stage_and_install_beads
fi
```

- [ ] **Step 2: Update summary loop**

Find:
```sh
for tool in "${TOOLS[@]}" beads; do
```

Change to:
```sh
for tool in "${TOOLS[@]}" "${PLUGINS[@]}"; do
```

- [ ] **Step 3: Add plugin skipped-display to summary**

Find the existing "not detected, skipped" block for tools at the bottom of the summary:

```sh
for tool in "${ALL_TOOLS[@]}"; do
    in_tools=false
    ...
done
```

After this block, add a parallel block for plugins:

```sh
for plugin in "${ALL_PLUGINS[@]}"; do
    in_plugins=false
    for p in "${PLUGINS[@]}"; do
        if [[ "$p" == "$plugin" ]]; then
            in_plugins=true
            break
        fi
    done
    if [[ "$in_plugins" == false ]]; then
        printf "\n${DIM}-- %s (not detected, skipped) --${RESET}\n" "$plugin"
    fi
done
```

- [ ] **Step 4: Delete old install_tool() and install_beads() functions**

Remove the entire `install_tool()` function body (the function that was replaced by `stage_and_install_tool()`). Remove the entire `install_beads()` function body.

- [ ] **Step 5: Verify syntax**

```bash
bash -n scripts/install.sh && echo "PASS" || echo "FAIL"
```

Expected: `PASS`

- [ ] **Step 6: Commit**

```bash
git add scripts/install.sh
git commit -m "feat(install): wire main loop, update summary, remove old install_tool/install_beads"
```

---

### Task 8: End-to-end smoke tests

- [ ] **Step 1: Full dry-run — auto-detect**

```bash
./scripts/install.sh --dry-run 2>&1
```

Check for:
- `Plugins: beads` (if `bd` on PATH or `~/.beads/` exists) OR `Plugins: none`
- `-- claude --` section with phases 1–7
- `-- beads formulas --` section (if beads enabled)
- `-- Summary --` section with beads counters or "(not detected, skipped)"
- No unhandled errors

- [ ] **Step 2: Dry-run with explicit --plugins=beads**

```bash
./scripts/install.sh --dry-run --plugins=beads 2>&1 | grep -E "Plugin|beads|formula"
```

Expected: beads plugin active; formula files listed as up-to-date or would-install.

- [ ] **Step 3: Dry-run with --plugins= (no plugins)**

```bash
./scripts/install.sh --dry-run --plugins= 2>&1 | grep -E "Plugin|beads|excluded"
```

Expected: warning "Plugin 'beads' excluded via --plugins="; no beads formulas section.

- [ ] **Step 4: Dry-run with invalid plugin name**

```bash
./scripts/install.sh --dry-run --plugins=bogus 2>&1; echo "exit: $?"
```

Expected: error message "Unknown plugin: bogus", non-zero exit code.

- [ ] **Step 5: Verify beads.md installs from plugin**

```bash
./scripts/install.sh --dry-run --plugins=beads 2>&1 | grep "beads.md"
```

Expected: output shows `beads.md` would be installed or is up-to-date in `~/.claude/rules/`.

- [ ] **Step 6: Verify implement-bead.md installs from plugin**

```bash
./scripts/install.sh --dry-run --plugins=beads 2>&1 | grep "implement-bead"
```

Expected: output shows `implement-bead.md` would be installed or is up-to-date in `~/.claude/commands/`.

- [ ] **Step 7: Verify no beads content in tool output when plugins disabled**

```bash
./scripts/install.sh --dry-run --plugins= 2>&1 | grep -E "beads\.md|implement-bead"
```

Expected: no output (beads content not installed when plugin disabled).

- [ ] **Step 8: Fix and commit if any smoke test failed**

If any step above failed, diagnose and fix the issue, then:

```bash
git add scripts/install.sh
git commit -m "fix(install): smoke test fixes"
```

If all steps passed, no additional commit needed.
