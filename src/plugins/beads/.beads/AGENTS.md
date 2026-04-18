# Beads Formulas — Agent Guide

The .beads folder contains files and concepts specific to the beads plugin
and `bd` CLI: **workflow formulas** that are reusable templates that encode
multi-step development processes as executable molecules.

---

## The Core Concepts

### Formula (the template)

A formula is a TOML file in `.beads/formulas/`. It defines:
- A DAG of `[[steps]]`, each with an `id`, `title`, `description`, and
  optional `needs` array (which steps must complete first)
- `[vars.name]` declarations for substitutable inputs
- A `phase` (usually `vapor` for one-shot runs)

Formulas are **not executed directly**. They are instantiated into molecules.

Think of a formula as source code; a molecule as a running process.

### Molecule (the instance)

When you instantiate a formula, you get a molecule: a real set of beads
(issues) with dependency relationships, tracked in the project's bead
database. Each step in the formula becomes a bead.

Two instantiation modes:

**Wisp (vapor phase)** — ephemeral. Creates real beads, but the molecule
is designed to be burned when done. Use for one-off tasks.

```bash
bd mol wisp create <formula-name> --var key=value
```

**Pour (liquid phase)** — persistent. The molecule survives squash/resume
across sessions and appears in `bd mol progress`. Use for long-running
work that spans many sessions.

```bash
bd mol pour <formula-name> --var key=value
```

### Finding your place in a molecule

```bash
bd mol current <mol-id>       # what step should I work next?
bd mol progress <mol-id>      # how far along is this molecule?
bd mol show <mol-id>          # full structure and status
```

### When you are done

```bash
bd mol squash <mol-id>        # compress molecule to a digest (pour)
bd mol burn <mol-id>          # discard without trace (wisp)
```

### Distilling a formula from existing work

If you have an ad-hoc epic that represents a repeatable workflow:

```bash
bd mol distill <epic-id>      # extracts a .formula.toml from the epic
```

Edit the output, strip the particulars, and save it to
`.beads/formulas/` for future use.

---

## Formula Search Paths

Beads discovers formulas in this order (first match wins):

1. `.beads/formulas/` — project-level (this repo only)
2. `~/.beads/formulas/` — user-level (all your projects)
3. `$GT_ROOT/.beads/formulas/` — orchestrator-level (if GT_ROOT is set)

The formulas in this `agents-config` repo are designed to be deployed to
`~/.beads/formulas/` so they are available in every project.

```bash
bd formula list               # show all discoverable formulas
bd formula show <name>        # inspect a formula's steps and variables
```

---

## Formulas in This Folder

### `implement-feature.formula.toml`

**Use when**: implementing a new feature, enhancement, or non-trivial task.

**What it encodes**: the full TDD workflow from `INSTRUCTIONS.md`,
`completion-gate.md`, `delivery.md`, and `delegation.md`:

```
brainstorm → worktree → write-tests (red)
          → implement (green) → refactor
          → code-review → simplify → verify (completion gate)
          → create-pr → await-review (delivery)
          → housekeeping (close + remember + discovered work)
```

**Enforces**:
- Brainstorming skill runs before any code decisions
- Worktree isolation before any code changes
- Tests written before implementation (TDD red phase)
- Completion gate cannot be skipped (code-reviewer → code-simplifier →
  verify-checklist, all mandatory)
- PR created before claiming work complete
- Copilot review awaited before merge

**Invoke**:
```bash
bd mol pour implement-feature \
  --var feature="Add rate limiting to the API" \
  --var bead-id=proj-42
```

---

### `fix-bug.formula.toml`

**Use when**: fixing a confirmed bug.

**What it encodes**: a diagnosis-first bug fix workflow that enforces root
cause identification as a hard gate before any code changes:

```
reproduce → root-cause (diagnose)
          → worktree
          → write-regression-test (red) → implement-fix (green)
          → code-review → simplify → verify (completion gate)
          → create-pr → await-review (delivery)
          → housekeeping
```

**Enforces**:
- Bug reproduced and confirmed before any code changes
- Root cause identified (not just symptom patched) before touching code
- Regression test written first (proves the bug; proves the fix)
- Full test suite must pass (not just the regression test)
- Completion gate and delivery steps — same as implement-feature

**The key rule this formula encodes**: you may not write a single line of
fix code until you have written the root cause in the bead. If you cannot
articulate the root cause, you do not understand the bug well enough to fix it.

**Invoke**:
```bash
bd mol pour fix-bug \
  --var bug="Login fails when username contains apostrophe" \
  --var bead-id=proj-17
```

---

## The `bd human` Escalation Valve

Both formulas have decision points where an agent should escalate to the
human rather than proceed. These include:

- Brainstorm reveals ambiguous or contradictory requirements
- Root cause is significantly different from the bead description
- A code review finding requires an architectural decision
- The scope of a fix turns out to be much larger than expected

Escalate with:
```bash
bd human <bead-id>            # flags this bead for human attention
bd human list                 # Scott: see all escalated items
bd human respond <bead-id>    # Scott: provide guidance and close the flag
```

Agents: do NOT guess through an escalation point. Park the question, move
to other work, and let the human respond when they next sit down.

---

## When NOT to Use a Formula

Formulas are for non-trivial work that spans multiple steps or sessions.
Skip them for:

- Obvious one-liners, config changes, typos
- Work that takes under 5 minutes and fits in one agent turn
- Exploratory spikes where the outcome is unknown

For those cases, say "start on &lt;id&gt;" or similar — the `start-bead` skill will route to inline execution for trivial work.

---

## Adding Your Own Formulas

1. Write a `.formula.toml` file in this folder
2. Follow the structure: `formula`, `description`, `type`, `phase`,
   `version`, `[vars.*]`, `[[steps]]`
3. Steps reference each other via `needs = ["step-id"]`
4. Parallel steps share the same `needs` parent — they can run concurrently
5. Variables substitute with `{{varname}}` anywhere in step descriptions
6. `bd formula list` will pick it up automatically

To reverse-engineer a formula from an epic you already ran ad-hoc:
```bash
bd mol distill <epic-id>
```

---

## Skill Activation

There is no slash command for this workflow. The skills activate via intent
matching from natural language:

- "create a bead for X" → `create-bead`
- "start on &lt;id&gt;" / "work on &lt;id&gt;" → `start-bead` (routes to brainstorm, implement, or inline)
- "process the queue" / "start implementing beads" → `run-queue`

`start-bead` evaluates the bead and either wisps the `brainstorm-bead` formula
(if spec is incomplete), invokes `implement-bead` (if `implementation-ready`),
or executes inline (if trivial).

Use a formula (molecule) when:
- The work spans multiple sessions
- You want gate enforcement (steps that literally cannot be skipped)
- You want `bd mol current` to tell a new session where to resume
- You want the step history tracked in the bead database for audit
