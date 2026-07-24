# Eval-Set Format

Used by Phase 4a (description-optimization loop via `scripts/run_loop.py`) and
Phase 4b (output-review battery via inline subagent orchestration).

## File location

`<skill-dir>/evals.json` — co-located with the SKILL.md it scores. Git-versioned
alongside the skill.

## Schema

A JSON array of eval entries. Each entry:

```json
{
  "query": "string — the user-facing prompt sent to a Claude instance with the skill loaded",
  "should_trigger": true,
  "expectations": [
    "string — a single observable behavior the skill's output should satisfy",
    "string — another expectation"
  ]
}
```

| Field | Required | Used by |
|-------|----------|---------|
| `query` | yes | both 4a (run_eval) and 4b (run-on-prompts) |
| `should_trigger` | yes | 4a precision/recall; 4b only consumes entries where this is `true` |
| `expectations` | optional list of strings | 4b grader subagent only; empty or missing list means "do not grade this run's output quality" |

## When auto-drafting (Phase 4a.1 fallback)

If `<skill-dir>/evals.json` is missing when `--deep` runs, the skill drafts a
starter set by reading the target SKILL.md. The auto-draft prompt instructs
Claude to:

1. Generate 5–10 `should_trigger:true` queries that a real user would phrase to
   invoke the skill — including 2–3 *near-miss* queries that the existing
   description might not catch but should.
2. Generate 5–10 `should_trigger:false` queries that are adjacent in topic but
   should NOT invoke the skill. Favor near-misses with sibling skills over
   wildly-unrelated queries (which prove nothing).
3. For each `should_trigger:true` entry, propose 1–3 observable expectations the
   skill's output should satisfy. Skip expectations for entries where the
   skill's output is inherently subjective (writing style, creative work).
4. Write the JSON array to `<skill-dir>/evals.json`.

The user reviews the drafted set before `run_loop.py` runs — the skill pauses
via AskUserQuestion with three options: Accept, Edit (skill pauses, user edits
the file, types continue), Reject (abort `--deep`).

## Quality criteria (weak vs strong evals)

**Weak eval — query is too generic or expectation is trivially satisfied:**

```json
{
  "query": "Help me write a skill.",
  "should_trigger": true,
  "expectations": ["produces a response"]
}
```

Anything triggers; any response passes. Useless signal.

**Strong eval — query is realistic and probes a specific failure mode:**

```json
{
  "query": "Can you audit the writing-skills skill for me and tell me if its description over-triggers?",
  "should_trigger": true,
  "expectations": [
    "Reads writing-skills/SKILL.md before proposing anything",
    "Reports concrete frontmatter findings, not vague advice",
    "Surfaces a per-skill structured proposal with current vs proposed description"
  ]
}
```

Specific query, observable behaviors, fails meaningfully if the skill drifts.

**Strong negative — adjacent but should NOT trigger:**

```json
{
  "query": "I want to write a brand new skill for parsing PDFs from scratch.",
  "should_trigger": false,
  "expectations": []
}
```

Probes the optimize-vs-create boundary with `writing-skills`.

## Subsequent runs

If the file already exists, the skill uses it as-is — no auto-draft, no
review gate. Users curate the file over time as the skill evolves and new
failure modes surface.
