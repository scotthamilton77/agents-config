#!/usr/bin/env bash
# PR #72 stress-test — GROUP E: post-migration sanity (regression of
# PR #72 AC #8).
#
# Read-only assertions: no open epic or milestone carries
# implementation-ready / implementation-readied-session-*. These are the
# Rule C invariant violators that the PR #72 migrations stripped; this
# group regresses against re-introduction.
#
# Coverage:
#   E1. `bd list --type epic --status open,in_progress --limit 0 --json`:
#       zero rows carry implementation-ready or implementation-readied-session-*.
#   E2. Same query for milestone-type beads: zero rows.
set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v bd      >/dev/null 2>&1 || fail "bd CLI not on PATH"
command -v jq      >/dev/null 2>&1 || fail "jq required"
command -v python3 >/dev/null 2>&1 || fail "python3 required"

# `--limit 0` ensures the full inventory is returned — `bd list` defaults
# to 50 rows. Without it a violator past row 50 could slip past the
# sanity check.

# =============================================================================
# E1: open epics.
# =============================================================================
EPICS_JSON=$(bd list --type epic --status open,in_progress --limit 0 --json 2>/dev/null) \
    || fail "E1: bd list --type epic failed"
[ -n "$EPICS_JSON" ] || fail "E1: bd list --type epic returned empty stdout"

BAD_EPICS_COUNT=$(echo "$EPICS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not isinstance(data, list):
    raise SystemExit('bd output is not a JSON array')
bad = []
for b in data:
    labels = b.get('labels', []) or []
    if 'implementation-ready' in labels or any(l.startswith('implementation-readied-session-') for l in labels):
        bad.append(b.get('id'))
print(len(bad))
" 2>/dev/null) || fail "E1: failed to parse epic JSON"

# Also surface the offending IDs for debug context.
BAD_EPICS_IDS=$(echo "$EPICS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
bad = []
for b in data:
    labels = b.get('labels', []) or []
    if 'implementation-ready' in labels or any(l.startswith('implementation-readied-session-') for l in labels):
        bad.append(b.get('id'))
print(','.join(bad))
")

if [ "$BAD_EPICS_COUNT" != "0" ]; then
    fail "E1: $BAD_EPICS_COUNT open epic(s) carry forbidden labels: $BAD_EPICS_IDS"
fi
pass "E1: no open epics carry implementation-ready / implementation-readied-session-*"

# =============================================================================
# E2: open milestones.
# =============================================================================
MS_JSON=$(bd list --type milestone --status open,in_progress --limit 0 --json 2>/dev/null) \
    || fail "E2: bd list --type milestone failed"
[ -n "$MS_JSON" ] || fail "E2: bd list --type milestone returned empty stdout"

BAD_MS_COUNT=$(echo "$MS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if not isinstance(data, list):
    raise SystemExit('bd output is not a JSON array')
bad = []
for b in data:
    labels = b.get('labels', []) or []
    if 'implementation-ready' in labels or any(l.startswith('implementation-readied-session-') for l in labels):
        bad.append(b.get('id'))
print(len(bad))
" 2>/dev/null) || fail "E2: failed to parse milestone JSON"

BAD_MS_IDS=$(echo "$MS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
bad = []
for b in data:
    labels = b.get('labels', []) or []
    if 'implementation-ready' in labels or any(l.startswith('implementation-readied-session-') for l in labels):
        bad.append(b.get('id'))
print(','.join(bad))
")

if [ "$BAD_MS_COUNT" != "0" ]; then
    fail "E2: $BAD_MS_COUNT open milestone(s) carry forbidden labels: $BAD_MS_IDS"
fi
pass "E2: no open milestones carry implementation-ready / implementation-readied-session-*"

echo "GROUP E: post-migration sanity passed."
