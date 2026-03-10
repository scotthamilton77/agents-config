# RALF-IT Implementer Subagent Prompt Template

Use this template when dispatching the initial implementation subagent(s).

```
Agent tool (general-purpose, mode: "auto"):
  isolation: "worktree"  (if not already in a worktree)
  description: "Implement: [task name]"
  prompt: |
    You are implementing a task as part of a RALF-IT iterative refinement workflow.
    Your work will be reviewed and refined by subsequent agents, so focus on getting
    the implementation RIGHT rather than fast.

    ## Definition of Done

    [PASTE the agreed Definition of Done here — not a summary, the actual criteria]

    ## Task Description

    [FULL TEXT of task/plan/spec — paste it, don't make subagent read a file]

    ## Context

    [Where this fits architecturally, dependencies, related files, conventions]

    ## Your Job

    1. Read and understand the spec completely before writing code
    2. Follow TDD: write tests first, watch them fail, implement, refactor
    3. Implement exactly what the spec requires — no more, no less
    4. Run build, typecheck, lint, and tests — all must pass
    5. Commit your work with semantic commit messages
    6. Self-review against the Definition of Done
    7. Report back

    If ANYTHING is unclear, ask before proceeding. Don't guess.

    ## Report Format

    When done, report:
    - What you implemented (map to DoD criteria)
    - Test results (count, all passing?)
    - Build/typecheck/lint status
    - Files changed
    - Self-review: any DoD criteria you're uncertain about
    - Concerns or areas that might need refinement

    Work from: [worktree directory]
```
