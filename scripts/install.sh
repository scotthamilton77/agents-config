#!/bin/sh
# Re-exec with bash or zsh if running under a basic POSIX shell
if [ -z "${BASH_VERSION:-}" ] && [ -z "${ZSH_VERSION:-}" ]; then
    if command -v bash >/dev/null 2>&1; then
        exec bash "$0" "$@"
    elif command -v zsh >/dev/null 2>&1; then
        exec zsh "$0" "$@"
    else
        echo "Error: bash or zsh is required but neither was found." >&2
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
#
# Source layout:
#   src/user/.agents/          Shared content (agents, skills, templates)
#   src/user/.claude/          Claude-specific overrides & extensions
#   src/user/.codex/           Codex-specific overrides & extensions
#   src/user/.gemini/          Gemini-specific overrides & extensions
#
# Per-tool install phases (in order):
#   1. Shared templates   .agents/*.template → ~/.<tool>/
#   2. Shared skills      .agents/skills/    → ~/.<tool>/skills/
#   3. Shared agents      .agents/agents/    → ~/.<tool>/agents/
#   4. Tool templates     .<tool>/*.template → ~/.<tool>/
#   5. Tool subdirs       .<tool>/{commands,skills,agents}/ → ~/.<tool>/
#   6. Settings merge     *.json.template → union-merge; *.toml.template → copy
#
# Flags:
#   --dry-run            Show what would be done without making changes
#   --yes, -y            Auto-accept all prompts
#   --tools=claude,...   Comma-separated list of tools (default: auto-detect)
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

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN=true ;;
        --yes|-y)      AUTO_YES=true ;;
        --tools=*)     TOOLS_OVERRIDE="${arg#--tools=}" ;;
        --help|-h)
            echo "Usage: install.sh [--dry-run] [--yes|-y] [--tools=TOOLS] [--help|-h]"
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

# ── Per-tool counters ─────────────────────────────────────────────────────

declare -A tool_installed tool_updated tool_skipped tool_merged tool_backed_up
for tool in "${ALL_TOOLS[@]}"; do
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

# ── Install everything for one tool ───────────────────────────────────────

install_tool() {
    local tool="$1"
    local dest_dir="$HOME/.$tool"
    local src_tool="$SRC_USER/.$tool"

    CURRENT_TOOL="$tool"

    header "$tool"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_dir"

    # Phase 1: Shared templates (.agents/*.md.template -> ~/.<tool>/)
    info "Phase 1: Shared templates"
    sync_templates "$SRC_SHARED" "$dest_dir" "shared"

    # Phase 2: Shared skills (.agents/skills/ -> ~/.<tool>/skills/)
    sync_directory "skills" "$SRC_SHARED" "$dest_dir" "shared"

    # Phase 3: Shared agents (.agents/agents/ -> ~/.<tool>/agents/)
    sync_directory "agents" "$SRC_SHARED" "$dest_dir" "shared"

    # Phase 4: Tool-specific templates (.<tool>/*.md.template -> ~/.<tool>/)
    if [[ -d "$src_tool" ]]; then
        info "Phase 4: Tool-specific templates"
        sync_templates "$src_tool" "$dest_dir" "$tool-specific"
    fi

    # Phase 5: Tool-specific subdirs (commands/, skills/, agents/)
    if [[ -d "$src_tool" ]]; then
        for subdir in commands skills agents; do
            sync_directory "$subdir" "$src_tool" "$dest_dir" "$tool-specific"
        done
    fi

    # Phase 6: Settings merge (*.json.template and *.toml.template)
    local settings_found=false
    # Shared settings files
    for settings_file in "$SRC_SHARED"/*.json.template "$SRC_SHARED"/*.toml.template; do
        [[ -f "$settings_file" ]] || continue
        if [[ "$settings_found" == false ]]; then
            header "Settings ($tool)"
            settings_found=true
        fi
        sync_settings_file "$settings_file" "$dest_dir" "shared"
    done
    # Tool-specific settings files
    if [[ -d "$src_tool" ]]; then
        for settings_file in "$src_tool"/*.json.template "$src_tool"/*.toml.template; do
            [[ -f "$settings_file" ]] || continue
            if [[ "$settings_found" == false ]]; then
                header "Settings ($tool)"
                settings_found=true
            fi
            sync_settings_file "$settings_file" "$dest_dir" "$tool-specific"
        done
    fi
}

# ── Main loop ─────────────────────────────────────────────────────────────

for tool in "${TOOLS[@]}"; do
    install_tool "$tool"
done

# ── Summary ──────────────────────────────────────────────────────────────

header "Summary"

for tool in "${TOOLS[@]}"; do
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

echo ""
ok "Done."
