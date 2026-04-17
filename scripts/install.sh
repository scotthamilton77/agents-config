#!/bin/sh
# Re-exec with zsh or bash 4+ if running under a shell that lacks associative arrays.
# macOS /bin/sh is bash 3.2 (no declare -A), so we check version too.
_need_reexec=0
if [ -n "${ZSH_VERSION:-}" ]; then
    _need_reexec=0  # zsh supports associative arrays
elif [ -n "${BASH_VERSION:-}" ]; then
    _major="${BASH_VERSION%%.*}"
    [ "$_major" -lt 4 ] && _need_reexec=1
else
    _need_reexec=1  # unknown shell
fi
if [ "$_need_reexec" = "1" ]; then
    if command -v zsh >/dev/null 2>&1; then
        exec zsh "$0" "$@"
    elif bash_path="$(command -v bash 2>/dev/null)" && [ "$("$bash_path" -c 'echo ${BASH_VERSINFO[0]}')" -ge 4 ] 2>/dev/null; then
        exec "$bash_path" "$0" "$@"
    else
        echo "Error: zsh or bash 4+ is required but neither was found." >&2
        exit 1
    fi
fi

set -euo pipefail

# Unmatched globs expand to nothing (not an error or literal)
if [ -n "${BASH_VERSION:-}" ]; then
    shopt -s nullglob
elif [ -n "${ZSH_VERSION:-}" ]; then
    setopt nullglob
fi

# --------------------------------------------------------------------------
# install.sh — Sync agent config into tool-specific home directories
#
# Supports: Claude (~/.claude/), Codex (~/.codex/), Gemini (~/.gemini/)
# Plugins:  beads (~/.beads/formulas/, tool rules/commands)
#
# Source layout:
#   src/user/.agents/          Shared content (agents, skills, templates)
#   src/user/.claude/          Claude-specific overrides & extensions
#   src/user/.codex/           Codex-specific overrides & extensions
#   src/user/.gemini/          Gemini-specific overrides & extensions
#   src/plugins/<name>/        Optional plugin content (beads, etc.)
#
# Per-tool install phases (in order):
#   1. Stage shared templates   .agents/*.md.template → staging/<tool>/
#   2. Stage shared skills/agents .agents/{skills,agents}/ → staging/<tool>/
#   3. Stage tool templates     .<tool>/*.md.template → staging/<tool>/
#   4. Stage tool subdirs       .<tool>/{commands,skills,agents,rules}/ → staging/<tool>/
#   5. Stage tool settings      .<tool>/*.json.template → staging/<tool>/
#   6. Overlay active plugins   src/plugins/<name>/.<tool>/ → staging/<tool>/
#   7. Sync staging → ~/.<tool>/ (hash-compare, diff, confirm)
#
# For beads plugin: staging/<beads>/formulas/ → ~/.beads/formulas/
#
# Flags:
#   --dry-run            Show what would be done without making changes
#   --yes, -y            Auto-accept all prompts
#   --tools=claude,...   Comma-separated list of tools (default: auto-detect)
#   --plugins=beads,...  Comma-separated list of plugins (default: auto-detect)
#   --help, -h           Show this help
# --------------------------------------------------------------------------

# ── Colors & helpers ─────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

DRY_RUN=false
AUTO_YES=false
TOOLS_OVERRIDE=""
PLUGINS_OVERRIDE=""
PLUGINS_FLAG_SET=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN=true ;;
        --yes|-y)      AUTO_YES=true ;;
        --tools=*)     TOOLS_OVERRIDE="${arg#--tools=}" ;;
        --plugins=*)   PLUGINS_OVERRIDE="${arg#--plugins=}"; PLUGINS_FLAG_SET=true ;;
        --help|-h)
            echo "Usage: install.sh [--dry-run] [--yes|-y] [--tools=TOOLS] [--plugins=PLUGINS] [--help|-h]"
            echo ""
            echo "Installs shared and tool-specific agent config into ~/.<tool>/ directories"
            echo "for Claude Code, OpenAI Codex CLI, and Google Gemini CLI."
            echo ""
            echo "Shared content (skills, agents, instructions, personas) from src/user/.agents/"
            echo "is installed into all detected tools. Tool-specific content from src/user/.<tool>/"
            echo "is installed only into that tool's directory."
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be done without making changes"
            echo "  --yes, -y          Auto-accept all prompts"
            echo "  --tools=TOOLS      Comma-separated tools: claude,codex,gemini"
            echo "                     Default: auto-detect (claude always, others if ~/.<tool>/ exists)"
            echo "  --plugins=PLUGINS  Comma-separated plugins: beads"
            echo "                     Default: auto-detect (enabled if bd is on PATH or ~/.beads/ exists)"
            echo "  --help, -h         Show this help"
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

info()  { printf "${CYAN}i${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}+${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
err()   { printf "${RED}x${RESET}  %s\n" "$*" >&2; }
header(){ printf "\n${BOLD}-- %s --${RESET}\n" "$*"; }

# Ask y/n, default to No. Auto-accepts with --yes, warns in non-interactive mode.
confirm() {
    local prompt="$1"
    if [[ "$AUTO_YES" == true ]]; then
        info "(auto-yes) $prompt"
        return 0
    fi
    if [[ ! -t 0 ]]; then
        warn "Non-interactive mode detected, skipping: $prompt"
        return 1
    fi
    local answer
    printf "${YELLOW}?${RESET}  %s [y/N] " "$prompt"
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

# ── Prerequisites ─────────────────────────────────────────────────────────

if ! command -v jq &>/dev/null; then
    err "jq is required but not installed."
    info "Install with:  brew install jq  (macOS)  or  apt install jq  (Linux)"
    exit 1
fi

# ── Paths ─────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_USER="$PROJECT_ROOT/src/user"
SRC_SHARED="$SRC_USER/.agents"
SRC_PLUGINS="$PROJECT_ROOT/src/plugins"

if [[ ! -d "$SRC_SHARED" ]]; then
    err "Shared source directory not found: $SRC_SHARED"
    exit 1
fi

if [[ "$DRY_RUN" == true ]]; then
    info "DRY RUN -- no changes will be made"
fi

# ── Tool detection ────────────────────────────────────────────────────────

ALL_TOOLS=(claude codex gemini)
TOOLS=()
ALL_PLUGINS=(beads)
PLUGINS=()

if [[ -n "$TOOLS_OVERRIDE" ]]; then
    if [ -n "${BASH_VERSION:-}" ]; then
        IFS=',' read -ra TOOLS <<< "$TOOLS_OVERRIDE"
    else
        IFS=',' read -rA TOOLS <<< "$TOOLS_OVERRIDE"
    fi
    # Validate each requested tool
    for tool in "${TOOLS[@]}"; do
        local_valid=false
        for valid in "${ALL_TOOLS[@]}"; do
            if [[ "$tool" == "$valid" ]]; then
                local_valid=true
                break
            fi
        done
        if [[ "$local_valid" != true ]]; then
            err "Unknown tool: $tool (valid: ${ALL_TOOLS[*]})"
            exit 1
        fi
    done
else
    # Auto-detect: always include claude, add others if their dir exists
    TOOLS=(claude)
    for tool in codex gemini; do
        if [[ -d "$HOME/.$tool" ]]; then
            TOOLS+=("$tool")
        fi
    done
fi

info "Tools: ${TOOLS[*]}"

# ── Plugin detection ─────────────────────────────────────────────────────────

if [[ "$PLUGINS_FLAG_SET" == true ]]; then
    if [[ -z "$PLUGINS_OVERRIDE" ]]; then
        PLUGINS=()  # --plugins= with empty value means no plugins
    else
        if [ -n "${BASH_VERSION:-}" ]; then
            IFS=',' read -ra PLUGINS <<< "$PLUGINS_OVERRIDE"
        else
            IFS=',' read -rA PLUGINS <<< "$PLUGINS_OVERRIDE"
        fi
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

# Normalize PLUGINS: deduplicate and sort for deterministic alphabetical collision resolution
if [[ ${#PLUGINS[@]} -gt 0 ]]; then
    if [ -n "${BASH_VERSION:-}" ]; then
        readarray -t PLUGINS < <(printf '%s\n' "${PLUGINS[@]}" | sort -u)
    else
        PLUGINS=($(printf '%s\n' "${PLUGINS[@]}" | sort -u))
    fi
fi

info "Plugins: ${PLUGINS[*]:-none}"

# ── Per-tool counters ─────────────────────────────────────────────────────

declare -A tool_installed tool_updated tool_skipped tool_merged tool_backed_up
for tool in "${ALL_TOOLS[@]}" "${ALL_PLUGINS[@]}"; do
    tool_installed[$tool]=0
    tool_updated[$tool]=0
    tool_skipped[$tool]=0
    tool_merged[$tool]=0
    tool_backed_up[$tool]=0
done

# Current tool being processed (used by utility functions)
CURRENT_TOOL=""

# ── Utility: back up a file with timestamp ────────────────────────────────

backup() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local timestamp
        timestamp="$(date +%Y%m%d-%H%M%S)"
        local backup_file="${file}.backup-${timestamp}"
        cp "$file" "$backup_file"
        info "Backed up $(basename "$file") -> $(basename "$backup_file")"
        (( tool_backed_up[$CURRENT_TOOL]++ )) || true
    fi
}

# ── Utility: check if a plugin is in the active PLUGINS array ─────────────────

plugin_enabled() {
    local name="$1"
    for p in "${PLUGINS[@]}"; do
        [[ "$p" == "$name" ]] && return 0
    done
    return 1
}

# ── Utility: compute a recursive hash for a directory or file ─────────────

# Returns a single SHA-256 representing all file contents under a path.
# Files are sorted by relative path for deterministic ordering.
compute_hash() {
    local target="$1"
    if [[ -f "$target" ]]; then
        shasum -a 256 "$target" | cut -d' ' -f1
    elif [[ -d "$target" ]]; then
        (cd "$target" && find . -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -d' ' -f1)
    else
        echo "none"
    fi
}

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
            warn "TOML collision: $(basename "$incoming") — later plugin overwrites earlier (alphabetical order)"
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

# ── Utility: stage all items from one source subdir into a staging subdir ─────

stage_content_from_dir() {
    local src_parent="$1"   # parent containing the named subdir
    local staging_parent="$2"  # staging parent to copy into
    local dir_name="$3"        # subdir name: skills, rules, commands, agents

    local src_dir="$src_parent/$dir_name"
    local staging_dir="$staging_parent/$dir_name"

    [[ -d "$src_dir" ]] || return 0

    mkdir -p "$staging_dir"

    local item_name file_type
    for item in "$src_dir"/*; do
        [[ -e "$item" ]] || continue
        item_name="$(basename "$item")"
        file_type="$(classify_file "$item" "$dir_name")"
        stage_item "$item" "$staging_dir/$item_name" "$file_type"
    done
}

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
    info "Phase 2: Shared skills and agents"
    stage_content_from_dir "$SRC_SHARED" "$staging" "skills"
    stage_content_from_dir "$SRC_SHARED" "$staging" "agents"

    # Note: $SRC_SHARED/*.json.template (shared settings) are intentionally not staged here.
    # Shared settings are not used today; tool-specific settings are handled in Phase 5.

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
    local file_type
    if [[ -d "$src_tool" ]]; then
        for settings_file in "$src_tool"/*.json.template "$src_tool"/*.toml.template; do
            [[ -f "$settings_file" ]] || continue
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

# ── Install beads formulas via staging ───────────────────────────────────────

stage_and_install_beads() {
    local dest_formulas="$HOME/.beads/formulas"
    local staging_formulas="$STAGING_DIR/.beads/formulas"

    header "beads formulas"
    CURRENT_TOOL="beads"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_formulas"
    mkdir -p "$staging_formulas"

    # Stage formulas from all active plugins with a .beads/formulas/ subdir
    local plugin_formulas formula_name
    for plugin in "${PLUGINS[@]}"; do
        plugin_formulas="$SRC_PLUGINS/$plugin/.beads/formulas"
        [[ -d "$plugin_formulas" ]] || continue

        for formula in "$plugin_formulas"/*.toml; do
            [[ -f "$formula" ]] || continue
            formula_name="$(basename "$formula")"
            stage_item "$formula" "$staging_formulas/$formula_name" "toml"
        done
    done

    # Sync staged formulas → ~/.beads/formulas/
    local found_any=false
    local name dest_file src_hash dst_hash
    for formula in "$staging_formulas"/*.toml; do
        [[ -f "$formula" ]] || continue
        found_any=true
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
    local extra_name
    for dest_file in "$dest_formulas"/*.toml; do
        [[ -f "$dest_file" ]] || continue
        extra_name="$(basename "$dest_file")"
        if [[ ! -f "$staging_formulas/$extra_name" ]]; then
            warn "formulas/$extra_name exists in ~/.beads/formulas but not in plugin source (keeping)"
        fi
    done
}

# ── Sync templates from a source dir into a dest dir ──────────────────────
#
# Handles *.md.template files: strip .template suffix, confirm-on-diff.
# JSON and TOML templates are handled separately in the settings phase.

sync_templates() {
    local src_dir="$1"
    local dest_dir="$2"
    local label="$3"    # e.g. "shared" or "claude-specific"
    local found=false
    local basename_template target_name dest_file src_hash dst_hash

    for template in "$src_dir"/*.md.template; do
        [[ -f "$template" ]] || continue
        found=true
        basename_template="$(basename "$template")"
        # Strip .template suffix -> target filename
        target_name="${basename_template%.template}"
        dest_file="$dest_dir/$target_name"

        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                ok "Would install $target_name (new, $label)"
            else
                cp "$template" "$dest_file"
                ok "Installed $target_name (new, $label)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            src_hash="$(compute_hash "$template")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                ok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                info "$target_name differs from installed version:"
                diff --color=auto -u "$dest_file" "$template" || true
                echo
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would update $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Overwrite $dest_file with $label version?"; then
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    ok "Updated $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    done

    if [[ "$found" == false ]]; then
        info "No .md.template files in $label source"
    fi
}

# ── Sync a subdirectory (agents/, skills/, commands/) ─────────────────────
#
# Hash-compare each top-level item, confirm on diff. Warns about items in
# dest that aren't in source.

sync_directory() {
    local dir_name="$1"
    local src_base="$2"   # parent of the dir_name (e.g. SRC_SHARED or SRC_TOOL)
    local dest_base="$3"  # dest tool dir (e.g. ~/.claude)
    local label="$4"      # e.g. "shared" or "claude-specific"
    local src_parent="$src_base/$dir_name"
    local dest_parent="$dest_base/$dir_name"
    local item_name dest_item src_hash dest_hash

    if [[ ! -d "$src_parent" ]]; then
        return
    fi

    header "Syncing $dir_name/ ($label)"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_parent"

    # Sync each item (subdirectory or file) from source
    for item in "$src_parent"/*; do
        [[ -e "$item" ]] || continue
        item_name="$(basename "$item")"
        dest_item="$dest_parent/$item_name"

        src_hash="$(compute_hash "$item")"

        if [[ ! -e "$dest_item" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                ok "Would install $dir_name/$item_name (new)"
            else
                cp -R "$item" "$dest_item"
                ok "Installed $dir_name/$item_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            dest_hash="$(compute_hash "$dest_item")"

            if [[ "$src_hash" == "$dest_hash" ]]; then
                ok "$dir_name/$item_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                warn "$dir_name/$item_name has changed"
                if [[ -d "$item" ]]; then
                    diff -rq "$dest_item" "$item" 2>/dev/null || true
                else
                    diff --color=auto -u "$dest_item" "$item" || true
                fi
                echo
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would update $dir_name/$item_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Replace $dir_name/$item_name? (removes existing, copies fresh)"; then
                    rm -rf "$dest_item"
                    cp -R "$item" "$dest_item"
                    ok "Updated $dir_name/$item_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $dir_name/$item_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    done

    # Warn about items in dest that aren't in source
    for dest_item in "$dest_parent"/*; do
        [[ -e "$dest_item" ]] || continue
        item_name="$(basename "$dest_item")"
        if [[ ! -e "$src_parent/$item_name" ]]; then
            warn "$dir_name/$item_name exists in ~/.$CURRENT_TOOL but not in $label source (keeping)"
        fi
    done
}

# ── Merge or copy a settings file ─────────────────────────────────────────
#
# For .json.template: union-merge using jq (user values preserved, template
# adds new keys; arrays deduplicated).
# For .toml.template: plain copy (TOML merge is out of scope).

sync_settings_file() {
    local template="$1"
    local dest_dir="$2"
    local label="$3"

    local basename_template
    basename_template="$(basename "$template")"
    local target_name="${basename_template%.template}"
    local dest_file="$dest_dir/$target_name"

    if [[ "$basename_template" == *.json.template ]]; then
        # JSON union-merge
        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                ok "Would install $target_name (new)"
            else
                cp "$template" "$dest_file"
                ok "Installed $target_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            # Validate existing JSON before merging
            if ! jq empty "$dest_file" 2>/dev/null; then
                err "$dest_file contains invalid JSON. Fix it manually or remove it."
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
                return
            fi

            # Union merge using jq:
            # - Objects: deep merge (user values preserved, template adds new keys)
            # - Arrays: union (deduplicated)
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
            ' "$dest_file" "$template")"

            # Check if merge actually changed anything
            local current proposed
            current="$(jq -S . "$dest_file")"
            proposed="$(printf '%s\n' "$merged_json" | jq -S .)"

            if [[ "$current" == "$proposed" ]]; then
                ok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                info "Proposed $target_name changes:"
                diff --color=auto -u <(printf '%s\n' "$current") <(printf '%s\n' "$proposed") || true
                echo
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would merge $target_name [$label]"
                    (( tool_merged[$CURRENT_TOOL]++ )) || true
                elif confirm "Apply merged $target_name?"; then
                    backup "$dest_file"
                    local tmp
                    tmp="$(mktemp)"
                    printf '%s\n' "$merged_json" | jq . > "$tmp"
                    mv "$tmp" "$dest_file"
                    ok "Merged $target_name [$label]"
                    (( tool_merged[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name merge [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi

    elif [[ "$basename_template" == *.toml.template ]]; then
        # TOML: plain copy (merge is out of scope)
        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                ok "Would install $target_name (new)"
            else
                cp "$template" "$dest_file"
                ok "Installed $target_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            local src_hash dst_hash
            src_hash="$(compute_hash "$template")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                ok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                info "$target_name differs from installed version:"
                diff --color=auto -u "$dest_file" "$template" || true
                echo
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would update $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Overwrite $dest_file with template version?"; then
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    ok "Updated $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    fi
}

# ── Staging directory (cleaned up on exit) ────────────────────────────────────

STAGING_DIR="$(mktemp -d /tmp/agents-config-install-XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT

# ── Main loop ─────────────────────────────────────────────────────────────

for tool in "${TOOLS[@]}"; do
    stage_and_install_tool "$tool"
done

if plugin_enabled "beads"; then
    stage_and_install_beads
fi

# ── Summary ──────────────────────────────────────────────────────────────

header "Summary"

for tool in "${TOOLS[@]}" "${PLUGINS[@]}"; do
    printf "\n${BOLD}-- %s --${RESET}\n" "$tool"
    printf "  Installed:  %s\n" "${tool_installed[$tool]}"
    printf "  Updated:    %s\n" "${tool_updated[$tool]}"
    printf "  Merged:     %s\n" "${tool_merged[$tool]}"
    printf "  Backed up:  %s\n" "${tool_backed_up[$tool]}"
    printf "  Skipped:    %s\n" "${tool_skipped[$tool]}"
done

# Show tools that were in ALL_TOOLS but not in TOOLS (auto-detect skipped)
for tool in "${ALL_TOOLS[@]}"; do
    in_tools=false
    for t in "${TOOLS[@]}"; do
        if [[ "$t" == "$tool" ]]; then
            in_tools=true
            break
        fi
    done
    if [[ "$in_tools" == false ]]; then
        printf "\n${DIM}-- %s (not detected, skipped) --${RESET}\n" "$tool"
    fi
done

# Show plugins that were in ALL_PLUGINS but not in PLUGINS (auto-detect skipped)
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

echo ""
ok "Done."
