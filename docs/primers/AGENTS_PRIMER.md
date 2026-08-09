# Agent Definitions — Context Primer

> Use this document to orient yourself to agent definition files before auditing or writing agents.

---

## What Agents Are and Why They Exist

An **agent definition** is a specialized AI persona — a role file that, when an orchestrating agent dispatches it, instantiates a subagent with a prescribed purpose, skills, tools, model, and memory scope. Agent files exist because some work is best done by a fresh context with a single focused role: a code reviewer should not also be writing tests, and a test writer should not be reviewing security.

Agents differ from skills in a critical way:
- **Skills' frontmatter** (`name` + `description`) is loaded into the main agent's context, giving it awareness of a skill's purpose; the agent loads and follows the full body only when the context implicitly warrants it or the user explicitly asks. A subagent's `skills:` frontmatter field works the opposite way: it injects each named skill's **full content** into the subagent's context at startup, not just its frontmatter — see the skills primer's Invocation Model section
- **Agents** are DISPATCHED as separate instances — a new context with its own tools, skills, model, and isolation boundary

A subagent dispatched via the `Agent` tool runs in parallel with the orchestrator and reports back when complete.

### Key constraints (from the official docs)

- **Subagents can spawn subagents of their own**, by default up to three layers below the main conversation (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` changes the limit). At the depth limit, Claude Code withholds the `Agent` tool from the deepest subagent, so it does the delegated work itself and returns one summary instead of nesting further.
- **Subagents start in the main conversation's working directory.** The working directory persists between the subagent's own Bash calls, but shell state (env vars, aliases) does not, and a `cd` never affects the parent's working directory. Use `isolation: worktree` to give the subagent an isolated copy of the repository.
- **Subagents receive their own system prompt** (the file body) plus basic environment details — not the full Claude Code system prompt. They DO receive the same CLAUDE.md/AGENTS.md hierarchy the main conversation loads (user-level, project-level, `CLAUDE.local.md`, managed policy); the built-in Explore and Plan agents are the only exception and skip it. What a subagent does NOT inherit is the rest of the conversation's state — prior tool outputs, already-invoked skills, conversation history — so restate anything from there it needs.
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
model: opus                    # optional; options: sonnet, opus, haiku, fable, a full model ID (e.g. claude-opus-5), or inherit (default)
effort: high                   # optional; low | medium | high | xhigh | max
memory: project                # optional; project | user | local (omit for none, the default)
color: purple                  # optional; display color in UI
admission:                     # required for deployment (see below)
  provides: <the capability this supplies>   # or `prevents:`, never both
  cost: <what it costs, and on which surface>
  remove_when: <the observation that would retire it>
---
```

`agents` is a gated namespace alongside `rules`, `skills` and `commands`: an agent
definition carrying no `admission:` record is dropped at deploy and any previously
deployed copy is pruned, and a malformed record aborts the whole deploy. The gate
strips the record from the bytes that ship. The rules primer's File Format section
states the mechanism in full; it applies here unchanged.

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
| `opus` | Thoroughness required: code review, security analysis, architectural assessment, adversarial review |
| `sonnet` | Balanced speed/quality: general implementation, coordination |
| `haiku` | Fast and mechanical: evidence collection, grep/search, format verification, triage |
| `fable` | Frontier-tier judgment; `src/user/.claude/rules/delegation.md` requires consulting the user before spawning a subagent on this tier |

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
| Tool-capability dependence in a shared agent | A shared agent depends on a capability only one tool has (Claude subagent orchestration, the Skill tool, `AskUserQuestion`, hooks) — naming a tracker CLI like `work` does not qualify on its own; it runs from any tool's shell | Move it to that tool's tree, or to the owning plugin (`src/plugins/<plugin>/`) |
| No `admission:` record | Front matter carries `name` and `description` only | Add a complete record; without one the agent deploys nothing |
| `skills` lists unused skills | `skills:` field lists skills the body never references or invokes | Remove unused skill references |

---

## File Locations

```
src/user/.agents/agents/           # Shared agents (staged into every active tool except OpenCode, which refuses the shared agents namespace)
  <agent-name>.md

src/user/.claude/agents/           # Claude-only agents (staged into ~/.claude/ alone)
  <agent-name>.md

src/plugins/<plugin>/
  .agents/agents/                  # Plugin agents for every active tool except OpenCode (same exclusion as the shared tree)
    <agent-name>.md
  .<tool>/agents/                  # Plugin agents for one tool (e.g. .claude/agents/)
    <agent-name>.md
```

None of these directories exists in the tree today — this repository ships no agent definitions at all, so the layout above is where one would go rather than where one is. `agents` is nonetheless a live staged namespace, which is why the admission record above is required rather than aspirational.

Shared agents must not reference Claude-specific constructs (e.g. claude rules) in their bodies. Use generic language that maps to multiple tool environments, or place an agent that needs a Claude-only capability in the Claude tree instead.
