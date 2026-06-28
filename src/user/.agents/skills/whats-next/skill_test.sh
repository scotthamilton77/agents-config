#!/usr/bin/env bash
# Red-phase tests for AC "whats-next SKILL.md: 7-column table, four sections, all-mode default includes implementation":
#   T1. 7-column table header rendered in a SINGLE table-header line:
#       P | Milestone | Feature | Parent Epic | Bead ID | Type | Title
#   T2. All FOUR sections referenced (loose casing/hyphenation accepted):
#         Needs your attention | Planning-ready | Ready to brainstorm | Ready to implement
#   T3. `all`-mode → planning-ready binding is documented tightly: within a
#       5-line window of the SKILL.md text, a backticked `all` (the mode
#       value) and a 'planning' token both appear (e.g. in the intent→mode
#       mapping or an all-mode section list).
#   T4. Intent→mode mapping table-or-list mentions all 5 mode values.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_MD="$SCRIPT_DIR/SKILL.md"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[ -f "$SKILL_MD" ] || fail "SKILL.md not found at $SKILL_MD"

# ---------------------------------------------------------------------------
# T1. 7-column table header — single line, exact column names in order.
# ---------------------------------------------------------------------------
# Build a strict header regex: 7 columns joined by '|', in order.
header_re='\|[[:space:]]*P[[:space:]]*\|[[:space:]]*Milestone[[:space:]]*\|[[:space:]]*Feature[[:space:]]*\|[[:space:]]*Parent Epic[[:space:]]*\|[[:space:]]*Bead ID[[:space:]]*\|[[:space:]]*Type[[:space:]]*\|[[:space:]]*Title[[:space:]]*\|'
grep -Eq "$header_re" "$SKILL_MD" \
    || fail "T1: SKILL.md missing 7-column table header line 'P | Milestone | Feature | Parent Epic | Bead ID | Type | Title' (all on ONE line)"
pass "T1: 7-column header present on a single line"

# ---------------------------------------------------------------------------
# T2. All four section names (or reasonable variants) appear.
#   - "Needs your attention"  (case-insensitive)
#   - "Planning-ready"  or  "Planning Ready" / "Planning ready"
#   - "Ready to brainstorm"  or  "Ready-to-brainstorm"
#   - "Ready to implement"   or  "Ready-to-implement"
# ---------------------------------------------------------------------------
grep -qiE 'needs[[:space:]]+your[[:space:]]+attention' "$SKILL_MD" \
    || fail "T2: missing 'Needs your attention' section"
grep -qiE 'planning[-[:space:]]+ready' "$SKILL_MD" \
    || fail "T2: missing 'Planning-ready' section"
grep -qiE 'ready[-[:space:]]+to[-[:space:]]+brainstorm' "$SKILL_MD" \
    || fail "T2: missing 'Ready to brainstorm' section"
grep -qiE 'ready[-[:space:]]+to[-[:space:]]+implement' "$SKILL_MD" \
    || fail "T2: missing 'Ready to implement' section"
pass "T2: all four section names referenced (with casing/hyphenation variants accepted)"

# ---------------------------------------------------------------------------
# T3. Default-mode → planning-ready binding documented WITHIN a 5-line window.
# Probe: there exists a 5-line window in SKILL.md containing BOTH 'default'
# (case-insensitive) AND a 'planning' token (covering 'planning_ready',
# 'planning-ready', 'Planning-ready', etc.).
# ---------------------------------------------------------------------------
python3 - "$SKILL_MD" <<'PY' || fail "T3: SKILL.md does not bind the \`all\` mode to a planning section within a tight (5-line) window"
import sys, re
path = sys.argv[1]
lines = open(path).readlines()
window = 5
found = False
for i in range(len(lines)):
    chunk = "".join(lines[i:i + window])
    # Backticked `all` matches the mode value specifically (rejects the
    # ubiquitous English word "all"); planning matches the section name.
    if re.search(r"`all`", chunk) and re.search(r"planning", chunk, re.IGNORECASE):
        found = True
        break
if not found:
    print("FAIL: no 5-line window contains both `all` (backticked) and 'planning' tokens", file=sys.stderr)
    sys.exit(1)
PY
pass "T3: SKILL.md documents the \`all\`-mode → planning binding within a 5-line window"

# ---------------------------------------------------------------------------
# T4. Intent→mode mapping references all 5 mode values somewhere in the doc.
# Spec mode values: all, brainstorm, implementation, planning, human.
# ---------------------------------------------------------------------------
for mv in all brainstorm implementation planning human; do
    grep -qiE "(^|[^[:alnum:]_])$mv([^[:alnum:]_]|$)" "$SKILL_MD" \
        || fail "T4: SKILL.md does not mention mode value '$mv' (spec mandates all 5)"
done
pass "T4: SKILL.md references all 5 mode values (all, brainstorm, implementation, planning, human)"

# ---------------------------------------------------------------------------
# T5. Label filtering is documented: the skill must (a) reference the
# `--label` flag, (b) instruct the agent to reduce a natural-language
# qualifier to a canonical stemmed label, and (c) give the installer
# example (installer/installation/installing -> install).
# ---------------------------------------------------------------------------
grep -qE '\-\-label' "$SKILL_MD" \
    || fail "T5: SKILL.md does not document the --label flag"
grep -qiE 'install(er|ation|ing)' "$SKILL_MD" \
    || fail "T5: SKILL.md does not show the installer stemming example"
grep -qiE 'stem|reduc|canonical|root' "$SKILL_MD" \
    || fail "T5: SKILL.md does not instruct stemming the qualifier to a canonical label"
pass "T5: SKILL.md documents --label filtering with the installer stemming example"

# ---------------------------------------------------------------------------
# T6. Show-all phrasing is bound to --limit 0: within a 6-line window there
# must appear both a show-all/everything/more cue and `--limit 0`.
# ---------------------------------------------------------------------------
python3 - "$SKILL_MD" <<'PY' || fail "T6: SKILL.md does not bind show-all/everything/more phrasing to --limit 0 within a tight window"
import sys, re
lines = open(sys.argv[1]).readlines()
window = 6
cue = re.compile(r"show (all|everything|more)|everything", re.IGNORECASE)
for i in range(len(lines)):
    chunk = "".join(lines[i:i + window])
    if cue.search(chunk) and "--limit 0" in chunk:
        sys.exit(0)
print("FAIL: no window binds show-all phrasing to --limit 0", file=sys.stderr)
sys.exit(1)
PY
pass "T6: SKILL.md binds show-all/everything/more phrasing to --limit 0"

echo "All whats-next SKILL.md red-phase tests reached."
