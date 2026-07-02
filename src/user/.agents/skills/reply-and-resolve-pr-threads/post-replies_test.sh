#!/usr/bin/env bash
# Smoke test for post-replies.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/post-replies.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

assert() {
  if eval "$2"; then
    echo "  ok: $1"
  else
    echo "  FAIL: $1"
    FAIL=1
  fi
}

echo "[post-replies_test]"

assert "script file exists" "[ -f '$SCRIPT' ]"
assert "script is executable" "[ -x '$SCRIPT' ]"
assert "uses set -euo pipefail" "grep -qE 'set -euo pipefail' '$SCRIPT'"
assert "documents inputs/outputs in header" "head -50 '$SCRIPT' | grep -qiE 'input|output|exit'"
assert "accepts --inventory flag" "grep -q -- '--inventory' '$SCRIPT'"
assert "accepts --owner flag" "grep -q -- '--owner' '$SCRIPT'"
assert "accepts --repo flag" "grep -q -- '--repo' '$SCRIPT'"
assert "accepts --pr flag" "grep -q -- '--pr' '$SCRIPT'"

# --- Fake-gh shim: validates endpoint + required flags; logs every call ---
# Why validate, not just exit 0: a bare `exit 0` shim cannot catch wrong-
# endpoint regressions (e.g., review_summary accidentally hitting the
# /pulls/.../replies path, or a missing --method POST / --field body=@-).
# Logging to $FAKE_GH_LOG lets behavior tests assert which endpoint was hit
# per kind.
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
export FAKE_GH_LOG="$TMP/fake-gh.log"
cat > "$FAKEBIN/gh" <<'FAKE'
#!/usr/bin/env bash
# Fake gh — validates endpoint + required flags; logs every invocation.
LOG="${FAKE_GH_LOG:-/tmp/fake-gh.log}"
echo "$@" >> "$LOG"
# Locate the endpoint arg (first positional after 'api', skipping flags).
endpoint=""
saw_api=0
skip_next=0
for a in "$@"; do
  if [ "$skip_next" = "1" ]; then skip_next=0; continue; fi
  case "$a" in
    api) saw_api=1; continue ;;
    --method|--field|-f|-F|-H|--header|--input|--hostname)
      skip_next=1; continue ;;
    --*=*) continue ;;
    --*) continue ;;
    *)
      if [ "$saw_api" = "1" ] && [ -z "$endpoint" ]; then endpoint="$a"; fi
      ;;
  esac
done
case "$endpoint" in
  repos/*/*/issues/*/comments) ;;
  repos/*/*/pulls/*/comments/*/replies)
    cid_segment="$(echo "$endpoint" | awk -F/ '{print $(NF-1)}')"
    if ! [[ "$cid_segment" =~ ^[0-9]+$ ]]; then
      echo "fake-gh: non-numeric comment id in pulls/.../replies endpoint: $cid_segment" >&2
      exit 2
    fi
    ;;
  *)
    echo "fake-gh: unexpected endpoint: $endpoint" >&2
    exit 2 ;;
esac
case " $* " in
  *" --method POST "*) ;;
  *) echo "fake-gh: missing --method POST" >&2; exit 2 ;;
esac
case " $* " in
  *" --field body=@- "*) ;;
  *) echo "fake-gh: missing --field body=@- (stdin body contract)" >&2; exit 2 ;;
esac
# Drain stdin (body) so the caller's pipe doesn't error.
cat >/dev/null
exit 0
FAKE
chmod +x "$FAKEBIN/gh"

# Inventory fixture matching the real schema produced by build-inventory-body.sh:
#   review_thread → top-level .reply_to_comment_id (numeric)
#   issue_comment → top-level .issue_comment_id (numeric)
# NO top-level .comment_id field exists in real inventories.
INV_MIXED="$TMP/inv-mixed.json"
cat >"$INV_MIXED" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_kwDO_thread1",
      "reply_to_comment_id": 11111,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "Fixed in abc123. (apostrophe's are fine.)"
    },
    {
      "kind": "issue_comment",
      "thread_id": null,
      "reply_to_comment_id": null,
      "issue_comment_id": 22222,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "Acknowledged on issue comment."
    }
  ]
}
JSON

# Behavior test: --skip-comment-ids must be accepted as a flag.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_MIXED" --owner o --repo r --pr 1 \
  --skip-comment-ids "11111,22222" > "$TMP/skip-out.txt" 2>&1
rc_skip=$?
assert "--skip-comment-ids is not rejected as unknown flag (rc != 2)" \
  "[ \$rc_skip -ne 2 ]"

# Behavior test (POSTED contract): every POSTED line must carry a non-empty
# comment_id token. Regression guard against a prior bug where the script
# read a non-existent .comment_id field and emitted 'POSTED ' (empty token
# after the space) for every successful post.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_MIXED" --owner o --repo r --pr 1 \
  > "$TMP/posted-out.txt" 2>&1
rc_posted=$?
if [ "$rc_posted" = "0" ]; then
  echo "  ok: mixed-kind inventory exits 0 with successful fake gh"
else
  echo "  FAIL: mixed-kind inventory should exit 0; got $rc_posted; output: $(cat "$TMP/posted-out.txt")"
  FAIL=1
fi
if grep -qE '^POSTED 11111$' "$TMP/posted-out.txt"; then
  echo "  ok: review_thread POSTED line names .reply_to_comment_id (11111)"
else
  echo "  FAIL: expected 'POSTED 11111' for review_thread; got: $(cat "$TMP/posted-out.txt")"
  FAIL=1
fi
if grep -qE '^POSTED 22222$' "$TMP/posted-out.txt"; then
  echo "  ok: issue_comment POSTED line names .issue_comment_id (22222)"
else
  echo "  FAIL: expected 'POSTED 22222' for issue_comment; got: $(cat "$TMP/posted-out.txt")"
  FAIL=1
fi
if grep -qE '^POSTED[[:space:]]*$' "$TMP/posted-out.txt"; then
  echo "  FAIL: emitted 'POSTED' with empty comment_id (cid-dispatch regression)"
  FAIL=1
else
  echo "  ok: no 'POSTED <empty>' lines"
fi

# Behavior test (SKIP contract with real id shape): passing the real numeric
# ids in --skip-comment-ids must SKIP both items.
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_MIXED" --owner o --repo r --pr 1 \
  --skip-comment-ids "11111,22222" > "$TMP/skipped-out.txt" 2>&1
if grep -qE '^SKIPPED 11111$' "$TMP/skipped-out.txt" && grep -qE '^SKIPPED 22222$' "$TMP/skipped-out.txt"; then
  echo "  ok: --skip-comment-ids matches real id fields per kind"
else
  echo "  FAIL: --skip-comment-ids did not match; got: $(cat "$TMP/skipped-out.txt")"
  FAIL=1
fi

# Behavior test (FAILED contract): when gh fails, the FAILED line must (a)
# carry a non-empty cid, (b) surface the underlying gh stderr instead of the
# bare 'gh-rest-reply-failed' label. Regression guard against prior silent
# failures where the cid was empty and the gh stderr was swallowed.
FAKEBIN_FAIL="$TMP/bin-fail"
mkdir -p "$FAKEBIN_FAIL"
cat > "$FAKEBIN_FAIL/gh" <<'FAKE'
#!/usr/bin/env bash
echo "HTTP 422: Validation Failed (fake-gh-stderr-marker)" >&2
exit 1
FAKE
chmod +x "$FAKEBIN_FAIL/gh"

PATH="$FAKEBIN_FAIL:$PATH" "$SCRIPT" --inventory "$INV_MIXED" --owner o --repo r --pr 1 \
  > "$TMP/failed-out.txt" 2>&1
rc_failed=$?
if [ "$rc_failed" = "1" ]; then
  echo "  ok: failing gh causes exit 1"
else
  echo "  FAIL: failing gh should exit 1; got $rc_failed"
  FAIL=1
fi
if grep -qE '^FAILED 11111 ' "$TMP/failed-out.txt"; then
  echo "  ok: FAILED line for review_thread names .reply_to_comment_id (11111)"
else
  echo "  FAIL: expected 'FAILED 11111 ...'; got: $(cat "$TMP/failed-out.txt")"
  FAIL=1
fi
if grep -qE '^FAILED 22222 ' "$TMP/failed-out.txt"; then
  echo "  ok: FAILED line for issue_comment names .issue_comment_id (22222)"
else
  echo "  FAIL: expected 'FAILED 22222 ...'; got: $(cat "$TMP/failed-out.txt")"
  FAIL=1
fi
if grep -qE '^FAILED[[:space:]]+[^[:space:]]+[[:space:]]+gh-[a-z-]+-failed[[:space:]]*$' "$TMP/failed-out.txt"; then
  echo "  FAIL: FAILED line ends at bare reason label (gh stderr swallowed)"
  FAIL=1
else
  echo "  ok: FAILED line carries content beyond the bare reason label"
fi
if grep -q 'fake-gh-stderr-marker' "$TMP/failed-out.txt"; then
  echo "  ok: FAILED line surfaces underlying gh stderr"
else
  echo "  FAIL: gh stderr ('fake-gh-stderr-marker') not surfaced; got: $(cat "$TMP/failed-out.txt")"
  FAIL=1
fi

# Behavior test: items missing reply_body must emit FAILED <cid> reply_body_missing
# with a non-empty cid, and process must exit 1.
INV_NO_BODY="$TMP/inv-no-body.json"
cat >"$INV_NO_BODY" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_x",
      "reply_to_comment_id": 33333,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed"
    }
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_NO_BODY" --owner o --repo r --pr 1 \
  > "$TMP/nobody-out.txt" 2>&1
rc_nobody=$?
if [ "$rc_nobody" = "1" ]; then
  echo "  ok: missing reply_body causes exit 1"
else
  echo "  FAIL: missing reply_body should exit 1, got $rc_nobody"
  FAIL=1
fi
if grep -qE '^FAILED 33333 reply_body_missing$' "$TMP/nobody-out.txt"; then
  echo "  ok: emits FAILED <cid> reply_body_missing with non-empty cid"
else
  echo "  FAIL: missing 'FAILED 33333 reply_body_missing'; got: $(cat "$TMP/nobody-out.txt")"
  FAIL=1
fi

# Behavior test: ESCALATE+escalation_filed=true items must be POSTED (not FILTERED).
INV_ESCALATE="$TMP/inv-escalate.json"
cat >"$INV_ESCALATE" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_kwDO_escalate",
      "reply_to_comment_id": 44444,
      "issue_comment_id": null,
      "classification": "ESCALATE",
      "escalation_filed": true,
      "reply_body": "Captured for follow-up; will respond on a later push to this PR or in a related issue.",
      "rationale": "needs human review"
    }
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_ESCALATE" --owner o --repo r --pr 1 \
  > "$TMP/escalate-out.txt" 2>&1
rc_escalate=$?
if [ "$rc_escalate" = "0" ] && grep -qE '^POSTED 44444$' "$TMP/escalate-out.txt"; then
  echo "  ok: ESCALATE+escalation_filed=true is POSTED (not FILTERED)"
else
  echo "  FAIL: ESCALATE+escalation_filed=true should exit 0 with POSTED 44444; got rc=$rc_escalate, output: $(cat "$TMP/escalate-out.txt")"
  FAIL=1
fi

# Behavior test (review_summary support): review_summary items have all
# three id fields null (validation guard 3) — must dispatch to the issue
# comments endpoint, synthesize a stable non-empty cid, and POST cleanly.
INV_RSUM="$TMP/inv-rsum.json"
cat >"$INV_RSUM" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_summary",
      "thread_id": null,
      "reply_to_comment_id": null,
      "issue_comment_id": null,
      "classification": "SKIP",
      "reply_body": "Acknowledged review summary; no per-thread action required."
    }
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_RSUM" --owner o --repo r --pr 1 \
  > "$TMP/rsum-out.txt" 2>&1
rc_rsum=$?
if [ "$rc_rsum" = "0" ] && grep -qE '^POSTED summary-[0-9a-f]+$' "$TMP/rsum-out.txt"; then
  echo "  ok: review_summary POSTED with synthetic non-empty cid"
else
  echo "  FAIL: review_summary should POST with 'POSTED summary-<hash>'; got rc=$rc_rsum output: $(cat "$TMP/rsum-out.txt")"
  FAIL=1
fi
# Same-content re-run must produce the SAME synthetic cid (idempotency anchor).
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_RSUM" --owner o --repo r --pr 1 \
  > "$TMP/rsum-out2.txt" 2>&1
cid1="$(grep -oE 'summary-[0-9a-f]+' "$TMP/rsum-out.txt"  | head -1)"
cid2="$(grep -oE 'summary-[0-9a-f]+' "$TMP/rsum-out2.txt" | head -1)"
if [ -n "$cid1" ] && [ "$cid1" = "$cid2" ]; then
  echo "  ok: review_summary synthetic cid is stable across runs ($cid1)"
else
  echo "  FAIL: review_summary synthetic cid not stable; first=$cid1 second=$cid2"
  FAIL=1
fi

# Behavior test (cross-version stability anchor): review_summary cid for a
# pinned fixture item must equal a known hash. Regression guard against
# removing `-c` from the jq canonicalization in the dispatch — jq's
# pretty-print whitespace varies across versions/platforms, so without `-c`
# the hash drifts and idempotency breaks across environments. The expected
# hash below was computed via:
#   printf '%s' "$item" | jq -c --sort-keys . | shasum -a 1 \
#     | cut -d' ' -f1 | cut -c1-12
# against the INV_RSUM fixture item content above.
EXPECTED_RSUM_CID="summary-aad5a242e21c"
if grep -qE "^POSTED ${EXPECTED_RSUM_CID}\$" "$TMP/rsum-out.txt"; then
  echo "  ok: review_summary cid matches pinned canonical hash ($EXPECTED_RSUM_CID)"
else
  echo "  FAIL: review_summary cid does not match pinned hash; expected $EXPECTED_RSUM_CID, got: $(grep '^POSTED summary-' "$TMP/rsum-out.txt")"
  FAIL=1
fi

# Behavior tests (endpoint correctness): each kind must dispatch to the
# correct REST endpoint. These guard against regressions where, e.g.,
# review_summary accidentally hit /pulls/.../replies — a bug the old
# always-exit-0 fake gh would not have caught.

# review_summary → /issues/N/comments (NOT /pulls/...).
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_RSUM" --owner o --repo r --pr 1 \
  > "$TMP/rsum-endpoint-out.txt" 2>&1
if grep -qE 'repos/o/r/issues/1/comments' "$FAKE_GH_LOG" \
   && ! grep -qE 'repos/o/r/pulls/' "$FAKE_GH_LOG"; then
  echo "  ok: review_summary hits /issues/N/comments (not /pulls/...)"
else
  echo "  FAIL: review_summary endpoint wrong; fake-gh log: $(cat "$FAKE_GH_LOG")"
  FAIL=1
fi

# review_thread → /pulls/N/comments/<reply_to>/replies.
: > "$FAKE_GH_LOG"
INV_RT="$TMP/inv-rt.json"
cat >"$INV_RT" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"kind":"review_thread","thread_id":"T_x","reply_to_comment_id":99999,"issue_comment_id":null,"classification":"FIX","fix_outcome":"committed","reply_body":"ok"}
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_RT" --owner o --repo r --pr 1 \
  > "$TMP/rt-endpoint-out.txt" 2>&1
if grep -qE 'repos/o/r/pulls/1/comments/99999/replies' "$FAKE_GH_LOG"; then
  echo "  ok: review_thread hits /pulls/N/comments/<reply_to>/replies"
else
  echo "  FAIL: review_thread endpoint wrong; fake-gh log: $(cat "$FAKE_GH_LOG")"
  FAIL=1
fi

# issue_comment → /issues/N/comments (NOT /pulls/...).
: > "$FAKE_GH_LOG"
INV_IC="$TMP/inv-ic.json"
cat >"$INV_IC" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"kind":"issue_comment","thread_id":null,"reply_to_comment_id":null,"issue_comment_id":88888,"classification":"FIX","fix_outcome":"committed","reply_body":"ok"}
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_IC" --owner o --repo r --pr 1 \
  > "$TMP/ic-endpoint-out.txt" 2>&1
if grep -qE 'repos/o/r/issues/1/comments' "$FAKE_GH_LOG" \
   && ! grep -qE 'repos/o/r/pulls/' "$FAKE_GH_LOG"; then
  echo "  ok: issue_comment hits /issues/N/comments (not /pulls/...)"
else
  echo "  FAIL: issue_comment endpoint wrong; fake-gh log: $(cat "$FAKE_GH_LOG")"
  FAIL=1
fi

# Behavior test (union skip-set): when BOTH the sidecar AND --skip-comment-ids
# carry different cids, both sources must apply (union, not override).
INV_UNION="$TMP/inv-union.json"
cat >"$INV_UNION" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"kind": "review_thread", "thread_id": "T_a", "reply_to_comment_id": 81111, "issue_comment_id": null, "classification": "FIX", "fix_outcome": "committed", "reply_body": "ok"},
    {"kind": "review_thread", "thread_id": "T_b", "reply_to_comment_id": 82222, "issue_comment_id": null, "classification": "FIX", "fix_outcome": "committed", "reply_body": "ok"}
  ]
}
JSON
printf '81111\n' > "${INV_UNION}.posted"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_UNION" --owner o --repo r --pr 1 \
  --skip-comment-ids "82222" > "$TMP/union-out.txt" 2>&1
if grep -qE '^SKIPPED 81111$' "$TMP/union-out.txt" \
   && grep -qE '^SKIPPED 82222$' "$TMP/union-out.txt" \
   && ! grep -qE '^POSTED ' "$TMP/union-out.txt"; then
  echo "  ok: sidecar ∪ --skip-comment-ids both apply (union, not override)"
else
  echo "  FAIL: union skip-set didn't skip both; got: $(cat "$TMP/union-out.txt")"
  FAIL=1
fi

# Behavior test (sidecar idempotency): a successful 100% run MUST delete
# any prior <inventory>.posted sidecar so re-runs don't keep stale state.
INV_SIDECAR_CLEAN="$TMP/inv-sidecar-clean.json"
cat >"$INV_SIDECAR_CLEAN" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_x",
      "reply_to_comment_id": 55555,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "Fixed in def456."
    }
  ]
}
JSON
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_SIDECAR_CLEAN" --owner o --repo r --pr 1 \
  > "$TMP/sidecar-clean-out.txt" 2>&1
if [ -f "${INV_SIDECAR_CLEAN}.posted" ]; then
  echo "  FAIL: 100% success should delete <inventory>.posted sidecar; still present"
  FAIL=1
else
  echo "  ok: 100% success deletes <inventory>.posted sidecar"
fi

# Behavior test (sidecar idempotency): a prior <inventory>.posted sidecar
# MUST be honored as an implicit skip-set on the next invocation. Simulate
# a crashed prior run that already POSTED 55555 before dying.
PRE_POSTED="${INV_SIDECAR_CLEAN}.posted"
printf '55555\n' > "$PRE_POSTED"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_SIDECAR_CLEAN" --owner o --repo r --pr 1 \
  > "$TMP/sidecar-skip-out.txt" 2>&1
if grep -qE '^SKIPPED 55555$' "$TMP/sidecar-skip-out.txt" \
   && ! grep -qE '^POSTED 55555$' "$TMP/sidecar-skip-out.txt"; then
  echo "  ok: prior <inventory>.posted entries are honored as implicit skip-set"
else
  echo "  FAIL: prior sidecar entry 55555 should SKIP (and not POST); got: $(cat "$TMP/sidecar-skip-out.txt")"
  FAIL=1
fi

# Behavior test (sidecar idempotency): a partial-failure run MUST preserve
# the sidecar so the next invocation can pick up where it left off.
INV_SIDECAR_PARTIAL="$TMP/inv-sidecar-partial.json"
cat >"$INV_SIDECAR_PARTIAL" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_a",
      "reply_to_comment_id": 66666,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "ok"
    },
    {
      "kind": "review_thread",
      "thread_id": "T_b",
      "reply_to_comment_id": 77777,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "ok"
    }
  ]
}
JSON
# Fake gh that succeeds for /66666/replies, fails for /77777/replies.
FAKEBIN_PART="$TMP/bin-partial"
mkdir -p "$FAKEBIN_PART"
cat > "$FAKEBIN_PART/gh" <<'FAKE'
#!/usr/bin/env bash
for arg in "$@"; do
  case "$arg" in
    *"/comments/77777/replies"*) echo "fail-on-77777" >&2; exit 1 ;;
  esac
done
exit 0
FAKE
chmod +x "$FAKEBIN_PART/gh"
PATH="$FAKEBIN_PART:$PATH" "$SCRIPT" --inventory "$INV_SIDECAR_PARTIAL" --owner o --repo r --pr 1 \
  > "$TMP/sidecar-partial-out.txt" 2>&1
rc_partial=$?
if [ "$rc_partial" = "1" ]; then
  echo "  ok: partial-failure run exits 1"
else
  echo "  FAIL: partial-failure run should exit 1; got $rc_partial"
  FAIL=1
fi
if [ -f "${INV_SIDECAR_PARTIAL}.posted" ] && grep -qE '^66666$' "${INV_SIDECAR_PARTIAL}.posted"; then
  echo "  ok: partial-failure run preserves sidecar with the 66666 success"
else
  echo "  FAIL: sidecar should exist and contain 66666 after partial run; sidecar=$(cat "${INV_SIDECAR_PARTIAL}.posted" 2>&1 || echo missing)"
  FAIL=1
fi

# Behavior test (sidecar idempotency, --skip-comment-ids): when the operator
# supplies --skip-comment-ids, even a 100%-success run (every item handled
# via sidecar-skip ∪ CSV-skip) MUST preserve the sidecar. The operator has
# externally asserted some items are already done, so the script can NOT
# claim the sidecar is a complete record of what THIS run posted; deleting
# it would lose prior-run POSTED state and let a subsequent retry (without
# the flag) re-post duplicates.
INV_SIDECAR_SKIP_CSV="$TMP/inv-sidecar-skipcsv.json"
cat >"$INV_SIDECAR_SKIP_CSV" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {
      "kind": "review_thread",
      "thread_id": "T_x",
      "reply_to_comment_id": 91111,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "x"
    },
    {
      "kind": "review_thread",
      "thread_id": "T_y",
      "reply_to_comment_id": 92222,
      "issue_comment_id": null,
      "classification": "FIX",
      "fix_outcome": "committed",
      "reply_body": "y"
    }
  ]
}
JSON
# Pre-populate sidecar with X (91111); operator asserts Y (92222) is done.
printf '91111\n' > "${INV_SIDECAR_SKIP_CSV}.posted"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_SIDECAR_SKIP_CSV" --owner o --repo r --pr 1 \
  --skip-comment-ids "92222" > "$TMP/sidecar-skipcsv-out.txt" 2>&1
rc_skipcsv=$?
if [ "$rc_skipcsv" = "0" ]; then
  echo "  ok: sidecar∪CSV-only run (no POST needed) exits 0"
else
  echo "  FAIL: sidecar∪CSV-only run should exit 0; got $rc_skipcsv; out: $(cat "$TMP/sidecar-skipcsv-out.txt")"
  FAIL=1
fi
if [ -f "${INV_SIDECAR_SKIP_CSV}.posted" ] && grep -qE '^91111$' "${INV_SIDECAR_SKIP_CSV}.posted"; then
  echo "  ok: sidecar preserved when --skip-comment-ids supplied (prior-run POSTED record retained)"
else
  echo "  FAIL: sidecar must survive when --skip-comment-ids supplied; sidecar=$(cat "${INV_SIDECAR_SKIP_CSV}.posted" 2>&1 || echo missing)"
  FAIL=1
fi

# Behavior test (whitespace normalization): --skip-comment-ids with spaces in the CSV
# must still match the skipset cids. Regression guard against operators or tooling
# that pass "11111, 22222" instead of "11111,22222".
: > "$FAKE_GH_LOG"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_MIXED" --owner o --repo r --pr 1 \
  --skip-comment-ids "11111, 22222" > "$TMP/csv-ws-out.txt" 2>&1
if grep -qE '^SKIPPED 11111$' "$TMP/csv-ws-out.txt" \
   && grep -qE '^SKIPPED 22222$' "$TMP/csv-ws-out.txt"; then
  echo "  ok: --skip-comment-ids tolerates whitespace in the CSV"
else
  echo "  FAIL: --skip-comment-ids did not match with whitespace; got: $(cat "$TMP/csv-ws-out.txt")"
  FAIL=1
fi

# Behavior test (sidecar append failure is surfaced): if the sidecar path is
# un-writable (simulated by making it a directory), the script must emit a
# WARNING on stderr and exit 1 — NOT silently print POSTED while the state
# write is lost.
INV_WRITE_FAIL="$TMP/inv-write-fail.json"
cat >"$INV_WRITE_FAIL" <<'JSON'
{
  "schema_version": 1,
  "pr": {"number": 1, "owner": "o", "repo": "r"},
  "items": [
    {"kind":"review_thread","thread_id":"T_x","reply_to_comment_id":77777,"issue_comment_id":null,"classification":"FIX","fix_outcome":"committed","reply_body":"ok"}
  ]
}
JSON
# Make the sidecar path a directory so >> fails.
mkdir -p "${INV_WRITE_FAIL}.posted"
PATH="$FAKEBIN:$PATH" "$SCRIPT" --inventory "$INV_WRITE_FAIL" --owner o --repo r --pr 1 \
  > "$TMP/write-fail-out.txt" 2> "$TMP/write-fail-err.txt"
rc_wf=$?
if [ "$rc_wf" = "1" ]; then
  echo "  ok: sidecar append failure causes exit 1"
else
  echo "  FAIL: sidecar append failure should exit 1, got $rc_wf"
  FAIL=1
fi
if grep -q 'sidecar-append-failed' "$TMP/write-fail-err.txt"; then
  echo "  ok: sidecar append failure surfaces WARNING on stderr"
else
  echo "  FAIL: sidecar append failure should emit WARNING with 'sidecar-append-failed'; got stderr: $(cat "$TMP/write-fail-err.txt")"
  FAIL=1
fi
# Cleanup the directory-sidecar so EXIT trap doesn't try to delete a non-empty dir
rmdir "${INV_WRITE_FAIL}.posted" 2>/dev/null || rm -rf "${INV_WRITE_FAIL}.posted"

# Failure path: invoking without --inventory must fail (flag validation)
if "$SCRIPT" --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted invocation without --inventory"
  FAIL=1
else
  echo "  ok: rejects missing --inventory"
fi

# Failure path: bad inventory path must fail
if "$SCRIPT" --inventory /nonexistent/path.json --owner o --repo r --pr 1 2>/dev/null; then
  echo "  FAIL: accepted nonexistent inventory file"
  FAIL=1
else
  echo "  ok: rejects nonexistent inventory file"
fi

# ── posted_reply_id recording ────────────────────────────────────────────────
T16="$(mktemp -d)"
cat > "$T16/gh" <<'STUB'
#!/usr/bin/env bash
if [ "$1" = "api" ]; then
  # POST returns the created comment object, like the real API
  printf '{"id": 777001, "html_url": "https://example.invalid/c/777001"}'
  exit 0
fi
exit 0
STUB
chmod +x "$T16/gh"
jq -n '{schema_version: 1, pr: {}, polling: {}, items: [
  {kind: "issue_comment", issue_comment_id: 4242, thread_id: null, reply_to_comment_id: null,
   author: "reviewer", body_excerpt: "x", classification: "SKIP", rationale: "noise",
   fix_outcome: null, reply_body: "Acknowledged — skipping as cosmetic."}
], crash_recovery: {skill_a_completed: true, last_completed_phase: "7-write-inventory"}}' > "$T16/inv.json"

out16=$(PATH="$T16:$PATH" "$HERE/post-replies.sh" --inventory "$T16/inv.json" --owner o --repo r --pr 1 2>&1)
rc16=$?
assert "post succeeds against stub" "[ \$rc16 -eq 0 ]"
assert "POSTED line emitted" "grep -q 'POSTED 4242' <<<\"\$out16\""
assert "posted_reply_id recorded on the item" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$T16/inv.json\")\" = 777001 ]"
rm -rf "$T16"

# ── idempotent retry: cid must not shift when posted_reply_id gets recorded ──
# review_summary's cid is sha1 of the item JSON. record_reply_id mutates the
# posted item with posted_reply_id AFTER posting. If the cid hash includes
# that field, a re-read of the item on retry hashes to a DIFFERENT cid, the
# sidecar skip-set (built from the run-1 cid) misses it, and the summary gets
# posted a second time.
T17="$(mktemp -d)"
cat > "$T17/gh" <<'STUB'
#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in
    *"/comments/555017/replies"*) echo "fail-on-555017" >&2; exit 1 ;;
  esac
done
printf '{"id": 900001}'
exit 0
STUB
chmod +x "$T17/gh"

INV17="$T17/inv.json"
jq -n '{schema_version: 1, pr: {number: 1, owner: "o", repo: "r"}, items: [
  {kind: "review_summary", review_id: 17001, thread_id: null, reply_to_comment_id: null, issue_comment_id: null,
   classification: "SKIP", reply_body: "Acknowledged review summary; no per-thread action required."},
  {kind: "review_thread", thread_id: "T_17", reply_to_comment_id: 555017, issue_comment_id: null,
   classification: "FIX", fix_outcome: "committed", reply_body: "will fail first attempt"}
]}' > "$INV17"

out17a=$(PATH="$T17:$PATH" "$HERE/post-replies.sh" --inventory "$INV17" --owner o --repo r --pr 1 2>&1)
rc17a=$?
cid17="$(printf '%s' "$out17a" | grep -oE 'POSTED summary-[0-9a-f]+' | awk '{print $2}')"

assert "run 1: partial failure (thread post fails) exits 1" "[ \$rc17a -eq 1 ]"
assert "run 1: review_summary POSTED with a synthetic cid" "[ -n \"\$cid17\" ]"
assert "run 1: sidecar records the summary cid" \
  "[ -f \"${INV17}.posted\" ] && grep -qF \"\$cid17\" \"${INV17}.posted\""
assert "run 1: posted_reply_id recorded on the review_summary item" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$INV17\")\" = \"900001\" ]"

out17b=$(PATH="$T17:$PATH" "$HERE/post-replies.sh" --inventory "$INV17" --owner o --repo r --pr 1 2>&1)
rc17b=$?
assert "run 2: still partial failure (thread post keeps failing)" "[ \$rc17b -eq 1 ]"
assert "run 2: review_summary is SKIPPED (same cid as run 1), not re-posted" \
  "grep -qF \"SKIPPED \$cid17\" <<<\"\$out17b\""
assert "run 2: review_summary is NOT posted again" \
  "! grep -qE '^POSTED summary-' <<<\"\$out17b\""
assert "run 2: exactly one POST total for the review_summary cid across both runs" \
  "[ \$(printf '%s\n%s' \"\$out17a\" \"\$out17b\" | grep -cF \"POSTED \$cid17\") -eq 1 ]"
assert "run 2: posted_reply_id on the review_summary item is unchanged" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$INV17\")\" = \"900001\" ]"

rm -rf "$T17"

# ── posted_reply_id recording branch coverage ────────────────────────────────
# (a) review_summary branch: recorded onto the matching item by review_id.
T18="$(mktemp -d)"
cat > "$T18/gh" <<'STUB'
#!/usr/bin/env bash
printf '{"id": 800001}'
exit 0
STUB
chmod +x "$T18/gh"
INV18="$T18/inv.json"
jq -n '{schema_version: 1, pr: {number: 1, owner: "o", repo: "r"}, items: [
  {kind: "review_summary", review_id: 18001, thread_id: null, reply_to_comment_id: null, issue_comment_id: null,
   classification: "SKIP", reply_body: "Acknowledged."}
]}' > "$INV18"
out18=$(PATH="$T18:$PATH" "$HERE/post-replies.sh" --inventory "$INV18" --owner o --repo r --pr 1 2>&1)
rc18=$?
assert "(a) review_summary+review_id: run succeeds" "[ \$rc18 -eq 0 ]"
assert "(a) review_summary+review_id: posted_reply_id recorded by review_id match" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$INV18\")\" = \"800001\" ]"
rm -rf "$T18"

# (b) review_thread branch: recorded by reply_to_comment_id match.
T19="$(mktemp -d)"
cat > "$T19/gh" <<'STUB'
#!/usr/bin/env bash
printf '{"id": 800002}'
exit 0
STUB
chmod +x "$T19/gh"
INV19="$T19/inv.json"
jq -n '{schema_version: 1, pr: {number: 1, owner: "o", repo: "r"}, items: [
  {kind: "review_thread", thread_id: "T_19", reply_to_comment_id: 612345, issue_comment_id: null,
   classification: "FIX", fix_outcome: "committed", reply_body: "fixed"}
]}' > "$INV19"
out19=$(PATH="$T19:$PATH" "$HERE/post-replies.sh" --inventory "$INV19" --owner o --repo r --pr 1 2>&1)
rc19=$?
assert "(b) review_thread: run succeeds" "[ \$rc19 -eq 0 ]"
assert "(b) review_thread: posted_reply_id recorded by reply_to_comment_id match" \
  "[ \"\$(jq -r '.items[0].posted_reply_id' \"$INV19\")\" = \"800002\" ]"
rm -rf "$T19"

# (c) WARNING fallback: legacy review_summary item WITHOUT review_id ->
# warning to stderr, no crash, no recording.
T20A="$(mktemp -d)"
cat > "$T20A/gh" <<'STUB'
#!/usr/bin/env bash
printf '{"id": 800003}'
exit 0
STUB
chmod +x "$T20A/gh"
INV20A="$T20A/inv.json"
jq -n '{schema_version: 1, pr: {number: 1, owner: "o", repo: "r"}, items: [
  {kind: "review_summary", thread_id: null, reply_to_comment_id: null, issue_comment_id: null,
   classification: "SKIP", reply_body: "Legacy item, no review_id."}
]}' > "$INV20A"
out20a=$(PATH="$T20A:$PATH" "$HERE/post-replies.sh" --inventory "$INV20A" --owner o --repo r --pr 1 2>&1)
rc20a=$?
assert "(c) legacy review_summary w/o review_id: run still succeeds (no crash)" "[ \$rc20a -eq 0 ]"
assert "(c) legacy review_summary w/o review_id: WARNING names the missing review_id" \
  "grep -qi 'lacks review_id' <<<\"\$out20a\""
assert "(c) legacy review_summary w/o review_id: posted_reply_id NOT recorded" \
  "[ \"\$(jq -r '.items[0].posted_reply_id // \"null\"' \"$INV20A\")\" = \"null\" ]"
rm -rf "$T20A"

# (d) WARNING fallback: POST response id that matches NO inventory item ->
# warning, no crash. Simulated via a fake gh that mutates the inventory's
# match field out from under the run between POST and record (a stand-in for
# any real-world skew between the id used to POST and the id later matched).
T20B="$(mktemp -d)"
INV20B="$T20B/inv.json"
jq -n '{schema_version: 1, pr: {number: 1, owner: "o", repo: "r"}, items: [
  {kind: "review_summary", review_id: 20001, thread_id: null, reply_to_comment_id: null, issue_comment_id: null,
   classification: "SKIP", reply_body: "y"}
]}' > "$INV20B"
export NOMATCH_INV="$INV20B"
cat > "$T20B/gh" <<'STUB'
#!/usr/bin/env bash
tmp="$(mktemp)"
jq '.items[0].review_id = 20002' "$NOMATCH_INV" > "$tmp" && mv "$tmp" "$NOMATCH_INV"
printf '{"id": 900099}'
exit 0
STUB
chmod +x "$T20B/gh"
out20b=$(PATH="$T20B:$PATH" "$HERE/post-replies.sh" --inventory "$INV20B" --owner o --repo r --pr 1 2>&1)
rc20b=$?
unset NOMATCH_INV
assert "(d) no-match record: run still succeeds (no crash)" "[ \$rc20b -eq 0 ]"
assert "(d) no-match record: WARNING emitted for the unmatched reply id" \
  "grep -qi 'WARNING' <<<\"\$out20b\""
assert "(d) no-match record: posted_reply_id NOT recorded anywhere" \
  "[ \"\$(jq -r '.items[0].posted_reply_id // \"null\"' \"$INV20B\")\" = \"null\" ]"
rm -rf "$T20B"

exit $FAIL
