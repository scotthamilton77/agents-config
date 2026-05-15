#!/usr/bin/env bash
# Red-phase tests for AC bullets 8 & 9 of agents-config-pqvc:
# start-bead container-routing for Y_container targets.
#
# AC bullet coverage:
#   8 — start-bead on closed X (carrying produced-bead-<Y_container_id>):
#       preflight forwards to Y_container; then container-routing
#       resolves to Y_impl. End state: Route A on Y_impl.
#   9 — start-bead on open Y_container:
#         - zero impl-ready children     → Route C (brainstorm Y_container)
#         - exactly one impl-ready child → resolve to Y_impl and route via A
#         - multiple impl-ready children → HEP escalation
#
# Targets:
#   - src/plugins/beads/.agents/skills/start-bead/SKILL.md
#
# This is a doc-contract test: the SKILL.md must contain the
# container-routing algorithm prose AND a row in the routing decision
# table covering the open-epic-container-with-impl-ready-children case.

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

SKILL_MD="$REPO_ROOT/src/plugins/beads/.agents/skills/start-bead/SKILL.md"
[ -f "$SKILL_MD" ] || fail "start-bead SKILL.md not found at $SKILL_MD"

# ---------------------------------------------------------------------------
# T1 — SKILL.md documents a container-routing algorithm referenced by name.
# Spec calls this "container-routing" or "container-routing-to-Y_impl".
# ---------------------------------------------------------------------------
grep -qiE 'container[-[:space:]]routing' "$SKILL_MD" \
    || fail "T1: start-bead SKILL.md does not mention a 'container-routing' algorithm by name (per AC 8/9 spec)"
pass "T1: SKILL.md references container-routing algorithm by name"

# ---------------------------------------------------------------------------
# T2 — Container-routing algorithm probes impl-ready children of
# Y_container via 'bd list --parent <Y_container> --label implementation-ready'.
# This is the canonical resolution step described in the spec.
# ---------------------------------------------------------------------------
python3 - "$SKILL_MD" <<'PY' || fail "T2: SKILL.md does not show 'bd list --parent <Y_container> --label implementation-ready' as the resolution probe"
import re, sys
body = open(sys.argv[1]).read()
# Look for the canonical probe: bd list --parent (something) --label implementation-ready
# (or label implementation-ready --parent ... — flag order isn't fixed).
ok = False
for m in re.finditer(r'bd\s+list[^\n]{0,400}', body):
    seg = m.group(0)
    if '--parent' in seg and re.search(r'--label\s+implementation-ready', seg):
        ok = True
        break
if not ok:
    raise SystemExit(
        "no 'bd list --parent <Y_container> --label implementation-ready' "
        "invocation found in start-bead SKILL.md"
    )
PY
pass "T2: SKILL.md shows the impl-ready child probe under Y_container"

# ---------------------------------------------------------------------------
# T3 — Routing handles all three cardinalities: 0 / exactly-1 / multiple
# impl-ready children. (AC 9).
#
# Spec mapping:
#   0 children       → Route C (brainstorm)
#   exactly 1 child  → resolve to Y_impl, then Route A
#   multiple         → HEP escalation
# ---------------------------------------------------------------------------
# We probe the SKILL.md prose for each of the three branches AND verify
# each cardinality cue is co-located (within a small line window) with
# its routing destination:
#   0 children  → Route C
#   1 child     → Y_impl / Route A
#   multiple    → HEP escalation
#
# Cardinality words without destinations (or destinations without
# cardinality words) are not sufficient — the contract is the MAPPING.
python3 - "$SKILL_MD" <<'PY' || fail "T3: SKILL.md container-routing algorithm does not map all three cardinalities to their routing destinations (0→Route C, 1→Y_impl/Route A, multi→HEP)"
import re, sys
body = open(sys.argv[1]).read().lower()
lines = body.split("\n")

# Window: cardinality cue must appear within WINDOW lines of its
# matching destination. 6 lines accommodates a bullet list with a
# routing description on the same or adjacent line.
WINDOW = 6

# Regexes for cardinality cues (per branch) and destination cues.
zero_cue_re = re.compile(
    r'(\bzero\b|\bno\b|\b0\b)\s+(impl-ready|implementation-ready)'
    r'|^[^a-z]*0\s*(impl-ready|implementation-ready|child)',
    re.IGNORECASE,
)
one_cue_re = re.compile(
    r'(\bexactly\s+one\b|\bone\b|\bsingle\b|\b1\b)\s+(impl-ready|implementation-ready)',
    re.IGNORECASE,
)
multi_cue_re = re.compile(
    r'(\bmultiple\b|\bseveral\b|\btwo\s+or\s+more\b|\b>1\b|\b>\s*1\b)\s+'
    r'(impl-ready|implementation-ready|child|children)',
    re.IGNORECASE,
)

route_c_re = re.compile(r'route\s*c\b', re.IGNORECASE)
y_impl_re = re.compile(r'(y[-_]?impl|route\s*a\b)', re.IGNORECASE)
hep_re = re.compile(r'\bhep\b|human[-\s]escalation', re.IGNORECASE)

def line_hits(regex):
    return [i for i, l in enumerate(lines) if regex.search(l)]

def co_located(cue_hits, dest_hits, window=WINDOW):
    for i in cue_hits:
        for j in dest_hits:
            if abs(i - j) <= window:
                return (i, j)
    return None

zero_cues = line_hits(zero_cue_re)
one_cues = line_hits(one_cue_re)
multi_cues = line_hits(multi_cue_re)

route_c = line_hits(route_c_re)
y_impl = line_hits(y_impl_re)
hep = line_hits(hep_re)

if not zero_cues:
    raise SystemExit("zero-impl-ready-children cue not present anywhere")
if not one_cues:
    raise SystemExit("exactly-one-impl-ready-child cue not present anywhere")
if not multi_cues:
    raise SystemExit("multiple-impl-ready-children cue not present anywhere")

zero_map = co_located(zero_cues, route_c)
if not zero_map:
    raise SystemExit(
        f"zero-children cue (lines {zero_cues}) not co-located within "
        f"{WINDOW} lines of a 'Route C' mention (lines {route_c}). "
        f"Spec requires: 0 impl-ready children → Route C."
    )

one_map = co_located(one_cues, y_impl)
if not one_map:
    raise SystemExit(
        f"exactly-one cue (lines {one_cues}) not co-located within "
        f"{WINDOW} lines of a 'Y_impl' or 'Route A' mention (lines {y_impl}). "
        f"Spec requires: 1 impl-ready child → resolve to Y_impl and Route A."
    )

multi_map = co_located(multi_cues, hep)
if not multi_map:
    raise SystemExit(
        f"multiple cue (lines {multi_cues}) not co-located within "
        f"{WINDOW} lines of an 'HEP' / 'human-escalation' mention (lines {hep}). "
        f"Spec requires: multiple impl-ready children → HEP escalation."
    )
PY
pass "T3: SKILL.md container-routing maps 0→Route C, 1→Y_impl/Route A, multi→HEP"

# ---------------------------------------------------------------------------
# T4 — Routing decision table gains the new row for
# 'open epic container with impl-ready child(ren)' → container-routing.
# The new row's RHS should reference container-routing or Y_impl.
# ---------------------------------------------------------------------------
# Find the routing decision table block (delimited by a Routing Decision
# Table heading or the markdown table itself).
python3 - "$SKILL_MD" <<'PY' || fail "T4: routing decision table does not include a row for open-container-with-impl-ready-children"
import re, sys
body = open(sys.argv[1]).read()
# The existing table heading is "Routing Decision Table". Locate it.
m = re.search(r'Routing Decision Table[\s\S]*?(?=\n#+\s|\Z)', body)
if not m:
    raise SystemExit("Routing Decision Table heading not found")
table = m.group(0)
# We expect a row that mentions container-routing (or an analogous reference
# to Y_impl routing) — the new row added per AC.
if not re.search(r'container[-\s]routing', table, re.IGNORECASE) \
   and not re.search(r'Y[-_]?impl', table):
    raise SystemExit("no row references container-routing or Y_impl in the Routing Decision Table")
PY
pass "T4: routing decision table includes container-routing / Y_impl row"

# ---------------------------------------------------------------------------
# T5 — Closed-bead preflight forwarding integrates with container-routing
# (AC 8). After preflight forwards to Y_container (an open epic), the
# container-routing algorithm runs to resolve to Y_impl. SKILL.md must
# document this chained flow.
# ---------------------------------------------------------------------------
python3 - "$SKILL_MD" <<'PY' || fail "T5: SKILL.md does not document closed-bead-preflight forward → container-routing chain"
import re, sys
body = open(sys.argv[1]).read().lower()
# Probe: there exists some passage that mentions BOTH the preflight forward
# (or 'closed-bead-preflight' / 'route z' / 'forward to y_container')
# AND container-routing within ~30 lines of each other.
lines = body.split("\n")
window = 30
hit_forward = [i for i, l in enumerate(lines)
               if 'forward' in l or 'preflight' in l or 'route z' in l]
hit_routing = [i for i, l in enumerate(lines)
               if 'container-routing' in l or 'container routing' in l]
ok = False
for i in hit_forward:
    for j in hit_routing:
        if abs(i - j) <= window:
            ok = True
            break
    if ok:
        break
if not ok:
    raise SystemExit("preflight/forward and container-routing are not co-located within 30 lines")
PY
pass "T5: SKILL.md chains closed-bead-preflight forward → container-routing"

echo "All pqvc start-bead container-routing red-phase tests reached — exit 0 only when every assertion passes."
