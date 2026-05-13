#!/usr/bin/env bash
# Red-phase test for AC4: implement-bead SKILL.md must add 'milestone' to
# the epic → flag-human path. The existing prose at line 98 names only 'epic'
# as the container type that triggers flag-human; the spec mandates that
# 'milestone' is also covered.
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

SKILL="$REPO_ROOT/src/plugins/beads/.agents/skills/implement-bead/SKILL.md"
[ -f "$SKILL" ] || fail "implement-bead SKILL.md not found at $SKILL"

# Find lines in the SKILL that name the type-based flag-human dispatch.
# Current state: "`epic` → flag-human". Required state: both 'epic' AND
# 'milestone' map to flag-human (e.g. "`epic`/`milestone` → flag-human" or
# "epic or milestone → flag-human"). Probe broadly: any line that says
# "<type> → flag-human" must include milestone alongside epic.
flag_human_lines=$(grep -nE 'flag-human' "$SKILL" || true)
[ -n "$flag_human_lines" ] || fail "AC4: no flag-human references found in implement-bead SKILL.md"

# Probe: at least one line within ~120 chars of an "epic" mention and a
# "flag-human" mention must ALSO mention "milestone".
match=$(grep -E '`?epic`?[^a-z]*.*flag-human|flag-human.*`?epic`?' "$SKILL" \
       | grep -F 'milestone' || true)
[ -n "$match" ] \
    || fail "AC4: no line in implement-bead SKILL.md routes BOTH epic AND milestone to flag-human"

pass "AC4: implement-bead SKILL.md routes epic AND milestone to flag-human"
