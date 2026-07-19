#!/usr/bin/env bash
# Grind PR watcher — an ACTIVITY DOORBELL that also reports a PROVISIONAL CLASS.
#
# Wakes a parked lane when anything happens on its PR, and labels the ring with
# the SHAPE of that activity so the orchestrator does not have to disambiguate
# it by hand every time. The class is a hint for routing, NEVER a verdict:
# reading the actual verdict belongs to the repo's PR-review skill, and the lane
# still consults that skill on every ring.
#
# Two rules keep this from becoming the "clever watcher" that ghosts silently:
#
#   1. THE POLL LOOP STAYS DUMB. Detection is a plain count comparison, exactly
#      as before. Classification runs ONCE, at ring time, on the way out.
#   2. CLASSIFICATION CAN NEVER SUPPRESS A RING. Every failure path degrades to
#      class=ACTIVITY and rings anyway. A missed ring costs a bounded wait; a
#      silent watcher costs the whole lane.
#
# ── CLASSES, IN PRECEDENCE ORDER ────────────────────────────────────────────
#
#   FINDINGS   The reviewer wants changes. A new CHANGES_REQUESTED review, any
#              new inline review comment, or a findings-marker comment.
#   CLEAN      The reviewer signalled done-and-happy. A new APPROVED review, a
#              `+1`/`rocket`/`hooray` reaction from a trusted reviewer, or a
#              clean-marker comment.
#   IN-FLIGHT  The reviewer started but has not concluded. An `eyes` reaction
#              from a trusted reviewer.
#   ACTIVITY   Something happened that none of the above describes — including
#              every case where classification could not run.
#
# ── PRECEDENCE, AND WHY (this is the tie-breaking contract) ─────────────────
#
# Signals arrive out of order, collapse into one polling window, and contradict
# each other. The class is therefore computed from PR STATE AT RING TIME, never
# from the order events arrived in, and resolved by this fixed severity order:
#
#     FINDINGS  >  CLEAN  >  IN-FLIGHT  >  ACTIVITY
#
#   FINDINGS beats CLEAN because the costs are asymmetric. A false CLEAN can
#   send an unaddressed finding toward a merge; a false FINDINGS costs one
#   wasted lane check. When both are present — an approving review alongside a
#   new inline comment — the lane must look at the comment.
#
#   CLEAN beats IN-FLIGHT because `eyes` is a START marker. A review that both
#   started and finished inside one 60s window is finished; eyes->+1 nets to
#   CLEAN, which is the exact sequence Codex produces on a fast clean pass.
#
#   MOST SEVERE WINS, NOT MOST RECENT. Several new reviews in one window
#   resolve to the most severe among them. This is what makes out-of-order
#   delivery harmless: no ordering assumption is ever made.
#
#   RE-ARMING RESETS EVERYTHING. A fresh watcher samples fresh baselines, so a
#   class never carries across arms. There is no sticky state to go stale.
#
#   A CLASS IS NOT AUTHORIZATION. class=CLEAN is not approval, and never
#   licenses a merge. Only `merge-guard` decides that.
#
# TEMPLATE — substitute before use:
#   354              PR number, e.g. 320
#   scotthamilton77/agents-config            owner/name, e.g. acme/widgets
#   chatgpt-codex-connector[bot],Copilot,copilot-pull-request-reviewer[bot]   OPTIONAL comma-separated reviewer logins whose
#                       reactions count as signal, e.g.
#                       "chatgpt-codex-connector[bot],Copilot".
#                       Leave empty to trust ANY actor's reactions.
#       OPTIONAL grep -E regex marking a clean-pass comment.
#                       Empty disables the check.
#    OPTIONAL grep -E regex marking a findings comment.
#                       Empty disables the check.
#
# LAUNCH DIRECTLY via run_in_background. NEVER nest this inside a wrapper
# command with `&` — the wrapper exits immediately, the completion
# notification fires for the wrapper, and this watcher is orphaned: still
# running, unwatched, and silent.
#
#   Bash(command: "bash /path/to/watch-pr-320.sh", run_in_background: true)

set -uo pipefail

PR="354"
REPO="scotthamilton77/agents-config"
BOT_REVIEWERS="chatgpt-codex-connector[bot],Copilot,copilot-pull-request-reviewer[bot]"
CLEAN_MARKER=""
FINDINGS_MARKER=""

INTERVAL_SECONDS=60
TIMEOUT_SECONDS=1800   # 30 minutes

# --- Sampling ---------------------------------------------------------------
# Baselines are sampled by THIS watcher at arm time, so a ring always means
# "something new since you armed" — never "a signal from a previous head is
# still sitting there." Counts only; contents are not inspected.
# Only fields `gh pr view --json` actually supports. `reviewThreads` is a
# GraphQL-only connection and is rejected here — verify any field you add
# against a real `gh` before shipping, not against a stub.
fetch_pr() {
  gh pr view "$PR" --repo "$REPO" --json reviews,comments,reactionGroups 2>/dev/null
}

# `gh pr view --json comments` returns ISSUE comments only — inline
# review-thread comments live on a different endpoint and carry their own
# reactions. A reaction there moves no other count, so without this second
# fetch a thumbs-up on a review comment is still invisible. Emits a bare
# integer, or NOTHING on failure (treated as unreadable by the caller).
#
# The failure path must stay distinguishable from a real zero. Piping straight
# into `jq -s` cannot do that: a failed `gh` produces an empty stream, which
# `jq -s ... // 0` happily renders as a successful "0" — fabricating a zero
# baseline, defeating the WATCH-ERROR/WATCH-FLAKE guards, and setting up a
# false ring when the endpoint recovers. So capture first, check, then parse.
fetch_review_comment_reactions() {
  local json
  json=$(gh api --paginate "repos/$REPO/pulls/$PR/comments" 2>/dev/null) || return 1
  [ -n "$json" ] || return 1
  jq -s -r '[ .[][] | (.reactions.total_count // 0) ] | add // 0' <<<"$json" 2>/dev/null
}

read_counts() {
  # stdin: PR JSON. stdout: "<reviews> <comments> <reactions>"
  # Each array element is fully parenthesized: in jq `|` binds across `,`, so
  # bare `A | length, B | length` chains the second expression onto the first.
  # Reactions are counted because a reviewer can approve with nothing but a
  # thumbs-up: no review object, no comment, and a watcher blind to reactions
  # sleeps through it to timeout. Two subtleties:
  #   - `reactionGroups` is one entry per emoji, so sum the per-group user
  #     totals rather than taking `length` — a second thumbs-up on an existing
  #     group must still register.
  #   - A reaction can land on the PR body OR on any individual comment or
  #     review, and those nested reactions move none of the other counts.
  #     `comments[]` and `reviews[]` each carry their own reactionGroups, so
  #     all three sources are flattened into one total.
  jq -r '
    [ ((.reviews // []) | length),
      ((.comments // []) | length),
      ([ (.reactionGroups // []),
         ((.comments // []) | map(.reactionGroups // []) | add // []),
         ((.reviews  // []) | map(.reactionGroups // []) | add // [])
       ] | flatten | map(.users.totalCount // 0) | add // 0)
    ] | @tsv' 2>/dev/null | tr '\t' ' '
}

read -r BASE_REVIEWS BASE_COMMENTS BASE_PR_REACTIONS <<<"$(fetch_pr | read_counts)"
BASE_RC_REACTIONS="$(fetch_review_comment_reactions)"

# An unreadable baseline would make every later comparison meaningless, so
# fail loud rather than arming a watcher that can only produce noise.
if [ -z "$BASE_REVIEWS" ] || [ -z "$BASE_COMMENTS" ] || [ -z "$BASE_PR_REACTIONS" ] \
   || [ -z "$BASE_RC_REACTIONS" ]; then
  echo "WATCH-ERROR pr=$PR could not sample baselines (gh unavailable or PR unreadable)"
  exit 2
fi

BASE_REACTIONS=$((BASE_PR_REACTIONS + BASE_RC_REACTIONS))

# --- Classification baselines (BEST-EFFORT) ---------------------------------
# These feed the ring-time classifier only. Unlike the count baselines above, a
# failure here is NOT fatal: it disables classification (every ring reports
# class=ACTIVITY) while leaving detection fully intact. Losing the label is an
# inconvenience; losing the doorbell is a dead lane.
#
# Each baseline is a high-water mark, so "new" means "id greater than the mark"
# — no timestamps, no clock skew, no ordering assumptions.
#
# ── A FAILED BASELINE IS DANGEROUS, NOT MERELY MISSING ──────────────────────
# These fetches obey the capture-check-parse rule documented for
# `fetch_review_comment_reactions` above, and for a sharper reason. Piping `gh`
# straight into `jq -s 'add // []' | ... max // 0` renders a FAILED call as the
# string "0" — indistinguishable from a real empty PR. A zero baseline is not a
# missing label; it makes every pre-existing review and comment read as NEW at
# ring time, so a quiet PR gets classified a confident FINDINGS. That is worse
# than no classification at all, because it is wrong rather than absent.
#
# So each fetch returns NON-ZERO on failure and the caller drops CLASSIFY_OK to
# 0 — the only path to the documented safe degradation. Note the asymmetry with
# the ring-time fetches in classify_ring(): there, a failed fetch yields
# "nothing new", which lands on ACTIVITY and is already safe. Only the baseline
# can fabricate a false positive, which is why only the baseline is guarded
# this strictly.
CLASSIFY_OK=1

# Emits the highest id at `repos/$REPO/$1`, or NOTHING with a non-zero return
# when the endpoint is unreadable. A successful fetch of an empty collection is
# a legitimate "0" and must stay distinguishable from that failure.
fetch_max_id() {
  local json
  json=$(gh api --paginate "repos/$REPO/$1" 2>/dev/null) || return 1
  [ -n "$json" ] || return 1
  jq -s '[ add[]?.id // empty ] | max // 0' <<<"$json" 2>/dev/null
}

# Reaction identities, not counts: "<login>:<content>" pairs. A reaction is
# mutable, so the classifier compares SETS rather than high-water marks. An
# empty set is a legitimate result (nobody has reacted), so failure is again
# signalled by the return code, never by an empty string.
# A reaction can land on the PR body, on any issue comment, on any review, or
# on any inline review-thread comment — and a nested one moves none of the
# other counts. The count baseline above already flattens all four sources for
# exactly this reason; the identity set MUST cover the same four, or a `+1` on
# a review comment rings the doorbell and then classifies as a bare ACTIVITY.
# That is the body-only blind spot in a narrower form, and it is the one this
# classifier exists to close.
#
# REST has no single endpoint for that, and an N+1 sweep over every comment is
# both slow and fragile, so this is one GraphQL call. Note the content values
# are GraphQL ENUMS (THUMBS_UP, EYES, ...), not REST's `+1`/`eyes` strings.
#
# BASELINE AND RING-TIME MUST USE THIS SAME FUNCTION. If the two sampled
# different sources, every reaction from the unsampled source would read as new
# on the very first ring.
# Page sizes are deliberately bounded, not arbitrary. GitHub rejects a query
# whose worst-case node count exceeds 500,000, and the naive
# 100-threads x 100-comments x 100-reactions nesting alone requests 1,000,000.
# The shape below budgets ~30,000: breadth on threads (a PR has many threads,
# each with few comments) rather than depth. A PR that overruns these caps
# loses part of the identity set, which can only downgrade a class toward
# ACTIVITY — never upgrade one — so the failure direction stays safe.
REACTION_QUERY='query($owner:String!,$name:String!,$pr:Int!){
  repository(owner:$owner,name:$name){ pullRequest(number:$pr){
    reactions(first:100){pageInfo{hasNextPage} nodes{content user{login}}}
    comments(first:100){pageInfo{hasNextPage} nodes{id reactions(first:50){pageInfo{hasNextPage} nodes{content user{login}}}}}
    reviews(first:100){pageInfo{hasNextPage} nodes{id reactions(first:50){pageInfo{hasNextPage} nodes{content user{login}}}}}
    reviewThreads(first:100){pageInfo{hasNextPage} nodes{comments(first:10){pageInfo{hasNextPage} nodes{id reactions(first:20){pageInfo{hasNextPage} nodes{content user{login}}}}}}}
  } } }'

# Emits a comma-joined, sorted set of "<objectId>:<login>:<CONTENT>" keys, or
# NOTHING with a non-zero return when unreadable OR truncated. An empty set is
# a legitimate result (nobody reacted), hence the return-code signalling.
#
# ── THE KEY CARRIES THE REACTED OBJECT'S IDENTITY ──────────────────────────
# A bare "<login>:<CONTENT>" key collapses distinct events. If a reviewer has
# already THUMBS_UP'd the PR body at arm time and then THUMBS_UP's an inline
# comment, both render identically, the pair is already in the baseline, and
# the new approval is silently discarded as "already present". Prefixing the
# reactable's node id keeps them distinct. The PR body uses the literal "pr";
# GraphQL node ids and GitHub logins contain no ":", so the three-field split
# in classify_ring is unambiguous.
#
# ── TRUNCATION IS TREATED AS UNREADABLE ────────────────────────────────────
# These connections are paged. If a reactable holds more reactions than its
# page, a REMOVAL from the sampled page promotes a previously-unsampled older
# reaction into the next sample, where it reads as new — a spurious CLEAN in
# the one direction this classifier must never guess. Rather than page
# exhaustively (unbounded work on the doorbell path), any `hasNextPage` marks
# the whole sample untrustworthy and returns non-zero, which the existing
# failure plumbing already turns into ACTIVITY.
fetch_reaction_set() {
  local json out
  json=$(gh api graphql -F owner="${REPO%%/*}" -F name="${REPO##*/}" -F pr="$PR" \
           -f query="$REACTION_QUERY" 2>/dev/null) || return 1
  [ -n "$json" ] || return 1
  # `as $p` rather than a bare pipe into a `,`-separated list: in jq `|` binds
  # across `,`, so the array form would chain each source onto the previous one.
  out=$(jq -r '
    .data.repository.pullRequest as $p
    | ( [ ($p.reactions.pageInfo.hasNextPage // false),
          ($p.comments.pageInfo.hasNextPage // false),
          ($p.reviews.pageInfo.hasNextPage // false),
          ($p.reviewThreads.pageInfo.hasNextPage // false),
          (($p.comments.nodes // []) | map(.reactions.pageInfo.hasNextPage // false)),
          (($p.reviews.nodes  // []) | map(.reactions.pageInfo.hasNextPage // false)),
          (($p.reviewThreads.nodes // []) | map(.comments.pageInfo.hasNextPage // false)),
          (($p.reviewThreads.nodes // []) | map(.comments.nodes // []) | add // []
             | map(.reactions.pageInfo.hasNextPage // false))
        ] | flatten | any ) as $truncated
    | if $truncated then "TRUNCATED"
      else
        [ (($p.reactions.nodes // []) | map(select(.user != null)
             | "pr:\(.user.login):\(.content)")),
          (($p.comments.nodes // []) | map(.id as $i | (.reactions.nodes // [])
             | map(select(.user != null) | "\($i):\(.user.login):\(.content)")) | add // []),
          (($p.reviews.nodes // []) | map(.id as $i | (.reactions.nodes // [])
             | map(select(.user != null) | "\($i):\(.user.login):\(.content)")) | add // []),
          (($p.reviewThreads.nodes // []) | map(.comments.nodes // []) | add // []
             | map(.id as $i | (.reactions.nodes // [])
             | map(select(.user != null) | "\($i):\(.user.login):\(.content)")) | add // [])
        ] | flatten | sort | unique | join(",")
      end' <<<"$json" 2>/dev/null) || return 1
  [ "$out" = "TRUNCATED" ] && return 1
  printf '%s' "$out"
}

BASE_MAX_REVIEW_ID=$(fetch_max_id "pulls/$PR/reviews")   || CLASSIFY_OK=0
BASE_MAX_INLINE_ID=$(fetch_max_id "pulls/$PR/comments")  || CLASSIFY_OK=0
BASE_MAX_ISSUE_ID=$(fetch_max_id "issues/$PR/comments")  || CLASSIFY_OK=0
BASE_REACTION_SET=$(fetch_reaction_set)                  || CLASSIFY_OK=0

# Second line of defence: `jq` itself can fail (malformed payload) after a
# successful fetch, which yields an empty value with a zero return. Unlike the
# check this replaces, this one is genuinely reachable.
if [ -z "$BASE_MAX_REVIEW_ID" ] || [ -z "$BASE_MAX_INLINE_ID" ] \
   || [ -z "$BASE_MAX_ISSUE_ID" ]; then
  CLASSIFY_OK=0
fi

echo "WATCH-ARMED pr=$PR reviews=$BASE_REVIEWS comments=$BASE_COMMENTS reactions=$BASE_REACTIONS classify=$CLASSIFY_OK"

# --- Ring-time classifier ---------------------------------------------------
# Runs ONCE, after detection has already decided to ring. Emits exactly one of
# FINDINGS / CLEAN / IN-FLIGHT / ACTIVITY on stdout, and CANNOT fail: every
# error path falls through to ACTIVITY.
#
# `is_trusted <login>` decides whose reactions count. An empty BOT_REVIEWERS
# trusts everyone — the permissive default, because a watcher that ignores an
# unlisted reviewer's approval is the blind spot this classifier exists to
# close. Matching is exact against a comma-separated list, so a login that
# happens to contain another as a substring cannot be confused for it.
is_trusted() {
  [ -z "$BOT_REVIEWERS" ] && return 0
  case ",$BOT_REVIEWERS," in (*",$1,"*) return 0 ;; esac
  return 1
}

# Fetch a ring-time source, or fail. `$1` is the REST path under repos/$REPO,
# `$2` the jq filter applied to the slurped pages. Same capture-check-parse
# discipline as the baselines, for the same reason.
fetch_ring_json() {
  local json
  json=$(gh api --paginate "repos/$REPO/$1" 2>/dev/null) || return 1
  [ -n "$json" ] || return 1
  jq -s "$2" <<<"$json" 2>/dev/null
}

classify_ring() {
  [ "$CLASSIFY_OK" -eq 1 ] || { echo "ACTIVITY"; return 0; }

  local findings=0 clean=0 inflight=0 ring_failed=0

  # ── WHY A PARTIAL FAILURE MUST ABANDON CLASSIFICATION ─────────────────────
  # It is tempting to reason that a failed ring-time fetch is harmless because
  # it contributes "nothing new". That holds only for a TOTAL failure. Consider
  # a PARTIAL one: the inline-comments fetch (the FINDINGS source) fails while
  # the reaction fetch succeeds and returns a `+1`. The cascade would then emit
  # CLEAN on a PR that actually has unread findings — a failure silently
  # DOWNGRADING severity, which inverts the precedence contract's whole safety
  # asymmetry. So any unreadable source forfeits the class entirely and falls
  # back to ACTIVITY. A bare doorbell is always honest; a wrong class is not.

  # New reviews since arm: state decides severity. A COMMENTED review is not
  # itself a finding — its inline comments are, and those are counted below.
  local reviews
  reviews=$(fetch_ring_json "pulls/$PR/reviews" \
    "add // [] | [ .[] | select((.id // 0) > ${BASE_MAX_REVIEW_ID:-0}) ]") || ring_failed=1
  review_state_count() {
    jq -r --arg s "$1" '[ .[] | select(.state == $s) ] | length' <<<"$reviews" 2>/dev/null || echo 0
  }
  if [ -n "$reviews" ]; then
    [ "$(review_state_count "CHANGES_REQUESTED")" -gt 0 ] && findings=1
    [ "$(review_state_count "APPROVED")" -gt 0 ] && clean=1
  fi

  # Any new inline review comment is a finding. This is the single highest-
  # value signal: it is how both Copilot and Codex actually raise defects.
  local inline_new
  inline_new=$(fetch_ring_json "pulls/$PR/comments" \
    "add // [] | [ .[] | select((.id // 0) > ${BASE_MAX_INLINE_ID:-0}) ] | length") || ring_failed=1
  [ -n "$inline_new" ] && [ "$inline_new" -gt 0 ] && findings=1

  # New issue comments, matched against the OPTIONAL markers. Marker matching
  # is the one place this script reads prose, which is why both patterns are
  # caller-supplied and default to disabled — a phrase hardcoded here would rot
  # the first time a reviewer reworded its summary.
  local issue_new
  issue_new=$(fetch_ring_json "issues/$PR/comments" \
    "add // [] | [ .[] | select((.id // 0) > ${BASE_MAX_ISSUE_ID:-0}) | .body // \"\" ] | join(\"\n\")") || ring_failed=1
  if [ -n "$issue_new" ]; then
    if [ -n "$FINDINGS_MARKER" ] && grep -qE "$FINDINGS_MARKER" <<<"$issue_new" 2>/dev/null; then
      findings=1
    fi
    if [ -n "$CLEAN_MARKER" ] && grep -qE "$CLEAN_MARKER" <<<"$issue_new" 2>/dev/null; then
      clean=1
    fi
  fi

  # Reaction identities added since arm, from trusted reviewers only, across ALL
  # four reaction sources (see fetch_reaction_set). A lone thumbs-up IS an
  # approval in the reference run, and a watcher blind to it slept through to
  # timeout — hence reactions are first-class here, not a footnote. Removals are
  # ignored by the classifier (they still RANG, via the `-ne` count test in the
  # poll loop); a withdrawn reaction is activity without being a verdict.
  local now_set
  now_set=$(fetch_reaction_set) || ring_failed=1
  if [ -n "$now_set" ]; then
    while IFS= read -r pair; do
      [ -n "$pair" ] || continue
      case ",${BASE_REACTION_SET}," in (*",$pair,"*) continue ;; esac   # already present at arm
      # Key is "<objectId>:<login>:<CONTENT>". Peel from the right: content is
      # the last field, login the one before it, and the object id (which never
      # contains ":") is whatever remains.
      local content="${pair##*:}" rest="${pair%:*}"
      local login="${rest#*:}"
      is_trusted "$login" || continue
      # GraphQL enum names, not REST's `+1`/`eyes` strings.
      case "$content" in
        THUMBS_UP|ROCKET|HOORAY) clean=1 ;;
        EYES)                    inflight=1 ;;
      esac
    done <<<"$(tr ',' '\n' <<<"$now_set")"
  fi

  # Any unreadable source forfeits the class — checked BEFORE the cascade, so a
  # partial failure can never downgrade FINDINGS to CLEAN.
  [ "$ring_failed" -eq 0 ] || { echo "ACTIVITY"; return 0; }

  # Fixed severity order. See the precedence contract in the header — this
  # cascade IS that contract, and the two must be changed together.
  if   [ "$findings" -eq 1 ]; then echo "FINDINGS"
  elif [ "$clean"    -eq 1 ]; then echo "CLEAN"
  elif [ "$inflight" -eq 1 ]; then echo "IN-FLIGHT"
  else                             echo "ACTIVITY"
  fi
}

# --- Poll loop --------------------------------------------------------------
elapsed=0
while [ "$elapsed" -lt "$TIMEOUT_SECONDS" ]; do
  sleep "$INTERVAL_SECONDS"
  elapsed=$((elapsed + INTERVAL_SECONDS))

  read -r reviews comments pr_reactions <<<"$(fetch_pr | read_counts)"
  rc_reactions="$(fetch_review_comment_reactions)"

  # An empty read is a flake, not a signal. Skip the round; do not treat a
  # missing value as zero — that would read as a count DECREASE and mask a
  # real increase on the following poll.
  if [ -z "$reviews" ] || [ -z "$comments" ] || [ -z "$pr_reactions" ] \
     || [ -z "$rc_reactions" ]; then
    echo "WATCH-FLAKE pr=$PR t=${elapsed}s (empty read, skipping round)"
    continue
  fi
  reactions=$((pr_reactions + rc_reactions))

  # Reviews and comments only ever accumulate, so `-gt` is the right test for
  # them. Reactions are MUTABLE — they can be removed — so `-gt` would miss
  # activity whenever a removal offsets an addition: baseline 1, a reviewer
  # withdraws theirs (0), another reacts before the next poll (1), and both
  # rounds compare equal while two reaction events went by. Any change is
  # activity, so reactions test `-ne`. A removal on its own is a ring too;
  # this is a doorbell, and someone taking a reaction back is something
  # happening.
  #
  # KNOWN LIMIT — accepted, not overlooked. A total cannot see a replacement
  # that completes INSIDE one 60s window (one reviewer's reaction removed and
  # another's added before the next sample nets to zero). Catching that needs
  # per-user reaction identities diffed across polls, which is exactly the
  # "clever watcher" this script's header rejects: in the reference run a
  # filter-based monitor ghosted twice and each time the lane looked stuck when
  # the monitor had died. A missed ring costs a bounded wait — the timeout is
  # documented as "no activity," never "no verdict," and the lane re-arms or
  # checks the PR directly. A silently dead watcher costs the whole lane. Given
  # that trade, the dumb total wins.
  if [ "$reviews" -gt "$BASE_REVIEWS" ] || [ "$comments" -gt "$BASE_COMMENTS" ] \
     || [ "$reactions" -ne "$BASE_REACTIONS" ]; then
    # Classify AFTER the decision to ring, never before it. The ring is already
    # guaranteed at this point, so no classifier failure can swallow it.
    ring_class="$(classify_ring)"
    echo "WATCH-RING pr=$PR t=${elapsed}s class=$ring_class reviews=$reviews/$BASE_REVIEWS comments=$comments/$BASE_COMMENTS reactions=$reactions/$BASE_REACTIONS"
    case "$ring_class" in
      FINDINGS)  echo "PROVISIONAL: the reviewer appears to want changes. Re-engage the lane to work them." ;;
      CLEAN)     echo "PROVISIONAL: the reviewer appears done and satisfied. NOT approval and NOT merge authorization — the lane confirms via the review skill, and merge-guard rules on merging." ;;
      IN-FLIGHT) echo "PROVISIONAL: a review appears to have STARTED but not concluded. Usually re-arm rather than re-engage the lane." ;;
      ACTIVITY)  echo "PROVISIONAL: activity of an unrecognized shape (or classification unavailable). Treat as a bare doorbell." ;;
    esac
    echo "The class is a ROUTING HINT, never a verdict. The lane still consults the PR-review skill on every ring."
    exit 0
  fi

  echo "WATCH-QUIET pr=$PR t=${elapsed}s reviews=$reviews comments=$comments reactions=$reactions"
done

# Timeout means NO ACTIVITY, not "no verdict" — a reviewer can signal in ways a
# count-based poll will not see. Re-arm, or have the lane check directly.
echo "WATCH-TIMEOUT pr=$PR after ${TIMEOUT_SECONDS}s — no activity detected. Re-arm or have the lane check the PR directly."
exit 1
