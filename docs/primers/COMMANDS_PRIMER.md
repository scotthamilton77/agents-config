# Slash Commands — Context Primer

> Use this document to orient yourself to slash command files before auditing or writing commands.

---

## What Commands Are and Why They Exist

A **slash command** is a user-initiated entry point — a `/command` the user types directly in their prompt. Commands exist to give users repeatable workflows that are too complex to type ad-hoc but too situation-specific to warrant a permanent agent definition. They are the external user interface to the system.

Commands differ from skills and agents in a critical way:
- **Skills** are invoked by agents, autonomously, during task execution, although users can explicitly reference a skill (e.g. 'use the /special-skill to ...' - arguably that could be a command if relatively simple, but skills bring other benefits such as progressive context reading)
- **Commands** are invoked by USERS, explicitly, at the start of a workflow
- **Agents** are dispatched by orchestrators for role-specific subwork

Commands should be lean and delegating: parse the user's intent, extract `$ARGUMENTS`, then execute in-agent for relatively simple tasks, or hand off to skills or agents for complex work. A command carrying pages of methodology has potentially confused itself with a skill.

---

## File Format

Markdown with YAML front matter. The front matter is not optional: the deploy
gate treats `commands` as a gated namespace, and **a command carrying no
`admission:` record is dropped at deploy** — it stages, and then simply never
lands in the tool's config directory. In this repository `content-lint` catches
it first and fails, because a record-less artifact under the user tree is fatal
there; where that gate does not run, the installer reports the drop and carries
on — a count of unadmitted artifacts on every run, and the names behind it only
under `--verbose`. A malformed record is worse in both places: it aborts the
whole deploy.

```markdown
---
description: One line, shown to the user in the command list. Nothing here
  reaches the model's context until someone types the command.
admission:
  provides: <the capability this supplies>   # or `prevents:`, never both
  cost: <what it costs, and on which surface>
  remove_when: <the observation that would retire it>
---

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

`$ARGUMENTS` is a placeholder that receives everything the user typed after the slash command name. Example: `/clean-up-git packages/` → `$ARGUMENTS = "packages/"`.

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

Commands installed from `src/user/.claude/commands/` land at `~/.claude/commands/` (user-scoped). Commands in `src/plugins/<plugin>/.<tool>/commands/` (e.g. `.claude/commands/`) are plugin-scoped.

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

- **Lean body**: a smell, not a cap — nothing in a command reaches context until it is invoked, so no token budget measures it. Length signals prose doing work that code should do, or methodology that belongs in a skill and role work that belongs in an agent.
- **Explicit `$ARGUMENTS` documentation**: what forms are accepted, what the defaults are, what happens on empty input.
- **Delegate, don't inline complexity**: use `Skill({ skill: "name" })` or dispatch an agent rather than re-implementing methodology inline.
- **Single purpose**: one command, one workflow. Complex branching logic is a signal to split into multiple commands.
- **Graceful empty args**: if `$ARGUMENTS` is optional, define the default behavior explicitly. If required, emit a clear usage message.

---

## Command vs. Skill vs. Agent

| Criterion | Command | Skill | Agent |
|-----------|---------|-------|-------|
| Who triggers it | User (explicit `/cmd`) | Agent (autonomous, when relevant) or user (explicit) | Orchestrator (dispatched) or user (explicit) |
| Runs in | Current session (inline) | Current session (loaded) | New isolated context |
| Contains methodology? | Only simple — delegates complex | Yes — is the methodology | No — delegates to skills |

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Too much inline instruction | 200+ line command body re-implementing a skill | Extract to skill; command delegates |
| Undocumented `$ARGUMENTS` | No description of input format or defaults | Add argument documentation section |
| No empty-args handling | Silent failure or undefined behavior when user omits args | Add explicit default behavior or usage message |
| Duplicate of a skill | Command re-implements what a skill already provides | Refactor: command calls the skill |
| Beads-specific content in a user-scoped command | `bd` commands or bead tracker terminology | Rewrite to use the `work` facade instead — agent workflow never invokes `bd` directly, only the tracker's one-time human bootstrap script does (`scripts/bootstrap-installer-beads.sh`), and no plugin exists to move the content to |
| Hardcoded paths or assumptions | Command assumes specific directory structure | Parameterize via `$ARGUMENTS` or config |

---

## File Locations

```
src/user/.claude/commands/         # Installs to ~/.claude/commands/ (user-scoped)
  <command-name>.md

src/plugins/<plugin>/
  .<tool>/commands/                # Plugin commands for one tool (e.g. .claude/commands/)
    <command-name>.md
```

Commands are a tool-scoped namespace — there is no shared commands tree, so the only names a new command can collide with are the other commands staged into that same tool: its own tree plus every active plugin's. Collisions are a **fatal install error** — check before adding.
