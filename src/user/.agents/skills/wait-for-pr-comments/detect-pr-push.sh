#!/usr/bin/env bash
# PostToolUse hook: detect PR creation or push, suggest /wait-for-pr-comments
# Reads JSON from stdin. Outputs context injection on match, nothing otherwise.
set -euo pipefail

# Read hook input
input="$(cat)"

# Extract tool name — only care about Bash
tool_name="$(echo "$input" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
[[ "$tool_name" == "Bash" ]] || exit 0

# Extract command and stdout
command="$(echo "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)" || exit 0
stdout="$(echo "$input" | jq -r '.tool_output.stdout // empty' 2>/dev/null)" || exit 0

# Pattern 1: gh pr create — look for PR URL in stdout
if [[ "$command" == *"gh pr create"* ]]; then
    pr_url="$(echo "$stdout" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)" || true
    if [[ -n "$pr_url" ]]; then
        pr_number="$(echo "$pr_url" | grep -oE '[0-9]+$')"
        echo "PR activity detected: #${pr_number} (${pr_url}). Run /wait-for-pr-comments to monitor for review comments."
        exit 0
    fi
fi

# Pattern 2: git push — check if branch has an open PR
if [[ "$command" == git\ push* ]]; then
    pr_json="$(gh pr view --json number,url,state 2>/dev/null)" || exit 0
    pr_state="$(echo "$pr_json" | jq -r '.state // empty')" || exit 0
    if [[ "$pr_state" == "OPEN" ]]; then
        pr_number="$(echo "$pr_json" | jq -r '.number')"
        pr_url="$(echo "$pr_json" | jq -r '.url')"
        echo "PR activity detected: #${pr_number} (${pr_url}). Run /wait-for-pr-comments to monitor for review comments."
    fi
fi

exit 0
