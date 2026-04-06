# Completion Gate

Implements shared `<verification-checklist>` steps 1–5 with Claude-specific tools.

MANDATORY for non-trivial work (skip for obvious one-liners, config changes, typos):

1. `code-reviewer` agent — review changes against plan and standards (checklist step 1)
2. Address any findings from code-reviewer (checklist step 2)
3. `code-simplifier` agent — simplify/refine changed code (checklist step 3)
4. Address any findings from code-simplifier (checklist step 4)
5. `verify-checklist` skill — run tests, build, lint; evidence before claims; structured completion report (checklist step 5)

No exceptions. No partial runs. Each step feeds the next.

**Subagents**: When dispatching subagents to do implementation work, always include the full completion gate workflow (review, simplify, verify) in their instructions. Subagent work that skips the gate is incomplete work.

**HARD STOP**: After this gate, you MUST run delivery steps before calling work complete.
DO NOT commit to main. DO NOT push directly. `finishing-a-development-branch` is NEXT.
