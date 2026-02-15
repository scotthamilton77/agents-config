#!/usr/bin/env bash
set -euo pipefail

# --------------------------------------------------------------------------
# install.sh — Sync src/user/.claude/ into ~/.claude/
#
# - *.md.template files → ~/.claude/<name>.md (confirm if different)
# - agents/, skills/, commands/ → recursive hash comparison per item
#   (remove + recopy on mismatch with confirmation)
# - settings.json.template → union-merge into ~/.claude/settings.json
# --------------------------------------------------------------------------

# ── Colors & helpers ─────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

DRY_RUN=false
AUTO_YES=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --yes|-y)  AUTO_YES=true ;;
        --help|-h)
            echo "Usage: install.sh [--dry-run] [--yes|-y] [--help|-h]"
            echo "  --dry-run  Show what would be done without making changes"
            echo "  --yes, -y  Auto-accept all prompts"
            echo "  --help, -h Show this help"
            exit 0
            ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

info()  { printf "${CYAN}ℹ${RESET}  %s\n" "$*"; }
ok()    { printf "${GREEN}✓${RESET}  %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${RESET}  %s\n" "$*"; }
err()   { printf "${RED}✗${RESET}  %s\n" "$*" >&2; }
header(){ printf "\n${BOLD}── %s ──${RESET}\n" "$*"; }

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$PROJECT_ROOT/src/user/.claude"
DEST_DIR="$HOME/.claude"

if [[ ! -d "$SRC_DIR" ]]; then
    err "Source directory not found: $SRC_DIR"
    exit 1
fi

if [[ "$DRY_RUN" == true ]]; then
    info "DRY RUN — no changes will be made"
fi

mkdir -p "$DEST_DIR"

# Counters
installed=0
updated=0
skipped=0
merged=0
backed_up=0

# ── Utility: back up a file with timestamp ────────────────────────────────

backup() {
    local file="$1"
    if [[ -f "$file" ]]; then
        local timestamp
        timestamp="$(date +%Y%m%d-%H%M%S)"
        local backup_file="${file}.backup-${timestamp}"
        cp "$file" "$backup_file"
        info "Backed up $(basename "$file") → $(basename "$backup_file")"
        ((backed_up++)) || true
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

# ── 1. Template files (*.md.template) ────────────────────────────────────

header "Template files"

for template in "$SRC_DIR"/*.md.template; do
    [[ -f "$template" ]] || continue
    basename_template="$(basename "$template")"
    # Strip .template suffix → target filename
    target_name="${basename_template%.template}"
    dest_file="$DEST_DIR/$target_name"

    if [[ ! -f "$dest_file" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            ok "Would install $target_name (new)"
        else
            cp "$template" "$dest_file"
            ok "Installed $target_name (new)"
        fi
        ((installed++)) || true
    else
        src_hash="$(compute_hash "$template")"
        dst_hash="$(compute_hash "$dest_file")"

        if [[ "$src_hash" == "$dst_hash" ]]; then
            ok "$target_name is up to date"
            ((skipped++)) || true
        else
            info "$target_name differs from installed version:"
            diff --color=auto -u "$dest_file" "$template" || true
            echo
            if confirm "Overwrite $dest_file with template version?"; then
                if [[ "$DRY_RUN" == true ]]; then
                    ok "Would update $target_name"
                else
                    backup "$dest_file"
                    cp "$template" "$dest_file"
                    ok "Updated $target_name"
                fi
                ((updated++)) || true
            else
                warn "Skipped $target_name"
                ((skipped++)) || true
            fi
        fi
    fi
done

# ── 2. Directory sync (agents/, skills/, commands/) ──────────────────────

sync_directory() {
    local dir_name="$1"
    local src_parent="$SRC_DIR/$dir_name"
    local dest_parent="$DEST_DIR/$dir_name"

    header "Syncing $dir_name/"

    if [[ ! -d "$src_parent" ]]; then
        warn "Source directory $src_parent not found, skipping"
        return
    fi

    mkdir -p "$dest_parent"

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
            ((installed++)) || true
        else
            dest_hash="$(compute_hash "$dest_item")"

            if [[ "$src_hash" == "$dest_hash" ]]; then
                ok "$dir_name/$item_name is up to date"
                ((skipped++)) || true
            else
                warn "$dir_name/$item_name has changed"
                if [[ -d "$item" ]]; then
                    diff -rq "$dest_item" "$item" 2>/dev/null || true
                else
                    diff --color=auto -u "$dest_item" "$item" || true
                fi
                echo
                if confirm "Replace $dir_name/$item_name? (removes existing, copies fresh)"; then
                    if [[ "$DRY_RUN" == true ]]; then
                        ok "Would update $dir_name/$item_name"
                    else
                        rm -rf "$dest_item"
                        cp -R "$item" "$dest_item"
                        ok "Updated $dir_name/$item_name"
                    fi
                    ((updated++)) || true
                else
                    warn "Skipped $dir_name/$item_name"
                    ((skipped++)) || true
                fi
            fi
        fi
    done

    # Warn about items in dest that aren't in source
    for dest_item in "$dest_parent"/*; do
        [[ -e "$dest_item" ]] || continue
        item_name="$(basename "$dest_item")"
        if [[ ! -e "$src_parent/$item_name" ]]; then
            warn "$dir_name/$item_name exists in ~/.claude but not in project (keeping)"
        fi
    done
}

sync_directory "agents"
sync_directory "skills"
sync_directory "commands"

# ── 3. Settings JSON merge ───────────────────────────────────────────────

header "Settings JSON"

SETTINGS_TEMPLATE="$SRC_DIR/settings.json.template"
SETTINGS_DEST="$DEST_DIR/settings.json"

if [[ ! -f "$SETTINGS_TEMPLATE" ]]; then
    warn "No settings.json.template found, skipping"
else
    if [[ ! -f "$SETTINGS_DEST" ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            ok "Would install settings.json (new)"
        else
            cp "$SETTINGS_TEMPLATE" "$SETTINGS_DEST"
            ok "Installed settings.json (new)"
        fi
        ((installed++)) || true
    else
        # Validate existing settings.json before merging
        if ! jq empty "$SETTINGS_DEST" 2>/dev/null; then
            err "$SETTINGS_DEST contains invalid JSON. Fix it manually or remove it."
            ((skipped++)) || true
        else
            # Union merge using jq:
            # - Objects: deep merge (user values preserved, template adds new keys)
            # - Arrays: union (deduplicated)
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
            ' "$SETTINGS_DEST" "$SETTINGS_TEMPLATE")"

            # Check if merge actually changed anything
            current="$(jq -S . "$SETTINGS_DEST")"
            proposed="$(printf '%s\n' "$merged_json" | jq -S .)"

            if [[ "$current" == "$proposed" ]]; then
                ok "settings.json is up to date"
                ((skipped++)) || true
            else
                info "Proposed settings.json changes:"
                diff --color=auto -u <(printf '%s\n' "$current") <(printf '%s\n' "$proposed") || true
                echo
                if confirm "Apply merged settings.json?"; then
                    if [[ "$DRY_RUN" == true ]]; then
                        ok "Would merge settings.json"
                    else
                        backup "$SETTINGS_DEST"
                        tmp="$(mktemp)"
                        printf '%s\n' "$merged_json" | jq . > "$tmp"
                        mv "$tmp" "$SETTINGS_DEST"
                        ok "Merged settings.json"
                    fi
                    ((merged++)) || true
                else
                    warn "Skipped settings.json merge"
                    ((skipped++)) || true
                fi
            fi
        fi
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────────

header "Summary"
echo "  Installed:  $installed"
echo "  Updated:    $updated"
echo "  Merged:     $merged"
echo "  Backed up:  $backed_up"
echo "  Skipped:    $skipped"
echo ""
ok "Done."
