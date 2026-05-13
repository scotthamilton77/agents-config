# Agent Skills — Context Primer

> Use this document to orient yourself to the skills system before auditing, writing, or executing skills.
> References:
> - [Anthropic Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
> - [Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)

---

## What Skills Are

A **skill** is a methodology guide — a SKILL.md file (with optional supporting files) that tells an agent *how* to approach a category of work. At session startup, only the `name` and `description` from each skill's YAML frontmatter are pre-loaded. Claude reads SKILL.md only when the skill becomes relevant, and reads supporting files only on demand. This is **progressive disclosure**: the context window cost is paid in proportion to actual use.

Skills exist because some workflows (debugging, TDD, brainstorming, code review) benefit from a consistent, opinionated process. Rather than embedding that process in every agent definition, skills provide a shared, reusable methodology that any agent can invoke.

---

## Invocation Model

| Tool | How skills are invoked |
|------|------------------------|
| Claude Code | `Skill` tool with the skill name (e.g. `Skill({ skill: "bugfix" })`) |
| Gemini CLI | `activate_skill` tool — skills auto-discovered at session start |
| Copilot CLI | `skill` tool |

Agents do not use the Read tool on SKILL.md files; the Skill tool is the interface.

When a subagent definition lists skills in its `skills:` frontmatter field, those skills' **full content** is injected into the subagent's context at startup (this is the inverse of the on-demand model).

---

## Frontmatter Schema

Per the official Anthropic spec, the SKILL.md frontmatter has two **required** fields:

```yaml
---
name: skill-name           # required; max 64 chars; lowercase letters/numbers/hyphens only
                            # no XML tags; cannot contain reserved words "anthropic" or "claude"
description: "..."         # required; max 1024 chars; non-empty; no XML tags
                            # MUST be written in third person
---
```

### Optional documented fields

| Field | Purpose |
|-------|---------|
| `license` | SPDX identifier (MIT, Apache-2.0, etc.) |
| `allowed-tools` | Restrict tool access (space-separated patterns, e.g. `"Bash(python:*) WebFetch"`) |
| `compatibility` | Environment requirements (1-500 chars) |
| `metadata` | Custom YAML object (author, version, etc.) |

### Project-specific extensions seen in this codebase

Some skills in this project use additional fields not part of the official spec but interpreted by the Claude Code harness:

```yaml
model: opus[1m]      # which model to invoke for this skill
effort: high         # low | medium | high | xhigh | max
```

When auditing, treat these as project conventions; verify with the harness behavior before adding them to new skills.

---

## The Description Is the Trigger Contract

The description is the primary signal Claude uses to decide whether to invoke a skill. It must encode WHAT the skill does and WHEN to use it.

**Write in third person.** The description is injected into the system prompt; first-person or second-person phrasing causes discovery problems.

- ✓ "Processes Excel files and generates reports"
- ✗ "I can help you process Excel files"
- ✗ "You can use this to process Excel files"

**Be specific and include observable triggers.**

- ✓ `"Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction."`
- ✗ `"Helps with documents"` (vague)
- ✗ `"document, pdf, parse, extract, table, form"` (keyword stuffing — Claude is not a search engine)

A negative trigger ("Do NOT use for…") sharpens scope when the skill is adjacent to other skills that could be confused with it.

---

## Naming Conventions

Use **gerund form** (verb + -ing) for clarity about the activity the skill provides:

- ✓ `processing-pdfs`, `analyzing-spreadsheets`, `writing-documentation`
- Acceptable alternatives: noun phrases (`pdf-processing`) or action-oriented (`process-pdfs`)
- ✗ Avoid: `helper`, `utils`, `tools`, `documents`, `data`, or any name containing reserved words

---

## SKILL.md Body Structure

The body is what the agent reads after invocation. It should:

- Lead with what to do, not with rationale or history
- Express methodology clearly (checklists, process flows, decision trees)
- Include red flags / anti-patterns to prevent common mistakes
- Push detail not needed at first-step into supporting files (see Progressive Disclosure)

**Body length budget**: keep SKILL.md under **500 lines** for optimal performance. Approaching that limit is a signal to split content into separate reference files.

---

## Degrees of Freedom

Match the level of specificity to task fragility:

| Freedom | Use when | Form |
|---------|----------|------|
| **High** | Multiple approaches valid; decisions depend on context | Text instructions and heuristics |
| **Medium** | A preferred pattern exists, some variation OK | Pseudocode or scripts with parameters |
| **Low** | Operations are fragile; consistency is critical | Specific scripts with few or no parameters |

A database migration that must run in exact sequence: low freedom. A code review where context determines approach: high freedom.

---

## Progressive Disclosure

Long skill bodies should be split into a primary SKILL.md plus supporting files, loaded on demand:

```
skills/
  processing-pdfs/
    SKILL.md           # Entry point — under 500 lines
    FORMS.md           # Loaded when user mentions form filling
    REFERENCE.md       # Loaded when API details are needed
    EXAMPLES.md        # Loaded when concrete examples are needed
    scripts/
      analyze_form.py  # Executed, not read into context
```

### Keep references one level deep

Claude may partially read files referenced from referenced files. **All reference files should link directly from SKILL.md**, not from each other.

- ✓ `SKILL.md → references/api.md` (one hop)
- ✗ `SKILL.md → references/intro.md → references/details.md` (two hops; risk of incomplete reads)

### TOC for longer reference files

For reference files longer than 100 lines, include a table of contents at the top so Claude sees the full scope even when previewing partial content.

### Acid test for what stays in SKILL.md

"Does the agent need this to execute its FIRST STEP reliably?" Edge cases, anti-pattern catalogs, exhaustive examples — those go in supporting files. The SKILL.md is the launching pad.

---

## Common Patterns

| Pattern | Use for | Form |
|---------|---------|------|
| **Workflow checklist** | Multi-step processes where Claude must track progress | Code-block checklist Claude can copy and check off |
| **Plan-validate-execute** | Batch operations, destructive changes, complex validation | Intermediate JSON/file → validation script → execution |
| **Feedback loop** | Quality-critical tasks | Validator → fix errors → repeat → only proceed when clean |
| **Conditional workflow** | Decision points based on input characteristics | "If X, follow workflow A; if Y, follow workflow B" |

---

## Utility Scripts

Pre-built scripts in `scripts/` are preferred over inline code generation when a deterministic operation is needed:

- More reliable than generated code
- Save tokens (not loaded into context)
- Save time (no generation)
- Ensure consistency

**Make execution intent explicit**:

- "Run `analyze_form.py` to extract fields" → execute (most common)
- "See `analyze_form.py` for the extraction algorithm" → read as reference

---

## MCP Tool References

When a skill references MCP tools, **always use the fully qualified `ServerName:tool_name` format** to avoid "tool not found" errors:

- ✓ `Use the BigQuery:bigquery_schema tool to retrieve table schemas.`
- ✗ `Use the bigquery_schema tool…` (ambiguous when multiple MCP servers are available)

---

## Avoid

- **Time-sensitive information**: "Before August 2025, use the old API" rots. Use a "## Old patterns" section with a `<details>` block instead.
- **Inconsistent terminology**: pick one term (e.g. "field" not a mix of "field"/"box"/"element") and use it throughout.
- **Windows-style paths**: always use forward slashes; backslashes break on Unix.
- **Too many options**: present a default with an escape hatch, not a menu of equivalents.
- **Punting on errors**: scripts should handle errors explicitly, not rely on Claude to figure out what went wrong.
- **Voodoo constants**: every magic number gets a comment explaining why that value.

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| Vague trigger description | No observable trigger condition; too abstract | Rewrite to "use when [situation]"; include third-person phrasing |
| Description not in third person | "I can…" or "You can…" framing | Rewrite as "Processes…", "Generates…" |
| Description over 1024 chars | Validation will fail | Tighten or split |
| `name` violates schema | Uppercase, spaces, reserved words, XML, over 64 chars | Rename to lowercase-kebab-case |
| Body over 500 lines | SKILL.md is the entire methodology with no supporting files | Split into reference files; keep SKILL.md as entry point |
| References more than one level deep | SKILL.md → A → B → C | Flatten to SKILL.md → A, SKILL.md → B, SKILL.md → C |
| Reference file >100 lines without TOC | Claude may read partial content and miss sections | Add a Contents section at the top |
| History/rationale as primary content | Long preamble before the methodology | Move rationale to references/ or remove |
| Mixed instruction + reference material | Body contains both checklist AND anti-pattern catalog AND examples | Split: SKILL.md = checklist; references/ = catalog and examples |
| Time-sensitive information in main body | Dates that will go stale | Move to "Old patterns" section with `<details>` |
| Inconsistent terminology | Same concept named multiple ways across the body | Pick one term; replace all instances |
| Windows-style paths | Backslashes in path examples | Convert to forward slashes |
| Bead references in shared skills | `bd` commands or bead terminology in `src/user/` skills | Move to plugin namespace (`src/plugins/beads/`) |
| Inline shell sequences for deterministic logic | Skill prescribes complex bash steps in prose | Extract to a script; skill references the script |
| Missing MCP qualified names | `bigquery_schema` instead of `BigQuery:bigquery_schema` | Add server prefix |
| Spurious cross-references | "See also: skill-x" with no actionable dependency | Remove or make the dependency concrete |

---

## File Locations

```
src/user/.agents/skills/           # Shared skills (copied to all detected tools)
  <skill-name>/
    SKILL.md                       # Required entry point
    <REFERENCE>.md                 # Optional: on-demand reference files (one level deep)
    scripts/                       # Optional: helper scripts (executed, not read)

src/plugins/<plugin>/
  .agents/skills/                  # Plugin-specific skills (installed only when plugin detected)
```

Shared skills must be tool-agnostic. Tool-specific behavior (Bash, Read, Agent tools by name) belongs in plugin skills or in the optional `allowed-tools` frontmatter field where it can be enforced rather than narrated.
