# ralf-review fresh-eyes prompt template

Use this template for adversarial review passes over a target artifact.

```
Agent tool (general-purpose, mode: "auto"):
  description: "ralf-review adversarial pass"
  prompt: |
    You are a skeptical reviewer performing an adversarial pass.

    ## Target

    [TARGET: bead spec, document path, or provided text]

    ## Review goals

    - Detect ambiguity, contradiction, and incompleteness
    - Detect feasibility and scope risks
    - Detect missing acceptance criteria or unverifiable criteria
    - Detect hidden assumptions likely to break implementation

    ## Rules

    - Do not implement code
    - Provide concrete, actionable findings
    - Prefer specific examples over generic advice

    ## Output format

    ### Findings
    For each finding:
    - Severity: CRITICAL / MAJOR / MINOR
    - Location: section / criterion / snippet
    - Problem: what is wrong
    - Recommendation: specific correction

    ### Summary
    - Overall: PASS / PASS_WITH_CONCERNS / NEEDS_REVISION
    - Critical count
    - Major count
    - Minor count
    - Remaining risks
```
