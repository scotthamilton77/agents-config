# Beads Formulas — Agent Context Primer
> **Source**: Copied from the beads project (`~/src/oss/FORMULAS_PRIMER.md`).
> Internal path references (`docs/MOLECULES.md`, `docs/CLI_REFERENCE.md`, `internal/formula/`, `cmd/bd/`) refer to the beads source project, not this agents-config repository.
> The best-practices and operational guidance sections apply directly to this project.

---


# Beads Formulas — Agent Context Primer

> Use this document to orient yourself to the formula/molecule system before writing or executing workflows.
> See `docs/MOLECULES.md` for deeper molecule internals, and `docs/CLI_REFERENCE.md` for exhaustive flag docs.

---

## What Formulas Are and Why They Exist

A **formula** is a declarative TOML workflow template. It defines a DAG of work steps, the variables that parameterize them, and the composition rules that let formulas build on each other.

Formulas exist because AI-supervised workflows are complex and repeatable: the steps to release software, review a PR, or implement a feature follow a predictable structure. Formulas encode that structure once; instances of them (molecules and wisps) execute it with specific values.

The pipeline is:

```
.formula.toml  →  cook (resolve + transform)  →  pour/wisp  →  issue hierarchy in db
(template)          (variables still intact)      (variables substituted, real issues created)
```

---

## Formula File Structure

Formulas are named `*.formula.toml`. Search order (highest priority first):

1. `.beads/formulas/` — project-level (ships with the repo)
2. `~/.beads/formulas/` — user-level
3. `$GT_ROOT/.beads/formulas/` — orchestrator-level

### Minimal example

```toml
formula    = "mol-feature"
description = "Standard feature workflow"
version    = 1
type       = "workflow"

[vars]
feature_name = ""      # shorthand: empty string means required input

[[steps]]
id    = "design"
title = "Design {{feature_name}}"
type  = "task"

[[steps]]
id    = "implement"
title = "Implement {{feature_name}}"
needs = ["design"]

[[steps]]
id    = "test"
title = "Test {{feature_name}}"
needs = ["implement"]
```

### Root-level fields

| Field | Required | Notes |
|-------|----------|-------|
| `formula` | yes | Unique identifier. Convention: `mol-<name>` for workflows, `exp-<name>` for expansions |
| `version` | yes | Always `1` currently |
| `type` | yes | `workflow` (default), `expansion`, `aspect`, or `convoy` |
| `description` | no | Human-readable summary |
| `extends` | no | List of parent formula names (inheritance) |
| `phase` | no | `vapor` → recommend wisp; `liquid` → recommend pour |
| `pour` | no | `true` → materialize steps into DB on pour (use for release/critical workflows) |

### Variable definitions

```toml
[vars]
environment = "staging"          # shorthand default

[vars.version]
description = "Semantic version"
required    = true               # mutually exclusive with default
pattern     = "^\\d+\\.\\d+\\.\\d+$"
type        = "string"           # string | int | bool
```

`{{variable_name}}` is substituted in titles, descriptions, labels, and assignees at pour/wisp time.

---

## Step Fields

Each `[[steps]]` entry becomes one issue in the created hierarchy.

```toml
[[steps]]
id          = "review"
title       = "Review {{feature_name}}"   # required; supports {{var}} substitution
type        = "task"                       # task | bug | feature | epic | chore
priority    = 1                            # 0 (critical) – 4 (backlog)
description = "Full description of work"
notes       = "Supplementary context"
labels      = ["backend", "needs-review"]
assignee    = "{{reviewer}}"

# Dependencies (pick one style)
needs       = ["implement"]   # simpler alias
depends_on  = ["implement"]   # equivalent

# Conditional inclusion (evaluated at cook time)
condition   = "{{run_tests}}"              # truthy/falsy
condition   = "{{env}} == production"      # comparison
condition   = "!{{skip_lint}}"             # negation

# Inline expansion (replace this step with an expansion formula)
expand      = "exp-docker-build"
expand_vars = {image = "golang:1.26"}
```

### Gate (async wait)

Creates a blocking issue that must be manually closed to unblock the next step.

```toml
[steps.gate]
type     = "gh:run"          # gh:run | gh:pr | timer | human | mail
id       = "release.yml"     # identifier (workflow name for gh:run)
await_id = "ci_complete"     # maps to Issue.AwaitID
timeout  = "30m"             # escalation timeout
```

### Loop (iteration)

```toml
[steps.loop]
count = 3              # fixed; OR:
# range = "1..7"       # computed (exposes {{move_num}})
# until = "done"; max = 50   # conditional
var = "move_num"

[[steps.loop.body]]
id    = "task-{{move_num}}"
title = "Task {{move_num}}"
```

### Runtime fan-out (for-each from step output)

```toml
[steps.on_complete]
for_each = "output.workers"          # path into step's JSON output (must start "output.")
bond     = "mol-worker-arm"          # formula to instantiate per item
vars     = {name = "{item.name}", idx = "{index}"}
parallel = true
```

### Step metadata (routing hints for agents)

```toml
[steps.metadata]
execution_agent_type       = "polecat"
execution_suggested_model  = "claude-opus"
execution_reasoning_effort = "high"
execution_mode             = "parallel"
```

---

## Molecules vs. Wisps

| | Molecule | Wisp |
|---|---|---|
| Created by | `bd mol pour` | `bd mol wisp create` |
| Persisted to git | yes (Dolt-synced) | no (`Ephemeral=true`, excluded) |
| Use case | Tracked feature work, multi-session workflows | Operational cycles, health checks, ephemeral runs |
| Cleanup | Manual | Auto-expire (TTL) or manual burn |
| Formula `phase` hint | `liquid` | `vapor` |

**Rule of thumb**: if you need a full audit trail across git history, pour a molecule. If it's a fire-and-forget operational run (patrol, health check, one-off), wisp it.

---

## Molecule Lifecycle

1. **Pour** — `bd mol pour <formula> --var key=val` creates a root epic + child issues
2. **Claim** — `bd update <step-id> --claim` marks a step in_progress (atomic CAS)
3. **Execute** — agent does the work; child issues have `open → in_progress → closed` transitions
4. **Dependencies** — `bd ready` only surfaces steps whose `needs` are all closed
5. **Complete** — all steps closed; walk up the parent chain and close empty epics (I2)

### Parent-chain invariants

**I1 — Claim walk**: When starting work on any step, also mark every ancestor epic `in_progress`.

```bash
bd update <id> --status in_progress
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  bd update "$PARENT" --status in_progress
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

**I2 — Close walk**: After closing a step, walk up and close ancestors that have no remaining open children.

```bash
bd close <id> --reason "Done"
PARENT=$(bd show <id> --json | jq -r '.[0].parent // empty')
while [ -n "$PARENT" ]; do
  NON_CLOSED=$(bd list --parent="$PARENT" --json | jq '[.[] | select(.status != "closed")] | length')
  [ "$NON_CLOSED" = "0" ] || break
  bd close "$PARENT" --reason "All children closed"
  PARENT=$(bd show "$PARENT" --json | jq -r '.[0].parent // empty')
done
```

---

## Composition (Reuse and Extension)

### Inheritance

```toml
extends = ["mol-base-workflow"]
# Child inherits parent vars, steps, compose rules; overrides by step ID
```

### Bond points (attach sites for other formulas)

```toml
[compose]
[[compose.bond_points]]
id          = "pre-review"
description = "Attach steps before code review"
after_step  = "implement"
parallel    = false
```

Attach a formula at runtime: `bd mol bond <mol-id> <formula> --ref pre-review`

### Hooks (auto-attach on condition)

```toml
[[compose.hooks]]
trigger = "label:critical"     # label:<name> | type:<name> | priority:<range>
attach  = "mol-escalation"
at      = "bond-point-id"
vars    = {level = "urgent"}
```

### Aspects (cross-cutting concerns)

```toml
[compose]
aspects = ["security-audit", "logging"]
```

Aspect formulas weave `before`/`after`/`around` advice onto matching steps.

### Expansions (apply a macro to steps)

```toml
[[compose.expand]]
target = "build"
with   = "exp-docker-build"
vars   = {image = "golang:1.26"}

[[compose.map]]
select = "*.test"              # glob; matches test-unit, test-integration, ...
with   = "exp-report-results"
```

---

## Key Commands

```bash
# Inspect available formulas
bd formula list
bd formula show <name>

# Dry-run (compile without creating issues)
bd cook <formula> --var version=1.2.0

# Create a persistent molecule
bd mol pour <formula> --var key=val

# Create an ephemeral wisp
bd mol wisp create <formula> --var key=val

# Inspect a molecule's step structure
bd mol show <mol-id>

# Check what's ready to work (respects dependencies)
bd ready

# Work the molecule
bd update <step-id> --claim
bd close  <step-id> --reason "Implemented"
```

---

## Best Practices

**Formula design**
- Use `needs` (not `depends_on`) — it's the idiomatic shorthand.
- Provide sensible defaults for non-critical vars; mark truly required vars with `required = true`.
- Set `phase = "vapor"` for operational/patrol workflows to signal wisp intent.
- Name steps as imperative verbs: `implement-auth`, not `auth`.

**Step descriptions**
- Include acceptance criteria or links to relevant context — the description is what the executing agent reads.
- Human decision points should use `type = "task"` with a gate or a clear "human:" prefix in the title.

**Composition**
- Add bond points to any workflow that might be extended — future-you will thank present-you.
- Put cross-cutting concerns (security scan, notification) in aspect formulas, not inline.
- Keep base formulas slim; add behavior through `extends` and aspects.

**Durable state**
- Agents should write findings and reports to bead notes (`bd update <id> --append-notes`), not to scratch files. Notes survive session restarts and are visible to coordinators.
- Emit events to `gc events` for operator visibility on long-running operational workflows.

**Operational hygiene**
- Always run `bd ready --json` before claiming a step — never start a step whose dependencies aren't closed.
- If stuck >15 minutes on a step, append notes with current status and escalate rather than spinning.
- Use `bd mol wisp create` + ephemeral TTLs for patrol and health-check cycles; never pour molecules for throwaway runs.

---

## Formula Type Summary

| Type | Use for | Key mechanism |
|------|---------|---------------|
| `workflow` | Standard ordered work | Steps + `needs` DAG |
| `expansion` | Reusable step macro | Expanded inline via `expand` field |
| `aspect` | Cross-cutting concerns | Advice weaved via pointcut matching |
| `convoy` | Multi-agent fan-out | Parallel worker lanes + synthesis |

---

## File Locations in This Repo

```
.beads/formulas/
  beads-release.formula.toml     # project release workflow (reference example)

examples/formulas/
  feature-workflow.formula.toml  # standard feature development
  release.formula.toml           # release with semver gate
  quick-check.formula.toml       # lint → test → build (wisp candidate)

internal/formula/
  types.go          # Formula, Step, Gate, LoopSpec, ComposeRules structs
  parser.go         # load, resolve inheritance, cycle detection
  controlflow.go    # loops, branches, gates
  expand.go         # expansion operators
  advice.go         # aspect weaving

cmd/bd/
  cook.go           # bd cook — compile/dry-run
  mol.go            # bd mol — molecule commands
  pour.go           # bd mol pour
  wisp.go           # bd mol wisp
  formula.go        # bd formula list/show
```
