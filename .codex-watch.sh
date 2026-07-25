#!/bin/bash
# Poll BOTH endpoints: findings rounds land on pulls/reviews, clean rounds on
# issues/comments. Match on the SHA -- that is what makes a hit trustworthy.
SHA="b2068d9196"
REPO="scotthamilton77/agents-config"
PR=398
while true; do
  hit=$(gh api "repos/$REPO/pulls/$PR/reviews" \
    --jq ".[] | select(.user.login | test(\"codex\")) | select(.body | contains(\"$SHA\")) | .body[0:180]" 2>/dev/null || true)
  if [ -n "$hit" ]; then
    echo "CODEX ROUND 5 (findings) for $SHA -- endpoint: pulls/$PR/reviews"
    echo "$hit" | tr '\n' ' '
    exit 0
  fi
  hit=$(gh api "repos/$REPO/issues/$PR/comments" \
    --jq ".[] | select(.user.login | test(\"codex\")) | select(.body | contains(\"$SHA\")) | .body[0:180]" 2>/dev/null || true)
  if [ -n "$hit" ]; then
    echo "CODEX ROUND 5 (clean) for $SHA -- endpoint: issues/$PR/comments"
    echo "$hit" | tr '\n' ' '
    exit 0
  fi
  sleep 45
done
