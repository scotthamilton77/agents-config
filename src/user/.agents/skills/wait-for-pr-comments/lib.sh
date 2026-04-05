#!/usr/bin/env bash
# lib.sh — Shared helpers for wait-for-pr-comments polling scripts.
# Source this file: source "$(dirname "$0")/lib.sh"

# Wrapped gh api — keeps stderr separate from stdout to avoid JSON contamination
gh_api() {
    local result exit_code=0
    result=$(gh api "$@" 2>/dev/null) || exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        echo "gh api failed (exit $exit_code)" >&2
        return 1
    fi
    printf '%s' "$result"
}

# Validate owner/repo format — exits 3 on failure
validate_repo() {
    [[ "$1" == */* ]] || { echo "Error: first argument must be owner/repo" >&2; exit 3; }
}

# Pre-flight: verify gh auth and jq availability — exits 3 on failure
preflight_checks() {
    if ! gh auth status &>/dev/null; then
        echo "Error: gh auth failed — not authenticated" >&2
        exit 3
    fi
    if ! command -v jq &>/dev/null; then
        echo "Error: jq is required but not found" >&2
        exit 3
    fi
}
