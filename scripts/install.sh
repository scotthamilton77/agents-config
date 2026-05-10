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

# Index base for array indexing in C-style for-loops. zsh arrays are 1-indexed
# by default; bash arrays are 0-indexed. Used by the parallel ORPHAN_* arrays
# (and any future indexed iteration).
if [ -n "${ZSH_VERSION:-}" ]; then
    _ARRAY_BASE=1
else
    _ARRAY_BASE=0
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
#                   staging/<beads>/scripts/   → ~/.beads/scripts/  (chmod +x on install)
#
# Flags:
#   --dry-run            Show what would be done without making changes
#   --yes, -y            Auto-accept all prompts
#   --verbose, -v        Show per-file progress (phases, up-to-date, installed)
#   --tools=claude,...   Comma-separated list of tools (default: auto-detect)
#   --plugins=beads,...  Comma-separated list of plugins (default: auto-detect)
#   --prune              After install, remove retired paths listed in scripts/prune-list (with backup) under
#                        ~/.<tool>/{commands,skills,agents,rules}/ (or
#                        ~/.config/<tool>/ for OpenCode) and ~/.beads/formulas/
#                        that are not in current staging
#   --prune-only         Skip Phase 7 (install) and only scan + remove retired paths listed in scripts/prune-list
#                        (mutually exclusive with --prune)
#   --help, -h           Show this help
#
# Output modes:
#   Default: only warnings, errors, diffs-needing-decision, and a terse summary.
#   --verbose: full per-file chatter (phases, "up to date", installed, etc.).
#   --yes (quiet): also suppresses diffs since no confirmation is needed.
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
VERBOSE=false
TOOLS_OVERRIDE=""
PLUGINS_OVERRIDE=""
PLUGINS_FLAG_SET=false
PRUNE=false
PRUNE_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --dry-run)     DRY_RUN=true ;;
        --yes|-y)      AUTO_YES=true ;;
        --verbose|-v)  VERBOSE=true ;;
        --tools=*)     TOOLS_OVERRIDE="${arg#--tools=}" ;;
        --plugins=*)   PLUGINS_OVERRIDE="${arg#--plugins=}"; PLUGINS_FLAG_SET=true ;;
        --prune)       PRUNE=true ;;
        --prune-only)  PRUNE_ONLY=true ;;
        --help|-h)
            echo "Usage: install.sh [--dry-run] [--yes|-y] [--verbose|-v] [--tools=TOOLS] [--plugins=PLUGINS] [--prune] [--prune-only] [--help|-h]"
            echo ""
            echo "Installs shared and tool-specific agent config into ~/.<tool>/ directories"
            echo "for Claude Code, OpenAI Codex CLI, Google Gemini CLI, and OpenCode."
            echo ""
            echo "Shared content (skills, agents, instructions, personas) from src/user/.agents/"
            echo "is installed into all detected tools. Tool-specific content from src/user/.<tool>/"
            echo "is installed only into that tool's directory."
            echo ""
            echo "Options:"
            echo "  --dry-run          Show what would be done without making changes"
            echo "  --yes, -y          Auto-accept all prompts (suppresses diffs in quiet mode)"
            echo "  --verbose, -v      Show per-file progress (phases, up-to-date, installed, diffs)"
            echo "  --tools=TOOLS      Comma-separated tools: claude,codex,gemini,opencode"
            echo "                     Default: auto-detect (claude always; others if ~/.<tool>/ exists;"
            echo "                     opencode also if ~/.config/opencode/ exists or opencode is on PATH)"
            echo "  --plugins=PLUGINS  Comma-separated plugins: beads"
            echo "                     Default: auto-detect (enabled if bd is on PATH or ~/.beads/ exists)"
            echo "  --prune            After install, remove retired paths listed in scripts/prune-list (with backup)"
            echo "  --prune-only       Skip install (Phase 7); scan + remove retired paths from scripts/prune-list (mutually exclusive with --prune)"
            echo "  --help, -h         Show this help"
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

if [[ "$PRUNE" == true && "$PRUNE_ONLY" == true ]]; then
    echo "Error: --prune and --prune-only are mutually exclusive." >&2
    exit 1
fi

# Diffs are shown in verbose mode, or when the user is about to be prompted for
# confirmation (they need to see the change to decide). Quiet + dry-run gives a
# summary preview only — use --verbose for per-file diffs.
SHOW_DIFFS=false
if [[ "$VERBOSE" == true ]]; then
    SHOW_DIFFS=true
elif [[ "$AUTO_YES" == false && "$DRY_RUN" == false ]]; then
    SHOW_DIFFS=true
fi

info()  { printf "${CYAN}i${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}+${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}!${RESET}  %s\n" "$*"; }
err()   { printf "${RED}x${RESET}  %s\n" "$*" >&2; }
header(){ printf "\n${BOLD}-- %s --${RESET}\n" "$*"; }

# Verbose-only variants: silent unless --verbose. Use these for per-file chatter
# (phase announcements, "up to date" confirmations, install/update progress).
vinfo()   { [[ "$VERBOSE" == true ]] && info   "$@"; return 0; }
vok()     { [[ "$VERBOSE" == true ]] && ok     "$@"; return 0; }
vheader() { [[ "$VERBOSE" == true ]] && header "$@"; return 0; }

# Ask y/n, default to No. Auto-accepts with --yes, warns in non-interactive mode.
confirm() {
    local prompt="$1"
    if [[ "$AUTO_YES" == true ]]; then
        vinfo "(auto-yes) $prompt"
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
elif [[ "$AUTO_YES" == true && "$VERBOSE" == false ]]; then
    info "Auto-yes mode -- prompts and diffs suppressed"
fi

# ── Utility: return 0 if $1 appears in the remaining arguments ────────────────
#
# Usage: in_list "needle" "${haystack[@]}"

in_list() {
    local needle="$1"
    shift
    local item
    for item in "$@"; do
        [[ "$item" == "$needle" ]] && return 0
    done
    return 1
}

# ── Utility: check if a plugin is in the active PLUGINS array ─────────────────

plugin_enabled() {
    in_list "$1" "${PLUGINS[@]}"
}

# True when --prune or --prune-only was passed (the two flags are mutually
# exclusive; "active" means the prune phase will run).
prune_active() {
    [[ "$PRUNE" == true || "$PRUNE_ONLY" == true ]]
}

# ── Utility: split a comma-separated string into a named array ────────────────
#
# Handles the bash (read -ra) vs zsh (read -rA) split. The target array name
# is passed as $2; the caller does not need to pre-declare it.

split_csv() {
    local csv="$1"
    local _arrname="$2"
    if [ -n "${BASH_VERSION:-}" ]; then
        IFS=',' read -ra "$_arrname" <<< "$csv"
    else
        IFS=',' read -rA "$_arrname" <<< "$csv"
    fi
}

# ── Utility: resolve destination directory for a tool ─────────────────────────
#
# OpenCode uses XDG config dir (~/.config/opencode/) instead of a dot-dir.

tool_dest_dir() {
    local tool="$1"
    if [[ "$tool" == "opencode" ]]; then
        echo "$HOME/.config/opencode"
    else
        echo "$HOME/.$tool"
    fi
}

# ── Tool detection ────────────────────────────────────────────────────────

ALL_TOOLS=(claude codex gemini opencode)
TOOLS=()
ALL_PLUGINS=(beads)
PLUGINS=()

if [[ -n "$TOOLS_OVERRIDE" ]]; then
    split_csv "$TOOLS_OVERRIDE" TOOLS
    for tool in "${TOOLS[@]}"; do
        if ! in_list "$tool" "${ALL_TOOLS[@]}"; then
            err "Unknown tool: $tool (valid: ${ALL_TOOLS[*]})"
            exit 1
        fi
    done
else
    # Auto-detect: always include claude, add others if their dir exists
    TOOLS=(claude)
    for tool in codex gemini; do
        [[ -d "$HOME/.$tool" ]] && TOOLS+=("$tool")
    done
    if command -v opencode &>/dev/null || [[ -d "$HOME/.config/opencode" ]]; then
        TOOLS+=(opencode)
    fi
fi

vinfo "Tools: ${TOOLS[*]}"

# ── Plugin detection ─────────────────────────────────────────────────────────

if [[ "$PLUGINS_FLAG_SET" == true ]]; then
    # --plugins= with empty value means "no plugins"
    [[ -n "$PLUGINS_OVERRIDE" ]] && split_csv "$PLUGINS_OVERRIDE" PLUGINS
    for plugin in "${PLUGINS[@]}"; do
        if ! in_list "$plugin" "${ALL_PLUGINS[@]}"; then
            err "Unknown plugin: $plugin (valid: ${ALL_PLUGINS[*]})"
            exit 1
        fi
    done
    # Warn about explicitly excluded plugins. Wording depends on whether prune is
    # active: under --prune/--prune-only the excluded plugin's previously-installed
    # files DO become orphans and may be removed (strict mode, AC#16).
    for plugin in "${ALL_PLUGINS[@]}"; do
        if ! in_list "$plugin" "${PLUGINS[@]}"; then
            if prune_active; then
                warn "Plugin '$plugin' excluded via --plugins= — under --prune, previously-installed files become orphans and may be removed."
            else
                warn "Plugin '$plugin' excluded via --plugins= — files already installed are not removed (use --prune or --prune-only to remove orphans under strict mode)."
            fi
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

vinfo "Plugins: ${PLUGINS[*]:-none}"

# ── Per-tool counters ─────────────────────────────────────────────────────

declare -A tool_installed tool_updated tool_skipped tool_merged tool_backed_up tool_pruned
for tool in "${ALL_TOOLS[@]}" "${ALL_PLUGINS[@]}"; do
    tool_installed[$tool]=0
    tool_updated[$tool]=0
    tool_skipped[$tool]=0
    tool_merged[$tool]=0
    tool_backed_up[$tool]=0
    tool_pruned[$tool]=0
done

# Current tool being processed (used by utility functions)
CURRENT_TOOL=""

# ── Utility: back up a file or directory with timestamp ────────────────────
#
# Path-aware: if the parent dir is one of the prune-managed namespaces
# {commands, skills, agents, rules, formulas}, route the backup into a
# sibling <namespace>-backup/ directory under the grandparent. Otherwise,
# fall back to in-place "<path>.backup-<timestamp>" alongside the original.
# Handles both files (cp) and directories (cp -R).

backup() {
    local target="$1"
    [[ -e "$target" ]] || return 0

    local timestamp parent grandparent base backup_dir backup_path
    timestamp="$(date +%Y%m%d-%H%M%S)"
    parent="$(basename "$(dirname "$target")")"
    base="$(basename "$target")"

    case "$parent" in
        commands|skills|agents|rules|formulas)
            grandparent="$(dirname "$(dirname "$target")")"
            backup_dir="$grandparent/${parent}-backup"
            backup_path="$backup_dir/${base}.backup-${timestamp}"
            mkdir -p "$backup_dir"
            ;;
        *)
            backup_path="${target}.backup-${timestamp}"
            ;;
    esac

    if [[ -d "$target" ]]; then
        cp -R "$target" "$backup_path"
    else
        cp "$target" "$backup_path"
    fi
    vinfo "Backed up $base -> $(basename "$(dirname "$backup_path")")/$(basename "$backup_path")"
    (( tool_backed_up[$CURRENT_TOOL]++ )) || true
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
        jsonc)
            warn "JSONC collision: $(basename "$incoming") — later plugin overwrites earlier (alphabetical order)"
            cp "$incoming" "$existing"
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
    elif [[ "$basename" == *.jsonc.template ]]; then
        echo "jsonc"
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

# ── Utility: flatten instruction templates (DYNAMIC-INCLUDE) ──────────────────
#
# Some tools (like OpenCode) do not support `@` include resolution, or we want
# a single flat file for distribution. This function reads a template
# containing <!-- DYNAMIC-INCLUDE: path --> and
# <!-- DYNAMIC-INCLUDE-RULES: rule1,... --> markers and produces a single
# flat file with all references inlined.
#
# marker paths are relative to project_root.

# ── Utility: transform Gemini agent frontmatter ────────────────────────────
#
# Gemini agent loader rejects Claude-specific keys (skills, color, memory)
# and requires `tools:` to be a YAML array.

transform_gemini_agent_frontmatter() {
    local file="$1"
    local tmp
    tmp="$(mktemp -t gemini-agent.XXXXXX)"

    # awk logic:
    # 1. track if we are inside the frontmatter (between first and second ---)
    # 2. inside frontmatter:
    #    - skip skills:, color:, memory: lines and their indented blocks
    #    - rewrite tools: "Read, Grep" -> tools: [Read, Grep]
    # 3. outside frontmatter: pass through
    awk '
        BEGIN { count=0; skipping=0 }
        /^---$/ { 
            count++; 
            skipping=0; 
            print; 
            next 
        }
        count == 1 {
            if (skipping) {
                if ($0 ~ /^[[:space:]]+/ || $0 ~ /^$/) { next }
                skipping = 0
            }

            # Strip Claude-only keys and their blocks
            if ($1 ~ /^(skills:|color:|memory:)$/) { 
                skipping = 1
                next 
            }

            # Transform tools: String -> [Array], but avoid block-style
            if ($0 ~ /^tools:[[:space:]]*/) {
                match($0, /^tools:[[:space:]]*/)
                val = substr($0, RSTART + RLENGTH)
                if (length(val) > 0 && val !~ /^\[/) {
                    printf "tools: [%s]\n", val
                    next
                }
            }
        }
        { print }
    ' "$file" > "$tmp"

    mv "$tmp" "$file"
}

flatten_agents_md() {
    local template="$1"
    local output="$2"
    local project_root="$3"

    local line marker_path rule_names rule_file first_rule rule_name

    while IFS= read -r line || [[ -n "$line" ]]; do
        # Extract path from <!-- DYNAMIC-INCLUDE: path --> using sed (portable bash/zsh)
        marker_path="$(printf '%s' "$line" | sed -n "s/^<!-- DYNAMIC-INCLUDE: \(.*\) -->$/\1/p")"
        if [[ -n "$marker_path" ]]; then
            if [[ -f "$project_root/$marker_path" ]]; then
                cat "$project_root/$marker_path" >> "$output"
            else
                warn "DYNAMIC-INCLUDE not found: $marker_path"
            fi
            continue
        fi

        # Extract rule list from <!-- DYNAMIC-INCLUDE-RULES: rule1,... --> using sed
        rule_names="$(printf '%s' "$line" | sed -n "s/^<!-- DYNAMIC-INCLUDE-RULES: \(.*\) -->$/\1/p")"
        if [[ -n "$rule_names" ]]; then
            first_rule=true
            # Use tr + while read for portable comma splitting (works in bash and zsh)
            while IFS= read -r rule_name; do
                rule_name="$(printf '%s' "$rule_name" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                [[ -n "$rule_name" ]] || continue
                rule_file="$project_root/src/user/.claude/rules/$rule_name.md"
                if [[ -f "$rule_file" ]]; then
                    if [[ "$first_rule" == true ]]; then
                        first_rule=false
                    else
                        printf '\n---\n' >> "$output"
                    fi
                    cat "$rule_file" >> "$output"
                else
                    warn "DYNAMIC-INCLUDE-RULES not found: $rule_name.md"
                fi
            done < <(printf '%s' "$rule_names" | tr ',' '\n')
            continue
        fi

        printf '%s\n' "$line" >> "$output"
    done < "$template"
}

# ── Install one tool via staging ──────────────────────────────────────────────

stage_and_install_tool() {
    local tool="$1"
    local dest_dir="$(tool_dest_dir "$tool")"
    local src_tool="$SRC_USER/.$tool"
    local staging="$STAGING_DIR/$tool"
    # Hoist all loop-internal locals to function scope — see commit 2fe276d:
    # zsh prints the variable's value when `local` is re-invoked in a loop.
    local file_type plugin_tool_dir plugin_agents_dir flattened
    local inc_path inc_base include_only_file
    local -a include_only_staged

    CURRENT_TOOL="$tool"
    vheader "$tool"

    # Skip dest_dir creation under --prune-only: Phase 7 is skipped, so creating
    # ~/.<tool>/ would leave behind an empty directory on systems that didn't
    # already have one. Staging dir is still required for scan_orphans.
    [[ "$DRY_RUN" != true && "$PRUNE_ONLY" != true ]] && mkdir -p "$dest_dir"
    mkdir -p "$staging"

    # ── Phase 1: Stage shared templates (.agents/*.md.template → staging/) ───
    vinfo "Phase 1: Shared templates"
    for template in "$SRC_SHARED"/*.md.template; do
        [[ -f "$template" ]] || continue
        stage_item "$template" "$staging/$(basename "$template")" "other"
    done

    # ── Phase 2: Stage shared skills and agents ───────────────────────────────
    vinfo "Phase 2: Shared skills and agents"
    stage_content_from_dir "$SRC_SHARED" "$staging" "skills"
    # OpenCode: skip shared agents (frontmatter format differs)
    if [[ "$tool" != "opencode" ]]; then
        stage_content_from_dir "$SRC_SHARED" "$staging" "agents"
    fi

    # Note: $SRC_SHARED/*.json.template (shared settings) are intentionally not staged here.
    # Shared settings are not used today; tool-specific settings are handled in Phase 5.

    # ── Phases 3-5: Stage tool-specific content (templates, subdirs, settings) ─
    if [[ -d "$src_tool" ]]; then
        vinfo "Phase 3: Tool-specific templates"
        for template in "$src_tool"/*.md.template; do
            [[ -f "$template" ]] || continue
            stage_item "$template" "$staging/$(basename "$template")" "other"
        done

        for subdir in commands skills agents rules; do
            stage_content_from_dir "$src_tool" "$staging" "$subdir"
        done

        for settings_file in "$src_tool"/*.json.template "$src_tool"/*.jsonc.template "$src_tool"/*.toml.template; do
            [[ -f "$settings_file" ]] || continue
            file_type="$(classify_file "$settings_file" "")"
            stage_item "$settings_file" "$staging/$(basename "$settings_file")" "$file_type"
        done
    fi

    # ── Phase 6: Overlay active plugins (alphabetical order) ─────────────────
    for plugin in "${PLUGINS[@]}"; do
        plugin_tool_dir="$SRC_PLUGINS/$plugin/.$tool"
        plugin_agents_dir="$SRC_PLUGINS/$plugin/.agents"

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

    # ── Phase 6.5 + 6.75: Flatten and remove include-only templates ─────────
    # Collect DYNAMIC-INCLUDE targets BEFORE flattening — the markers are
    # consumed (replaced with file content) by flatten_agents_md, so they must
    # be read from the pre-flattened staging copy.
    include_only_staged=()
    for template in "$staging/AGENTS.md.template" "$staging/GEMINI.md.template"; do
        [[ -f "$template" ]] || continue
        while IFS= read -r inc_path; do
            inc_base="$(basename "$inc_path")"
            include_only_staged+=("$staging/$inc_base")
        done < <(sed -n 's/^<!-- DYNAMIC-INCLUDE: \(.*\) -->$/\1/p' "$template")

        vinfo "Phase 6.5: Flattening $(basename "$template") for $tool"
        flattened="$(mktemp "$STAGING_DIR/flatten.XXXXXXXX")"
        flatten_agents_md "$template" "$flattened" "$PROJECT_ROOT"
        mv "$flattened" "$template"
    done

    # Phase 6.75: Remove include-only templates from staging.
    # Their content is already inlined into AGENTS.md; keeping the staged copies
    # would cause sync_templates to also install them as spurious standalone files.
    if [[ ${#include_only_staged[@]} -gt 0 ]]; then
        vinfo "Phase 6.75: Removing include-only templates from staging"
        for include_only_file in "${include_only_staged[@]}"; do
            if [[ -f "$include_only_file" ]]; then
                vinfo "  $(basename "$include_only_file") — inlined via DYNAMIC-INCLUDE, not installed standalone"
                rm "$include_only_file"
            fi
        done
    fi

    # ── Phase 6.6: Gemini agent frontmatter transformation ──────────────────
    if [[ "$tool" == "gemini" && -d "$staging/agents" ]]; then
        vinfo "Phase 6.6: Transforming agent frontmatter for Gemini"
        for agent_file in "$staging/agents"/*.md; do
            [[ -f "$agent_file" ]] || continue
            transform_gemini_agent_frontmatter "$agent_file"
        done
    fi

    # ── Phase 7: Sync staging → ~/.<tool>/ (reusing existing sync functions) ──
    # Skipped under --prune-only: staging tree (Phases 1-6) is still built so
    # scan_orphans has a comparison baseline, but no files are written to ~/.
    if [[ "$PRUNE_ONLY" == true ]]; then
        vinfo "Phase 7: skipped (--prune-only)"
        return 0
    fi

    vinfo "Phase 7: Sync to $dest_dir"

    # Sync templates: staging has *.md.template; sync_templates strips the suffix
    sync_templates "$staging" "$dest_dir" "staged"

    # Sync subdirectories
    for subdir in rules commands skills agents; do
        # OpenCode: skip agents (frontmatter format differs; see OPENCODE-EXTENSIONS.md)
        if [[ "$tool" == "opencode" && "$subdir" == "agents" ]]; then
            continue
        fi
        [[ -d "$staging/$subdir" ]] || continue
        sync_directory "$subdir" "$staging" "$dest_dir" "staged"
    done

    # Sync settings files (union-merges staged template with installed settings)
    for settings_file in "$staging"/*.json.template "$staging"/*.jsonc.template "$staging"/*.toml.template; do
        [[ -f "$settings_file" ]] || continue
        sync_settings_file "$settings_file" "$dest_dir" "staged"
    done
}

# ── Install beads formulas via staging ───────────────────────────────────────

stage_and_install_beads() {
    local dest_formulas="$HOME/.beads/formulas"
    local staging_formulas="$STAGING_DIR/.beads/formulas"

    vheader "beads formulas"
    CURRENT_TOOL="beads"

    # Only create ~/.beads/formulas/ when beads is an active plugin AND we're
    # actually going to install (not --prune-only). Without these gates, a
    # --prune/--prune-only run with beads disabled or absent would silently
    # create a brand-new ~/.beads/formulas tree on machines that never had
    # beads installed. Staging dir is still required for scan_orphans.
    if [[ "$DRY_RUN" != true && "$PRUNE_ONLY" != true ]] && plugin_enabled "beads"; then
        mkdir -p "$dest_formulas"
    fi
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

    # Skip the actual install when running --prune-only; staging is preserved
    # for scan_orphans to compare against.
    if [[ "$PRUNE_ONLY" == true ]]; then
        vinfo "beads sync: skipped (--prune-only)"
        return 0
    fi

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
                vok "Would install formulas/$name (new)"
            else
                cp "$formula" "$dest_file"
                vok "Installed formulas/$name (new)"
            fi
            (( tool_installed[beads]++ )) || true
        else
            src_hash="$(compute_hash "$formula")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                vok "formulas/$name is up to date"
                (( tool_skipped[beads]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "formulas/$name differs:"
                    diff --color=auto -u "$dest_file" "$formula" || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update formulas/$name"
                    (( tool_updated[beads]++ )) || true
                elif confirm "Overwrite ~/.beads/formulas/$name?"; then
                    backup "$dest_file"
                    cp "$formula" "$dest_file"
                    vok "Updated formulas/$name"
                    (( tool_updated[beads]++ )) || true
                else
                    warn "Skipped formulas/$name"
                    (( tool_skipped[beads]++ )) || true
                fi
            fi
        fi
    done

    [[ "$found_any" == false ]] && vinfo "No formula files staged"

    # Warn about formulas in dest that aren't in staged source
    # (suppressed when --prune/--prune-only is active — prune phase will report and act on these)
    if ! prune_active; then
        local extra_name
        for dest_file in "$dest_formulas"/*.toml; do
            [[ -f "$dest_file" ]] || continue
            extra_name="$(basename "$dest_file")"
            if [[ ! -f "$staging_formulas/$extra_name" ]]; then
                warn "formulas/$extra_name exists in ~/.beads/formulas but not in plugin source (keeping)"
            fi
        done
    fi

    # ── Sync beads scripts → ~/.beads/scripts/ ───────────────────────────────
    # Scripts are installed with chmod +x. Not tracked by --prune (scripts are
    # rare and hand-managed; add _scan_namespace call here if that changes).
    local dest_scripts staging_scripts plugin_scripts_dir found_any_script
    local script_name dest_script script_src_hash script_dst_hash
    dest_scripts="$HOME/.beads/scripts"
    staging_scripts="$STAGING_DIR/.beads/scripts"

    for plugin in "${PLUGINS[@]}"; do
        plugin_scripts_dir="$SRC_PLUGINS/$plugin/.beads/scripts"
        [[ -d "$plugin_scripts_dir" ]] || continue
        mkdir -p "$staging_scripts"
        for script in "$plugin_scripts_dir"/*.sh; do
            [[ -f "$script" ]] || continue
            script_name="$(basename "$script")"
            stage_item "$script" "$staging_scripts/$script_name" "other"
        done
    done

    if [[ ! -d "$staging_scripts" ]]; then
        vinfo "No beads scripts staged"
        return 0
    fi

    if [[ "$DRY_RUN" != true && "$PRUNE_ONLY" != true ]] && plugin_enabled "beads"; then
        mkdir -p "$dest_scripts"
    fi

    found_any_script=false
    for script in "$staging_scripts"/*.sh; do
        [[ -f "$script" ]] || continue
        found_any_script=true
        script_name="$(basename "$script")"
        dest_script="$dest_scripts/$script_name"

        if [[ ! -f "$dest_script" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                vok "Would install scripts/$script_name (new)"
            else
                cp "$script" "$dest_script"
                chmod +x "$dest_script"
                vok "Installed scripts/$script_name (new)"
            fi
            (( tool_installed[beads]++ )) || true
        else
            script_src_hash="$(compute_hash "$script")"
            script_dst_hash="$(compute_hash "$dest_script")"

            if [[ "$script_src_hash" == "$script_dst_hash" ]]; then
                # Content matches but exec bit may have been lost — restore it without a full copy.
                [[ "$DRY_RUN" == true ]] || { [[ -x "$dest_script" ]] || { chmod +x "$dest_script"; vinfo "Restored +x on scripts/$script_name"; }; }
                vok "scripts/$script_name is up to date"
                (( tool_skipped[beads]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "scripts/$script_name differs:"
                    diff --color=auto -u "$dest_script" "$script" || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update scripts/$script_name"
                    (( tool_updated[beads]++ )) || true
                elif confirm "Overwrite ~/.beads/scripts/$script_name?"; then
                    backup "$dest_script"
                    cp "$script" "$dest_script"
                    chmod +x "$dest_script"
                    vok "Updated scripts/$script_name"
                    (( tool_updated[beads]++ )) || true
                else
                    warn "Skipped scripts/$script_name"
                    (( tool_skipped[beads]++ )) || true
                fi
            fi
        fi
    done

    if [[ "$found_any_script" == false ]]; then
        vinfo "No script files staged"
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
                vok "Would install $target_name (new, $label)"
            else
                cp "$template" "$dest_file"
                vok "Installed $target_name (new, $label)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            src_hash="$(compute_hash "$template")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                vok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "$target_name differs from installed version:"
                    diff --color=auto -u "$dest_file" "$template" || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Overwrite $dest_file with $label version?"; then
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    vok "Updated $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    done

    if [[ "$found" == false ]]; then
        vinfo "No .md.template files in $label source"
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

    vheader "Syncing $dir_name/ ($label)"

    [[ "$DRY_RUN" != true ]] && mkdir -p "$dest_parent"

    # Sync each item (subdirectory or file) from source
    for item in "$src_parent"/*; do
        [[ -e "$item" ]] || continue
        item_name="$(basename "$item")"
        dest_item="$dest_parent/$item_name"

        src_hash="$(compute_hash "$item")"

        if [[ ! -e "$dest_item" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                vok "Would install $dir_name/$item_name (new)"
            else
                cp -R "$item" "$dest_item"
                vok "Installed $dir_name/$item_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            dest_hash="$(compute_hash "$dest_item")"

            if [[ "$src_hash" == "$dest_hash" ]]; then
                vok "$dir_name/$item_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    warn "$dir_name/$item_name has changed"
                    if [[ -d "$item" ]]; then
                        diff -rq "$dest_item" "$item" 2>/dev/null || true
                    else
                        diff --color=auto -u "$dest_item" "$item" || true
                    fi
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update $dir_name/$item_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Replace $dir_name/$item_name? (removes existing, copies fresh)"; then
                    rm -rf "$dest_item"
                    cp -R "$item" "$dest_item"
                    vok "Updated $dir_name/$item_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $dir_name/$item_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    done

    # Warn about items in dest that aren't in source
    # (suppressed when --prune/--prune-only is active — prune phase will report and act on these)
    if ! prune_active; then
        for dest_item in "$dest_parent"/*; do
            [[ -e "$dest_item" ]] || continue
            item_name="$(basename "$dest_item")"
            if [[ ! -e "$src_parent/$item_name" ]]; then
                warn "$dir_name/$item_name exists in $(tool_dest_dir "$CURRENT_TOOL") but not in $label source (keeping)"
            fi
        done
    fi
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
                vok "Would install $target_name (new)"
            else
                cp "$template" "$dest_file"
                vok "Installed $target_name (new)"
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
                vok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "Proposed $target_name changes:"
                    diff --color=auto -u <(printf '%s\n' "$current") <(printf '%s\n' "$proposed") || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would merge $target_name [$label]"
                    (( tool_merged[$CURRENT_TOOL]++ )) || true
                elif confirm "Apply merged $target_name?"; then
                    backup "$dest_file"
                    local tmp
                    tmp="$(mktemp -t gemini-settings.XXXXXX)"
                    printf '%s\n' "$merged_json" | jq . > "$tmp"
                    mv "$tmp" "$dest_file"
                    vok "Merged $target_name [$label]"
                    (( tool_merged[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name merge [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi

    elif [[ "$basename_template" == *.jsonc.template ]]; then
        # JSONC: plain copy (jq cannot parse JSONC comments; merge is out of scope)
        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                vok "Would install $target_name (new)"
            else
                cp "$template" "$dest_file"
                vok "Installed $target_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            local src_hash dst_hash
            src_hash="$(compute_hash "$template")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                vok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "$target_name differs from installed version:"
                    diff --color=auto -u "$dest_file" "$template" || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Overwrite $dest_file with template version?"; then
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    vok "Updated $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    elif [[ "$basename_template" == *.toml.template ]]; then
        # TOML: plain copy (merge is out of scope)
        if [[ ! -f "$dest_file" ]]; then
            if [[ "$DRY_RUN" == true ]]; then
                vok "Would install $target_name (new)"
            else
                cp "$template" "$dest_file"
                vok "Installed $target_name (new)"
            fi
            (( tool_installed[$CURRENT_TOOL]++ )) || true
        else
            local src_hash dst_hash
            src_hash="$(compute_hash "$template")"
            dst_hash="$(compute_hash "$dest_file")"

            if [[ "$src_hash" == "$dst_hash" ]]; then
                vok "$target_name is up to date"
                (( tool_skipped[$CURRENT_TOOL]++ )) || true
            else
                if [[ "$SHOW_DIFFS" == true ]]; then
                    info "$target_name differs from installed version:"
                    diff --color=auto -u "$dest_file" "$template" || true
                    echo
                fi
                if [[ "$DRY_RUN" == true ]]; then
                    vok "Would update $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                elif confirm "Overwrite $dest_file with template version?"; then
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    vok "Updated $target_name [$label]"
                    (( tool_updated[$CURRENT_TOOL]++ )) || true
                else
                    warn "Skipped $target_name [$label]"
                    (( tool_skipped[$CURRENT_TOOL]++ )) || true
                fi
            fi
        fi
    fi
}

# ── Orphan scanning and pruning ───────────────────────────────────────────────
#
# An orphan is a top-level entry directly inside ~/.<tool>/{commands,skills,
# agents,rules}/ or ~/.beads/formulas/ that does NOT exist in the current run's
# staging tree. Item granularity is the top-level entry — we don't recurse into
# nested skill directories. Legacy in-place backup files matching *.backup-*
# (produced by older versions of backup() before the namespace refactor) are
# skipped so they aren't treated as orphans. Sibling <namespace>-backup/ dirs
# (the new layout) live at the GRANDPARENT level alongside the namespace, so
# they are never visited by this scan in the first place. Anything outside
# these scoped subdirs (top-level *.md, settings.json, hooks/, etc.) is never
# pruned.

# Parallel arrays — indexed orphan records. Pipe-delimited single-array storage
# was unsafe because filenames are user-controlled and may contain `|` or
# newlines, which would misparse via `IFS='|' read` and could end up
# backing up / deleting the wrong target. Four arrays, indexed in lockstep:
#   ORPHAN_TOOLS[i]  — tool bucket (e.g. "claude", "beads")
#   ORPHAN_NS[i]     — namespace label (e.g. "commands", "formulas")
#   ORPHAN_PATHS[i]  — absolute path to the orphan
#   ORPHAN_KINDS[i]  — "dir" or "file"
ORPHAN_TOOLS=()
ORPHAN_NS=()
ORPHAN_PATHS=()
ORPHAN_KINDS=()

PRUNE_LIST=()

_load_prune_list() {
    local list_file
    list_file="$SCRIPT_DIR/prune-list"
    [[ -f "$list_file" ]] || return 0
    local line
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line#"${line%%[! ]*}"}"
        line="${line%"${line##*[! ]}"}"
        [[ -n "$line" ]] && PRUNE_LIST+=("$line")
    done < "$list_file"
}
_load_prune_list

_in_prune_list() {
    local tool="$1" ns="$2" base="$3" key entry
    key="$tool/$ns/$base"
    for entry in "${PRUNE_LIST[@]}"; do
        # shellcheck disable=SC2254
        case "$key" in ($entry) return 0;; esac
    done
    return 1
}

# Append orphans found in a single dest namespace to the parallel ORPHAN_*
# arrays, tagged with the given tool/namespace labels. Skips legacy *.backup-*
# entries (in-place backups from older backup() implementations); classifies as
# dir/file.
_scan_namespace() {
    local tool="$1" ns_label="$2" dest="$3" staging="$4"
    [[ -d "$dest" ]] || return 0
    local entry base kind
    for entry in "$dest"/*; do
        [[ -e "$entry" ]] || continue
        base="$(basename "$entry")"
        [[ "$base" == *.backup-* ]] && continue
        [[ -e "$staging/$base" ]] && continue
        _in_prune_list "$tool" "$ns_label" "$base" || continue
        if [[ -d "$entry" ]]; then kind="dir"; else kind="file"; fi
        ORPHAN_TOOLS+=("$tool")
        ORPHAN_NS+=("$ns_label")
        ORPHAN_PATHS+=("$entry")
        ORPHAN_KINDS+=("$kind")
    done
}

scan_orphans() {
    ORPHAN_TOOLS=()
    ORPHAN_NS=()
    ORPHAN_PATHS=()
    ORPHAN_KINDS=()
    local tool sub
    local prune_subdirs=(commands skills agents rules)
    local dest_tool staged_tool dest_md md_name

    for tool in "${TOOLS[@]}"; do
        for sub in "${prune_subdirs[@]}"; do
            _scan_namespace "$tool" "$sub" "$(tool_dest_dir "$tool")/$sub" "$STAGING_DIR/$tool/$sub"
        done
    done

    # ~/.beads/formulas/ — scanned whenever --prune/--prune-only runs,
    # regardless of beads plugin auto-detection. If beads isn't an active plugin
    # the staging dir is empty (or absent), so all dest formulas register as
    # orphans — consistent with strict mode (AC#19).
    _scan_namespace "beads" "formulas" "$HOME/.beads/formulas" "$STAGING_DIR/.beads/formulas"

    # Scan top-level .md files in each tool's dest dir.
    # An installed .md is an orphan if there is no matching .md.template in
    # staging — catches include-only templates that were previously installed as
    # spurious standalone files before Phase 6.75 was added.
    for tool in "${TOOLS[@]}"; do
        dest_tool="$(tool_dest_dir "$tool")"
        staged_tool="$STAGING_DIR/$tool"
        for dest_md in "$dest_tool"/*.md; do
            [[ -f "$dest_md" ]] || continue
            md_name="$(basename "$dest_md")"
            if [[ ! -f "$staged_tool/${md_name}.template" ]]; then
                ORPHAN_TOOLS+=("$tool")
                ORPHAN_NS+=("(top-level)")
                ORPHAN_PATHS+=("$dest_md")
                ORPHAN_KINDS+=("file")
            fi
        done
    done
}

# Display the orphan list grouped by tool, then namespace, with a summary count.
# Hoist all loop-internal locals to function scope — see commit 2fe276d:
# zsh prints the variable's value when `local` is re-invoked in a loop.
# Array indexing uses _ARRAY_BASE so the same C-style loop works under zsh
# (1-indexed) and bash (0-indexed).
_display_orphans() {
    # NOTE: variable named 'orphan_path', not 'path' — see _delete_orphan
    # comment about zsh's tied `path` ↔ `PATH` array.
    local last_tool="" last_ns="" tool ns orphan_path kind i n stop
    n=${#ORPHAN_PATHS[@]}
    stop=$(( n + _ARRAY_BASE ))
    header "Orphans detected (${n} total)"
    for (( i = _ARRAY_BASE; i < stop; i++ )); do
        tool="${ORPHAN_TOOLS[i]}"
        ns="${ORPHAN_NS[i]}"
        orphan_path="${ORPHAN_PATHS[i]}"
        kind="${ORPHAN_KINDS[i]}"
        if [[ "$tool" != "$last_tool" ]]; then
            printf "\n${BOLD}%s${RESET}\n" "$tool"
            last_tool="$tool"
            last_ns=""
        fi
        if [[ "$ns" != "$last_ns" ]]; then
            printf "  %s/\n" "$ns"
            last_ns="$ns"
        fi
        printf "    [%s] %s\n" "$kind" "$orphan_path"
    done
    echo ""
}

# Backup + delete one orphan, increment counter for its tool bucket.
# NOTE: do NOT name a local 'path' here — zsh ties the lowercase `path`
# array to PATH, so `local path=...` clobbers PATH for the function's
# scope and any callee (e.g. `date`, `rm`) becomes "command not found".
_delete_orphan() {
    local tool="$1" orphan_path="$2"
    local prev="$CURRENT_TOOL"
    CURRENT_TOOL="$tool"
    backup "$orphan_path"
    rm -rf "$orphan_path"
    (( tool_pruned[$tool]++ )) || true
    CURRENT_TOOL="$prev"
}

# Backup + delete every orphan, then report the count. Iterate by index across
# the parallel ORPHAN_* arrays (zsh/bash index-base safe via _ARRAY_BASE).
_delete_all_orphans() {
    local i n stop
    n=${#ORPHAN_PATHS[@]}
    stop=$(( n + _ARRAY_BASE ))
    for (( i = _ARRAY_BASE; i < stop; i++ )); do
        _delete_orphan "${ORPHAN_TOOLS[i]}" "${ORPHAN_PATHS[i]}"
    done
    ok "Pruned ${n} orphan(s)."
}

prune_orphans() {
    # Non-interactive guard runs FIRST — before the empty-orphan fast path —
    # so --prune-only without -y/--dry-run hard-fails regardless of orphan
    # count (intent unfulfilled: caller asked for action with no auth).
    # --dry-run and -y are themselves the auth, so they're exempt.
    if [[ ! -t 0 && "$DRY_RUN" != true && "$AUTO_YES" != true ]]; then
        if [[ "$PRUNE_ONLY" == true ]]; then
            err "prune-only requires --yes or --dry-run in non-interactive mode"
            exit 1
        else
            warn "prune phase requires confirmation, skipping"
            return 0
        fi
    fi

    if [[ ${#ORPHAN_PATHS[@]} -eq 0 ]]; then
        info "No orphans detected."
        return 0
    fi

    _display_orphans

    # Dry-run: display only, no deletes/backups
    if [[ "$DRY_RUN" == true ]]; then
        info "Dry-run: ${#ORPHAN_PATHS[@]} orphan(s) listed above; no changes made."
        return 0
    fi

    # Auto-yes: backup + delete all without prompting
    if [[ "$AUTO_YES" == true ]]; then
        _delete_all_orphans
        return 0
    fi

    # Interactive: 3-way prompt
    local action
    while true; do
        printf "${YELLOW}?${RESET}  Action? [a]ll, [o]ne-by-one, [c]ancel: "
        if ! read -r action; then
            # EOF -> cancel
            info "Cancelled (EOF). No changes made."
            return 0
        fi
        case "$action" in
            a|A)
                _delete_all_orphans
                return 0
                ;;
            o|O)
                # Hoist all loop-internal locals to function scope — see commit
                # 2fe276d: zsh prints the variable's value when `local` is
                # re-invoked in a loop. Array indexing is _ARRAY_BASE-aware so
                # the loop works in both zsh (1-indexed) and bash (0-indexed).
                # 'orphan_path', not 'path' — zsh ties `path` to PATH; see _delete_orphan.
                local tool orphan_path ans i n stop quit=false
                n=${#ORPHAN_PATHS[@]}
                stop=$(( n + _ARRAY_BASE ))
                for (( i = _ARRAY_BASE; i < stop; i++ )); do
                    [[ "$quit" == true ]] && break
                    tool="${ORPHAN_TOOLS[i]}"
                    orphan_path="${ORPHAN_PATHS[i]}"
                    while true; do
                        printf "${YELLOW}?${RESET}  Delete %s? [y/N/q] " "$orphan_path"
                        if ! read -r ans; then
                            ans=""  # EOF -> default skip
                        fi
                        case "$ans" in
                            y|Y) _delete_orphan "$tool" "$orphan_path"; break ;;
                            q|Q) info "Quit per-item loop; remaining orphans left in place."; quit=true; break ;;
                            n|N|"") break ;;
                            *)   warn "Invalid input — please answer y, N, or q." ;;
                        esac
                    done
                done
                return 0
                ;;
            c|C|"")
                info "Cancelled. No changes made."
                return 0
                ;;
            *)
                warn "Invalid input — please answer a, o, or c."
                ;;
        esac
    done
}

# ── Staging directory (cleaned up on exit) ────────────────────────────────────

STAGING_DIR="$(mktemp -d /tmp/agents-config-install-XXXXXX)"
trap 'rm -rf "$STAGING_DIR"' EXIT

# ── Main loop ─────────────────────────────────────────────────────────────
#
# Phases 1-6 (staging) always run; Phase 7 (sync to ~/) is skipped inside
# stage_and_install_tool / stage_and_install_beads when PRUNE_ONLY=true so
# scan_orphans still has a populated staging tree to compare against.

for tool in "${TOOLS[@]}"; do
    stage_and_install_tool "$tool"
done

# Beads staging must run whenever --prune/--prune-only is active so scan_orphans
# has a comparison baseline for ~/.beads/formulas/ (AC#19), even if beads is not
# in the active PLUGINS array. When beads is excluded, the staging build loops
# over an empty plugin set and produces an empty staging dir — under strict mode,
# all dest formulas then register as orphans, which is the intended behavior.
if plugin_enabled "beads" || prune_active; then
    stage_and_install_beads
fi

# Prune phase (post-install) — only when --prune or --prune-only is active
if prune_active; then
    scan_orphans
    prune_orphans
fi

# ── Summary ──────────────────────────────────────────────────────────────
#
# Build the report set: active TOOLS + active PLUGINS, plus any plugin that
# isn't in PLUGINS but accumulated activity (e.g., beads pruned when the
# plugin wasn't auto-detected, per AC#19).

REPORT_TARGETS=("${TOOLS[@]}" "${PLUGINS[@]}")
for plugin in "${ALL_PLUGINS[@]}"; do
    in_list "$plugin" "${REPORT_TARGETS[@]}" && continue
    if (( ${tool_pruned[$plugin]:-0} + ${tool_backed_up[$plugin]:-0} > 0 )); then
        REPORT_TARGETS+=("$plugin")
    fi
done

if [[ "$VERBOSE" == true ]]; then
    header "Summary"

    for tool in "${REPORT_TARGETS[@]}"; do
        printf "\n${BOLD}-- %s --${RESET}\n" "$tool"
        printf "  Installed:  %s\n" "${tool_installed[$tool]}"
        printf "  Updated:    %s\n" "${tool_updated[$tool]}"
        printf "  Merged:     %s\n" "${tool_merged[$tool]}"
        printf "  Backed up:  %s\n" "${tool_backed_up[$tool]}"
        printf "  Pruned:     %s\n" "${tool_pruned[$tool]}"
        printf "  Skipped:    %s\n" "${tool_skipped[$tool]}"
    done

    # Show tools and plugins that were in ALL_* but not reported above
    # (key off REPORT_TARGETS, not TOOLS/PLUGINS, so a plugin pruned outside
    # the active set — e.g. beads under strict mode, AC#19 — isn't double-printed
    # as both a real block and a "not detected, skipped" footer).
    for tool in "${ALL_TOOLS[@]}"; do
        in_list "$tool" "${REPORT_TARGETS[@]}" || \
            printf "\n${DIM}-- %s (not detected, skipped) --${RESET}\n" "$tool"
    done
    for plugin in "${ALL_PLUGINS[@]}"; do
        in_list "$plugin" "${REPORT_TARGETS[@]}" || \
            printf "\n${DIM}-- %s (not detected, skipped) --${RESET}\n" "$plugin"
    done

    echo ""
    ok "Done."
else
    # Quiet summary: one line per target with non-zero changes; "all up to date" otherwise.
    total_changes=0
    summary_lines=()
    for tool in "${REPORT_TARGETS[@]}"; do
        changed=$(( ${tool_installed[$tool]} + ${tool_updated[$tool]} + ${tool_merged[$tool]} + ${tool_pruned[$tool]} ))
        (( total_changes += changed )) || true
        if (( changed > 0 )); then
            parts=()
            (( ${tool_installed[$tool]}  > 0 )) && parts+=("${tool_installed[$tool]} installed")
            (( ${tool_updated[$tool]}    > 0 )) && parts+=("${tool_updated[$tool]} updated")
            (( ${tool_merged[$tool]}     > 0 )) && parts+=("${tool_merged[$tool]} merged")
            (( ${tool_backed_up[$tool]}  > 0 )) && parts+=("${tool_backed_up[$tool]} backed up")
            (( ${tool_pruned[$tool]}     > 0 )) && parts+=("${tool_pruned[$tool]} pruned")
            summary_lines+=("${tool}: $(IFS=', '; printf '%s' "${parts[*]}")")
        fi
    done

    echo ""
    if (( total_changes == 0 )); then
        ok "All files up to date — no changes made."
    else
        ok "Done."
        for line in "${summary_lines[@]}"; do
            printf "   %s\n" "$line"
        done
    fi
fi
