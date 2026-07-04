#!/usr/bin/env bash
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/compute-rereview-polling.sh"
FAIL=0
assert() { if eval "$2"; then echo "  ok: $1"; else echo "  FAIL: $1"; FAIL=1; fi; }

# first silent ask on a fresh head exhausts at cap 1
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event silent)
assert "silent from 0 → count 1" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 1 ]"
assert "silent from 0 → exhausted true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# a non-silent (arriving) cycle does not advance the silent count or exhaust
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event none)
assert "none from 0 → count 0" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 0 ]"
assert "none from 0 → exhausted false" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# chatty cap exhausts without touching the silent count
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event chatty-cap)
assert "chatty-cap → count 0" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 0 ]"
assert "chatty-cap → exhausted true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# exhausted is monotonic on the same head
out=$("$SCRIPT" --prior-count 1 --prior-exhausted true --event none)
assert "prior-exhausted stays true" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = true ]"

# a higher explicit cap does not exhaust on the first silent ask
out=$("$SCRIPT" --prior-count 0 --prior-exhausted false --event silent --silent-cap 2)
assert "silent from 0, cap 2 → count 1" "[ \"\$(jq '.rereview_round_count' <<<\"\$out\")\" = 1 ]"
assert "silent from 0, cap 2 → not exhausted" "[ \"\$(jq '.bot_review_cap_exhausted' <<<\"\$out\")\" = false ]"

# bad usage
"$SCRIPT" --prior-count 0 >/dev/null 2>&1; assert "missing --event → exit 2" "[ \$? -eq 2 ]"
"$SCRIPT" --event silent --prior-count x >/dev/null 2>&1; assert "non-int count → exit 2" "[ \$? -eq 2 ]"

exit $FAIL
