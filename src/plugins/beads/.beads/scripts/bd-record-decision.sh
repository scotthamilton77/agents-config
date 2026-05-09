#!/usr/bin/env bash
# bd-record-decision.sh — Record an architectural decision as a tracked bead.
#
# Creates a decision-type bead, links it to the source bead via a
# discovered-from dependency, then applies the outcome:
#
#   --implemented    Decision is resolved in the current spec or work.
#                    Closes the decision bead immediately.
#
#   --needs-approval Decision impacts future work and requires human sign-off.
#                    Keeps the bead open and adds the 'human' label.
#
# Usage:
#   bd-record-decision.sh --bead-id <id> --title "<text>" --notes "<text>"
#                         (--implemented | --needs-approval)

set -euo pipefail

BEAD_ID=""
TITLE=""
NOTES=""
IMPLEMENTED=false
NEEDS_APPROVAL=false

usage() {
    echo "Usage: $(basename "$0") --bead-id <id> --title <text> --notes <text> (--implemented | --needs-approval)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bead-id)        BEAD_ID="$2";       shift 2 ;;
        --title)          TITLE="$2";         shift 2 ;;
        --notes)          NOTES="$2";         shift 2 ;;
        --implemented)    IMPLEMENTED=true;   shift ;;
        --needs-approval) NEEDS_APPROVAL=true; shift ;;
        -h|--help)        usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

[[ -z "$BEAD_ID" ]] && { echo "Error: --bead-id is required" >&2; usage; }
[[ -z "$TITLE" ]]   && { echo "Error: --title is required" >&2;   usage; }
[[ -z "$NOTES" ]]   && { echo "Error: --notes is required" >&2;   usage; }

if [[ "$IMPLEMENTED" == true && "$NEEDS_APPROVAL" == true ]]; then
    echo "Error: --implemented and --needs-approval are mutually exclusive" >&2
    usage
fi
if [[ "$IMPLEMENTED" == false && "$NEEDS_APPROVAL" == false ]]; then
    echo "Error: one of --implemented or --needs-approval is required" >&2
    usage
fi

OUTCOME=$([[ "$IMPLEMENTED" == true ]] && echo "implemented" || echo "needs-approval")

# Create the decision bead and capture its ID
CREATE_OUTPUT=$(bd create "$TITLE" --type decision 2>&1)
echo "$CREATE_OUTPUT"

DEC_ID=$(echo "$CREATE_OUTPUT" | sed -n 's/.*Created issue: \([^ ]*\).*/\1/p')
if [[ -z "$DEC_ID" ]]; then
    echo "Error: could not extract decision bead ID from bd create output" >&2
    exit 1
fi

# Attach rationale
bd update "$DEC_ID" --notes="$NOTES"

# Link decision to source bead — this decision was discovered while working on it
bd dep add "$DEC_ID" "$BEAD_ID" --type discovered-from

# Apply outcome
if [[ "$OUTCOME" == "implemented" ]]; then
    bd close "$DEC_ID" --reason "Resolved in spec/work for $BEAD_ID"
    echo "Decision $DEC_ID created and closed (resolved in current spec)."
elif [[ "$OUTCOME" == "needs-approval" ]]; then
    bd label add "$DEC_ID" human
    bd update "$DEC_ID" --append-notes "Needs human approval before implementation can proceed."
    echo "Decision $DEC_ID created and flagged for human review."
fi
