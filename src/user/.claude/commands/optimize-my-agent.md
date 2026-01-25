# Optimize Agent.md

You are an expert at writing effective agent instruction files. Your task is to analyze and optimize the agent.md file at: $ARGUMENTS

## Your Process

### Phase 1: Read and Understand
First, read the target agent.md file completely. Then identify:
1. **Agent Purpose**: What is this agent supposed to do?
2. **Current State**: How complete/effective is the current file?

If the purpose is unclear or missing, ask the user to clarify before proceeding.

### Phase 2: Assess Against Quality Criteria
Rate the file against these six core areas (derived from analysis of 2,500+ successful agent files):

| Area | Present? | Quality (1-5) | Notes |
|------|----------|---------------|-------|
| **Commands** | | | Executable commands with flags, not just tool names |
| **Testing** | | | How to run/validate the agent's work |
| **Project Structure** | | | File locations, what goes where |
| **Code Style** | | | Concrete examples, not descriptions |
| **Git Workflow** | | | Commit conventions, branch patterns |
| **Boundaries** | | | Clear never/ask-first/always rules |

### Phase 3: Identify Specific Problems
Check for these common failures:
- [ ] Too vague ("You are a helpful assistant" = useless)
- [ ] Missing executable commands (or commands without flags/options)
- [ ] Descriptions instead of examples for code style
- [ ] No explicit boundaries on what NOT to do
- [ ] Generic tech stack ("React project" vs "React 18 with TypeScript 5.3, Vite 5.x, Tailwind CSS 3.4")
- [ ] Missing file structure context
- [ ] No validation/testing commands

### Phase 4: Propose Improvements
For each gap, propose specific additions. Use this structure for your recommendations:

**Missing/Weak Area**: [area name]
**Current**: [what exists now, or "nothing"]
**Recommended Addition**:
```markdown
[exact content to add]
```
**Why**: [one sentence on why this matters]

### Phase 5: Collaborative Refinement
Present your assessment and proposed changes. Ask the user:
1. Which improvements they want to implement
2. If there are project-specific details you need to fill in
3. Whether boundary rules need adjustment for their workflow

Then generate the optimized file.

---

## Reference: What Makes Agent Files Work

### Effective Structure
```markdown
---
name: agent-name
description: One clear sentence about what this agent does
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
[Code examples showing good vs bad patterns - NOT descriptions]

## Boundaries
- ✅ **Always:** [things to always do]
- ⚠️ **Ask first:** [things requiring confirmation]
- 🚫 **Never:** [hard prohibitions - most important section]
```

### Key Principles
1. **Commands early**: Put executable commands near the top. Include flags and options.
2. **Examples > explanations**: One real code snippet beats three paragraphs describing style.
3. **Explicit boundaries**: "Never commit secrets" was the most common helpful constraint.
4. **Specific stack**: Versions matter. "React 18" not "React."
5. **Three-tier boundaries**: Always/Ask-first/Never prevents most mistakes.

### Common Agent Types That Work Well
- **@docs-agent**: Reads code, writes docs. Commands: `npm run docs:build`, `markdownlint`
- **@test-agent**: Writes tests. Boundary: never remove failing tests
- **@lint-agent**: Fixes style only. Boundary: never change logic
- **@api-agent**: Creates endpoints. Boundary: ask before schema changes

---

Now read the file at $ARGUMENTS and begin your assessment.