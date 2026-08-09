# Rules Files — Context Primer

> Use this document to orient yourself to rules files before auditing or writing rules.
> Reference: [Claude Code memory docs — organize rules with `.claude/rules/`](https://code.claude.com/docs/en/memory)

---

## What Rules Are

**Rules** are markdown files in a tool's `rules/` directory. Claude Code loads them into the agent's context; the other three tools are meant to get the same content by a different route, described below. A rule whose front matter carries no `paths` field is loaded at session start with the same priority as `.claude/CLAUDE.md`. A rule with a `paths` field is **path-scoped**: it only enters context when the agent reads files matching the configured glob patterns.

> Quoted directly from the official docs:
> *"Rules load into context every session or when matching files are opened. For task-specific instructions that don't need to be in context all the time, use skills instead, which only load when you invoke them or when Claude determines they're relevant to your prompt."*

The `paths` mechanism and the session-start loading priority are Claude Code behaviour. Distribution is not: `rules` is one of the shared namespaces, so a rule authored in the shared tree is staged into **every** active tool's `rules/` directory, and every admitted rule is charged against that tool's always-on budget. Author accordingly — a rule in the shared tree must read as a constraint any agent on any tool can follow. A rule that only makes sense inside Claude Code belongs in the Claude tree instead, where it stages nowhere else.

Staged is not the same as loaded. Claude Code reads a loose `rules/` directory natively; the other three tools are meant to receive rules inlined into their instruction file instead, and that wiring is currently incomplete — see "Embedding rules into the instruction file" below before assuming a shared rule takes effect everywhere it lands.

---

## File Format

Markdown with YAML front matter. The front matter is not optional: the deploy
gate treats `rules` as a gated namespace, and **a rule carrying no `admission:`
record is dropped at deploy** — it stages, and then simply never lands in the
tool's config directory, while any copy an earlier run deployed is pruned. In
this repository `content-lint` catches it first and fails, because a record-less
artifact under `src/user/` is fatal there; where that gate does not run, the
installer reports the drop and carries on — a count of unadmitted artifacts on
every run, and the names behind it only under `--verbose`. A malformed record is
worse in both places: it aborts the whole deploy.

The gate strips what it admits — the `admission:` and `claims:` blocks are
repo-side bookkeeping and never reach the deployed bytes — so the record costs
the reader nothing and is not charged against the always-on budget. Write it for
the next maintainer of this repository, not for the agent that loads the rule.

### Always-loaded rule

```markdown
---
admission:
  prevents: <the failure this rule stops>   # or `provides:`, never both
  cost: <what it costs, and on which surface>
  remove_when: <the observation that would retire it>
---

# Rule Name

One-line statement of what this rule governs.

Core constraint — what the agent always does or never does.

## When this applies
Specific situations or "all non-trivial work".

## What to do
Explicit prescriptions: "always X before Y", "never Z without explicit authorization".
```

### Path-scoped rule (with `paths` front matter)

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "src/api/**/*.tsx"
admission:
  provides: <the capability this supplies>
  cost: <what it costs, and on which surface>
  remove_when: <the observation that would retire it>
---

# API Development Rules

- All API endpoints must include input validation
- Use the standard error response format
- Include OpenAPI documentation comments
```

Sanitization removes only the governance keys, so `paths` survives into the
deployed file. A rule whose front matter held nothing but the admission record
deploys with no front matter at all.

Path-scoped rules trigger when the agent reads files matching the patterns. Glob syntax supports brace expansion: `"src/**/*.{ts,tsx}"`.

---

## How Rules Load

| Rule type | When loaded |
|-----------|-------------|
| Deployed rule with no `paths` field | Every session, at startup, like `.claude/CLAUDE.md` |
| Deployed rule with a `paths` field | Only when Claude reads a file matching one of the patterns |

User-level rules in `~/.claude/rules/` apply to every project. Project-level rules in `<project>/.claude/rules/` are loaded for that project specifically. **Project rules have higher priority than user rules** when both apply.

`.claude/rules/` supports symlinks for sharing a rule set across projects.

---

## The Always-On Budget

An always-loaded rule is the most expensive artifact class this repository ships: its bytes sit in every session whether or not they are needed. That cost is capped mechanically. A tool's **always-on surface** — its deployed instruction file, every admitted rule staged into it, and every skill's catalog entry (`name` + `description`) that tool's runtime publishes to the model — must stay under `ALWAYS_ON_TOKEN_CAP` in `packages/installer/src/installer/core/surface_budget.py`, currently **10,000 tokens**, counted as `ceil(bytes / 4)`. A breach is fatal: the deploy aborts before any write, and `make content-lint` fails the same way in this repository.

The cap is measured after sanitization, so the record is free and only the rule's own prose is charged. On a pass, `make content-lint` prints each tool's current weight and rule count — read that rather than guessing at headroom, and read a rising token count against a flat rule count as one rule bloating.

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

Rules in this project are sourced under `src/`, and where a rule lives decides which tools receive it. The shared tree reaches all of them; a tool tree reaches one. The behaviour described in this section is implemented in the installer core, `packages/installer/src/installer/core/`, and the module names below are relative to it.

### Source layout

```
src/user/.agents/rules/               # Shared rules — staged into EVERY active tool's rules/
  <rule-name>.md

src/user/.claude/rules/               # Claude-only rules — staged into ~/.claude/rules/ alone
  <rule-name>.md

src/plugins/<plugin>/.agents/rules/   # Plugin rules for every active tool
  <rule-name>.md

src/plugins/<plugin>/.<tool>/rules/   # Plugin rules for one tool (e.g. .claude/rules/)
  <rule-name>.md
```

Each rules directory carries its own `AGENTS.md` saying what is currently in it — read that rather than counting files, and read `namespaces.py` for which namespaces are shared as against tool-scoped.

Every one of these locations is gated, plugin trees included: a plugin can be discovered, activated, and still install nothing. A rule reaching every tool is charged against every tool's always-on budget, which is the practical argument for putting a rule in the narrowest tree that serves it.

### Collision / append model

Rule files with the same name across source trees (base + active plugins) are **appended** during install, not overwritten:

```
base:    src/user/.claude/rules/<rule-name>.md
plugin:  src/plugins/<plugin>/.claude/rules/<rule-name>.md

result:  ~/.claude/rules/<rule-name>.md
         = base content
           ---
           (plugin content appended)
```

The base content always lands first; plugins append alphabetically. The mechanism is `merge/strategies/append_rules.py`, and rules are the only namespace that resolves a collision this way — a same-name collision in `skills/`, `commands/` or `agents/` is a fatal install error.

**Consequences for authors**:
- Plugin additions must be purely additive (new clauses, new contexts) — not replacements
- Do not duplicate base rule content in plugin additions; the append model handles it
- Read the base rule before writing a plugin extension to avoid contradictions
- The merged file's front matter is the base file's (a plugin addition is normally pure prose with no front matter of its own). Admission is judged per contributor, not on the merged bytes: each source file in the append chain is classified and sanitized on its own, and the destination is reassembled only from the contributors that clear the bar. A record-less base contributes nothing to the result; a plugin addition with its own valid record still deploys — the append neither sinks it nor exempts it

### Embedding rules into the instruction file

Beyond copying rule files into each tool's `rules/` directory, the installer can inline them into the tool's assembled instruction file: a `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` marker in a tool's `*.md.template` is replaced by the staged rules, and `<!-- DYNAMIC-INCLUDE-RULES: a,b -->` inlines a named subset. When an instruction file inlines the rules this way, the flatten also drops the loose `rules/` files it consumed, so they are not deployed twice.

The mechanism is implemented in `templates.py`, and the design it encodes is that Claude keeps a loose `rules/` tree while Codex, Gemini and OpenCode receive their rules inlined. **No tool template carries either marker today** — every one of them includes only the shared `USER-CORE.md.template` — so nothing is inlined and nothing is dropped, and a shared rule currently lands as a loose file in three config directories whose tools the installer's own comments say do not read one.

The practical consequence for an author: a shared rule reliably reaches Claude Code, and reaching the other three depends on wiring that is not in place. Read the `*.md.template` files before claiming otherwise — the marker grammar exists and is fully implemented in the installer (`templates.py`), independent of whether any shipped template currently carries it.

---

## Quality Issues to Flag in Audit

| Issue | Symptom | Fix |
|-------|---------|-----|
| No `admission:` record | Front matter is absent, or carries `paths` alone | Add a complete record; without one the rule deploys nothing and any deployed copy is pruned |
| Incomplete `admission:` record | States both `prevents` and `provides`, or neither; a required field is empty | Fix it — a malformed record aborts the whole deploy, not just this artifact |
| Duplicates skill content | Rule re-describes methodology a skill already encodes | Replace with "invoke skill X"; remove duplication |
| Advisory vs. normative drift | "Should", "consider", "it's good to" language in a rule file | Rewrite as "always", "never", "must" |
| Mixed concerns | One file governs both completion AND delivery | Split into two focused files |
| No consequence grounding | Hard constraint with no "why" anchor | Add one-line rationale |
| Over-specified how-to | Rule includes a 10-step methodology inline | Extract to skill; rule becomes "invoke skill X" |
| Inline shell sequences | Rule prescribes a deterministic command sequence in prose | Move to a helper script; rule references the script |
| Missing path scope | Rule only matters for a subset of files but loads every session | Add `paths` front matter to scope it |
| Tool-specific content in the shared tree | A rule under `src/user/.agents/rules/` names a capability only one tool has | Move it to that tool's tree, or rephrase the substance as tool-agnostic |
| Plugin rule contradicts base | Plugin addition conflicts with the base rule it appends to | Rewrite as extension, not contradiction |
| Always-on weight nobody measured | Rule added without checking the tool's surface total | Run `make content-lint` and read the reported headroom |
