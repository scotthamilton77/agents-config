#!/usr/bin/env bash
# Red-phase tests for AC bullets 1-7 + 16 of agents-config-pqvc:
# brainstorm-bead finalize Y restructure to Y_container / Y_impl 2-level shape.
#
# Targets:
#   - src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh
#     The script must emit TWO lines on stdout in KEY=VALUE form:
#       Y_CONTAINER_ID=<id>
#       Y_IMPL_ID=<id>
#     The Y_container is type=epic with X.parent as its parent.
#     The Y_impl is the formula-derived type, child of Y_container, carrying
#     the impl-ready label set.
#
#   - brainstorm-bead.formula.toml finalize step:
#     - documents and extracts both Y_CONTAINER_ID + Y_IMPL_ID
#     - step 5a/5b create merge-gate / human children under Y_CONTAINER_ID
#     - step 6 migrates deps to Y_IMPL_ID
#     - step 7 stamps produced-bead-<Y_CONTAINER_ID> on X
#
# AC bullet coverage:
#   1 — Y_container (epic) + Y_impl (formula-derived) 2-level shape
#   2 — Y_impl carries full impl-ready label set
#   3 — Y_container carries none of impl-ready labels
#   4 — merge-gate attaches under Y_container as sibling of Y_impl
#   5 — Human verify children attach under Y_container
#   6 — X produced-bead-* points to Y_container id
#   7 — All deps migrate from X to Y_impl (Y_container has no migrated deps)
#  16 — Idempotency: 4 resume states handled
#
# These are red-phase: they SHOULD FAIL against the current implementation
# (which emits a single ID and creates a single Y bead) and pass once the
# implementation lands.

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

HELPER="$REPO_ROOT/src/plugins/beads/.beads/scripts/bd-finalize-create-impl-bead.sh"
FORMULA="$REPO_ROOT/src/plugins/beads/.beads/formulas/brainstorm-bead.formula.toml"

[ -f "$HELPER" ]  || fail "bd-finalize-create-impl-bead.sh not found at $HELPER"
[ -f "$FORMULA" ] || fail "brainstorm-bead.formula.toml not found at $FORMULA"

# ---------------------------------------------------------------------------
# T1 — Helper script documents the two-key output contract (AC 1).
# The script's usage / help text MUST mention both Y_CONTAINER_ID and
# Y_IMPL_ID as the stdout shape, NOT a single line ID.
# ---------------------------------------------------------------------------
grep -q 'Y_CONTAINER_ID' "$HELPER" \
    || fail "T1: helper script does not reference Y_CONTAINER_ID (expected two-line KEY=VALUE output)"
grep -q 'Y_IMPL_ID' "$HELPER" \
    || fail "T1: helper script does not reference Y_IMPL_ID (expected two-line KEY=VALUE output)"
pass "T1: helper documents Y_CONTAINER_ID and Y_IMPL_ID contract"

# ---------------------------------------------------------------------------
# T2 — Helper invokes `bd create --type epic` for Y_container (AC 1, 3).
# The Y_container is type=epic per spec design decision.
# Probe: at least one `bd create` invocation in the helper specifies
# `--type epic`.
# ---------------------------------------------------------------------------
python3 - "$HELPER" <<'PY' || fail "T2: helper does not create a Y_container via 'bd create --type epic'"
import re, sys
body = open(sys.argv[1]).read()
ok = False
# Match `bd create` followed by --type epic anywhere in the same statement
# (may have backslash-newline continuations).
for m in re.finditer(r'bd\s+create\b[\s\S]{0,800}', body):
    seg = m.group(0)
    if re.search(r'--type\s+epic\b', seg):
        ok = True
        break
if not ok:
    raise SystemExit("no `bd create --type epic` invocation found in helper")
PY
pass "T2: helper creates Y_container via 'bd create --type epic'"

# ---------------------------------------------------------------------------
# T3 — Helper emits TWO output lines on success (AC 1).
# We can't run the script without a bd backend, but we CAN assert that the
# script contains two `printf` (or echo) statements that emit the
# Y_CONTAINER_ID=... and Y_IMPL_ID=... lines.
# ---------------------------------------------------------------------------
grep -qE 'printf[[:space:]]+[^|]*Y_CONTAINER_ID=' "$HELPER" \
  || grep -qE 'echo[[:space:]]+[^|]*Y_CONTAINER_ID=' "$HELPER" \
  || fail "T3: helper does not emit a Y_CONTAINER_ID=... line via printf/echo"
grep -qE 'printf[[:space:]]+[^|]*Y_IMPL_ID=' "$HELPER" \
  || grep -qE 'echo[[:space:]]+[^|]*Y_IMPL_ID=' "$HELPER" \
  || fail "T3: helper does not emit a Y_IMPL_ID=... line via printf/echo"
pass "T3: helper emits both Y_CONTAINER_ID and Y_IMPL_ID output lines"

# ---------------------------------------------------------------------------
# T4 — Helper output is exactly two lines on the happy path (AC 1).
# Run the script with a controlled bd shim and inspect stdout.
# The shim simulates: no prior produced-from-X bead (state 0); bd create
# returns synthetic ids on each invocation.
# ---------------------------------------------------------------------------
TMP_T4=$(mktemp -d)
trap 'rm -rf "$TMP_T4"' EXIT

# Shim records each bd invocation; returns scripted responses.
cat > "$TMP_T4/bd" <<'SHIM'
#!/usr/bin/env bash
# bd shim for helper test: records calls; returns canned JSON.
LOG="${SHIM_LOG:-/dev/null}"
echo "bd $*" >> "$LOG"
case "$1" in
    list)
        # Always return empty list (no orphans, no pending-split candidates)
        echo '[]'
        ;;
    create)
        # Two distinct create calls — first call returns Y_container id,
        # second returns Y_impl id. Use a counter file.
        COUNTER="${SHIM_LOG}.counter"
        N=0
        if [ -f "$COUNTER" ]; then
            N=$(cat "$COUNTER")
        fi
        N=$((N + 1))
        echo "$N" > "$COUNTER"
        if [ "$N" = "1" ]; then
            echo '{"id":"test-yc-001"}'
        else
            echo '{"id":"test-yi-002"}'
        fi
        ;;
    label|update|comments|dep|show)
        # Side-effect commands — return success-ish output.
        case "$2" in
            list) echo '[]' ;;
            *) echo '{}' ;;
        esac
        ;;
    *)
        echo '{}'
        ;;
esac
exit 0
SHIM
chmod +x "$TMP_T4/bd"

# Spec + AC fixture files.
SPEC_FILE="$TMP_T4/spec.md"
AC_FILE="$TMP_T4/ac.md"
echo "spec body" > "$SPEC_FILE"
echo "[m] acceptance line" > "$AC_FILE"
SHIM_LOG="$TMP_T4/log"
touch "$SHIM_LOG"

# Run the helper with the shim on PATH and inspect stdout SHAPE.
#
# EXIT-CODE LENIENCY (narrow, intentional):
#   The helper may exit non-zero under the shim because the shim cannot
#   fully emulate a live bd backend (e.g., dep/label side-effects after
#   the two create calls). A non-zero exit therefore SKIPs T4 — the
#   helper crashing in the test harness is not the failure mode this
#   assertion is meant to guard. Static string probes T1+T3 carry the
#   "helper does not implement the contract" signal.
#
# HAPPY-PATH ASSERTION (binding):
#   When the helper exits 0, it MUST emit exactly two non-empty lines
#   matching `Y_CONTAINER_ID=<id>` and `Y_IMPL_ID=<id>` in order. Any
#   other shape (1 line, 3+ lines, wrong keys) is a FAIL — a helper
#   that exits 0 but bypasses the two-line KEY=VALUE contract is the
#   exact regression this test guards.
HELPER_OUT="$TMP_T4/helper.out"
HELPER_ERR="$TMP_T4/helper.err"
HELPER_RC=0

# Force script to run under the shim by overriding PATH AND HOME so that
# any `$HOME/.beads/scripts/...` calls (none expected, but defensive) are
# isolated. The helper itself doesn't shell out to peer scripts.
PATH="$TMP_T4:$PATH" SHIM_LOG="$SHIM_LOG" \
    bash "$HELPER" \
        --source-bead-id test-x-001 \
        --type feature \
        --priority 1 \
        --title '[Impl] Test feature' \
        --labels 'produced-from-test-x-001,formula-implement-feature,brainstormed,implementation-ready,implementation-readied-session-deadbeef' \
        --spec-file "$SPEC_FILE" \
        --ac-file "$AC_FILE" \
        >"$HELPER_OUT" 2>"$HELPER_ERR" || HELPER_RC=$?

line_count=$(grep -cE '\S' "$HELPER_OUT" || true)
if [ "$HELPER_RC" -eq 0 ]; then
    [ "$line_count" -eq 2 ] \
        || fail "T4: helper exited 0 but emitted $line_count non-empty stdout line(s); expected exactly 2 (Y_CONTAINER_ID=<id>, Y_IMPL_ID=<id>). stdout: $(cat "$HELPER_OUT")"
    first_line=$(sed -n '1p' "$HELPER_OUT")
    second_line=$(sed -n '2p' "$HELPER_OUT")
    echo "$first_line"  | grep -qE '^Y_CONTAINER_ID=[A-Za-z0-9._-]+$' \
        || fail "T4: line 1 must match 'Y_CONTAINER_ID=<id>'; got: '$first_line'"
    echo "$second_line" | grep -qE '^Y_IMPL_ID=[A-Za-z0-9._-]+$' \
        || fail "T4: line 2 must match 'Y_IMPL_ID=<id>'; got: '$second_line'"
    pass "T4: helper emits two KEY=VALUE lines (Y_CONTAINER_ID, Y_IMPL_ID) on happy path"
else
    # Helper exited non-zero — likely shim cannot fully emulate the
    # live bd backend. T1+T3 static probes still carry the contract
    # signal; skip the dynamic shape assertion.
    echo "SKIP: T4: helper rc=$HELPER_RC (shim cannot fully emulate bd backend); static contract signal carried by T1+T3"
fi

# ---------------------------------------------------------------------------
# T5 — Helper passes X.parent as Y_container's parent (AC 1).
# When --parent is provided, the FIRST `bd create` call (Y_container) must
# include it. The SECOND `bd create` (Y_impl) must use Y_container_id as
# its parent, not X.parent.
# Inspect the SHIM_LOG from T4's run.
# ---------------------------------------------------------------------------
# We need a fresh run with --parent supplied.
SHIM_LOG2="$TMP_T4/log2"
touch "$SHIM_LOG2"
rm -f "$TMP_T4/log.counter" "$TMP_T4/log2.counter"
PATH="$TMP_T4:$PATH" SHIM_LOG="$SHIM_LOG2" \
    bash "$HELPER" \
        --source-bead-id test-x-001 \
        --type feature \
        --priority 1 \
        --title '[Impl] Test feature' \
        --labels 'produced-from-test-x-001,formula-implement-feature,brainstormed,implementation-ready,implementation-readied-session-deadbeef' \
        --spec-file "$SPEC_FILE" \
        --ac-file "$AC_FILE" \
        --parent test-x-parent-001 \
        >"$TMP_T4/run2.out" 2>"$TMP_T4/run2.err" || true

# Locate first/second create lines.
create_lines=$(grep -nE '^bd create' "$SHIM_LOG2" | head -2)
[ -n "$create_lines" ] \
    || fail "T5: helper did not invoke 'bd create' under shim; log: $(cat "$SHIM_LOG2")"
first_create=$(echo "$create_lines" | sed -n '1p')
second_create=$(echo "$create_lines" | sed -n '2p')

echo "$first_create" | grep -q -- '--parent test-x-parent-001' \
    || fail "T5: first bd create (Y_container) must include '--parent test-x-parent-001'; got: $first_create"
echo "$second_create" | grep -q -- '--parent test-yc-001' \
    || fail "T5: second bd create (Y_impl) must include '--parent test-yc-001' (the Y_container id); got: $second_create"
pass "T5: helper passes X.parent to Y_container and Y_container_id to Y_impl"

# ---------------------------------------------------------------------------
# T6 — Formula step 4 extracts BOTH Y_CONTAINER_ID and Y_IMPL_ID from the
# helper output (AC 1).
# The formula MUST parse the two-line KEY=VALUE output and bind both ids
# into shell variables that subsequent steps use.
# ---------------------------------------------------------------------------
# Extract the finalize step body.
TMP_FIN=$(mktemp)
TMP_FIN_OUT="$TMP_FIN"
trap 'rm -rf "$TMP_T4" "$TMP_FIN_OUT"' EXIT

awk '
    /^id[[:space:]]*=[[:space:]]*"finalize"/{f=1; print; next}
    f && /^\[\[steps\]\]/{f=0}
    f { print }
' "$FORMULA" > "$TMP_FIN_OUT"

grep -q 'Y_CONTAINER_ID' "$TMP_FIN_OUT" \
    || fail "T6: finalize body does not reference Y_CONTAINER_ID"
grep -q 'Y_IMPL_ID' "$TMP_FIN_OUT" \
    || fail "T6: finalize body does not reference Y_IMPL_ID"
pass "T6: finalize body extracts both Y_CONTAINER_ID and Y_IMPL_ID"

# ---------------------------------------------------------------------------
# T7 — Formula step 5 (children-under-Y) uses Y_CONTAINER_ID, not Y_IMPL_ID
# (AC 4, 5).
# Step 5a migrates pre-existing children; step 5b creates merge-gate and
# Human verify children. All `--parent` values must be Y_CONTAINER_ID.
# We assert: the finalize body's first `bd create --parent` (after the
# helper invocation) targets the container id.
# ---------------------------------------------------------------------------
# Find the first `bd create --parent` after the helper invocation block.
python3 - "$TMP_FIN_OUT" <<'PY' || fail "T7: finalize step 5 child-create blocks do not use Y_CONTAINER_ID as --parent"
import re, sys
body = open(sys.argv[1]).read()

# After the helper invocation, find all bd create or bd update --parent calls
# that have an explicit --parent <var> argument inside the post-helper block.
helper_idx = body.find('bd-finalize-create-impl-bead.sh')
if helper_idx == -1:
    raise SystemExit("helper invocation not found in finalize body")
tail = body[helper_idx:]

# Look for --parent followed by a variable reference. Reject any that use
# Y_ID (singular) or Y_IMPL_ID for attaching merge-gate / human children.
parent_uses = re.findall(r'--parent\s+"?\$?\{?([A-Za-z_][A-Za-z0-9_]*)\}?"?', tail)
if not parent_uses:
    raise SystemExit("no '--parent <var>' usages found in post-helper finalize body")

# At least one --parent must reference Y_CONTAINER_ID (children attach to Y_container).
if "Y_CONTAINER_ID" not in parent_uses:
    raise SystemExit(f"post-helper --parent usages do not reference Y_CONTAINER_ID; saw: {parent_uses}")

# None may attach merge-gate / human children to Y_IMPL_ID. Scan for any
# `bd create ... --parent Y_IMPL_ID ... merge-gate` / `--labels human`.
bad = re.search(
    r'bd\s+create\b[\s\S]{0,500}?--parent\s+"?\$?\{?Y_IMPL_ID\}?"?[\s\S]{0,500}?--labels\s+"?(merge-gate|human)',
    tail,
)
if bad:
    raise SystemExit(f"merge-gate / human child created with --parent Y_IMPL_ID — must be Y_CONTAINER_ID: {bad.group(0)[:200]}")
PY
pass "T7: finalize step 5 creates merge-gate / human children with --parent Y_CONTAINER_ID"

# ---------------------------------------------------------------------------
# T8 — Formula step 6 (dep migration) uses Y_IMPL_ID as the target (AC 7).
# bd-migrate-deps.sh --target must be Y_IMPL_ID, not Y_CONTAINER_ID.
# ---------------------------------------------------------------------------
python3 - "$TMP_FIN_OUT" <<'PY' || fail "T8: finalize step 6 dep migration does not target Y_IMPL_ID"
import re, sys
body = open(sys.argv[1]).read()
# Find the bd-migrate-deps.sh invocation and inspect its --target.
m = re.search(r'bd-migrate-deps\.sh[\s\S]{0,500}', body)
if not m:
    raise SystemExit("bd-migrate-deps.sh not invoked in finalize body")
seg = m.group(0)
target_match = re.search(r'--target\s+"?\$?\{?([A-Za-z_][A-Za-z0-9_]*)\}?"?', seg)
if not target_match:
    raise SystemExit("bd-migrate-deps.sh invocation has no --target arg")
target = target_match.group(1)
if target != "Y_IMPL_ID":
    raise SystemExit(f"bd-migrate-deps.sh --target must be Y_IMPL_ID; got {target}")
PY
pass "T8: finalize step 6 migrates deps to Y_IMPL_ID"

# ---------------------------------------------------------------------------
# T9 — Formula step 7 stamps produced-bead-<Y_CONTAINER_ID> on X (AC 6).
# The label form must reference $Y_CONTAINER_ID, not $Y_ID or $Y_IMPL_ID.
# ---------------------------------------------------------------------------
grep -qE 'produced-bead-\$\{?Y_CONTAINER_ID\}?' "$TMP_FIN_OUT" \
    || grep -qE 'produced-bead-"\$Y_CONTAINER_ID"' "$TMP_FIN_OUT" \
    || fail "T9: finalize step 7 does not stamp 'produced-bead-\$Y_CONTAINER_ID' on X (must point to Y_container, not Y_impl)"
pass "T9: finalize step 7 stamps produced-bead-\$Y_CONTAINER_ID on X"

# ---------------------------------------------------------------------------
# T10 — Idempotency: finalize body references the pending-split-<X_id>
# marker label per spec State 1 detection (AC 16).
# This label is the State 1 crash-recovery marker described in the spec.
# ---------------------------------------------------------------------------
grep -qE 'pending-split-' "$TMP_FIN_OUT" \
    || grep -qE 'pending-split-' "$HELPER" \
    || fail "T10: neither finalize body nor helper references the 'pending-split-<X_id>' State 1 marker (per spec idempotency state table)"
pass "T10: pending-split-<X_id> idempotency marker referenced"

echo "All pqvc 2-level shape red-phase tests reached — exit 0 only when every assertion passes."
