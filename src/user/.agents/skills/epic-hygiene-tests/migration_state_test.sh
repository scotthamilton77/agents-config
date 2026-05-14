#!/usr/bin/env bash
# Red-phase tests for AC "epic-hygiene live bd migrations (abn9.8 / 7bk.19 /
# 7bk.19.9 / bt9e) and post-migration sanity check".
#
# Coverage:
#   abn9.8:     labels stripped AND AC trimmed (no executable
#               "Build passes." style verification text).
#   7bk.19:     labels stripped AND verification AC moved.
#   7bk.19.9:   AC includes grep/smoke verification text moved from parent.
#   bt9e:       reclassified to spike.
#   sanity:     `bd list --type epic --json` open-epic query returns a valid
#               JSON array, and no open epic carries implementation-ready or
#               implementation-readied-session-*.
#
# bd-failure hardening: every `bd` call captures its exit status; the test
# FAILS loud on non-zero or unparseable output instead of silently treating
# bd failures as "empty array".
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v bd >/dev/null 2>&1 || fail "bd CLI not on PATH; migration + sanity-check tests require live bd"
command -v python3 >/dev/null 2>&1 || fail "python3 required for parsing bd output"

# bd_or_fail: run a bd command, capture stdout to TMP_OUT, fail the test if
# bd exited non-zero. Caller passes the failure context string.
TMP_OUT_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_OUT_DIR"' EXIT

bd_or_fail() {
    local context="$1"; shift
    local out_file="$TMP_OUT_DIR/$(echo "$context" | tr '/ ' '_').out"
    local err_file="$TMP_OUT_DIR/$(echo "$context" | tr '/ ' '_').err"
    if ! bd "$@" >"$out_file" 2>"$err_file"; then
        fail "$context: bd $* exited non-zero (stderr: $(cat "$err_file"))"
    fi
    cat "$out_file"
}

# parse_json_or_fail: validate that the captured bd output is parseable JSON.
parse_json_or_fail() {
    local context="$1" payload="$2"
    CTX="$context" PAYLOAD="$payload" python3 -c "
import json, os, sys
try:
    json.loads(os.environ['PAYLOAD'])
except Exception as e:
    print(f'{os.environ.get(\"CTX\", \"?\")}: bd output is not valid JSON: {e}', file=sys.stderr)
    sys.exit(1)
" || fail "$context: bd output unparseable"
}

# -----------------------------------------------------------------------------
# abn9.8 migration: labels stripped AND AC trimmed.
# -----------------------------------------------------------------------------
labels_abn98=$(bd_or_fail "abn9.8 label list" label list agents-config-abn9.8 --json)
parse_json_or_fail "abn9.8 label list" "$labels_abn98"

echo "$labels_abn98" | python3 -c "
import sys, json
labels = json.load(sys.stdin)
bad = [l for l in labels if l == 'implementation-ready' or l == 'brainstormed' or l.startswith('implementation-readied-session-')]
if bad:
    print(f'FAIL: abn9.8 still carries forbidden labels: {bad}', file=sys.stderr)
    sys.exit(1)
" || fail "labels-strip(abn9.8): agents-config-abn9.8 still carries forbidden labels"
pass "labels-strip(abn9.8): agents-config-abn9.8 labels stripped (no impl-ready/brainstormed/readied-session-*)"

# AC trimming — spec replaces verbose verification AC with the bare
# "All [Impl] beads for prgroom complete." line. The trim removes executable
# verification phrases like "Build passes", "Tests pass", "Typecheck passes",
# etc.
ac_abn98_json=$(bd_or_fail "abn9.8 show" show agents-config-abn9.8 --json)
echo "$ac_abn98_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not data:
    print('FAIL: abn9.8 not found', file=sys.stderr); sys.exit(1)
ac = data[0].get('acceptance_criteria', '') or ''
banned_phrases = ['Build passes', 'Tests pass', 'Typecheck passes']
hits = [p for p in banned_phrases if p in ac]
if hits:
    print(f'FAIL: abn9.8 AC still contains executable verification phrases: {hits}', file=sys.stderr)
    print(f'AC body: {ac!r}', file=sys.stderr)
    sys.exit(1)
" || fail "AC-trim(abn9.8): agents-config-abn9.8 AC has not been trimmed of executable verification phrases"
pass "AC-trim(abn9.8): agents-config-abn9.8 AC trimmed (no 'Build passes'/'Tests pass'/'Typecheck passes')"

# -----------------------------------------------------------------------------
# 7bk.19 migration: labels stripped + verification AC moved to 7bk.19.9.
# -----------------------------------------------------------------------------
labels_7bk19=$(bd_or_fail "7bk.19 label list" label list agents-config-7bk.19 --json)
parse_json_or_fail "7bk.19 label list" "$labels_7bk19"

echo "$labels_7bk19" | python3 -c "
import sys, json
labels = json.load(sys.stdin)
bad = [l for l in labels if l == 'implementation-ready' or l == 'brainstormed' or l.startswith('implementation-readied-session-')]
if bad:
    print(f'FAIL: 7bk.19 still carries forbidden labels: {bad}', file=sys.stderr)
    sys.exit(1)
" || fail "labels-strip(7bk.19): agents-config-7bk.19 still carries forbidden labels"
pass "labels-strip(7bk.19): agents-config-7bk.19 labels stripped"

# AC-cleanup: verification AC must have been REMOVED from 7bk.19 (the parent
# epic no longer carries the grep/smoke verification text).
ac_7bk19_json=$(bd_or_fail "7bk.19 show" show agents-config-7bk.19 --json)
echo "$ac_7bk19_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not data:
    print('FAIL: 7bk.19 not found', file=sys.stderr); sys.exit(1)
ac = data[0].get('acceptance_criteria', '') or ''
# Verification text the migration is supposed to MOVE OUT of the epic.
# Probe for any of the recognisable verification tokens.
verification_tokens = ['grep', 'smoke']
hits = [t for t in verification_tokens if t in ac.lower()]
if hits:
    print(f'FAIL: 7bk.19 AC still references verification tokens that should have moved to 7bk.19.9: {hits}', file=sys.stderr)
    print(f'AC body: {ac!r}', file=sys.stderr)
    sys.exit(1)
" || fail "AC-cleanup(7bk.19): agents-config-7bk.19 AC still contains verification text that should have moved"
pass "AC-cleanup(7bk.19): agents-config-7bk.19 AC no longer contains grep/smoke verification text"

# verification-text-migrated: 7bk.19.9 must exist AND its AC must include the
# moved verification text (recognisable by grep/smoke token).
ac_7bk199_json=$(bd_or_fail "7bk.19.9 show" show agents-config-7bk.19.9 --json)
echo "$ac_7bk199_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not data:
    print('FAIL: 7bk.19.9 not found', file=sys.stderr); sys.exit(1)
ac = data[0].get('acceptance_criteria', '') or ''
if not ac.strip():
    print('FAIL: 7bk.19.9 acceptance_criteria empty', file=sys.stderr); sys.exit(1)
verification_tokens = ['grep', 'smoke']
hits = [t for t in verification_tokens if t in ac.lower()]
if not hits:
    print(f'FAIL: 7bk.19.9 AC missing recognisable verification token from migration; expected one of {verification_tokens}', file=sys.stderr)
    print(f'AC body: {ac!r}', file=sys.stderr)
    sys.exit(1)
" || fail "verification-text-migrated(7bk.19.9): agents-config-7bk.19.9 does not contain the migrated verification text"
pass "verification-text-migrated(7bk.19.9): agents-config-7bk.19.9 carries the migrated verification text"

# -----------------------------------------------------------------------------
# bt9e migration: reclassified to spike.
# -----------------------------------------------------------------------------
bt9e_json=$(bd_or_fail "bt9e show" show agents-config-bt9e --json)
type_bt9e=$(echo "$bt9e_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[0].get('issue_type', '') if data else '')
")
[ "$type_bt9e" = "spike" ] \
    || fail "type-spike(bt9e): agents-config-bt9e issue_type is '$type_bt9e', expected 'spike'"
pass "type-spike(bt9e): agents-config-bt9e is type spike"

# -----------------------------------------------------------------------------
# open-epics-sanity-check: `bd list --type epic --json` query succeeds AND
# returns a JSON array. No open epic carries implementation-ready or
# implementation-readied-session-*. (Hardened per CR4: distinguish bd failure
# from empty result.)
#
# `--limit 0` is mandatory — bd list defaults to 50 rows; without an
# explicit limit override, an open epic past the first page would slip
# past the sanity check and let the assertion pass while AC8 is still
# violated. `--status open,in_progress` keeps the inventory focused on
# the rows whose label state actually matters (closed epics are irrelevant).
# -----------------------------------------------------------------------------
epics_json=$(bd_or_fail "list --type epic" list --type epic --status open,in_progress --limit 0 --json)
parse_json_or_fail "list --type epic" "$epics_json"

# Confirm the parsed structure is a list (could legitimately be empty).
echo "$epics_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not isinstance(data, list):
    print(f'FAIL: bd list --type epic --json returned non-list: {type(data).__name__}', file=sys.stderr)
    sys.exit(1)
" || fail "open-epics-sanity-check: bd list --type epic --json did not return a JSON array"

bad_epics=$(echo "$epics_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
bad = []
for b in data:
    if b.get('status') == 'closed':
        continue
    labels = b.get('labels', []) or []
    if 'implementation-ready' in labels or any(l.startswith('implementation-readied-session-') for l in labels):
        bad.append(b.get('id'))
print(','.join(bad))
")
[ -z "$bad_epics" ] \
    || fail "open-epics-sanity-check: open epics still carry implementation-ready labels: $bad_epics"
pass "open-epics-sanity-check: no open epics carry implementation-ready / implementation-readied-session-* labels"

echo "All migration-state red-phase tests passed (abn9.8 + 7bk.19 + 7bk.19.9 + bt9e + open-epics-sanity)."
