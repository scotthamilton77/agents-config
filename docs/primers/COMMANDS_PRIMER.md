# Slash Commands — Context Primer

> Use this document to orient yourself to slash command files before auditing or writing commands.

---

## What Commands Are and Why They Exist

A **slash command** is a user-initiated entry point — a `/command` the user types directly in their prompt. Commands exist to give users repeatable workflows that are too complex to type ad-hoc but too situation-specific to warrant a permanent agent definition. They are the external user interface to the system.

Commands differ from skills and agents in a critical way:
- **Skills** are invoked by agents, autonomously, during task execution
- **Commands** are invoked by USERS, explicitly, at the start of a workflow
- **Agents** are dispatched by orchestrators for role-specific subwork

Commands should be lean and delegating: parse the user's intent, extract `$ARGUMENTS`, then hand off to skills or agents that perform the actual work. A command that contains 200 lines of methodology has confused itself with a skill.

---

## File Format

Plain markdown. No frontmatter.

```markdown
# Command Name

Brief one-line description of what this command does.

`$ARGUMENTS` contains: [description of expected input and variations]

## Step 1 — Parse Input
Extract options/flags/scope from `$ARGUMENTS`. Document defaults.

## Step 2 — Delegate
Invoke the relevant skill or dispatch the relevant agent.

## Step 3 — Report
Summarize what was done.
```

`$ARGUMENTS` is a placeholder that receives everything the user typed after the slash command name. Example: `/optimize-my-skill writing-unit-tests` → `$ARGUMENTS = "writing-unit-tests"`.

---

## Invocation Model

The user types `/command-name [args]` in their prompt. The command file is loaded and executed inline in the current agent session — it is NOT a separate subagent. The command runs in the current context window.

Because commands run inline, they have access to the full current session context, but they also consume that context. Long-running commands that will produce large outputs should delegate to subagents to protect the orchestrator's context.

---

## Scope: User vs. Project

| Install location | Scope | Usage |
|----------|-------|-------|
| `~/.claude/commands/` | Available in ALL projects | User-wide workflows (optimize, refresh, audit) |
| `<project-root>/.claude/commands/` | Available in THIS project only | Project-specific shortcuts |

Commands installed from `src/user/.claude/commands/` land at `~/.claude/commands/` (user-scoped). Commands in `src/plugins/<plugin>/commands/` are plugin-scoped.

---

## `$ARGUMENTS` Patterns

```markdown
# Typical patterns for documenting $ARGUMENTS:

`$ARGUMENTS` specifies the target:
- **Skill name**: "bugfix", "writing-unit-tests" — targets that specific skill
- **Directory path**: "~/.claude/skills/" — targets all skills in that directory
- **Empty**: defaults to [describe default behavior]

# Or with flags:
`$ARGUMENTS` may contain:
- **Time range**: "last 2 weeks", "since v2.0", "50 commits" (default: 30 days)
- **Focus areas**: any remaining text describing what to emphasize
```

Always document what happens when `$ARGUMENTS` is empty. Commands that fail silently on missing args are a usability failure.

---

## Best Practices

- **Lean body**: under 80 lines. Complex methodology belongs in a skill; complex role work belongs in an agent.
- **Explicit `$ARGUMENTS` documentation**: what forms are accepted, what the defaults are, what happens on empty input.
- **Delegate, don't inline**: use `Skill({ skill: "name" })` or dispatch an agent rather than re-implementing methodology inline.
- **Single purpose**: one command, one workflow. Complex branching logic is a signal to split into multiple commands.
- **Graceful empty args**: if `$ARGUMENTS` is optional, define the default behavior explicitly. If required, emit a clear usage message.

---

## Command vs. Skill vs. Agent

| Criterion | Command | Skill | Agent |
|-----------|---------|-------|-------|
| Who triggers it | User (explicit `/cmd`) | Agent (autonomous, when relevant) | Orchestrator (dispatched) |
| Runs in | Current session (inline) | Current session (loaded) | New isolated context |
| Typical body length | Short (< 80 lines) | Medium (50-200 lines) | Long (role charter) |
| Contains methodology? | No — delegates | Yes — is the methodology | No — delegates to skills |

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Too much inline instruction | 200+ line command body re-implementing a skill | Extract to skill; command delegates |
| Undocumented `$ARGUMENTS` | No description of input format or defaults | Add argument documentation section |
| No empty-args handling | Silent failure or undefined behavior when user omits args | Add explicit default behavior or usage message |
| Duplicate of a skill | Command re-implements what a skill already provides | Refactor: command calls the skill |
| Beads-specific content in shared commands | `bd` commands or bead tracker terminology | Move to plugin commands namespace |
| Hardcoded paths or assumptions | Command assumes specific directory structure | Parameterize via `$ARGUMENTS` or config |

---

## File Locations

```
src/user/.claude/commands/         # Installs to ~/.claude/commands/ (user-scoped)
  <command-name>.md

src/plugins/<plugin>/
  commands/                        # Plugin-specific commands
  <command-name>.md
```

Command names must be unique across the merged installation tree (shared + all active plugins). Collisions are a **fatal install error** — check before adding.
