# Bulletproofing Against Rationalization

Discipline skills must resist rationalization. Agents are smart and will
find loopholes under pressure. The techniques here apply primarily to
discipline-type skills; technique and reference skills usually don't need
them.

**Psychology background:** see `persuasion-principles.md` for the research
foundation (Cialdini, Meincke et al.) on authority, commitment, scarcity,
social proof, and unity — the levers that make discipline-skill prose stick.

## Close Every Loophole Explicitly

Don't just state the rule — forbid specific workarounds:

```markdown
Write code before test? Delete it. Start over.

No exceptions:
- Don't keep it as "reference"
- Don't "adapt" it while writing tests
- Don't look at it
- Delete means delete
```

## Address Spirit-vs-Letter Arguments

Add the foundational principle early in the skill:

> **Violating the letter of the rules is violating the spirit of the rules.**

This cuts off the entire class of "I'm following the spirit" rationalizations.

## Build a Rationalization Table

Capture rationalizations from baseline (RED-phase) testing. Every excuse
the agent makes goes in the table with an explicit counter:

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve the same purpose" | Tests-after = "what does this do?" Tests-first = "what should this do?" |

## Create a Red Flags List

Make it easy for the agent to self-check when rationalizing:

```markdown
## Red Flags — STOP and Start Over

- Code before test
- "I already manually tested it"
- "It's about spirit not ritual"
- "This is different because..."

All of these mean: Delete code. Start over with TDD.
```
