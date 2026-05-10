# Findings for src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh
AUDIT_INPUT_SHA: af9c1bfc342bf7578ad491cc63dc95b07618c851

F11: poll-copilot-rereview-start.sh — hardcoded polling schedule, not configurable
  File: src/user/.agents/skills/wait-for-pr-comments/poll-copilot-rereview-start.sh:49-71
  Category: script
  Severity: Low
  Tier: 1
  Issue: Script hardcodes `sleep 20` (initial pre-sleep) + `6 × sleep 10` (poll loop) = 80-second maximum window. Sibling poll-new-comments.sh accepts `<interval-secs>` and `<max-duration-secs>` as arguments. The hardcoded 80-second window may be too short for high-latency GitHub environments or too long for fast CI setups.
  Recommendation: Extract `INITIAL_SLEEP`, `POLL_INTERVAL`, and `POLL_COUNT` as optional named arguments (with current values as defaults), matching poll-new-comments.sh's pattern. This is a medium-term improvement; current hardcoded values are functional.
  Vision-advancement-tier: B
  Vision-advancement: Making poll timing configurable closes a gap in the wall-clock pipelining vision (vision-85-5-10 tag: "Wall-clock pipelining across external waits — future work").
  Resolution: ACCEPTED
  Rationale: Phase 2 did not address; Phase 1 finding stands.
  Sources: phase1/scripts.md:F11

---
