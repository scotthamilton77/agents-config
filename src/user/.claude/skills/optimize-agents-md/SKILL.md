---
name: optimize-agents-md
description: Use when CLAUDE.md or AGENTS.md files need optimization, when agent behavior degrades, when AGENT.md or CLAUDE.md files exceed 100 lines, or when merging redundant instructions across hierarchy.  Use when the user asks to update or optimize AGENTS.md or CLAUDE.md files.
---

# Optimize AGENTS.md / CLAUDE.md

## Core Principle

**Every token costs budget on every request.** Frontier models reliably follow ~150-200 instructions. Beyond that, rules get ignored. Bloated files actively hurt agent performance.

**The Iron Law:** If removing a line wouldn't cause Claude to make mistakes, delete it.

## When to Use

- AGENTS.md or CLAUDE.md exceeds 100 lines
- Agent ignores instructions (file too long, rules getting lost)
- Agent asks questions answered in the file (phrasing ambiguous)
- Merging instructions from multiple sources
- Periodic maintenance (treat like code review)

## The Optimization Process

### 1. Inventory the Hierarchy

```
~/.claude/CLAUDE.md           # Broadest: universal personal rules
project/CLAUDE.md             # Project: architecture, team practices
project/AGENTS.md             # Alternative (symlink to CLAUDE.md if needed)
project/feature/CLAUDE.md     # Scoped: package-specific rules
```

- Read target file AND all parent/child files
- Note what's already covered at other levels

### 2. Eliminate Ruthlessly

**Delete entirely:**

| Category | Examples |
|----------|----------|
| Generic AI capabilities | "write clean code", "debug effectively", "be helpful" |
| Universal best practices | DRY, SOLID, "use good naming" (without project-specific constraints) |
| Self-evident from code | Languages used, obvious framework choices |
| Parent duplication | Rules already in higher-level CLAUDE.md |
| Child concerns | Rules that should be in subdirectory CLAUDE.md |
| Stale file paths | Structure changes constantly; describe capabilities not paths |

**Preserve:**

| Category | Examples |
|----------|----------|
| Quantified constraints | "max 50 lines per function", "response time <200ms" |
| Non-obvious architecture | Deviations from framework defaults |
| Explicit prohibitions | "never use library X", "no direct DB access from handlers" |
| Domain terminology | Project-specific acronyms, business concepts |
| Commands Claude can't guess | Non-standard build/test commands |
| Post-training knowledge | Explicitly tagged version info, breaking changes |

### 3. Transform Weak to Strong

| Before (weak) | After (strong) |
|---------------|----------------|
| "Try to keep functions small" | "Functions >50 lines require justification comment" |
| "Use good naming conventions" | "Boolean vars: `is/has/should` prefix. Functions: verb-noun" |
| "Write tests" | "Test file required for new `.ts` files. 80% coverage for business logic" |
| "Follow project structure" | "New features: `/src/features/<name>/[components,hooks,services]`" |
| "Be careful with dependencies" | "No new deps without checking latest version from web" |

### 4. Apply Progressive Disclosure

Move heavy content out of main file:

```markdown
# In CLAUDE.md (light reference)
For TypeScript conventions, see docs/TYPESCRIPT.md

# NOT this (inline bloat)
Always use const instead of let. Never use var. Use interface
instead of type when possible. Use strict null checks...
```

**Use `@path/to/file` imports** for stable references:
```markdown
See @README.md for project overview
Git workflow: @docs/git-instructions.md
```

### 5. Optimize Structure

**Target: <100 lines total**

**Format rules:**
- Bullet points over paragraphs
- Sentence fragments acceptable
- Tables for multi-attribute rules
- No filler words ("please", "try to", "should consider")
- Emphasis sparingly (IMPORTANT, NEVER, CRITICAL)

**Structural template:**
```markdown
Single sentence: what Claude is in this context

<constraints>
- Quantified limits only
- Format: <metric>: <value>
</constraints>

<standards>
- Project-specific deviations from defaults
- Reference files/tools by exact path
</standards>

<context>
- Non-obvious architectural decisions
- Domain terms not in general knowledge
</context>
```

**When to use XML tags:**
- Major functional sections needing clear boundaries
- Content that must not bleed into adjacent content

**When to use markdown:**
- Navigation within sections
- Reference material meant to be scanned

### 6. Monorepo Specifics

| Level | Content |
|-------|---------|
| Root | Monorepo purpose, navigation hints, shared tools |
| Package | Package purpose, stack, package-specific conventions |

Don't overload any level. Agent sees ALL merged files in context.

## Validation Checklist

Before finalizing:
- [ ] No generic AI advice (assumes Claude baseline competence)
- [ ] No vague imperatives (all rules measurable or falsifiable)
- [ ] No parent duplication (hierarchy respected)
- [ ] No child overlap (concerns delegated appropriately)
- [ ] Every directive has concrete action or threshold
- [ ] File paths are exact, not illustrative
- [ ] <100 lines total
- [ ] Can answer: "Would removing this cause Claude to make mistakes?"

## Output Format

When presenting optimized file:

1. **Diff summary**: What was removed and why (line counts)
2. **Transformations**: Weak directives made strong
3. **Hierarchy notes**: What was delegated up/down
4. **Token savings**: Original vs optimized line count

## Example Transformation

### Before (92 lines, low efficacy)
```markdown
You are a helpful coding assistant for this React project.

Please write clean, maintainable code following best practices.
Try to keep components small and focused on one thing.
Use TypeScript for type safety.
Write tests when appropriate.
Follow the existing code style in the project.
Be thoughtful about performance.
...
```

### After (23 lines, high efficacy)
```markdown
React component architect for /dashboard feature

<constraints>
- Components: max 200 lines excl. types
- Props: max 8 per component
- Hooks: use `/hooks/useDashboard.ts` for state
- Tests: required for components >50 lines
</constraints>

<standards>
- API calls: only via `/lib/api/client.ts` wrapper
- Errors: log to `/lib/logger` + show toast
- Forms: Zod schemas in `/schemas/<feature>.ts`
</standards>

<context>
- Dashboard widgets lazy-load via React.lazy()
- Chart library: Recharts (already imported)
- Date handling: date-fns (no moment.js)
</context>
```

**Result:** 75% reduction, 3x specificity increase

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Documenting file structure | Describe capabilities; let agent navigate |
| Keeping "just in case" rules | If Claude does it right without the rule, delete it |
| Accumulating without pruning | Review monthly; treat as code |
| Adding rules after every mistake | One strong rule beats three weak ones |
| Redundancy across hierarchy | Each level should add unique value only |

## Red Flags

If you see these in an AGENTS.md, it needs optimization:
- File over 100 lines
- Multiple rules saying similar things differently
- Instructions like "be careful", "try to", "consider"
- File paths that might be stale
- Rules Claude would follow anyway
- No clear hierarchy with parent/child files
