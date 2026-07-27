# Testing Methodology

How to verify a skill works, by skill type, plus the trigger-eval loop that
applies to all three. For the full pressure-subagent methodology, see
`testing-skills-with-subagents.md`.

## Pressure Scenarios (Discipline Skills)

Combine multiple pressures to surface rationalizations:

- **Time pressure** ("the deploy is in 10 minutes")
- **Sunk cost** ("you already wrote the implementation, just write tests
  to match it")
- **Authority** ("the senior engineer said to skip TDD here")
- **Exhaustion** (long context, many turns, late in a session)

Document the exact rationalization the agent produces. Each rationalization
goes into the skill's rationalization table with an explicit counter.

## Application Scenarios (Technique Skills)

Give the agent a new problem the technique should solve. Verify they apply
the method correctly, including edge cases and variations. Look for gaps in
the instructions where the agent had to guess.

## Retrieval Scenarios (Reference Skills)

Give the agent a question whose answer is in the reference. Verify they
find it, interpret it correctly, and apply it. Common gap: covered concepts
versus covered use cases — agents need use-case-shaped entry points, not
just concept-shaped ones.

## Trigger-Eval Methodology (All Skill Types)

The description decides whether the skill ever loads. Test it directly with
a trigger-eval set of 16-20 realistic queries:

**8-10 should-trigger queries.** Different phrasings of the same intent —
formal, casual, abbreviated. Include cases where the user doesn't name the
skill or its concepts. Include uncommon use cases and competing-skill
scenarios where this skill should win.

**8-10 should-not-trigger queries.** The valuable ones are *near-misses* —
queries that share keywords or concepts but actually need a different skill
or no skill at all. Adjacent domains, ambiguous phrasing, contexts where
another tool wins. Avoid trivially-irrelevant negatives — they test
nothing.

**Realistic phrasing.** Real users include specifics — file paths, column
names, company names, URLs, a little backstory. Some are lowercase, some
have typos. A good query:

> ok so my boss just sent me this xlsx file (its in my downloads, called
> something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a
> column that shows the profit margin as a percentage. The revenue is in
> column C and costs are in column D i think

A bad query:

> Format this data.

### Manual trigger-eval workflow

1. Write the 16-20 queries as `evals/trigger-eval.json`:
   ```json
   [
     {"query": "the user prompt", "should_trigger": true},
     {"query": "another prompt",  "should_trigger": false}
   ]
   ```
2. For each query, dispatch a subagent in an environment with the skill
   available; ask it whether it would invoke the skill, and why. Run each
   query 3 times to get a reliable trigger rate (model output is stochastic).
3. Tabulate hit rates: true-positives (correctly triggered),
   false-negatives (should have triggered, didn't), true-negatives
   (correctly skipped), false-positives (incorrectly triggered).
4. Iterate the description against the failures. Re-run.

Automation of this loop (a scripted optimizer that proposes description
edits, splits train/test, and runs to convergence) is the future home of
`scripts/run_loop.py` — not yet shipped in this skill. The
`evals/trigger-eval.json` shape is defined inline above; `schemas.md` covers
the broader eval/grading JSON shapes the future automation will use
(`evals/evals.json`, `grading.json`).

### How triggering actually works

Skills appear in the agent's available list with their name + description.
The agent decides whether to consult a skill based on that description.
Critically, simple one-step queries the agent can handle directly often
won't trigger any skill regardless of description quality — keep eval
queries substantive enough that a skill would actually help.
