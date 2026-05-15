#!/usr/bin/env bash
# Red-phase tests for AC bullets 13, 14, 15 of agents-config-pqvc:
# collect.py classification of the NEW Y_container / Y_impl shape produced
# by brainstorm-bead finalize after the pqvc restructure.
#
# AC bullet coverage:
#  13 — collect.py.is_container() returns True for a Y_container:
#         type=epic, no impl-ready labels, has ≥1 non-gate active child
#         (the Y_impl).
#  14 — collect.py.is_impl_candidate() returns False for that same
#         Y_container (epics never route to implementation).
#  15 — collect.py.is_container() returns False for a Y_impl:
#         type=feature, carries implementation-ready, has NO active
#         non-gate / non-human children — so it is a leaf impl bead, not
#         a container.
#         is_impl_candidate() returns True for that Y_impl (it surfaces
#         in the implementation-ready section).
#
# These probe collect.py directly using the same import/inject pattern as
# whats-next/collect_test.sh (no live bd backend required). The fixtures
# correspond to the post-pqvc-restructure shape:
#
#       X (closed) ──(produced-bead-<Y_container_id>)──▶ Y_container (epic)
#                                                          │
#                                                          ├─ Y_impl (feature, impl-ready)
#                                                          ├─ merge-gate child (excluded from count)
#                                                          └─ [optional] human verify child (excluded from count)
#
# These are red-phase: SHOULD FAIL until the pqvc restructure lands AND
# collect.py is verified end-to-end against the new shape. The current
# collect.py already implements the relevant filter logic (see Filter
# Matrix in collect.py), so most assertions may in fact already pass
# behaviorally — but the test asserts the EXACT post-restructure contract:
# Y_container fixtures and Y_impl fixtures are first-class probe inputs.
# Any future regression in is_container / is_impl_candidate that breaks
# this contract will be caught here. The red-phase failure surface for
# THIS iteration is the absence of the file itself — adding it
# establishes the regression net.

set -u

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [ "$REPO_ROOT" != "/" ] && [ ! -d "$REPO_ROOT/src/user/.agents/skills/whats-next" ]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[ -d "$REPO_ROOT/src/user/.agents/skills/whats-next" ] \
    || fail "could not locate repo root containing src/user/.agents/skills/whats-next"

COLLECT_PY="$REPO_ROOT/src/user/.agents/skills/whats-next/collect.py"
[ -f "$COLLECT_PY" ] || fail "collect.py not found at $COLLECT_PY"
command -v python3 >/dev/null 2>&1 || fail "python3 required"

# ---------------------------------------------------------------------------
# T1 — is_container() returns True for a Y_container (epic with active
# non-gate child).  AC 13.
# ---------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T1: is_container() must return True for Y_container (epic with active non-gate children)"
import importlib.util, sys, inspect
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, "is_container"), "is_container function not defined"

# Y_container has at least one active non-gate child (the Y_impl).
# Install the active_child_count index that main() would build at runtime.
YC = "proj-yc-001"
YI = "proj-yi-002"

sig = inspect.signature(mod.is_container)
nparams = len(sig.parameters)

if nparams == 2:
    setattr(mod, "active_child_count", {YC: 1, YI: 0})
    res = mod.is_container(YC, "epic")
    assert res is True, f"Y_container (epic) must be a container; got {res!r}"
elif nparams == 3:
    cc = {YC: 1, YI: 0}
    res = mod.is_container(YC, "epic", cc)
    assert res is True, f"Y_container (epic) must be a container; got {res!r}"
else:
    raise AssertionError(f"is_container has unexpected arity {nparams}")
PY
pass "T1: is_container(Y_container, 'epic') == True"

# ---------------------------------------------------------------------------
# T2 — is_impl_candidate() returns False for that same Y_container.
# AC 14.  Epics are always containers, must never route to implementation.
# ---------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T2: is_impl_candidate() must return False for Y_container (epic, never routes to impl)"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert hasattr(mod, "is_impl_candidate"), "is_impl_candidate function not defined"

YC = "proj-yc-001"
YI = "proj-yi-002"
setattr(mod, "active_child_count", {YC: 1, YI: 0})

# Y_container shape: epic type, no impl-ready labels (Rule C), has Y_impl as child.
yc_bead = {
    "id": YC,
    "issue_type": "epic",
    # Per AC 3, Y_container carries NONE of the impl-ready labels.
    "labels": ["produced-from-source-x"],
    "status": "open",
}
res = mod.is_impl_candidate(yc_bead)
assert res is False, f"Y_container must NOT be an impl candidate; got {res!r}"

# Defence-in-depth: even if Y_container ACCIDENTALLY carried
# `implementation-ready` (a Rule C violation), is_impl_candidate must
# still reject it because is_container() is True for any epic.
yc_violator = dict(yc_bead, labels=["implementation-ready"])
res2 = mod.is_impl_candidate(yc_violator)
assert res2 is False, (
    f"Y_container (epic) with stray implementation-ready label must still "
    f"be rejected from impl-ready (Rule C defence in depth); got {res2!r}"
)
PY
pass "T2: is_impl_candidate(Y_container) == False"

# ---------------------------------------------------------------------------
# T3 — is_container() returns False for a Y_impl (feature, impl-ready, no
# active non-gate/non-human children).  AC 15 part 1.
# ---------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T3: is_container() must return False for Y_impl (feature, no non-gate children)"
import importlib.util, sys, inspect
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

YC = "proj-yc-001"
YI = "proj-yi-002"

sig = inspect.signature(mod.is_container)
nparams = len(sig.parameters)

# active_child_count is built in main() to EXCLUDE merge-gate and human
# labeled children. So a Y_impl that has only a merge-gate child (and
# optionally a [Human verify] child) has active_child_count[YI] == 0.
if nparams == 2:
    setattr(mod, "active_child_count", {YC: 1, YI: 0})
    res = mod.is_container(YI, "feature")
    assert res is False, f"Y_impl (feature, no non-gate children) must NOT be a container; got {res!r}"
elif nparams == 3:
    cc = {YC: 1, YI: 0}
    res = mod.is_container(YI, "feature", cc)
    assert res is False, f"Y_impl (feature, no non-gate children) must NOT be a container; got {res!r}"
else:
    raise AssertionError(f"is_container has unexpected arity {nparams}")
PY
pass "T3: is_container(Y_impl, 'feature') == False"

# ---------------------------------------------------------------------------
# T4 — is_impl_candidate() returns True for the Y_impl.  AC 15 part 2.
# ---------------------------------------------------------------------------
python3 - "$COLLECT_PY" <<'PY' || fail "T4: is_impl_candidate() must return True for Y_impl (feature with implementation-ready, no non-gate children)"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("collect_mod", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

YC = "proj-yc-001"
YI = "proj-yi-002"
setattr(mod, "active_child_count", {YC: 1, YI: 0})

# Y_impl shape per AC 2: feature, carries the full impl-ready label set.
yi_bead = {
    "id": YI,
    "issue_type": "feature",
    "labels": [
        "produced-from-source-x",
        "formula-implement-feature",
        "brainstormed",
        "implementation-ready",
        "implementation-readied-session-deadbeef",
    ],
    "status": "open",
}
res = mod.is_impl_candidate(yi_bead)
assert res is True, (
    f"Y_impl (feature with implementation-ready, no non-gate children) "
    f"must surface as an impl candidate; got {res!r}"
)
PY
pass "T4: is_impl_candidate(Y_impl) == True"

# ---------------------------------------------------------------------------
# T5 — collect.py documentation references the canonical post-pqvc
# terminology by name: 'Y_container' AND 'Y_impl'.  AC 13/14/15 introduce
# this naming; the Filter Matrix and is_container() docstring should
# mention both terms so future maintainers can connect collect.py's
# behavior to the brainstorm-bead finalize 2-level shape.
#
# This is the red-phase failure surface for THIS test file: today the
# module describes the shape using the older "feature-Y impl beads"
# phrasing only. Green-phase will update the docstring/Filter Matrix to
# spell out Y_container / Y_impl explicitly.
# ---------------------------------------------------------------------------
grep -q 'Y_container' "$COLLECT_PY" \
    || fail "T5: collect.py does not reference 'Y_container' in its documentation (post-pqvc canonical name; AC 13/14)"
grep -q 'Y_impl' "$COLLECT_PY" \
    || fail "T5: collect.py does not reference 'Y_impl' in its documentation (post-pqvc canonical name; AC 15)"
pass "T5: collect.py documentation uses Y_container / Y_impl terminology"

echo "All pqvc collect.py classification red-phase tests reached — exit 0 only when every assertion passes."
