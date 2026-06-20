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

# A degenerate "/" line must not abort the loader. Run under `set -e` (as install.sh
# does): the unguarded code would assign to an empty array key (`bad array subscript`)
# and abort; the guard skips it, matching the Python loader.
printf '%s\n' '/' 'AGENTS.md' > "$work/slash"
( set -e; source "$LIB"; load_installignore "$work/slash" ) 2>/dev/null && r=0 || r=$?
assert "bare slash line does not abort under set -e" "0" "$r"

# Fail-fast on a missing manifest (run in a subshell so its exit does not kill us).
( source "$LIB"; load_installignore "$work/nope" ) 2>/dev/null && r=0 || r=$?
assert "missing manifest fail-fast (nonzero exit)" "1" "$r"

# Cross-shell regression: install.sh re-execs into zsh (preferred) before sourcing
# this lib, so the matcher MUST work under zsh too — not just the bash this test
# runs under. A quoted store subscript (["$key"]) silently embeds the quotes in the
# key under zsh while the lookup uses [$1], so every match misses and exclusions
# vanish. Source + load + query under zsh and assert the verdicts when zsh exists.
if command -v zsh >/dev/null 2>&1; then
    zverdicts="$(zsh -c '
        source "$1"
        load_installignore "$2"
        for q in "AGENTS.md:false" "AGENTS.md.template:false" "rules-readmes:true"; do
            n="${q%:*}"; d="${q#*:}"
            if is_installignored "$n" "$d"; then printf "drop "; else printf "keep "; fi
        done
    ' zsh_matcher_test "$LIB" "$manifest")"
    assert "matcher works under zsh (drop/keep/drop)" "drop keep drop " "$zverdicts"
else
    echo "ok: zsh unavailable — cross-shell check skipped"
fi

exit "$fail"
