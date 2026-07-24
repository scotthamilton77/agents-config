#!/usr/bin/env bash
# Purpose: request a re-review from one or more trusted PR bot reviewers,
# dispatching on reviewer identity — each bot's ask mechanism differs:
#
#   Identity                              Mechanism
#   -------------------------------------  ------------------------------------
#   Copilot,                               remove+re-add reviewer dance. The
#   copilot-pull-request-reviewer[bot]     `gh pr edit --remove-reviewer
#                                           @copilot && sleep && gh pr edit
#                                           --add-reviewer @copilot` pattern
#                                           reliably triggers a new review
#                                           event even when @copilot is already
#                                           listed. Copilot does not respond to
#                                           an issue comment.
#   chatgpt-codex-connector[bot] (Codex)   post an `@codex review` issue
#                                           comment. Codex does not respond to
#                                           reviewer-request events at all.
#
# An identity with no known mechanism warns to stderr and is skipped without
# aborting dispatch to its siblings.
#
# GraphQL projection: none directly; uses `gh pr edit` / `gh pr comment` REST
# under the hood.
#
# Inputs:
#   --owner <o>              repository owner
#   --repo  <r>              repository name
#   --pr    <n>              PR number
#   --bot-reviewers <json>   JSON array of reviewer identities to dispatch to
#                            (non-empty array of strings; identity matched
#                            case-insensitively, mirroring
#                            poll-copilot-review.sh's convention). Omit to
#                            preserve the legacy Copilot-only dance
#                            (backward-compatible default, not how the
#                            wait-for-pr-comments/merge-guard loops run).
#   --disposition-table-file <path>
#                            Do-not-relitigate context for the Codex ask ONLY
#                            (Copilot is unaffected, gets neither this nor
#                            --since-sha). Path to a file containing a
#                            non-empty JSON array of objects: {finding,
#                            classification: FIX|SKIP|REBUT, detail} — detail
#                            is the fixing commit SHA for FIX, a rationale
#                            for SKIP/REBUT. A FILE, not inline JSON — see
#                            "Argv-size note" below. Renders as a markdown
#                            table in the '@codex review' comment instead of
#                            the bare string, so Codex does not re-raise
#                            settled findings next round (confirmed PR #317,
#                            #331 — bare re-ask re-cites SKIP/fixed items; a
#                            disposition table does not, and can carry a
#                            REBUT Codex accepts instead of re-flagging).
#   --since-sha <sha>        Optional. Codex-only: appends a "focus on
#                            commits since <sha>" line to the comment body.
#
# Outputs:
#   stdout: one NDJSON line per dispatched mechanism, never per raw alias
#     (aliases deduping to one mechanism produce exactly one line):
#       {"identity": <alias matched>, "mechanism": "copilot"|"codex", "status": "success"|"failure"}
#     An unknown identity gets a stderr warning only, no stdout line -- it was
#     never dispatched. Lets callers tell "never asked" (mechanism absent or
#     "failure") apart from "asked but silent" ("success"). In the legacy
#     --bot-reviewers-omitted path there is no input alias to echo, so
#     "identity" is the fixed literal "Copilot", not a value read from input.
#   exit codes:
#     0 = every dispatched mechanism succeeded; 1 = none succeeded (including
#     all-unknown-identities); 2 = bad flag usage; 3 = partial (>=1 succeeded
#     AND >=1 failed) -- so callers don't read a failed identity as an
#     asked-but-silent bot.
#
# Argv-size note: --disposition-table-file takes a PATH, not inline JSON. A
# round with enough items (or a few verbose rationales) can exceed the OS's
# per-argument exec limit (Linux caps a single argv/environ string at 128
# KiB) well before it exceeds anything this script controls — passing the
# JSON inline would fail the `exec` itself, before this script's own
# comment-size fallback (below) ever got a chance to run.
set -euo pipefail

usage() {
  cat <<EOF
Usage: $(basename "$0") --owner <o> --repo <r> --pr <n> [--bot-reviewers <json-array>] [--disposition-table-file <path>] [--since-sha <sha>]

Requests a re-review from one or more trusted bot reviewers, dispatching on
identity: Copilot / copilot-pull-request-reviewer[bot] get the remove+re-add
reviewer dance; chatgpt-codex-connector[bot] gets an '@codex review' issue
comment. Omit --bot-reviewers to request only Copilot (legacy default).
--disposition-table-file and --since-sha add do-not-relitigate context to
the Codex ask only; they have no effect on the Copilot mechanism.
EOF
  exit 2
}

OWNER=""
REPO=""
PR=""
BOT_REVIEWERS=""
DISPOSITION_TABLE=""
DISPOSITION_TABLE_FILE_GIVEN=false
SINCE_SHA=""

[ $# -gt 0 ] || usage

while [ $# -gt 0 ]; do
  case "$1" in
    --owner)              OWNER="${2:-}";              shift 2 ;;
    --repo)               REPO="${2:-}";                shift 2 ;;
    --pr)                 PR="${2:-}";                  shift 2 ;;
    --bot-reviewers)      BOT_REVIEWERS="${2:-}";       shift 2 ;;
    --disposition-table-file)
      [ -n "${2:-}" ] || { echo "error: --disposition-table-file requires a value" >&2; usage; }
      [ -r "$2" ] || { echo "error: --disposition-table-file '$2' is not a readable file" >&2; exit 2; }
      DISPOSITION_TABLE="$(cat "$2")"
      DISPOSITION_TABLE_FILE_GIVEN=true
      shift 2
      ;;
    --since-sha)
      [ -n "${2:-}" ] || { echo "error: --since-sha requires a value" >&2; usage; }
      SINCE_SHA="$2"
      shift 2
      ;;
    -h|--help) usage ;;
    *) echo "error: unknown flag: $1" >&2; usage ;;
  esac
done

[ -n "$OWNER" ] && [ -n "$REPO" ] && [ -n "$PR" ] || {
  echo "error: --owner, --repo, --pr are all required" >&2
  exit 2
}

# Validate --bot-reviewers (when provided) as a non-empty JSON array of
# strings — same convention as poll-copilot-review.sh — then canonicalize via
# jq so only clean, re-serialized JSON is read below.
if [ -n "$BOT_REVIEWERS" ]; then
  BOT_REVIEWERS=$(jq -ce 'if (type == "array" and length > 0 and ([.[] | select(type != "string")] | length) == 0) then . else error("bad") end' <<<"$BOT_REVIEWERS" 2>/dev/null) || {
    echo "error: --bot-reviewers must be a non-empty JSON array of strings" >&2
    exit 2
  }
fi

# Validate --disposition-table-file's content (when the flag was given) as a
# non-empty JSON array of objects, each with a "finding" string, a
# "classification" of FIX/SKIP/REBUT, and a "detail" string (commit SHA for
# FIX, rationale for SKIP/REBUT) — same fail-closed convention as
# --bot-reviewers, then canonicalize via jq. Gated on
# DISPOSITION_TABLE_FILE_GIVEN, not on "$DISPOSITION_TABLE" being non-empty:
# a supplied file that reads back EMPTY (e.g. a zero-byte file) must still
# fail this check — checking non-emptiness of the variable would instead
# treat it exactly like the flag being omitted, silently dropping the
# do-not-relitigate context the caller explicitly asked to attach.
if [ "$DISPOSITION_TABLE_FILE_GIVEN" = true ]; then
  DISPOSITION_TABLE=$(jq -ce '
    if (type == "array" and length > 0 and
        ([.[] | select(
          (type == "object") and
          (has("finding") and (.finding | type) == "string") and
          (has("classification") and (.classification as $c | ["FIX","SKIP","REBUT"] | index($c) != null)) and
          (has("detail") and (.detail | type) == "string")
          | not
        )] | length) == 0)
    then . else error("bad") end
  ' <<<"$DISPOSITION_TABLE" 2>/dev/null) || {
    echo "error: --disposition-table-file's content must be a non-empty JSON array of objects, each with a string 'finding', a 'classification' of FIX/SKIP/REBUT, and a string 'detail' (commit SHA for FIX, rationale for SKIP/REBUT)" >&2
    exit 2
  }
fi

PR_REF="$OWNER/$REPO#$PR"

GH_ERR="$(mktemp)"
trap 'rm -f "$GH_ERR"' EXIT

# request_copilot — remove+re-add @copilot to trigger a fresh review event.
request_copilot() {
  # Remove @copilot — tolerate "not currently a reviewer" (a common no-op error).
  gh pr edit "$PR" --repo "$OWNER/$REPO" --remove-reviewer @copilot >/dev/null 2>"$GH_ERR" || true

  sleep 2

  # Add @copilot — capture stderr so callers (and operators debugging auth /
  # permission / rate-limit / invalid-PR failures) see the underlying gh message,
  # not just a generic exit code.
  if ! gh pr edit "$PR" --repo "$OWNER/$REPO" --add-reviewer @copilot >/dev/null 2>"$GH_ERR"; then
    echo "error: gh pr edit --add-reviewer failed for $PR_REF: $(cat "$GH_ERR")" >&2
    return 1
  fi
}

# GitHub issue-comment bodies are capped at 65536 characters. A disposition
# table has no per-item length bound (a verbose SKIP rationale, or enough
# FIX/SKIP items in one round, can exceed it), and gh's comment call would
# then fail outright, leaving a Codex-only policy with no successful
# re-review ask at all — worse than a plain, un-contextualized one. This
# threshold leaves comfortable margin for the surrounding prose.
MAX_CODEX_COMMENT_CHARS=60000

# build_codex_comment_body — bare '@codex review' by default; when
# --disposition-table-file and/or --since-sha are supplied, renders them as a
# structured markdown table + focus line instead. Falls back to the bare
# string (dropping the do-not-relitigate context, not the ask itself) when
# the rendered body would exceed MAX_CODEX_COMMENT_CHARS. This do-not-
# relitigate context is Codex-only — request_copilot never sees it.
build_codex_comment_body() {
  local full
  full="$(_render_codex_comment_body)"
  if [ "${#full}" -gt "$MAX_CODEX_COMMENT_CHARS" ]; then
    echo "@codex review"
    echo
    echo "(do-not-relitigate context omitted: exceeded ${MAX_CODEX_COMMENT_CHARS} characters)"
    return
  fi
  printf '%s' "$full"
}

_render_codex_comment_body() {
  if [ -z "$DISPOSITION_TABLE" ] && [ -z "$SINCE_SHA" ]; then
    echo "@codex review"
    return
  fi

  echo "@codex review"
  echo

  if [ -n "$DISPOSITION_TABLE" ]; then
    echo "Prior-round findings — do not re-raise FIX/SKIP/REBUT items below:"
    echo
    echo "| Finding | Classification | Commit / Rationale |"
    echo "| --- | --- | --- |"
    # Sanitize each cell before interpolation: collapse embedded newlines to
    # spaces and escape literal "|" so a finding/rationale containing either
    # cannot terminate or shift a row — free-text review excerpts and
    # rationales routinely contain both, and a shifted row breaks the
    # finding-to-classification association this table exists to preserve.
    # Backslashes are escaped FIRST, before pipes: a cell containing a
    # pre-existing '\|' (e.g. a regex excerpt) would otherwise have its own
    # backslash consume the escape this function adds for the pipe,
    # un-escaping it in the rendered Markdown and re-opening the same
    # row-splitting hazard.
    jq -r '
      def cell: gsub("\r\n|\r|\n"; " ") | gsub("\\\\"; "\\\\") | gsub("\\|"; "\\|");
      .[] | "| " + (.finding | cell) + " | " + .classification + " | " + (.detail | cell) + " |"
    ' <<<"$DISPOSITION_TABLE"
    echo
  fi

  if [ -n "$SINCE_SHA" ]; then
    echo "Focus on commits since $SINCE_SHA."
  fi
}

# request_codex — post an '@codex review' issue comment. Codex reviews on
# push, mark-draft-ready, and this comment, but not on a reviewer-request
# event, so this is its only ask mechanism.
request_codex() {
  local body
  body="$(build_codex_comment_body)"
  if ! gh pr comment "$PR" --repo "$OWNER/$REPO" --body "$body" >/dev/null 2>"$GH_ERR"; then
    echo "error: gh pr comment '@codex review' failed for $PR_REF: $(cat "$GH_ERR")" >&2
    return 1
  fi
}

# report_outcome — emit one NDJSON stdout line for a dispatched mechanism.
report_outcome() {
  local identity="$1" mechanism="$2" status="$3"
  jq -nc --arg identity "$identity" --arg mechanism "$mechanism" --arg status "$status" \
    '{identity: $identity, mechanism: $mechanism, status: $status}'
}

if [ -z "$BOT_REVIEWERS" ]; then
  # Backward-compatible default: the legacy Copilot-only dance. There is no
  # input alias to echo here (no --bot-reviewers was given), so "identity"
  # is the fixed literal "Copilot" -- see the Outputs note above.
  if request_copilot; then
    report_outcome Copilot copilot success
    exit 0
  fi
  report_outcome Copilot copilot failure
  exit 1
fi

SUCCEEDED=0
DISPATCHED_COUNT=0
# Track mechanisms already dispatched this invocation. Multiple aliases can map
# to the same mechanism (e.g. both `Copilot` and
# `copilot-pull-request-reviewer[bot]` -> the reviewer dance); dispatching each
# mechanism at most once avoids a redundant remove+re-add cycle per alias.
DISPATCHED=""
while IFS= read -r identity; do
  lower=$(printf '%s' "$identity" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    copilot|"copilot-pull-request-reviewer[bot]") mechanism=copilot ;;
    "chatgpt-codex-connector[bot]")               mechanism=codex ;;
    *)
      echo "warning: no known re-review mechanism for reviewer identity '$identity' — skipping" >&2
      continue
      ;;
  esac

  # Skip mechanisms already asked this invocation (alias dedup).
  case " $DISPATCHED " in
    *" $mechanism "*) continue ;;
  esac
  DISPATCHED="$DISPATCHED $mechanism"
  DISPATCHED_COUNT=$((DISPATCHED_COUNT + 1))

  case "$mechanism" in
    copilot)
      if request_copilot; then
        SUCCEEDED=$((SUCCEEDED + 1))
        report_outcome "$identity" copilot success
      else
        report_outcome "$identity" copilot failure
      fi
      ;;
    codex)
      if request_codex; then
        SUCCEEDED=$((SUCCEEDED + 1))
        report_outcome "$identity" codex success
      else
        report_outcome "$identity" codex failure
      fi
      ;;
  esac
done < <(jq -r '.[]' <<<"$BOT_REVIEWERS")

if [ "$SUCCEEDED" -eq 0 ]; then
  exit 1
elif [ "$SUCCEEDED" -lt "$DISPATCHED_COUNT" ]; then
  exit 3
fi
exit 0
