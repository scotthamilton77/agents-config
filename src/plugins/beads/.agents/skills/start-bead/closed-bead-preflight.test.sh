#!/bin/sh
# closed-bead-preflight.test.sh — POSIX shell tests for closed-bead-preflight.sh.
#
# Self-contained: stubs `bd` via a PATH-shadowed mock script that reads
# canned JSON from $BD_FIXTURE/<bead-id>.json. No project bead IDs leak into
# fixtures — only generic names (target, Y, Z, missing).

set -e

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFLIGHT="$HERE/closed-bead-preflight.sh"

if [ ! -x "$PREFLIGHT" ]; then
    printf 'FATAL: %s is not executable\n' "$PREFLIGHT" >&2
    exit 2
fi

# --- Mock bd in a tempdir on PATH -------------------------------------------
WORK_DIR=$(mktemp -d)
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT INT TERM HUP

MOCK_DIR="$WORK_DIR/bin"
mkdir -p "$MOCK_DIR"

cat > "$MOCK_DIR/bd" <<'MOCK_EOF'
#!/bin/sh
# Mock bd: only supports `bd show <id> --json`.
# Reads $BD_FIXTURE/<id>.json. Missing fixture file → exit 1 (mirrors real bd).
case "$1" in
    show)
        id=$2
        if [ -n "$BD_FIXTURE" ] && [ -f "$BD_FIXTURE/$id.json" ]; then
            cat "$BD_FIXTURE/$id.json"
            exit 0
        fi
        printf 'mock bd: no fixture for id=%s\n' "$id" >&2
        exit 1
        ;;
    *)
        printf 'mock bd: unsupported subcommand: %s\n' "$*" >&2
        exit 2
        ;;
esac
MOCK_EOF
chmod +x "$MOCK_DIR/bd"

PATH="$MOCK_DIR:$PATH"
export PATH

# --- Test harness -----------------------------------------------------------
PASS=0
FAIL=0

# assert_decision <test-name> <expected-substring> -- <preflight-args...>
# Captures stdout+stderr, treats nonzero exit as part of the actual output
# (so error-halt tests can match either way). The double-dash separates name
# args from preflight args.
assert_decision() {
    name=$1
    expected=$2
    shift 2
    if [ "$1" = "--" ]; then shift; fi

    actual=$("$PREFLIGHT" "$@" 2>&1) || actual="EXIT:$? $actual"

    if printf '%s' "$actual" | grep -qF "$expected"; then
        printf 'PASS: %s\n' "$name"
        PASS=$((PASS + 1))
    else
        printf 'FAIL: %s\n  expected substring: %s\n  actual output:      %s\n' \
            "$name" "$expected" "$actual"
        FAIL=$((FAIL + 1))
    fi
}

# --- Fixture builders -------------------------------------------------------
# Each test case sets up its own $BD_FIXTURE dir to keep cases isolated.
new_fixture() {
    fdir=$(mktemp -d "$WORK_DIR/fixture.XXXXXX")
    printf '%s\n' "$fdir"
}

write_bead() {
    # write_bead <fixture-dir> <id> <status> <comma-sep-labels-or-empty>
    fdir=$1; id=$2; status=$3; labels=$4
    if [ -z "$labels" ]; then
        labels_json='[]'
    else
        # Build a JSON array from comma-separated label names.
        labels_json=$(printf '%s' "$labels" \
            | tr ',' '\n' \
            | jq -R . \
            | jq -s -c .)
    fi
    cat > "$fdir/$id.json" <<JSON
[{"id":"$id","status":"$status","labels":$labels_json}]
JSON
}

# --- Test 1: open bead → proceed --------------------------------------------
F=$(new_fixture)
write_bead "$F" target open ""
BD_FIXTURE=$F assert_decision "open bead -> proceed" \
    "decision=proceed" -- target

# --- Test 2: closed, no produced-bead-* → friendly-exit ---------------------
F=$(new_fixture)
write_bead "$F" target closed "some-other-label,brainstormed"
BD_FIXTURE=$F assert_decision "closed without produced-bead-* -> friendly-exit" \
    "decision=friendly-exit current=target" -- target

# --- Test 3: closed, single produced-bead-Y, Y exists → forward -------------
F=$(new_fixture)
write_bead "$F" target closed "produced-bead-Y,brainstormed"
write_bead "$F" Y open ""
BD_FIXTURE=$F assert_decision "closed with single produced-bead-Y, Y exists -> forward" \
    "decision=forward target=Y chain=target" -- target

# --- Test 4: closed, single produced-bead-Y, Y missing → halt dangling ------
F=$(new_fixture)
write_bead "$F" target closed "produced-bead-missing"
# Note: no fixture for `missing` → mock bd exits 1 → preflight reports dangling.
BD_FIXTURE=$F assert_decision "closed with single produced-bead-Y, Y missing -> halt dangling" \
    "decision=halt reason=dangling original=target intermediate=target y=missing" -- target

# --- Test 5: closed, two produced-bead-* labels → halt multiple -------------
F=$(new_fixture)
write_bead "$F" target closed "produced-bead-Y,produced-bead-Z"
BD_FIXTURE=$F assert_decision "closed with two produced-bead-* labels -> halt multiple" \
    "decision=halt reason=multiple original=target intermediate=target labels=" -- target

# --- Test 6: closed, single produced-bead-Y, Y already in chain → halt cycle
# The agent has already visited Y earlier in the chain; the current closed
# bead "current" carries produced-bead-Y, which would loop back.
F=$(new_fixture)
write_bead "$F" current closed "produced-bead-Y"
write_bead "$F" Y open ""
BD_FIXTURE=$F assert_decision "closed with produced-bead-Y already in chain -> halt cycle" \
    "decision=halt reason=cycle original=Y chain=Y,current,Y" \
    -- current --original=Y --chain=Y

# --- Test 7: closed, label "produced-bead-" (empty Y) → halt error ---------
# An invalid label like "produced-bead-" (no Y suffix) MUST NOT silently
# collapse to friendly-exit — it is an invalid forward pointer and must
# halt with an explicit error so the operator can investigate label
# correctness.
F=$(new_fixture)
write_bead "$F" target closed "produced-bead-"
BD_FIXTURE=$F assert_decision "closed with produced-bead- (empty Y) -> halt error" \
    "decision=halt reason=error message=invalid-produced-bead-label-empty-y original=target intermediate=target" \
    -- target

# --- Summary ---------------------------------------------------------------
TOTAL=$((PASS + FAIL))
printf '\n%d/%d passed, %d failed\n' "$PASS" "$TOTAL" "$FAIL"

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
exit 0
