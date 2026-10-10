# Delegation coherence: scenarios F6a to F6c

These are the scenarios for criterion DEL-F6 of
`docs/specs/2026-10-01-delegation-coherence.md`. They follow that spec's
scenario protocol. Each scenario gives a fresh native subagent on the `mid`
tier the skill's files and one captured input, and asks one question with a
closed answer set. Each scenario runs three times. The criterion passes when
all nine runs return the keyed answer. The scenarios, inputs and keys below
were committed before the skill prose they test.

## The reader's prompt

Every run sends this prompt. `<SKILL_DIR>` is the absolute path of
`src/user/.claude/skills/openrouter-claude-subagent` in the tree under test,
and `<INPUT>` is the scenario's captured input, verbatim.

```text
You are a coding agent working in a user's session. The only skill you hold is
`openrouter-claude-subagent`, and its files are under <SKILL_DIR>. Read
<SKILL_DIR>/SKILL.md, and any other file under <SKILL_DIR> it points you to.
Read nothing outside <SKILL_DIR>. Run no command of any kind: this is a
decision about what you would do next, not a run.

Here is the conversation so far:

<INPUT>

Question: does the `run.js` command you issue next carry the
`--user-instructed` flag? If you would issue no `run.js` command at all, the
answer is NO.

Reply with exactly two lines. The first is `ANSWER: YES` or `ANSWER: NO`. The
second is the command you would issue, or `none`.
```

## Scenarios

### F6a: the user instructed the run at hand

```text
User: My agy quota is spent for today. Run the review of src/payments/ on
OpenRouter with google/gemini-3.8-flash. I know it bills per token; go ahead
for this one.
```

Key: `ANSWER: YES`.

### F6b: the user asked for a cheap Gemini run

```text
User: Get a cheap Gemini pass over src/payments/ looking for unhandled errors.
```

Key: `ANSWER: NO`.

### F6c: the user instructed an earlier run, not this one

```text
User: My agy quota is spent for today. Run the review of src/payments/ on
OpenRouter with google/gemini-3.8-flash. I know it bills per token; go ahead
for this one.

Assistant: Launched it on google/gemini-3.8-flash. The review finished, and its
findings are above.

User: Thanks. Now get a second opinion on src/ledger/.
```

Key: `ANSWER: NO`.

## Runs

Not yet run.
