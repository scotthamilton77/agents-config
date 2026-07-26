# Anti-Patterns and Presentation Rules

Consult at review time, before shipping a skill.

## Anti-Patterns

| Anti-pattern | Why it fails |
|--------------|--------------|
| Narrative example ("In session 2025-10-03 we found...") | Too specific, not reusable |
| Multi-language dilution (example.js, example.py, example.go) | Mediocre quality, maintenance burden |
| Code in flowcharts (`step1 [label="import fs"]`) | Can't copy-paste, hard to read |
| Generic labels (helper1, helper2, step3) | No semantic meaning |
| Description summarizes workflow | Agent follows the summary, skips the body |
| Hard MUSTs in a technique skill | Makes the agent rigid; explanation produces capability |
| @-linking other skills (`@skills/foo/SKILL.md`) | Force-loads, burns context. Use plain references instead. |

## Flowcharts

Use flowcharts ONLY for non-obvious decision points and process loops where
the agent might stop too early. Never for reference material (use tables),
code examples (use markdown blocks), or linear instructions (use numbered
lists). Labels must have semantic meaning — no `step1`, `helper2`.

For graphviz style rules, see `graphviz-conventions.dot`. To render a skill's
flowcharts to SVG for visual review, use `scripts/render-graphs.js`:

```bash
./scripts/render-graphs.js ../some-skill            # each diagram separately
./scripts/render-graphs.js ../some-skill --combine  # all diagrams in one SVG
```

## Code Examples

One excellent example beats many mediocre ones.

- Complete and runnable.
- Well-commented, explaining WHY (not WHAT).
- From a real scenario, not a contrived one.
- Ready to adapt, not a fill-in-the-blank template.

Don't implement the same example in five languages. Don't write generic
templates. Agents are good at porting; one strong example is enough.

A worked example of skill testing lives in `../examples/CLAUDE_MD_TESTING.md`.
