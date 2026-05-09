# Agent Definitions — Context Primer

> Use this document to orient yourself to agent definition files before auditing or writing agents.

---

## What Agents Are and Why They Exist

An **agent definition** is a specialized AI persona — a role file that, when an orchestrating agent dispatches it, instantiates a subagent with a prescribed purpose, tools, model, and memory scope. Agent files exist because some work is best done by a fresh context with a single focused role: a code reviewer should not also be writing tests, and a test writer should not be reviewing security.

Agents differ from skills in a critical way:
- **Skills** are loaded INTO the current agent's context — the agent invokes the skill and follows it in the same session
- **Agents** are DISPATCHED as separate instances — a new context with its own tools, model, and isolation boundary

An agent dispatched via the `Agent` tool runs in parallel with the orchestrator and reports back when complete. A forked agent (no `subagent_type`) inherits the orchestrator's full conversation context.

---

## Frontmatter Schema

```yaml
---
name: agent-name              # required; lowercase-kebab-case
description: |-               # required; multi-line allowed; the dispatch trigger contract
  What this agent does and when to dispatch it.

  Examples:
  <example>
  Context: ...
  user: "..."
  assistant: "..."
  <commentary>...</commentary>
  </example>

tools: Read, Grep, Glob, Bash  # recommended; explicit tool list for this role
skills: [skill-a, skill-b]     # optional; pre-loaded skills available to this agent
model: opus[1m]                # optional; options: opus[1m], sonnet[1m], sonnet, haiku
effort: high                   # optional; low | medium | high
memory: project                # optional; project | user | none (default)
color: purple                  # optional; display color in UI
---
```

The body follows — a full description of the agent's role, responsibilities, methodology, and communication protocol.

---

## Description as Dispatch Trigger

The description serves two purposes simultaneously:
1. **Dispatch signal**: tells the orchestrating agent WHEN to use this agent (observable situations, not abstract capabilities)
2. **Role framing**: the `<example>` blocks show the agent its own role through demonstrated context

Examples in the description are load-bearing — they establish the agent's mental model of its own job. An agent dispatched with no examples in its description must infer its role from the body alone.

**Works**: Description that starts with `"PROACTIVELY review code for quality, security, maintainability, AND alignment with the plan/spec after any code is written or modified"` — observable trigger + clear scope.

**Doesn't work**: `"A code reviewer"` — too abstract; no trigger signal for the orchestrator.

---

## Model Assignment Guidelines

| Model | Use for |
|-------|---------|
| `opus[1m]` | Thoroughness required: code review, security analysis, architectural assessment, adversarial review |
| `sonnet[1m]` | Balanced deep context: coordination requiring long context, complex multi-file analysis |
| `sonnet` | Balanced speed/quality: general implementation, coordination |
| `haiku` | Fast and mechanical: evidence collection, grep/search, format verification, triage |

Assign the most capable model *needed* for the role — not the most capable available. Haiku is the right choice for the `bead-verifier` (run quality-gate commands, report exit codes); Opus is right for `quality-reviewer` (deep architectural and security analysis).

---

## Tools Field

List only the tools the agent actually needs. Omit tools the role does not require:

| Role type | Typical tools |
|-----------|---------------|
| Read-only auditor | `Read, Grep, Glob, Bash` |
| Code writer | `Read, Edit, Write, Bash` |
| Orchestrator / coordinator | All tools (needs `Agent` tool to dispatch sub-subagents) |
| Browser automation | `mcp__claude-in-chrome__*` tools + core tools |

Over-broad tool grants are both a focus problem (agents reason better with a constrained set) and a safety concern (unneeded write tools on an auditor).

---

## Memory Scope

| Value | Behavior |
|-------|---------|
| `project` | Agent can read/write project-level persistent memory across sessions |
| `user` | Agent can read/write user-level persistent memory across sessions |
| `none` (default) | Ephemeral — all state is local to the current dispatch |

Most subagents should be ephemeral. Assign `memory: project` only to agents that need to persist findings or decisions across sessions (e.g., a quality reviewer tracking recurring issues).

---

## Agent Body Structure

The body follows the frontmatter and contains the agent's full operational charter:

```
## Core Responsibilities
What the agent is responsible for (bulleted).

## Methodology / Operational Framework
How the agent works — phases, decision criteria, specific steps.

## Output Format / Feedback Structure
How the agent reports findings or results.

## Communication Protocol
When to ask, when to decide, how to escalate.

## Quality Standards
What "done" looks like for this role.

## Constraints
What this agent does NOT do (important for scope clarity).
```

Keep the body focused on the ROLE — not on the specific task being dispatched. Task-specific instructions belong in the dispatch prompt, not the agent definition.

---

## Agent vs. Skill: Decision Table

| Situation | Use an agent | Use a skill |
|-----------|-------------|-------------|
| Work needs full context isolation | ✓ | |
| Fresh perspective / foreign eyes needed | ✓ | |
| Role has prescribed tools or model | ✓ | |
| Task can run in parallel with other work | ✓ | |
| Methodology runs in current conversation context | | ✓ |
| Process applies regardless of which agent is doing the work | | ✓ |
| Accumulated conversation context is needed | | ✓ |

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Over-broad role | "Does anything technical" or no bounded scope | Narrow to one specialty |
| No examples in description | Plain text description, no `<example>` blocks | Add 1-2 concrete dispatch scenarios |
| Underspecified tools | No `tools:` field; agent inherits all tools by default | Add explicit tools list |
| Wrong model tier | Haiku reviewing security-critical code; Opus doing a simple grep | Match model to role demands |
| Body mixes role with task | Body contains task-specific instructions that should be in dispatch prompt | Move task specifics to caller's prompt |
| Bead references in shared agents | `bd` commands or bead terminology in `src/user/` agents | Move to plugin namespace (`src/plugins/beads/`) |
| Skills list unused | `skills:` field lists skills the body never references or invokes | Remove unused skill references |

---

## File Locations

```
src/user/.agents/agents/           # Shared agents (copied to all detected tools)
  <agent-name>.md

src/plugins/<plugin>/
  .agents/agents/                  # Plugin-specific agents (installed only when plugin detected)
  <agent-name>.md
```

Shared agents must not reference Claude-specific constructs (Bash tool, git CLI flags, Skill tool syntax) in their bodies. Use generic language that maps to multiple tool environments, or move Claude-specific agents to `src/user/.claude/agents/`.
