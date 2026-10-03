# Bulletproofing Against Rationalization

Discipline skills must resist rationalization. Agents are smart and will
find loopholes under pressure. The techniques here apply primarily to
discipline-type skills; technique and reference skills usually don't need
them.

## Name Each Loophole and Its Target

State the rule with its reason, then name each workaround that baseline
testing surfaced. Pair each one with the behaviour to do instead, so the
agent's attention lands on the target rather than on the workaround:

```markdown
Wrote code before its test? Delete it and start over from the test.
The test has to come from the requirement, and code in view pulls the
test toward what the code already does.

- Tempted to keep it as "reference"? Delete the file instead.
- Tempted to "adapt" it while writing tests? Write new code from the
  failing test instead.
- Tempted to look at it? Start from the requirement and an empty file.
```

## Answer Spirit-vs-Letter Arguments

State early in the skill what the rule's letter protects. An agent that
claims to meet the purpose another way can then see that the other way
loses exactly that:

> The test comes first because a test written after the code checks what
> the code does, not what it should do. Any route that writes the test
> second loses that, whatever else it achieves.

This answers the whole class of "I'm following the spirit" rationalizations,
because the reason shows the letter and the spirit are the same thing.

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
## Red Flags

- Code before test
- "I already manually tested it"
- "It's about spirit not ritual"
- "This is different because..."

Each of these means the code came before its test: delete the code and
start over with TDD.
```
