# Completion Gate

Implements shared `<verification-checklist>` steps 1–5 with Claude-specific tools.

MANDATORY for non-trivial work (skip for obvious one-liners, config changes, typos):

1. `quality-reviewer` agent — review changes against plan and standards (checklist step 1)
2. Address any findings from quality-reviewer (checklist step 2)
3. `simplify` skill — simplify/refine changed code (checklist step 3)
4. Address any findings from the `simplify` skill (checklist step 4)
5. `verify-checklist` skill — run tests, build, lint; evidence before claims; structured completion report (checklist step 5)

No exceptions. No partial runs. Each step feeds the next.

**Subagents**: When dispatching subagents to do implementation work, always include the full completion gate workflow (review, simplify, verify) in their instructions. Subagent work that skips the gate is incomplete work.

**Optional adversarial pass** (operator-initiated): For high-stakes changes (architecture shifts, security-sensitive code, final pre-merge), add `/codex:adversarial-review --wait --model gpt-5.4` as defense-in-depth after the in-house review steps.

**HARD STOP**: After this gate, AUTOMATICALLY execute delivery steps. Do NOT pause for authorization.
DO NOT commit to main. DO NOT push directly.

Execute IN ORDER, without asking: (1) `using-git-worktrees` if not already in one, (2) `finishing-a-development-branch`, (3) `wait-for-pr-comments` (which internally chains to `reply-and-resolve-pr-threads` for thread reply + resolve). Only pause at the merge step — see `delivery.md` for the action categorization.
