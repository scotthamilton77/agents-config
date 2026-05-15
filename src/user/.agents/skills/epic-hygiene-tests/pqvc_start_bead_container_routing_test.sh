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
# We probe the SKILL.md prose for each of the three branches. The text
# should describe them within a reasonable window.
python3 - "$SKILL_MD" <<'PY' || fail "T3: SKILL.md container-routing algorithm does not cover all three cardinalities (0 / 1 / multi)"
import re, sys
body = open(sys.argv[1]).read().lower()

# Each branch must be discernible by a numeric cue near a routing verb.
# Zero impl-ready children → Route C.
zero_ok = (
    re.search(r'zero\s+(impl-ready|implementation-ready)', body)
    or re.search(r'no\s+(impl-ready|implementation-ready)\s+child', body)
    or re.search(r'0\s+(impl-ready|implementation-ready)', body)
)
one_ok = (
    re.search(r'(exactly\s+one|one)\s+(impl-ready|implementation-ready)', body)
    or re.search(r'single\s+(impl-ready|implementation-ready)', body)
    or re.search(r'1\s+(impl-ready|implementation-ready)', body)
)
multi_ok = (
    re.search(r'(multiple|several|two\s+or\s+more|>1)\s+(impl-ready|implementation-ready)', body)
    or re.search(r'(multiple|several)\s+(child|children)', body)
)

if not zero_ok:
    raise SystemExit("zero-impl-ready-children branch not described")
if not one_ok:
    raise SystemExit("exactly-one-impl-ready-child branch not described")
if not multi_ok:
    raise SystemExit("multiple-impl-ready-children branch not described")
PY
pass "T3: SKILL.md container-routing covers all three cardinalities"

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
