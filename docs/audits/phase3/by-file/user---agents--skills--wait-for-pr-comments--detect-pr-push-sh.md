# Findings for src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F13: detect-pr-push.sh — uses echo instead of printf for JSON parsing
  File: src/user/.agents/skills/wait-for-pr-comments/detect-pr-push.sh:10-15
  Category: script
  Severity: Low
  Tier: 1
  Issue: Lines 10-15 use `echo "$input" | jq ...` to extract fields from hook payload. Most other scripts use `printf '%s' "$var" | jq ...` to avoid echo interpretation of escape sequences. If hook payload contains `\t` or `\n`, echo would silently corrupt it.
  Recommendation: Replace `echo "$input" | jq` with `printf '%s' "$input" | jq` on lines 10, 14, 15. Three-line mechanical change.
  Vision-advancement-tier: C
  Vision-advancement: Reduces a latent data-corruption risk in hook payload parsing, protecting PR detection reliability.
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F13

---
