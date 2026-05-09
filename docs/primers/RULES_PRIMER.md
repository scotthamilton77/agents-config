# Rules Files — Context Primer

> Use this document to orient yourself to rules files before auditing or writing rules.
> Reference: [Claude Code memory docs — organize rules with `.claude/rules/`](https://code.claude.com/docs/en/memory)

---

## What Rules Are

**Rules** are markdown files in `.claude/rules/` that Claude Code loads into the agent's context. Rules without a `paths` frontmatter field are loaded at session start with the same priority as `.claude/CLAUDE.md`. Rules with a `paths` field are **path-scoped**: they only enter context when Claude reads files matching the configured glob patterns.

> Quoted directly from the official docs:
> *"Rules load into context every session or when matching files are opened. For task-specific instructions that don't need to be in context all the time, use skills instead, which only load when you invoke them or when Claude determines they're relevant to your prompt."*

Rules are a Claude Code-specific construct. In this project, rules are authored Claude-specifically, but their substantive content is intended to be **universal in applicability**: the install pipeline will eventually embed rule content into the AGENTS.md instruction files for Codex, Gemini, and other tools. Author rules accordingly — the constraint or convention should be tool-agnostic in spirit, even though the file lives under `.claude/rules/`.

---

## File Format

Plain markdown. YAML frontmatter is **required only for path-scoped rules**.

### Always-loaded rule (no frontmatter)

```markdown
# Rule Name

One-line statement of what this rule governs.

Core constraint — what the agent always does or never does.

## When this applies
Specific situations or "all non-trivial work".

## What to do
Explicit prescriptions: "always X before Y", "never Z without explicit authorization".
```

### Path-scoped rule (with `paths` frontmatter)

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/api/**/*.tsx"
---

# API Development Rules

- All API endpoints must include input validation
- Use the standard error response format
- Include OpenAPI documentation comments
```

Path-scoped rules trigger when Claude reads files matching the patterns. Glob syntax supports brace expansion: `"src/**/*.{ts,tsx}"`.

---

## How Rules Load

| Rule type | When loaded |
|-----------|-------------|
| Rule with no `paths` field | Every session, at startup, like `.claude/CLAUDE.md` |
| Rule with `paths` field | Only when Claude reads a file matching one of the patterns |

User-level rules in `~/.claude/rules/` apply to every project. Project-level rules in `<project>/.claude/rules/` are loaded for that project specifically. **Project rules have higher priority than user rules** when both apply.

`.claude/rules/` supports symlinks for sharing a rule set across projects.

---

## Rules vs. Skills: When to Use Which

This is the most important authoring decision. The official guidance:

| Use a **rule** when | Use a **skill** when |
|--------------------|----------------------|
| Constraint must be in context for every relevant session | Methodology should load only when explicitly invoked |
| Content is normative — "always", "never", "must" | Content is prescriptive process — "do this, then this" |
| One sentence captures the essence; reader follows it directly | A checklist, decision tree, or multi-step workflow is needed |
| Violating it breaks workflow safety or correctness | Skipping it loses quality but does not break things |

If a rule has grown to 5+ steps of methodology, the methodology belongs in a skill. The rule then becomes: `"Always run the X skill before Y"` — and the X skill carries the process.

---

## Best Practices

- **Single purpose**: one file, one concern. Do not mix two policies into one rule file.
- **Normative language**: say "always", "never", "must", "must not". Advisory language ("should", "consider", "it's good to") indicates the content belongs in a skill, not a rule.
- **Action-oriented**: every rule must answer "what does the agent DO differently because of this rule?"
- **No methodology duplication**: if a skill encodes the how-to, the rule references the skill — it does not repeat the skill's instructions.
- **Authority grounding for hard constraints**: state the consequence or reason. `"Never commit to main — direct commits bypass PR review and break the audit trail"` is more durable than `"Never commit to main"`.
- **Path-scope when applicable**: if a rule only matters for a subset of files, add a `paths` field rather than burning context on every session.
- **Prefer helper scripts to inline shell sequences**: when a rule prescribes a deterministic command sequence, point to a helper script rather than embedding the sequence in prose. Prose-prescribed sequences drift; scripts are deterministic.

---

## How Rules Are Organized in This Project

Rules in this project are sourced under `src/` and installed into the user-level Claude Code rules directory by `scripts/install.sh`.

### Source layout

```
src/user/.claude/rules/            # Shared rules — install to ~/.claude/rules/
  <rule-name>.md

src/plugins/<plugin>/.claude/rules/   # Plugin rules — appended to base on install
  <rule-name>.md
```

### Collision / append model

Rule files with the same name across source trees (base + active plugins) are **appended** during install, not overwritten:

```
base:    src/user/.claude/rules/completion-gate.md
plugin:  src/plugins/beads/.claude/rules/completion-gate.md

result:  ~/.claude/rules/completion-gate.md
         = base content
           ---
           (plugin content appended)
```

The base content always lands first; plugins append alphabetically.

**Consequences for authors**:
- Plugin additions must be purely additive (new clauses, new contexts) — not replacements
- Do not duplicate base rule content in plugin additions; the append model handles it
- Read the base rule before writing a plugin extension to avoid contradictions

### Future intent (cross-tool embedding)

Rules are currently a Claude Code-only construct, but the install pipeline is intended to eventually embed rule content into AGENTS.md instruction files for Codex, Gemini, and other tools so the same constraints apply across all agents. Author rules with universal applicability in mind: the substantive guidance should be tool-agnostic, even though the file format and loading mechanism are Claude-specific.

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Duplicates skill content | Rule re-describes methodology a skill already encodes | Replace with "invoke skill X"; remove duplication |
| Advisory vs. normative drift | "Should", "consider", "it's good to" language in a rule file | Rewrite as "always", "never", "must" |
| Mixed concerns | One file governs both completion AND delivery | Split into two focused files |
| No consequence grounding | Hard constraint with no "why" anchor | Add one-line rationale |
| Over-specified how-to | Rule includes a 10-step methodology inline | Extract to skill; rule becomes "invoke skill X" |
| Inline shell sequences | Rule prescribes a deterministic command sequence in prose | Move to a helper script; rule references the script |
| Missing path scope | Rule only matters for a subset of files but loads every session | Add `paths` frontmatter to scope it |
| Tool-specific phrasing where universal would do | Rule guidance reads as Claude-Code-only when it could apply to any agent | Rephrase substantive content as tool-agnostic |
| Plugin rule contradicts base | Plugin addition conflicts with the base rule it appends to | Rewrite as extension, not contradiction |
