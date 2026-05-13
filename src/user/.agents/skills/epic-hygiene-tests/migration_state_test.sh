#!/usr/bin/env bash
# Red-phase tests for:
#   AC6 — Migration applied:
#         - abn9.8: labels stripped + AC trimmed
#         - 7bk.19: labels stripped + verification AC moved to 7bk.19.9
#         - bt9e: reclassified to spike
#   AC8 — Post-migration verification:
#         `bd list --type epic --json` query for open epics with
#         implementation-ready or implementation-readied-session-* labels
#         must return empty array.
#
# These tests require the `bd` CLI. If bd is not on PATH, the tests fail loud
# (better than silently green).
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v bd >/dev/null 2>&1 || fail "bd CLI not on PATH; AC6/AC8 tests require live bd"
command -v python3 >/dev/null 2>&1 || fail "python3 required for parsing bd output"

# -----------------------------------------------------------------------------
# AC6a — abn9.8 labels stripped: must NOT carry 'implementation-ready'
#        (and any 'implementation-readied-session-*').
# -----------------------------------------------------------------------------
labels_abn98=$(bd label list agents-config-abn9.8 --json 2>/dev/null || echo '[]')
echo "$labels_abn98" | python3 -c "
import sys, json
labels = json.load(sys.stdin)
bad = [l for l in labels if l == 'implementation-ready' or l.startswith('implementation-readied-session-')]
if bad:
    print(f'FAIL: abn9.8 still carries impl-ready labels: {bad}', file=sys.stderr)
    sys.exit(1)
" || fail "AC6a: agents-config-abn9.8 still carries implementation-ready labels"
pass "AC6a: agents-config-abn9.8 labels stripped"

# -----------------------------------------------------------------------------
# AC6b — 7bk.19 labels stripped + verification AC moved to 7bk.19.9.
# -----------------------------------------------------------------------------
labels_7bk19=$(bd label list agents-config-7bk.19 --json 2>/dev/null || echo '[]')
echo "$labels_7bk19" | python3 -c "
import sys, json
labels = json.load(sys.stdin)
bad = [l for l in labels if l == 'implementation-ready' or l.startswith('implementation-readied-session-')]
if bad:
    print(f'FAIL: 7bk.19 still carries impl-ready labels: {bad}', file=sys.stderr)
    sys.exit(1)
" || fail "AC6b-labels: agents-config-7bk.19 still carries implementation-ready labels"
pass "AC6b: agents-config-7bk.19 labels stripped"

# AC6b also requires 7bk.19.9 to EXIST (verification AC moved there).
exists_7bk199=$(bd show agents-config-7bk.19.9 --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('yes' if d else 'no')
except Exception:
    print('no')
" 2>/dev/null)
[ "$exists_7bk199" = "yes" ] \
    || fail "AC6b: child bead agents-config-7bk.19.9 does not exist (verification AC was supposed to move there)"
pass "AC6b: agents-config-7bk.19.9 exists"

# -----------------------------------------------------------------------------
# AC6c — bt9e reclassified to spike.
# -----------------------------------------------------------------------------
type_bt9e=$(bd show agents-config-bt9e --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d[0].get('issue_type', '') if d else '')
except Exception:
    print('')
")
[ "$type_bt9e" = "spike" ] \
    || fail "AC6c: agents-config-bt9e type is '$type_bt9e', expected 'spike'"
pass "AC6c: agents-config-bt9e is type spike"

# -----------------------------------------------------------------------------
# AC8 — No open epic carries implementation-ready or
#       implementation-readied-session-*.
# -----------------------------------------------------------------------------
bad_epics=$(bd list --type epic --json 2>/dev/null | python3 -c "
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
    || fail "AC8: open epics still carry implementation-ready labels: $bad_epics"
pass "AC8: no open epics carry implementation-ready labels"

echo "AC6 + AC8 migration-state red-phase tests passed."
