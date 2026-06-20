#!/usr/bin/env bash
# Shared exclusion matcher for the install fileset — bash side of .installignore.
# Sourced by scripts/install.sh and by installignore_test.sh. Grammar matches the
# Python loader (installer.core.installignore): one entry per line; '#' comments
# and blank lines ignored; an exact basename matches a file; a trailing-'/' name
# matches a directory. No globs, no '**', no negation, no anchoring.
#
# Requires a shell with associative arrays — zsh or bash 4+. install.sh re-execs
# into zsh (preferred) or bash 4+ before sourcing this, and both support the
# `declare -A` used here. Do NOT `set -e` here — this file only defines functions.

declare -A _INSTALLIGNORE_BASENAMES
declare -A _INSTALLIGNORE_DIRNAMES

# load_installignore <path>: populate the matcher from the manifest. A missing or
# unreadable file is a HARD ERROR (fail-fast) — mirrors the Python loader.
load_installignore() {
    local file="$1" line name
    if [[ ! -r "$file" ]]; then
        echo "Error: .installignore missing or unreadable at $file; refusing to install with exclusions disabled" >&2
        exit 1
    fi
    _INSTALLIGNORE_BASENAMES=()
    _INSTALLIGNORE_DIRNAMES=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"   # ltrim
        line="${line%"${line##*[![:space:]]}"}"    # rtrim
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" == */ ]]; then
            name="${line%/}"
            # Unquoted subscript: a quoted ["$name"] embeds literal quotes in the
            # key under zsh (but not bash), breaking lookups when install.sh re-execs
            # into zsh. The lookup side uses [$1] unquoted, so the store must too.
            [[ -n "$name" ]] && _INSTALLIGNORE_DIRNAMES[$name]=1   # skip a bare "/" (parity with Python)
        else
            _INSTALLIGNORE_BASENAMES[$line]=1
        fi
    done < "$file"
}

# is_installignored <name> <is_dir:true|false>: succeed (0) if excluded.
is_installignored() {
    if [[ "$2" == true ]]; then
        [[ -n "${_INSTALLIGNORE_DIRNAMES[$1]:-}" ]]
    else
        [[ -n "${_INSTALLIGNORE_BASENAMES[$1]:-}" ]]
    fi
}
