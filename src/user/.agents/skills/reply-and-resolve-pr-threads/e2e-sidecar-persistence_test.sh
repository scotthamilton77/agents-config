#!/usr/bin/env bash
# e2e-sidecar-persistence_test.sh — cross-component regression test:
# post-replies.sh's durable reply-id/posted sidecars must survive SKILL.md's
# `$RENDERED="$(mktemp)"` indirection and be discoverable by
# merge-guard/check-merge-eligibility.sh at the CANONICAL inventory path.
#
# Why this test exists: the original post-replies_test.sh always passed a
# stable path directly as --inventory, never exercising the real Phase 2
# sequence where --inventory is a scratch mktemp copy ($RENDERED) distinct
# from the canonical $INVENTORY_FILE. That blind spot let a sidecar get
# silently keyed to the discarded scratch file and orphaned on every
# resume/read, while unit tests stayed green.
#
# This test drives the REAL post-replies.sh using the LITERAL invocation text
# extracted from SKILL.md's "Post replies for every inventory item" code
# block (not a hand-typed re-statement of it), so a flag-name or path-
# derivation drift in SKILL.md's prose fails this test even though SKILL.md
# has no bash test file of its own. It then drives the REAL
# check-merge-eligibility.sh and asserts the agent's own posted reply is
# excluded from the untriaged-feedback blocker.
#
# This test MUST fail if any of the following is reverted:
#   - post-replies.sh: --reply-id-sidecar / --posted-sidecar flag support
#   - SKILL.md: Phase 2 passing those flags keyed to $INVENTORY_FILE (not $RENDERED)
#   - check-merge-eligibility.sh: the *.json.replyids sidecar glob + union
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
POST_REPLIES="$HERE/post-replies.sh"
SKILL_MD="$HERE/SKILL.md"
MERGE_GUARD_DIR="$(cd "$HERE/../merge-guard" && pwd)"
CHECK_ELIGIBILITY="$MERGE_GUARD_DIR/check-merge-eligibility.sh"
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

echo "[e2e-sidecar-persistence_test]"

assert "post-replies.sh exists" "[ -f '$POST_REPLIES' ]"
assert "SKILL.md exists" "[ -f '$SKILL_MD' ]"
assert "check-merge-eligibility.sh exists" "[ -f '$CHECK_ELIGIBILITY' ]"

# ── (a) canonical inventory, shaped like the real convention ────────────────
# <owner>-<repo>-<pr>-<sha>.json, one SKIP issue_comment item, pre-render
# (no .reply_body yet — that only lands on the separate $RENDERED copy,
# mirroring the real Phase 2 split).
OWNER=o
REPO=r
PR=42
FAKE_HOME="$TMP/home"
INV_DIR="$FAKE_HOME/.claude/state/pr-inventory"
mkdir -p "$INV_DIR"
INVENTORY_FILE="$INV_DIR/${OWNER}-${REPO}-${PR}-deadbeefsha1.json"

# The ORIGINAL reviewer's comment this item replies to.
ORIGINAL_COMMENT_ID=900

jq -n --argjson cid "$ORIGINAL_COMMENT_ID" '{
  schema_version: 1,
  pr: {number: 42, owner: "o", repo: "r"},
  items: [
    {
      kind: "issue_comment",
      thread_id: null,
      reply_to_comment_id: null,
      issue_comment_id: $cid,
      classification: "SKIP",
      fix_outcome: null,
      rationale: "cosmetic nit, not worth a code change",
      reply_body: null
    }
  ],
  crash_recovery: {skill_a_completed: true, last_completed_phase: "7-write-inventory"}
}' > "$INVENTORY_FILE"

assert "(a) canonical inventory file created" "[ -f '$INVENTORY_FILE' ]"
assert "(a) canonical inventory has one FIX/SKIP issue_comment item" \
  "[ \"\$(jq -r '.items | length' \"$INVENTORY_FILE\")\" = 1 ]"

# ── (b) simulate the real Phase 2 sequence ───────────────────────────────────
# RENDERED = a mktemp scratch copy with .reply_body hand-populated (faithful
# stand-in for render-reply-bodies.sh's output, per the task's own allowance).
RENDERED="$(mktemp)"
jq '.items[0].reply_body = "Acknowledged — skipping as cosmetic."' "$INVENTORY_FILE" > "$RENDERED"

# Fake gh: POST returns a synthetic reply id, mirroring the shim pattern
# already used in post-replies_test.sh.
SYNTHETIC_REPLY_ID=700099
FAKEBIN="$TMP/bin"
mkdir -p "$FAKEBIN"
cat > "$FAKEBIN/gh" <<STUB
#!/usr/bin/env bash
if [ "\$1" = "api" ]; then
  printf '{"id": ${SYNTHETIC_REPLY_ID}}'
  exit 0
fi
exit 0
STUB
chmod +x "$FAKEBIN/gh"

# Extract the LITERAL Phase 2 post-replies.sh invocation out of SKILL.md's
# own code block (not a hand-typed re-statement) so a drift in SKILL.md's
# flag names/paths fails this test even though SKILL.md has no bash test of
# its own. Blank out the bracketed-optional --skip-comment-ids line (it is
# documentation syntax, not literal shell) rather than deleting it outright,
# so the preceding line's trailing `\` still joins onto a real (blank) line.
# Stop BEFORE the closing ``` fence (exclude it) — awk's pattern-action model
# evaluates actions top-to-bottom per line, so a single rule can't both
# "print this line" and "then exit without having printed it"; splitting the
# fence check into its own leading rule lets it fire (and exit) before the
# print rule ever sees that line.
PHASE2_CMD="$(awk 'p && /^```$/{exit} /post-replies\.sh \\$/{p=1} p{print}' "$SKILL_MD" \
  | sed 's/\[--skip-comment-ids "<csv>"\]//')"

assert "SKILL.md Phase 2 block extracted (non-empty)" "[ -n \"\$PHASE2_CMD\" ]"
assert "SKILL.md Phase 2 block has no stray code-fence backticks" \
  "! printf '%s' \"\$PHASE2_CMD\" | grep -q '\`\`\`'"
assert "SKILL.md Phase 2 block passes --reply-id-sidecar" \
  "printf '%s' \"\$PHASE2_CMD\" | grep -q -- '--reply-id-sidecar'"
assert "SKILL.md Phase 2 block passes --posted-sidecar" \
  "printf '%s' \"\$PHASE2_CMD\" | grep -q -- '--posted-sidecar'"
assert "SKILL.md Phase 2 sidecars are keyed to \$INVENTORY_FILE, not \$RENDERED" \
  "printf '%s' \"\$PHASE2_CMD\" | grep -qE '\\{INVENTORY_FILE\\}\\.(replyids|posted)'"

CLAUDE_SKILL_DIR="$HERE"
PATH="$FAKEBIN:$PATH" eval "$PHASE2_CMD" > "$TMP/phase2-out.txt" 2>&1
rc_phase2=$?

assert "Phase 2 post-replies.sh invocation succeeds" "[ \$rc_phase2 -eq 0 ]"

# ── (c) sidecar lands at the CANONICAL path, not next to \$RENDERED ─────────
# .replyids has no "100%-success" cleanup (its whole point is to durably
# outlive the run), so it must persist. .posted DOES get deleted on a
# 100%-success run with no --skip-comment-ids (same cleanup contract as the
# legacy <inventory>.posted derivation — see post-replies.sh's IDEMPOTENCY
# header); this single-item run is 100%-success, so its absence here is
# correct, not a regression (resume/no-duplicate-post is exercised by
# post-replies_test.sh's own Test C on a partial-failure run instead).
assert "canonical .replyids sidecar exists (not orphaned on the discarded \$RENDERED copy)" \
  "[ -f '${INVENTORY_FILE}.replyids' ]"
assert "canonical .posted sidecar is cleaned up after a 100%-success run (same contract as the legacy derivation)" \
  "[ ! -f '${INVENTORY_FILE}.posted' ]"
assert "no .replyids sidecar materializes next to the discarded \$RENDERED mktemp copy" \
  "[ ! -f '${RENDERED}.replyids' ]"

assert "every .replyids sidecar line parses as JSON" \
  "jq -c . '${INVENTORY_FILE}.replyids' >/dev/null 2>&1"
assert ".replyids sidecar records the synthetic reply id against the original comment id" \
  "[ \"\$(jq -r --argjson cid \"$ORIGINAL_COMMENT_ID\" 'select(.k==\"issue_comment_id\" and (.v|tostring)==(\$cid|tostring)) | .rid' \"${INVENTORY_FILE}.replyids\")\" = \"$SYNTHETIC_REPLY_ID\" ]"

# ── (d) check-merge-eligibility.sh must now report ELIGIBLE ─────────────────
# Live GitHub state after the reply: the ORIGINAL reviewer comment (900) is
# still there (issue comments never "resolve"), PLUS a brand-new live comment
# that IS the agent's own reply (id = the synthetic reply id). Without the
# sidecar exclusion, that second comment reads as fresh untriaged reviewer
# feedback and blocks the PR forever.
STUB_DIR="$TMP/eligibility-bin"
mkdir -p "$STUB_DIR"
cat > "$STUB_DIR/gh" <<'STUB'
#!/usr/bin/env bash
[ "$1" = "auth" ] && exit 0
if [ "$1" = "api" ]; then
  shift
  if [ "$1" = "graphql" ]; then
    printf '{"data":{"repository":{"pullRequest":{"reviewThreads":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[]}}}}}'
    exit 0
  fi
  path="$1"; shift
  filter=""
  while [ $# -gt 0 ]; do
    case "$1" in --jq) filter="$2"; shift 2 ;; *) shift ;; esac
  done
  case "$path" in
    */requested_reviewers)  body='{"users":[],"teams":[]}' ;;
    */issues/*/events*)     body='[]' ;;
    */issues/*/comments*)   body="${FIXTURE_ISSUE_COMMENTS}" ;;
    */pulls/*/reviews*)     body='[]' ;;
    */protection/required_status_checks*) echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
    */rules/branches/*)     echo "gh: Not Found (HTTP 404)" >&2; exit 1 ;;
    */pulls/*)              body="${FIXTURE_PR}" ;;
    *)                      body='{}' ;;
  esac
  if [ -n "$filter" ]; then printf '%s' "$body" | jq -r "$filter"; else printf '%s' "$body"; fi
  exit 0
fi
exit 0
STUB
chmod +x "$STUB_DIR/gh"
cat > "$STUB_DIR/prgroom" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB
chmod +x "$STUB_DIR/prgroom"

HEAD_SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
export FIXTURE_PR
FIXTURE_PR=$(jq -nc --arg sha "$HEAD_SHA" \
  '{state:"open", head:{sha:$sha}, base:{ref:"main"}, created_at:"2026-01-01T00:00:00Z"}')
export FIXTURE_ISSUE_COMMENTS
FIXTURE_ISSUE_COMMENTS=$(jq -nc \
  --argjson orig "$ORIGINAL_COMMENT_ID" --argjson rid "$SYNTHETIC_REPLY_ID" \
  '[{id: $orig, user: {login: "reviewer", type: "User"}},
    {id: $rid,  user: {login: "the-agent", type: "User"}}]')

BASE_POLICY='{"bot_review_expected":false,"bot_reviewers":[],"bot_inactivity_timeout_seconds":1200,"human_approvers_required":0,"human_review_timeout_seconds":null,"merge_authorization":"explicit","merge_rule":null}'

out_elig=$(env HOME="$FAKE_HOME" PATH="$STUB_DIR:$PATH" \
  FIXTURE_PR="$FIXTURE_PR" FIXTURE_ISSUE_COMMENTS="$FIXTURE_ISSUE_COMMENTS" \
  "$CHECK_ELIGIBILITY" --owner "$OWNER" --repo "$REPO" --pr "$PR" --policy-json "$BASE_POLICY" 2>"$TMP/eligibility-err.txt")
rc_elig=$?

assert "check-merge-eligibility.sh exits 0 (eligible)" "[ \$rc_elig -eq 0 ]"
assert "status is eligible" "[ \"\$(jq -r '.status' <<<\"\$out_elig\" 2>/dev/null)\" = eligible ]"
assert "blockers array is empty (agent's own reply excluded via .replyids sidecar)" \
  "[ \"\$(jq -r '.blockers | length' <<<\"\$out_elig\" 2>/dev/null)\" = 0 ]"
assert "no untriaged_feedback blocker naming the agent's own reply id" \
  "! jq -e '.blockers[]? | select(.code==\"untriaged_feedback\")' <<<\"\$out_elig\" >/dev/null 2>&1"

if [ "$rc_elig" != "0" ]; then
  echo "  (debug) check-merge-eligibility stderr: $(cat "$TMP/eligibility-err.txt")" >&2
  echo "  (debug) check-merge-eligibility stdout: $out_elig" >&2
fi

exit $FAIL
