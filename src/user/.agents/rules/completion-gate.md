# Completion Gate

Implements `<verification-checklist>` steps 1–5 with concrete tools. Mandatory for non-trivial work (skip one-liners, config, typos); run in order, each step feeding the next:

1. `quality-reviewer` agent — review against plan and standards
2. Address its findings
3. `simplify` skill — refine the changed code
4. Address its findings
5. `verify-checklist` skill — tests, build, lint; evidence before claims

Applicable subagent work (work that changes project files) must still pass this gate. A worker MAY run the full gate inline on its own output (its own review, simplify, tests) but MUST NOT spawn its own subagents to do it — a worker can't reliably await a child, so it stalls silently. When a step needs a separate agent, the dispatcher owns it: the worker reports DONE, you gate the returned work before delivery.

Optional adversarial pass for high-stakes changes (architecture, security, final pre-merge): `/codex:adversarial-review --wait --model gpt-5.5` after the in-house steps.

HARD STOP — when the gate passes, deliver automatically; do not pause, do not commit or push to main. In order: `using-git-worktrees` (if not already isolated) → `finishing-a-development-branch` → `wait-for-pr-comments`. Pause only at the merge step: merging follows the repo's merge-authorization policy via merge-guard — `explicit` (default) needs a human instruction ("merge it" / "ship it" / "go ahead and merge"); `rule-based` repos merge autonomously when the configured rule and eligibility both hold; `never` repos hand off to the human. Everything up to and including PR creation is automatic. The policy is configured per-repo in `project-config.toml`'s `[merge-policy]` section (`merge-authorization`, `merge-rule`); absent that section, `explicit` applies. Resolve it via the `merge-guard` skill's `resolve_policy.py`, not by assuming the default — a repo may have opted into `rule-based`.
