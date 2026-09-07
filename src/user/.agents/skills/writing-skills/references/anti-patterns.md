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

## Reading `persuasion-principles.md`

That file is carried for its background on why discipline prose reads the way it
does. The register split in `SKILL.md` overrides it, and three of its claims do
not survive contact with a current model.

Its per-principle recipes — deploy authority, scarcity and social-proof boosters
by skill type — lose to the split above and to the row in this table: stacked
imperatives make a model rigid rather than compliant, and the house prompt dialect
rules out ALL-CAPS pressure outright. Reach for a booster only in a discipline
document, only on the one rule that document exists to enforce; a second MUST
beside it dilutes the first.

The compliance figure it quotes comes from a study of jailbreak-style refusal on a
smaller, older model. Treat it as suggestive of the mechanism, not as an effect
size for skill instructions — baseline compliance on legitimate in-context
instructions leaves nothing like that headroom.

The tools it names in passing belong to one host. A skill in the shared tree ships
to every supported tool, so ask for a recorded choice — a box ticked, a decision
written down — rather than naming a particular tool's checklist. Its announce-the-
skill ritual is likewise a scaffold from a harness that showed the user nothing
else; where the host surfaces invocation itself, narrating it restates the UI.

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

The trigger-eval loop, with the eval shape it reads, is in `testing-methodology.md`.
