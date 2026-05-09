# Agent Skills — Context Primer

> Use this document to orient yourself to the skills system before auditing, writing, or executing skills.
> Reference: [Anthropic Agent Skills Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)

---

## What Skills Are and Why They Exist

A **skill** is a methodology guide — a text file that, when loaded, tells an agent *how* to approach a category of work. Skills exist because certain workflows (debugging, TDD, brainstorming, code review) benefit from a consistent, opinionated process. Rather than embedding that process in every agent definition, skills provide a shared, reusable methodology that any agent can invoke.

Skills are **on-demand**: they are NOT loaded into context by default. An agent explicitly invokes a skill when a situation matches the skill's trigger contract. Loading a skill injects its full content into the current context window.

---

## Invocation Model

**In Claude Code**: Use the `Skill` tool with the skill name.
```
Skill({ skill: "bugfix" })
Skill({ skill: "superpowers:brainstorming" })
```

**In Gemini CLI**: Use `activate_skill` — skills are auto-discovered at session start, loaded on demand.

**In Copilot CLI**: Use the `skill` tool.

The skill content is loaded and presented to the agent at invocation time. The agent follows it directly. The SKILL.md is the single source of truth — agents should never use the Read tool on skill files; the Skill tool is the intended interface.

---

## Frontmatter Schema

```yaml
---
name: skill-name                    # required; lowercase-kebab-case; matches directory name
description: "When to use..."       # required; single line ≤1024 chars; the trigger contract
model: opus[1m]                     # optional; overrides caller model for this skill
effort: high                        # optional; low | medium | high
allowed-tools: "Bash Read Grep"     # optional; restrict tool set
compatibility: "claude-code"        # optional; environment requirements
---
```

### The description field is the trigger contract

The description is the primary signal an agent uses to decide whether to invoke a skill. It must encode:
- **When**: observable situations that trigger invocation
- **Scope boundary**: what the skill does NOT cover ("Do NOT use for...")
- **Negative triggers**: exclusions that prevent misfires on similar topics

**Works**: `"Use when encountering a bug with unclear origins, when multiple files could be involved, or when the symptom does not obviously point to a single root cause"`

**Doesn't work**: `"Debugging skill"` (no trigger), `"Helps with bugs"` (vague), `"debug, bugfix, error, trace"` (keyword stuffing — Claude is not a search engine)

The 1% rule (from `using-superpowers`): if there is even a 1% chance a skill might apply, the agent MUST invoke it. Descriptions must be specific enough that clear non-matches self-select out without loading the body.

---

## Skill Body Structure

The body is what the agent reads after invocation. It should:
- Lead with what to do, not with history or rationale for the skill's existence
- Express the methodology clearly and actionably (checklists, process flows, decision trees)
- Include red flags and anti-patterns to prevent common mistakes
- Not duplicate content that should be in a referenced file (see Progressive Disclosure below)

### Rigid vs. Flexible Skills

**Rigid** (TDD, systematic-debugging): The body prescribes exact steps. The agent should follow it precisely; adapting away from the discipline undermines the purpose. The skill should say it is rigid.

**Flexible** (design patterns, style guidance): The body provides principles and heuristics. Agents adapt to context. The skill should say it is flexible.

---

## Progressive Disclosure

Long skill bodies should be split into a primary SKILL.md (the entry point) plus supporting files in subdirectories, loaded on demand:

```
skills/
  my-skill/
    SKILL.md               # Entry point — trigger contract + core process (~100-150 lines)
    references/
      edge-cases.md        # Loaded only when edge cases arise
      anti-patterns.md     # Loaded only when reviewing against anti-patterns
    examples/
      example-1.md         # Loaded only when a concrete example is needed
    scripts/
      helper.sh            # Support scripts called from SKILL.md
```

The SKILL.md should reference these files explicitly when the situation warrants loading them. Supporting files are loaded with the Read tool only when the current task needs them — not pre-loaded.

**Acid test for SKILL.md content**: "Does the agent need this to execute its FIRST STEP reliably?" Context the agent only needs later (edge case handling, historical examples, anti-pattern catalogs) belongs in a referenced file.

---

## Skill Types

| Type | Purpose | Examples |
|------|---------|---------|
| **Process skills** | How to APPROACH a category of work | `brainstorming`, `systematic-debugging`, TDD |
| **Implementation skills** | How to EXECUTE a specific task type | `frontend-design`, `mcp-builder` |
| **Inner-methodology skills** | How to do work INSIDE a bead step | `ralf-implement`, `ralf-review`, `verify-checklist` |
| **Lifecycle skills** | Pipeline management for bead-tracked work | `start-bead`, `implement-bead`, `run-queue` |

Process skills take priority over implementation skills when multiple apply — they set the *approach* before implementation begins.

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Vague trigger description | No observable trigger condition | Rewrite to "use when [situation]" |
| Missing scope boundary | Likely to over-trigger on similar topics | Add "Do NOT use for..." clause |
| History/rationale as primary content | Long preamble before the methodology | Move rationale to `references/` or remove |
| Mixed instruction + reference material | Body is part checklist, part anti-pattern catalog | Split into SKILL.md + `references/` |
| Content needed only at edge cases | Full catalog always loaded at invocation | Move to `references/` for on-demand loading |
| Bead references in shared skills | `bd` commands, bead IDs, bead tracker terminology in `src/user/` | Move to plugin namespace (`src/plugins/beads/`) |
| Spurious cross-references | "See also: skill-x" with no actionable dependency | Remove or make the dependency concrete |

---

## File Locations

```
src/user/.agents/skills/           # Shared skills (copied to all detected tools)
  <skill-name>/
    SKILL.md                       # Required entry point
    references/                    # Optional: on-demand reference files
    examples/                      # Optional: on-demand examples
    scripts/                       # Optional: helper scripts

src/plugins/<plugin>/
  .agents/skills/                  # Plugin-specific skills (installed only when plugin detected)
```

Shared skills must be tool-agnostic. Never reference Claude-specific tool names (Bash, Read, Agent) in shared skill bodies — use generic language that maps to any tool environment.
