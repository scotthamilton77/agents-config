#!/usr/bin/env bash
# Unit test for scripts/lib/installignore.sh — the bash exclusion matcher.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB="$SCRIPT_DIR/installignore.sh"
fail=0

assert() { # $1=desc  $2=expected  $3=actual
    if [[ "$2" != "$3" ]]; then echo "FAIL: $1 (expected '$2', got '$3')" >&2; fail=1
    else echo "ok: $1"; fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
manifest="$work/.installignore"
printf '%s\n' '# comment' '' 'AGENTS.md' 'rules-readmes/' > "$manifest"

# shellcheck source=/dev/null
source "$LIB"
load_installignore "$manifest"

is_installignored "AGENTS.md" false && r=drop || r=keep
assert "file basename excluded" "drop" "$r"
is_installignored "AGENTS.md.template" false && r=drop || r=keep
assert "template not excluded" "keep" "$r"
is_installignored "rules-readmes" true && r=drop || r=keep
assert "dir name excluded" "drop" "$r"
is_installignored "rules-readmes" false && r=drop || r=keep
assert "dir entry does not match a file query" "keep" "$r"

# Fail-fast on a missing manifest (run in a subshell so its exit does not kill us).
( source "$LIB"; load_installignore "$work/nope" ) 2>/dev/null && r=0 || r=$?
assert "missing manifest fail-fast (nonzero exit)" "1" "$r"

exit "$fail"
