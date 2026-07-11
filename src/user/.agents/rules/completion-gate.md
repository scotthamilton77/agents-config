# Completion Gate

Implements `<verification-checklist>` steps 1–5 with concrete tools, routed to one of three depths — `SKIP` / `SERIAL` / `HEAVY` — one contract, chosen at gate time. Mandatory for non-trivial work; the routing preamble below sizes trivially small changes into the `SKIP` tier (which still runs step 5) rather than bypassing the gate.

**Route first — pick the depth, then run it:**

- **Triage.** Run the `gate-triage` skill's `gate_triage.py` (`uv run <the skill's gate_triage.py> --repo-root . --base-ref <default branch>`) and capture its JSON payload — the tier floor, `scale_hint`, and `critical_path_hits`. The steps below call this "the triage JSON." If the helper exits non-zero (git error, unresolvable base ref, bad args) it produced no reliable measurement — fall back to `SERIAL`, never `SKIP`.
- **Escalate on risk class.** If the change touches security/auth, concurrency/locking, a public API/contract, a data migration/schema, or cross-subsystem architecture, raise the floor to `HEAVY`. Risk classes escalate only — never lower the tier.
- **Announce** one line: the tier, the driving facts, and the estimated `HEAVY` cost if applicable. Do not wait for approval.
- **Route** on the resolved tier:
    - `SKIP` (a size bound, not a file-type bound — a one-line change to a load-bearing or gate-policy file is never `SKIP`) → run **step 5 only** (mechanical evidence, where tests/build apply); skip steps 1–4.
    - `SERIAL` → run steps 1–5 below, **unchanged**.
    - `HEAVY` (Claude only) → invoke `Workflow({name: "quality-gate", args: <the triage JSON>})` **in place of steps 1–4**, then run step 5. Passing the triage JSON as `args` is **required, not optional** — the workflow sizes its fleet from `scale_hint`; omit it and it launches at default scale, silently defeating scale-to-the-diff. Step 5 (`verify-checklist`) still runs and is **non-substitutable**.
    - `HEAVY` **unavailable** (no Workflow harness — Codex/Gemini/OpenCode) → fall back to `SERIAL`.

`SERIAL` — run in order, each step feeding the next:

1. `quality-reviewer` agent — review against plan and standards
2. Address its findings
3. `simplify` skill — refine the changed code
4. Address its findings
5. `verify-checklist` skill — tests, build, lint; evidence before claims

Applicable subagent work (work that changes project files) must still pass this gate. A worker MAY run the full gate inline on its own output (its own review, simplify, tests) but MUST NOT spawn its own subagents to do it — a worker can't reliably await a child, so it stalls silently. When a step needs a separate agent, the dispatcher owns it: the worker reports DONE, you gate the returned work before delivery.

Optional adversarial pass for high-stakes changes (architecture, security, final pre-merge): `/codex:adversarial-review --wait --model gpt-5.6-sol` after the in-house steps.

HARD STOP — passing the gate at any tier (`SKIP`, `SERIAL`, or `HEAVY`) is not the finish line; the tier sets verification depth only, never whether delivery happens. When the gate passes, deliver automatically — do not pause, and do not commit or push directly to `main` (the PR branch is where the review-fix commits below belong). In order: `using-git-worktrees` (if not already isolated) → `finishing-a-development-branch` (create the PR) → **PR-review monitoring** → merge. PR-review monitoring is a required leg of the chain, not an optional coda: run `monitor-pr` where the prgroom CLI is deployed, otherwise `wait-for-pr-comments` — poll the review feedback, address it, push fixes, and resolve threads until the PR is quiescent. **Anti-stopping trip-wire:** declaring the work done at "PR created" without running that review loop is the exact regression this gate exists to prevent — if you catch yourself about to stop at PR-created, STOP and run the loop. The automatic scope runs all the way through PR-review monitoring; you pause only at the merge step. Merging follows the repo's merge-authorization policy via merge-guard — `explicit` (default) needs a human instruction ("merge it" / "ship it" / "go ahead and merge"); `rule-based` repos merge autonomously when the configured rule and eligibility both hold; `never` repos hand off to the human. The policy is configured per-repo in `project-config.toml`'s `[merge-policy]` section (`merge-authorization`, `merge-rule`); absent that section, `explicit` applies. Resolve it via the `merge-guard` skill's `resolve_policy.py`, not by assuming the default — a repo may have opted into `rule-based`.
