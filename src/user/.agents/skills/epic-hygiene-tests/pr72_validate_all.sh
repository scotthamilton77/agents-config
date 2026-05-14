#!/usr/bin/env bash
# PR #72 stress-test — Driver. Runs Groups A → F in order, aggregates exit
# codes, prints a per-group summary at the end. Not picked up by the
# project test gate (no _test.sh suffix); invoke manually.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Two parallel positional lists: group-letter at index N, script name at N.
# Earlier driver used a single `GROUPS=("A:foo" "B:bar")` array; some shells
# in this environment mishandle expansion of array-literal strings that mix
# colons + brace-pattern slicing. Two parallel plain string variables and an
# explicit numeric loop avoid that path entirely.
GROUP_A_SCRIPT="pr72_validate_a_test.sh"
GROUP_B_SCRIPT="pr72_validate_b_test.sh"
GROUP_C_SCRIPT="pr72_validate_c_test.sh"
GROUP_D_SCRIPT="pr72_validate_d_test.sh"
GROUP_E_SCRIPT="pr72_validate_e_test.sh"
GROUP_F_SCRIPT="pr72_validate_f_test.sh"

run_group() {
    local letter="$1" script="$2"
    local path="$SCRIPT_DIR/$script"
    echo
    echo "============================================================"
    echo "[GROUP $letter] $script"
    echo "============================================================"
    if [ ! -f "$path" ]; then
        echo "ERROR: $path not found"
        return 2
    fi
    bash "$path"
}

OVERALL=0
RESULT_A="?"; RESULT_B="?"; RESULT_C="?"; RESULT_D="?"; RESULT_E="?"; RESULT_F="?"

run_group A "$GROUP_A_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_A=pass || { RESULT_A=fail; OVERALL=1; }
run_group B "$GROUP_B_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_B=pass || { RESULT_B=fail; OVERALL=1; }
run_group C "$GROUP_C_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_C=pass || { RESULT_C=fail; OVERALL=1; }
run_group D "$GROUP_D_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_D=pass || { RESULT_D=fail; OVERALL=1; }
run_group E "$GROUP_E_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_E=pass || { RESULT_E=fail; OVERALL=1; }
run_group F "$GROUP_F_SCRIPT"; rc=$?; [ $rc -eq 0 ] && RESULT_F=pass || { RESULT_F=fail; OVERALL=1; }

echo
echo "============================================================"
echo "SUMMARY"
echo "============================================================"
echo "GROUP A: $RESULT_A"
echo "GROUP B: $RESULT_B"
echo "GROUP C: $RESULT_C"
echo "GROUP D: $RESULT_D"
echo "GROUP E: $RESULT_E"
echo "GROUP F: $RESULT_F"

if [ "$OVERALL" -eq 0 ]; then
    echo "ALL GROUPS PASSED"
else
    echo "AT LEAST ONE GROUP FAILED"
fi
exit "$OVERALL"
