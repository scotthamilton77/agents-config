---
name: optimize-my-agent
model: sonnet
allowed-tools: Read, Write, Edit, Glob, Grep, AskUserQuestion
description: Audits and improves agent persona files (agents/*.md) for role clarity, commands, examples, and explicit boundaries. Use when asked to optimize an agent file, when reviewing an agent persona for quality, or when an agent description, commands, or boundary section needs cleanup. Do NOT use for SKILL.md files or AGENTS.md configuration files.
---

# Optimize My Agent

Analyze and optimize an agent persona file (an `agents/*.md` with frontmatter fields `name`, `description`, `model`, `color`, `tools`). The goal is clarity, executable commands, concrete examples, and explicit boundaries — not generic advice.

**Scope note**: This skill targets agent persona files (`agents/*.md` with frontmatter fields name/description/model/color/tools). Do NOT use for AGENTS.md configuration files or SKILL.md files — those have different schemas and different review rubrics.

## Phase 1: Read and Understand

Read the target agent.md file completely. Then identify:

1. **Agent Purpose**: What is this agent supposed to do? Look at the frontmatter description, the opening role statement, and any embedded examples.
2. **Current State**: How complete and effective is the current file? Note whether commands have flags, whether examples exist (vs descriptions), whether boundaries are explicit.

If the purpose is unclear or missing, use `AskUserQuestion` to clarify before proceeding. Do not invent a purpose from thin context — agents whose role is guessed end up generic.

## Phase 2: Assess Against Quality Criteria

Rate the file against the AGENTS_PRIMER quality issues. Produce this table verbatim — the row titles are load-bearing and must match the primer exactly:

| Area | Present? | Quality (1-5) | Notes |
|------|----------|---------------|-------|
| Over-broad role | | | |
| No examples in description | | | |
| Wrong model tier | | | |
| Body mixes role with task | | | |
| Bead references in shared agents | | | |
| `skills` lists unused skills | | | |

Each row asks a different question:

- **Over-broad role** — the agent claims a wide remit ("software engineering assistant") rather than a specific role with a verifiable output.
- **No examples in description** — the frontmatter description omits concrete invocation examples; downstream model routing has to guess.
- **Wrong model tier** — `model:` is mismatched with workload (heavy reasoning on haiku, trivial tasks on opus).
- **Body mixes role with task** — the persona file embeds per-task content instead of staying at the role level.
- **Bead references in shared agents** — agents installed to all tools reference `bd` or beads-only labels, breaking when beads isn't installed.
- **`skills` lists unused skills** — the `skills:` frontmatter preloads skills the agent never invokes, wasting context.

## Phase 3: Identify Specific Problems

Check for these common failures:

- [ ] Too vague ("You are a helpful assistant" = useless)
- [ ] Missing executable commands (or commands without flags/options)
- [ ] Descriptions instead of examples for code style
- [ ] No explicit boundaries on what NOT to do
- [ ] Generic tech stack ("React project" vs "React 18 with TypeScript 5.3, Vite 5.x, Tailwind CSS 3.4")
- [ ] Missing file structure context
- [ ] No validation/testing commands

Each unchecked box is a concrete remediation item for Phase 4. Do not skip the checklist — these are the failure modes that produced the AGENTS_PRIMER rubric in the first place.

## Phase 4: Propose Improvements

For each gap identified in Phases 2 and 3, propose a specific addition. Use this structure for every recommendation so the user can scan, accept, or reject without rereading the source:

**Missing/Weak Area**: [area name]
**Current**: [what exists now, or "nothing"]
**Recommended Addition**:
```markdown
[exact content to add]
```
**Why**: [one sentence on why this matters]

Do not propose vague rewrites ("clarify the role"). Every recommendation should be paste-ready text the user can drop into the file. If a recommendation requires project-specific facts you don't have, mark the unknowns clearly and ask for them in Phase 5 rather than inventing them.

## Phase 5: Collaborative Refinement

Present your assessment and proposed changes. Use `AskUserQuestion` to capture:

1. **Which improvements to implement** — accept, modify, or reject each Phase 4 proposal.
2. **Project-specific details to fill in** — exact tech stack versions, real command names, real file paths.
3. **Boundary rules** — whether the proposed always/ask-first/never rules match the user's workflow.

Then generate the optimized agent file. Show a diff against the original so the user can verify each landed change.

## Reference: What Makes Agent Files Work

### Effective Structure

```markdown
---
name: agent-name
description: One clear sentence about what this agent does, including when to invoke
model: sonnet
color: blue
tools: Read, Grep, Glob, Bash
---

You are an expert [specific role] for this project.

## Your Role
- What you specialize in
- What you understand
- What you produce

## Project Knowledge
- **Tech Stack:** [specific versions]
- **File Structure:**
  - `src/` – [what's here]
  - `tests/` – [what's here]

## Commands You Can Use
- **Build:** `npm run build` (what it does)
- **Test:** `npm test` (what it validates)
- **Lint:** `npm run lint --fix` (what it fixes)

## Standards
[Code examples showing good vs bad patterns — NOT descriptions]

## Boundaries
- **Always:** [things to always do]
- **Ask first:** [things requiring confirmation]
- **Never:** [hard prohibitions — most important section]
```

### Key Principles

1. **Commands early**: Put executable commands near the top. Include flags and options.
2. **Examples > explanations**: One real code snippet beats three paragraphs describing style.
3. **Explicit boundaries**: "Never commit secrets" was the most common helpful constraint.
4. **Specific stack**: Versions matter. "React 18" not "React."
5. **Three-tier boundaries**: Always / Ask-first / Never prevents most mistakes.

### Common Agent Types That Work Well

- **@docs-agent**: Reads code, writes docs. Commands: `npm run docs:build`, `markdownlint`
- **@test-agent**: Writes tests. Boundary: never remove failing tests
- **@lint-agent**: Fixes style only. Boundary: never change logic
- **@api-agent**: Creates endpoints. Boundary: ask before schema changes
