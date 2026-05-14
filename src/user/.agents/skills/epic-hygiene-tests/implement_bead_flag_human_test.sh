#!/usr/bin/env bash
# Red-phase test for AC "implement-bead SKILL.md: milestone added to
# epic → flag-human routing": implement-bead SKILL.md must add 'milestone'
# to the epic → flag-human path so container-type beads route consistently.
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

# ---------------------------------------------------------------------------
# cross-type-dep-skip: §0 HEP boilerplate must type-condition the
# `bd dep add` for epic / milestone sources. Without this guard, the
# epic → flag-human path hard-errors on bd's cross-type `blocks` epic
# wall: an epic source cannot block on a task escalation bead. The
# canonical shape is a case statement with an `epic|milestone)` arm
# that skips the dep, plus a `*)` fall-through that issues `bd dep add`
# for leaf sources where the dep is still required for bd ready gating.
# ---------------------------------------------------------------------------
python3 - "$SKILL" <<'PY' || fail "cross-type-dep-skip: implement-bead SKILL.md §0 HEP boilerplate does not type-condition the bd dep add for epic/milestone sources"
import re, sys
body = open(sys.argv[1]).read()
# Probe for a case-statement arm naming epic|milestone (either order)
# whose body is empty (`;;` immediately after the closing paren), i.e.
# the skip arm.
skip = re.search(r'case\s+"?\$?\w+"?\s+in[\s\S]*?(?:epic\s*\|\s*milestone|milestone\s*\|\s*epic)\)\s*;;', body)
if not skip:
    raise SystemExit("no case-statement arm 'epic|milestone)' skipping the bd dep add was found in the HEP boilerplate")
# Probe for the `*) bd dep add ...` fall-through that issues the dep for
# non-container sources. This must live in the same HEP boilerplate.
fall_through = re.search(r'\*\)\s*bd\s+dep\s+add', body)
if not fall_through:
    raise SystemExit("HEP boilerplate has an epic|milestone skip arm but no '*) bd dep add' fall-through for leaf sources")
PY
pass "cross-type-dep-skip: implement-bead SKILL.md §0 HEP boilerplate type-conditions bd dep add for epic/milestone"
