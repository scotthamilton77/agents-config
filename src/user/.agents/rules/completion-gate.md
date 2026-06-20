# Completion Gate

Implements shared `<verification-checklist>` steps 1–5 with Claude-specific tools.

MANDATORY for non-trivial work (skip for obvious one-liners, config changes, typos):

1. `quality-reviewer` agent — review changes against plan and standards
2. Address any findings from quality-reviewer
3. `simplify` skill — simplify/refine changed code
4. Address any findings from the `simplify` skill
5. `verify-checklist` skill — run tests, build, lint; evidence before claims; structured completion report

No exceptions. No partial runs. Each step feeds the next.

**Subagents**: subagent-produced work must still pass this gate — but mind *who* runs it and *how*. A dispatched worker MAY run the full gate on its own work, provided it does so **without spawning its own subagents**: run each step inline (its own review pass, its own simplification, its own tests/build/lint). A worker generally cannot reliably await a child agent it spawns, so a worker that tries to gate by dispatching reviewer/fixer agents will stall silently. When a gate step genuinely needs a *separate* agent, the dispatcher owns it: have the worker report DONE, then gate the returned work yourself before delivery.

**Optional adversarial pass** (operator-initiated): For high-stakes changes (architecture shifts, security-sensitive code, final pre-merge), add `/codex:adversarial-review --wait --model gpt-5.5` as defense-in-depth after the in-house review steps.

**HARD STOP**: After this gate, AUTOMATICALLY execute delivery steps. Do NOT pause for authorization.
DO NOT commit to main. DO NOT push directly.

Execute IN ORDER, without asking: (1) `using-git-worktrees` if not already in one, (2) `finishing-a-development-branch`, (3) `wait-for-pr-comments` (which internally chains to `reply-and-resolve-pr-threads` for thread reply + resolve). Only pause at the merge step — the delivery rule's action categories define automatic vs. authorized steps.
