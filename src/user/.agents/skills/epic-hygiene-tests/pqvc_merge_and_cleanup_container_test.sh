#!/usr/bin/env bash
# Red-phase tests for AC bullets 10, 11, 12 of agents-config-pqvc:
# merge-and-cleanup jq bug fix + CONTAINER_ID resolution + container close.
#
# AC bullet coverage:
#   10 — merge-and-cleanup jq bug fixed: merge-gate child detected
#        (bd label list --json returns a flat JSON array, not an object
#        with .labels). Current line 279 reads `.labels | index("merge-gate")`
#        which yields null on flat-array shape — leaving merge-gate
#        children open after cleanup.
#   11 — merge-and-cleanup resolves CONTAINER_ID from Y_impl.parent at
#        the TOP of the formula; falls back to bead-id (legacy single-Y).
#   12 — merge-and-cleanup closes Y_container and runs close-walk when
#        all children closed.
#
# Targets:
#   - src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml
#
# These are red-phase: SHOULD FAIL against the current implementation,
# pass once the spec lands.

set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/plugins/beads" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/plugins/beads" ] \
    || fail "could not locate repo root containing src/plugins/beads"

FORMULA="$REPO_ROOT/src/plugins/beads/.beads/formulas/merge-and-cleanup.formula.toml"
[ -f "$FORMULA" ] || fail "merge-and-cleanup.formula.toml not found at $FORMULA"

# ---------------------------------------------------------------------------
# T1 — jq bug fix: `bd label list --json | jq -e 'index("merge-gate")'`
# (flat-array shape) NOT `... | jq -e '.labels | index("merge-gate")'`
# (object shape that doesn't exist).
#
# The current formula contains the buggy form on or near line 279. The
# fix removes the `.labels |` prefix because `bd label list <id> --json`
# returns a flat JSON array, not an object.
# ---------------------------------------------------------------------------
# Reject the buggy form. (Defence in depth: also reject any line that
# pipes `bd label list ... --json` into `jq ... '.labels |'`.)
if grep -qE 'bd label list[^|]*\| *jq[^|]*\.labels[[:space:]]*\|' "$FORMULA"; then
    bad_line=$(grep -nE 'bd label list[^|]*\| *jq[^|]*\.labels[[:space:]]*\|' "$FORMULA" | head -1)
    fail "T1: merge-and-cleanup contains buggy jq form '.labels | index(...)' on flat-array output from bd label list: $bad_line"
fi
# Require the corrected form: jq ... index("merge-gate") without `.labels |` prefix.
grep -qE 'index\("merge-gate"\)' "$FORMULA" \
    || fail "T1: merge-and-cleanup does not contain index(\"merge-gate\") at all"
pass "T1: merge-and-cleanup jq merge-gate probe uses flat-array shape (no '.labels |' prefix)"

# ---------------------------------------------------------------------------
# T2 — CONTAINER_ID resolution at formula top: the formula must contain a
# block that resolves CONTAINER_ID from Y_impl.parent BEFORE the
# source-bead-gate step's child lookups. Per spec:
#
#     CONTAINER_ID=$(bd show "$BEAD_ID" --json | jq -r '.[0].parent // empty')
#     [ -z "$CONTAINER_ID" ] && CONTAINER_ID="$BEAD_ID"
# ---------------------------------------------------------------------------
grep -q 'CONTAINER_ID' "$FORMULA" \
    || fail "T2: merge-and-cleanup does not reference CONTAINER_ID"

# Probe for the resolution shape: a CONTAINER_ID= assignment that reads
# `.[0].parent` from bd show on the source bead-id, AND a fallback line
# `[ -z "$CONTAINER_ID" ] && CONTAINER_ID=...` (or equivalent default).
python3 - "$FORMULA" <<'PY' || fail "T2: merge-and-cleanup lacks CONTAINER_ID resolution block (bd show .parent + legacy fallback)"
import re, sys
body = open(sys.argv[1]).read()
# Match an assignment that captures bd show ... | jq -r '.[0].parent ...' .
m1 = re.search(
    r'CONTAINER_ID=\$\(\s*bd\s+show[\s\S]{0,300}?\.\[0\]\.parent',
    body,
)
if not m1:
    raise SystemExit("no CONTAINER_ID=$(bd show ... .[0].parent ...) assignment found")
# Match a legacy fallback: [ -z "$CONTAINER_ID" ] && CONTAINER_ID=...
m2 = re.search(
    r'\[\s*-z\s+"?\$\{?CONTAINER_ID\}?"?\s*\]\s*&&\s*CONTAINER_ID=',
    body,
)
if not m2:
    raise SystemExit("no '[ -z \"$CONTAINER_ID\" ] && CONTAINER_ID=...' legacy fallback found")
PY
pass "T2: merge-and-cleanup resolves CONTAINER_ID at top via bd show .parent + legacy fallback"

# ---------------------------------------------------------------------------
# T3 — source-bead-gate child lookups use $CONTAINER_ID (not bead-id).
# Per spec: 'source-bead-gate steps 1, 2, 3: replace bd list --parent bead-id
# with bd list --parent $CONTAINER_ID'.
# ---------------------------------------------------------------------------
# Extract the source-bead-gate step body.
TMP_SBG=$(mktemp)
trap 'rm -f "$TMP_SBG"' EXIT

awk '
    /^id[[:space:]]*=[[:space:]]*"source-bead-gate"/{f=1; next}
    f && /^\[\[steps\]\]/{f=0}
    f { print }
' "$FORMULA" > "$TMP_SBG"

[ -s "$TMP_SBG" ] || fail "T3: source-bead-gate step body not found"

# Within the source-bead-gate body, every `bd list --parent ...` must use
# $CONTAINER_ID (or ${CONTAINER_ID}), not {{bead-id}} directly.
if grep -qE 'bd list --parent \{\{bead-id\}\}' "$TMP_SBG"; then
    fail "T3: source-bead-gate uses 'bd list --parent {{bead-id}}' — must use \$CONTAINER_ID"
fi
grep -qE 'bd list --parent[[:space:]]+"?\$\{?CONTAINER_ID\}?"?' "$TMP_SBG" \
    || fail "T3: source-bead-gate does not use 'bd list --parent \$CONTAINER_ID'"
pass "T3: source-bead-gate uses \$CONTAINER_ID for child lookups"

# ---------------------------------------------------------------------------
# T4 — cleanup step child lookups + merge-gate detection use $CONTAINER_ID.
# Per spec: cleanup steps 4, 5, 6 use $CONTAINER_ID.
# ---------------------------------------------------------------------------
TMP_CLN=$(mktemp)
trap 'rm -f "$TMP_SBG" "$TMP_CLN"' EXIT

awk '
    /^id[[:space:]]*=[[:space:]]*"cleanup"/{f=1; next}
    f && /^\[\[steps\]\]/{f=0}
    f { print }
' "$FORMULA" > "$TMP_CLN"

[ -s "$TMP_CLN" ] || fail "T4: cleanup step body not found"

# All `bd list --parent ...` inside cleanup must use $CONTAINER_ID, not bead-id.
if grep -qE 'bd list --parent \{\{bead-id\}\}' "$TMP_CLN"; then
    fail "T4: cleanup uses 'bd list --parent {{bead-id}}' — must use \$CONTAINER_ID"
fi
grep -qE 'bd list --parent[[:space:]]+"?\$\{?CONTAINER_ID\}?"?' "$TMP_CLN" \
    || fail "T4: cleanup does not use 'bd list --parent \$CONTAINER_ID' for the merge-gate probe loop"
pass "T4: cleanup uses \$CONTAINER_ID for child lookups"

# ---------------------------------------------------------------------------
# T5 — cleanup CLOSES the Y_container via $CONTAINER_ID (AC 12).
# Per spec: 'merge-and-cleanup closes CONTAINER_ID (Y_container) and runs
# close-walk from CONTAINER_ID.'
#
# So the cleanup body must call `bd-close-walk.sh --bead-id $CONTAINER_ID`
# (not --bead-id {{bead-id}}).
# ---------------------------------------------------------------------------
python3 - "$TMP_CLN" <<'PY' || fail "T5: cleanup does not run bd-close-walk.sh against \$CONTAINER_ID"
import re, sys
body = open(sys.argv[1]).read()
m = re.search(r'bd-close-walk\.sh[\s\S]{0,400}', body)
if not m:
    raise SystemExit("bd-close-walk.sh not invoked in cleanup")
seg = m.group(0)
bid_match = re.search(r'--bead-id\s+"?\$?\{?([A-Za-z_{}-][^"\s]*)', seg)
if not bid_match:
    raise SystemExit("bd-close-walk.sh has no --bead-id argument")
bid_arg = bid_match.group(1)
# Acceptable forms: $CONTAINER_ID, ${CONTAINER_ID}, "$CONTAINER_ID"
if "CONTAINER_ID" not in bid_arg:
    raise SystemExit(f"bd-close-walk.sh --bead-id must reference CONTAINER_ID; got: '{bid_arg}'")
PY
pass "T5: cleanup invokes bd-close-walk.sh --bead-id \$CONTAINER_ID"

# ---------------------------------------------------------------------------
# T6 — CONTAINER_ID resolution appears BEFORE the source-bead-gate step
# (before any child-lookup that depends on it).
# Probe: line number of the CONTAINER_ID= assignment must be earlier than
# any source-bead-gate `bd list --parent $CONTAINER_ID`.
# ---------------------------------------------------------------------------
container_resolve_line=$(grep -nE 'CONTAINER_ID=\$\(' "$FORMULA" | head -1 | cut -d: -f1)
sbg_header_line=$(grep -nE 'id[[:space:]]*=[[:space:]]*"source-bead-gate"' "$FORMULA" | head -1 | cut -d: -f1)
[ -n "$container_resolve_line" ] \
    || fail "T6: no CONTAINER_ID=\$(...) assignment found in formula"
[ -n "$sbg_header_line" ] \
    || fail "T6: source-bead-gate step header not found"
# CONTAINER_ID resolution must be in source-bead-gate body OR before it.
# We accept either: a top-of-formula resolution block, OR a resolution at
# the very start of source-bead-gate (within first 40 lines after header).
if [ "$container_resolve_line" -gt "$sbg_header_line" ]; then
    delta=$((container_resolve_line - sbg_header_line))
    [ "$delta" -le 40 ] \
        || fail "T6: CONTAINER_ID resolved at line $container_resolve_line, source-bead-gate starts at $sbg_header_line — resolution must be at top of formula or within first 40 lines of source-bead-gate body"
fi
pass "T6: CONTAINER_ID resolution precedes source-bead-gate child lookups"

echo "All pqvc merge-and-cleanup red-phase tests reached — exit 0 only when every assertion passes."
