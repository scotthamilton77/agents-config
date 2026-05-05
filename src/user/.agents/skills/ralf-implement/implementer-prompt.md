# ralf-implement implementer prompt template

Use this template when dispatching the initial implementation subagent.

```
Agent tool (general-purpose, mode: "auto"):
  description: "Implement: [task name]"
  prompt: |
    You are implementing a task that will go through independent fresh-eyes refinement.
    Focus on correctness, test coverage, and clear fit to the Definition of Done.

    ## Definition of Done

    [PASTE the agreed Definition of Done here — the actual criteria]

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
    7. Report back with a structured implementation summary

    If ANYTHING is unclear, ask before proceeding. Don't guess.

    ## Report Format

    When done, report:
    - What you implemented (map to DoD criteria)
    - Test results (count, all passing?)
    - Build/typecheck/lint status
    - Files changed
    - Self-review: any DoD criteria you're uncertain about
    - Concerns or areas that might need refinement
```
