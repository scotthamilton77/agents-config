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
# container-hep-parent-child: §0 HEP boilerplate must (a) detect whether
# the source bead is a container (epic / milestone / feature-with-active-
# children) and, on the container branch, (b) create the human bead with
# `--parent <source-bead-id>` so it becomes a CHILD of the source bead.
# This sidesteps bd's `blocks` epic wall (cross-type edges hard-error)
# and is the documented gating shape for container sources. Non-
# container sources must still receive a `bd dep add <source> <human>`
# blocker — that is what keeps them out of `bd ready --label
# implementation-ready` between escalation creation and resolution.
# ---------------------------------------------------------------------------
python3 - "$SKILL" <<'PY' || fail "container-hep-parent-child: implement-bead SKILL.md §0 HEP boilerplate does not implement the container parent-child shape correctly"
import re, sys
body = open(sys.argv[1]).read()

# Probe 1 — the container-detection case statement names both `epic` and
# `milestone` arms that set IS_CONTAINER=1, AND has a `feature)` arm
# that uses bd list --parent ... --status open,in_progress --limit 0
# (with a label filter that excludes merge-gate / human children).
container_branch = re.search(
    r'case\s+"?\$?\w+"?\s+in[\s\S]*?'
    r'(?:epic\s*\|\s*milestone|milestone\s*\|\s*epic)\)\s*IS_CONTAINER=1[\s\S]*?'
    r'feature\)[\s\S]*?bd\s+list\s+--parent[\s\S]*?--limit\s+0',
    body,
)
if not container_branch:
    raise SystemExit("missing container-detection case (epic|milestone IS_CONTAINER=1 + feature) bd list --parent --limit 0 probe)")

# Probe 2 — the container branch creates the human bead with --parent
# pointing at the source, AND uses --no-inherit-labels so the human
# bead does not inherit source labels.
container_create = re.search(
    r'bd\s+create\s+--parent\s+"?<?source-bead-id?>?"?\s+--no-inherit-labels',
    body,
)
if not container_create:
    raise SystemExit("container branch must `bd create --parent <source> --no-inherit-labels` for the human bead")

# Probe 3 — non-container sources MUST still receive `bd dep add` so the
# source is gated out of bd ready while the escalation is open. This
# must be conditional on IS_CONTAINER (an unconditional dep would re-
# introduce the cross-type epic-wall error).
dep_add_guarded = re.search(
    r'if\s+\[\s*"?\$IS_CONTAINER"?\s*=\s*"?0"?\s*\][\s\S]*?bd\s+dep\s+add\s+"?<?source-bead-id?>?"?\s+"?\$HUMAN_ID"?',
    body,
)
if not dep_add_guarded:
    raise SystemExit("non-container branch must `bd dep add <source> $HUMAN_ID` under a guard like `if [ \"$IS_CONTAINER\" = \"0\" ]`")
PY
pass "container-hep-parent-child: implement-bead SKILL.md §0 HEP boilerplate creates the human bead as a child of container sources and dep-blocks non-container sources"
