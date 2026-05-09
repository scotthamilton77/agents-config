# Rules Files — Context Primer

> Use this document to orient yourself to rules files before auditing or writing rules.

---

## What Rules Are and Why They Exist

**Rules** are normative constraints — always-on guidance that is present in the agent's context regardless of what task is being performed. They encode "how we work here": process requirements, tool conventions, safety boundaries, and workflow patterns that apply to every task.

Rules differ from skills and instructions in key ways:

| Content type | Scope | When active |
|-------------|-------|-------------|
| `INSTRUCTIONS.md` | Shared across ALL tools (Claude, Codex, Gemini) | Always — loaded at session start |
| Rules files | Claude-specific (or tool-specific) constraints | Always — referenced from AGENTS.md |
| Skills | Tool-specific methodology guides | On-demand — agent invokes when relevant |

Rules are loaded into the agent's context at session start via AGENTS.md references. An agent reading a rules file is not deciding whether to follow it — it is always in effect, for every task.

---

## File Format

Plain markdown. No frontmatter required.

```markdown
# Rule Name

One-line statement of what this rule governs.

Core constraint statement — what the agent always does or never does.

## When this applies
Specific situations where this rule is active (may be "all non-trivial work").

## Action categories / What to do
Explicit prescriptions: "always X before Y", "never Z without explicit authorization".

## Examples / Edge cases
Optional: concrete scenarios that clarify the rule's application.
```

---

## Rules in This Repository

| File | Governs |
|------|---------|
| `completion-gate.md` | Mandatory quality gate steps before delivery: quality-reviewer → simplify → verify-checklist |
| `delivery.md` | PR and branch workflow; automatic vs. authorization-required action categories |
| `delegation.md` | Which skill to use for planning, implementation, and testing |
| `git-commits.md` | Commit message format; heredoc prohibition in sandbox mode |
| `worktrees.md` | Worktree creation location (always `.claude/worktrees/`, never elsewhere) |
| `subagents.md` | Rules for dispatching and managing subagents |
| `codex-routing.md` | How to route work to Codex models via the Claude Code Codex plugin |
| `beads.md` _(plugin)_ | Full bead lifecycle, parent-chain invariants, session separation rules |

---

## Instruction Hierarchy

```
User explicit instructions (CLAUDE.md / AGENTS.md directives, user messages)  ← highest priority
    ↓
Superpowers skills (override default behavior where specified)
    ↓
Rules files (always-on normative constraints)
    ↓
Default system behavior                                                         ← lowest priority
```

Rules override default behavior but yield to user instructions. When a rule conflicts with an explicit user direction, follow the user direction and note the conflict.

---

## Collision / Append Model

Rules files with the same name across source trees are **appended** (not overwritten) during install:

```
base:    src/user/.claude/rules/completion-gate.md
plugin:  src/plugins/beads/.agents/rules/completion-gate.md

result:  ~/.claude/rules/completion-gate.md
         = base content
           ---
           (plugin content appended)
```

This means a plugin can EXTEND an existing rule by adding clauses. The base content always lands first; plugins append alphabetically.

**Consequence for authors**:
- Do not duplicate base rule content in plugin additions — the append model handles it
- Plugin additions should be purely additive (new clauses, new contexts) not replacements
- Read the base rule before writing a plugin extension to avoid contradictions

---

## Rules vs. Skills: When to Use Which

| Use a **rule** when | Use a **skill** when |
|--------------------|----------------------|
| Constraint applies to ALL tasks regardless of context | Methodology applies only when a specific situation arises |
| Content is normative ("must", "never", "always") | Content is prescriptive process ("do this, then this") |
| Violating it breaks the workflow or creates risk | Skipping it loses quality but doesn't break things |
| One sentence captures the essence | A checklist or decision tree is needed |

If a rule has grown to 5+ steps of methodology, consider whether the methodology belongs in a skill that the rule references: `"Always run the X skill before Y"` is a rule; the X skill's process is a skill.

---

## Best Practices

- **Single purpose**: one file, one concern. `completion-gate.md` governs the gate; `delivery.md` governs the pipeline. Don't mix.
- **Normative language**: say "always", "never", "must", "must not" — not "should", "consider", or "it's good to". Advisory language belongs in skills or INSTRUCTIONS.md.
- **Action-oriented**: every rule should be answerable: "what does the agent DO differently because of this rule?"
- **No methodology duplication**: if a skill encodes the how-to, the rule says "invoke skill X for Y" — it does not repeat the skill's instructions.
- **Authority grounding**: for hard constraints, state the consequence or reason. `"Never commit to main — direct commits bypass PR review and break the audit trail"` is better than just `"Never commit to main"`.
- **Explicit action categories**: for actions that are sometimes automatic and sometimes require authorization, create an explicit table (see `delivery.md` for a good example).

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Duplicates skill content | Rule re-describes methodology a skill already encodes | Replace with "invoke skill X"; remove duplication |
| Advisory vs. normative drift | "Should", "consider", "it's good to" language | Rewrite as "always", "never", "must" — or move to a skill |
| Mixed concerns | One file governs both completion AND delivery | Split into two focused files |
| No consequence grounding | Hard constraint with no "why" anchor | Add one-line rationale ("because X would happen otherwise") |
| Over-specified how-to | Rule includes 10-step methodology inline | Extract to skill; rule becomes "invoke skill X" |
| Beads concepts in non-plugin rules | `bd` commands or bead IDs in `~/.claude/rules/` (not a plugin rule) | Move to plugin rules (`src/plugins/beads/.agents/rules/`) |
| Plugin rule contradicts base | Plugin addition conflicts with the base rule it appends to | Rewrite as extension, not contradiction |

---

## File Locations

```
src/user/.claude/rules/            # Installs to ~/.claude/rules/ (user-scoped, always active)
  <rule-name>.md

src/plugins/<plugin>/
  .agents/rules/                   # Plugin-specific rules (active only when plugin detected)
  <rule-name>.md                   # Appended to base rule of same name on install
```
