# Agent Definitions — Context Primer

> Use this document to orient yourself to agent definition files before auditing or writing agents.

---

## What Agents Are and Why They Exist

An **agent definition** is a specialized AI persona — a role file that, when an orchestrating agent dispatches it, instantiates a subagent with a prescribed purpose, skills, tools, model, and memory scope. Agent files exist because some work is best done by a fresh context with a single focused role: a code reviewer should not also be writing tests, and a test writer should not be reviewing security.

Agents differ from skills in a critical way:
- **Skills' frontmatter** are loaded INTO the main agent's context giving the agent awareness of a skill's purpose, but for subagents configured with specific skills, these are loaded into the subagent's context on spawn; the agent loads and executes the skill when the context implicitly warrants it or the user explicitly asks for it, and follows it in the same session
- **Agents** are DISPATCHED as separate instances — a new context with its own tools, skills, model, and isolation boundary

A subagent dispatched via the `Agent` tool runs in parallel with the orchestrator and reports back when complete.

### Key constraints (from the official docs)

- **Subagents cannot spawn other subagents.** If a workflow needs nested delegation, use skills or chain subagents from the main conversation.
- **Subagents start in the main conversation's working directory.** `cd` commands do not persist between Bash calls within the subagent and do not affect the parent. Use `isolation: worktree` to give the subagent an isolated copy of the repository.
- **Subagents receive only their system prompt** (the file body) plus basic environment details — not the full Claude Code system prompt or the parent's CLAUDE.md context.
- **Plugin subagents do not support `hooks`, `mcpServers`, or `permissionMode`** for security reasons. These fields are ignored when an agent is loaded from a plugin.

---

## Frontmatter Schema (relevant subset)

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

tools: Read, Grep, Glob, Bash  # NOT recommended except for read-only agents; explicit tool list for this role
disallowedTools: Write, Edit   # recommended only when explicit prohibitions are necessary (and all other tools are allowed)
skills: [skill-a, skill-b]     # optional; pre-loaded skills available to this agent
model: opus[1m]                # optional; options: opus[1m], sonnet[1m], sonnet, haiku
effort: high                   # optional; low | medium | high | xhigh | max
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

**Works**: Description that starts with `"Use this agent when..."` along with observable (or explicit) trigger + clear scope.

**Doesn't work**: `"A code reviewer"` — too abstract; no trigger signal for the orchestrator.

---

## Model Assignment Guidelines

| Model | Use for |
|-------|---------|
| `opus[1m]` | Thoroughness required: code review, security analysis, architectural assessment, adversarial review |
| `sonnet[1m]` | Balanced deep context: coordination requiring long context, complex multi-file analysis |
| `sonnet` | Balanced speed/quality: general implementation, coordination |
| `haiku` | Fast and mechanical: evidence collection, grep/search, format verification, triage |

Assign the most capable model *needed* for the role — not the most capable available.  Tune the effort similarly.

---

## Memory Scope

When the `memory:` field is set, the subagent gets a persistent directory that survives across conversations. Per the official docs:

| Value | Location | When to use |
|-------|----------|-------------|
| `project` (recommended default) | `.claude/agent-memory/<agent-name>/` | Project-specific knowledge, shareable via version control |
| `user` | `~/.claude/agent-memory/<agent-name>/` | Knowledge that applies across all projects |
| `local` | `.claude/agent-memory-local/<agent-name>/` | Project-specific knowledge that should not be checked in |
| (field omitted) | none | Ephemeral — no persistent memory directory |

When memory is enabled, Claude Code automatically enables Read/Write/Edit tools so the subagent can manage its memory files, and includes the first 200 lines (or 25KB) of `MEMORY.md` in the system prompt at startup.

Most subagents should be ephemeral. Enable memory only for agents that genuinely benefit from cross-session learning (subject matter experts, reviewers tracking recurring patterns).

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
| Wrong model tier | Haiku reviewing security-critical code; Opus doing a simple grep | Match model to role demands |
| Body mixes role with task | Body contains task-specific instructions that should be in dispatch prompt | Move task specifics to caller's prompt |
| Bead references in shared agents | `bd` commands or bead terminology in `src/user/` agents | Move to plugin namespace (`src/plugins/beads/`) |
| `skills` lists unused skills | `skills:` field lists skills the body never references or invokes | Remove unused skill references |

---

## File Locations

```
src/user/.agents/agents/           # Shared agents (copied to all detected tools)
  <agent-name>.md

src/plugins/<plugin>/
  .agents/agents/                  # Plugin-specific agents (installed only when plugin detected)
  <agent-name>.md
```

Shared agents must not reference Claude-specific constructs (e.g. claude rules) in their bodies. Use generic language that maps to multiple tool environments, or move Claude-specific agents to `src/user/.claude/agents/`.
