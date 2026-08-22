# Agent Skills — Context Primer

> Use this document to orient yourself to the skills system before auditing, writing, or executing skills.
> References:
> - [Anthropic Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
> - [Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)

---

## What Skills Are

A **skill** is a methodology guide — a SKILL.md file (with optional supporting files) that tells an agent *how* to approach a category of work. At session startup, only the `name` and `description` from each skill's YAML frontmatter are pre-loaded — and on Claude Code, a skill that sets `disable-model-invocation` is left out of that pre-load entirely (see Body budget). Claude reads SKILL.md only when the skill becomes relevant, and reads supporting files only on demand. This is **progressive disclosure**: the context window cost is paid in proportion to actual use.

Skills exist because some workflows (debugging, TDD, brainstorming, code review) benefit from a consistent, opinionated process. Rather than embedding that process in every agent definition, skills provide a shared, reusable methodology that any agent can invoke.

---

## Invocation Model

| Tool | How skills are invoked |
|------|------------------------|
| Claude Code | `Skill` tool with the skill name (e.g. `Skill({ skill: "bugfix" })`) |
| Gemini CLI | `activate_skill` tool — skills auto-discovered at session start (unconfirmed; see the caveat below) |
| Copilot CLI | `skill` tool |

The four tools this repository installs into are Claude Code, Codex CLI, Gemini CLI and OpenCode; a shared skill is staged into all four. Copilot CLI appears above as a format reference, not as an install target. The invocation mechanism for Codex and OpenCode is not recorded here, and the Gemini row above is not established either: this project's own installer declares Gemini's skill loading unmodelled (`UNMODELLED_SKILL_LOADERS` — see Body budget), because no vendor documentation confirms whether a deployed skill reaches Gemini's runtime at all. Confirm all three against their own tools rather than inferring from this table.

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

### Required for deployment: the admission record

Those two fields make a skill *valid*; they do not make it *ship*. The deploy
gate treats `skills` as a gated namespace, and **a skill whose SKILL.md carries
no `admission:` record is dropped at deploy** — it stages, and then simply never
lands in the tool's config directory, while any copy an earlier run deployed is
pruned. In this repository `content-lint` catches it first and fails, because a
record-less artifact under `src/user/` is fatal there; where that gate does not
run, the installer reports the drop and carries on — a count of unadmitted
artifacts on every run, and the names behind it only under `--verbose`. A
malformed record is worse in both places: it aborts the whole deploy.

```yaml
---
name: skill-name
description: "..."
admission:
  provides: <the capability this supplies>   # or `prevents:`, never both
  cost: <what it costs, and on which surface>
  remove_when: <the observation that would retire it>
---
```

A skill directory keeps its record in `SKILL.md` and nowhere else — a directory
without one has no inspectable record and is dropped. The gate strips what it
admits: the `admission:` and `claims:` blocks never reach the deployed bytes and
are not charged against the body budget, so write them for the next maintainer of
this repository rather than for the agent that loads the skill.

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
model: sonnet        # which model to invoke for this skill
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

### Body budget

The budget is a token cap, not a line count, and it is enforced rather than advised. Each admitted skill **body** — the SKILL.md content after its front matter — is weighed as `ceil(bytes / 4)` against one of two caps in `packages/installer/src/installer/core/surface_budget.py`. A model-invoked skill is held to `SKILL_BODY_TOKEN_CAP`, currently **2,000 tokens**. A skill whose front matter sets `disable-model-invocation: true` is held to `USER_INVOKED_SKILL_BODY_TOKEN_CAP`, currently **5,000 tokens**. That flag is read from the **deployed** front matter, after the per-tool projection has stripped it for a tool whose loader does not define the key — so one skill's cap depends on which tool is being staged: on a tool that strips the key the strict 2,000-token cap is the one that applies there, even on Codex, where the deploy translates the declaration into a generated sidecar rather than leaving the skill model-invocable. Gemini's skill loading is deliberately unmodelled (see Invocation Model above), so neither cap is computed for it at all — no catalog charge, no body cap. The test is for the parsed YAML boolean and nothing else, so `true`, `True`, `yes` and `on` all qualify, while a quoted `"true"`, a bare `1`, or a misspelt key leaves the skill on the 2,000-token cap — the safe direction for the budget, and worth knowing when a body you believed was user-invoked fails the gate at 2,000. A breach is fatal: the deploy aborts before any write, and `make content-lint` fails the same way in this repository.

The two numbers price two different costs. A model-invoked skill's body is loaded on the model's own judgement, mid-task, on top of whatever the context is already carrying. On Claude Code, a skill carrying the flag is kept out of the model's catalog entirely — not even its description is pre-loaded — so it is reached only when the user names it, and its body is paid at a moment the user chose. The invocation relief is real on Claude Code and Codex: Codex defines no equivalent front-matter key, so the deploy strips the flag there and emits Codex's own declaration instead — a generated `agents/openai.yaml` sidecar carrying `policy.allow_implicit_invocation: false` — while OpenCode has no equivalent at all, so there the stripped flag leaves the skill model-invocable whatever its author declared. The cap relief is narrower: the flag is read from the deployed front matter, so the strict 2,000-token cap measures the body on Codex and OpenCode either way — on Codex an over-charge in the safe direction, and on both, the looser cap is relief on Claude Code, not a courtesy the deploy extends everywhere. Progressive disclosure applies identically to both kinds of skill, and a body that fits 5,000 tokens only because nothing was moved into `references/` has passed the gate and failed its intent.

Three consequences worth holding onto:

- **Only the body is charged.** Front matter, `references/`, and `scripts/` fall outside the measurement, which is exactly what makes progressive disclosure the way to stay under the cap rather than a stylistic preference.
- **Bytes, not lines.** A dense table costs several times more per line than a sparse list, so no line count converts reliably into a token count in either direction. The number the gate reads is the byte count.
- **Measure, do not estimate.** `make content-lint` prints every admitted skill's body weight against the cap that applies to it on a pass, so headroom is visible as a trend before it becomes a failed deploy.

When a body outgrows the cap, move sections into `references/` verbatim and leave a pointer. Cutting content to fit is how a skill quietly stops teaching what it used to.

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
    SKILL.md           # Entry point — the only file charged against the body cap
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
| No `admission:` record | Front matter carries `name` and `description` only | Add a complete record; without one the skill deploys nothing and any deployed copy is pruned |
| Incomplete `admission:` record | States both `prevents` and `provides`, or neither; a required field is empty | Fix it — a malformed record aborts the whole deploy, not just this artifact |
| Body over the token cap | SKILL.md is the entire methodology with no supporting files | Move sections into reference files verbatim; keep SKILL.md as entry point |
| References more than one level deep | SKILL.md → A → B → C | Flatten to SKILL.md → A, SKILL.md → B, SKILL.md → C |
| Reference file >100 lines without TOC | Claude may read partial content and miss sections | Add a Contents section at the top |
| History/rationale as primary content | Long preamble before the methodology | Move rationale to references/ or remove |
| Mixed instruction + reference material | Body contains both checklist AND anti-pattern catalog AND examples | Split: SKILL.md = checklist; references/ = catalog and examples |
| Time-sensitive information in main body | Dates that will go stale | Move to "Old patterns" section with `<details>` |
| Inconsistent terminology | Same concept named multiple ways across the body | Pick one term; replace all instances |
| Windows-style paths | Backslashes in path examples | Convert to forward slashes |
| Tool-capability dependence in a shared skill | A skill under `src/user/.agents/skills/` depends on a capability only one tool has (Claude subagent orchestration, the Skill tool, `AskUserQuestion`, hooks) — naming a tracker CLI like `work` does not qualify on its own; it runs from any tool's shell, and four shipped shared skills already name it | Move it to that tool's tree (`src/user/.claude/skills/`) or to the owning plugin (`src/plugins/<plugin>/`) |
| Inline shell sequences for deterministic logic | Skill prescribes complex bash steps in prose | Extract to a script; skill references the script |
| Shipped script with no test suite | A `.py`/`.js`/`.sh` file with no sibling `<stem>_test.*` or `test_<stem>.*` | Add the suite — `content-tests` fails a shipped script that has none |
| Missing MCP qualified names | `bigquery_schema` instead of `BigQuery:bigquery_schema` | Add server prefix |
| Spurious cross-references | "See also: skill-x" with no actionable dependency | Remove or make the dependency concrete |

---

## File Locations

```
src/user/.agents/skills/           # Shared skills — staged into EVERY active tool
  <skill-name>/
    SKILL.md                       # Required entry point; carries the admission record
    <REFERENCE>.md                 # Optional: on-demand reference files (one level deep)
    scripts/                       # Optional: helper scripts (executed, not read)

src/user/.claude/skills/           # Claude-only skills — staged into ~/.claude/ alone
  <skill-name>/

src/plugins/<plugin>/
  .agents/skills/                  # Plugin skills for every active tool
  .<tool>/skills/                  # Plugin skills for one tool (e.g. .claude/skills/)
```

Where a skill lives decides which tools receive it, and a skill is admitted or dropped the same way in every one of these trees — a plugin can be discovered, activated, and still install nothing. Two differences are worth knowing: `content-lint` treats a record-less artifact as fatal under `src/user/` but only reports it under `src/plugins/`, and a plugin's content deploys only into tools that are themselves detected — by auto-detection. An explicit `--tools=` override bypasses detection entirely: `resolve_tools` (`packages/installer/src/installer/config.py`) skips the per-tool adapter's `is_detected` check (defined on each tool adapter, e.g. `packages/installer/src/installer/tools/claude.py`) and returns exactly the tools named, and the install pipeline stages and overlays into every tool in that resolved set regardless of whether it was actually detected.

Skills are discovered exactly one level deep, so every immediate child of a skills root is one skill — never an organizational subfolder. Names must be unique across the combined tree (shared plus tool-specific plus every active plugin); a collision is a fatal install error, unlike the append-merge that rules get.

Shared skills must be tool-agnostic. Tool-specific behavior (Bash, Read, Agent tools by name) belongs in a tool tree or a plugin skill, or in the optional `allowed-tools` frontmatter field where it can be enforced rather than narrated.
