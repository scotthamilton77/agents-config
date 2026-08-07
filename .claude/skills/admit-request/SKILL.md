---
name: admit-request
description: Evaluate any request to admit a rule, skill, command, or agent into src/ — newly authored or reinstated after retirement. Use whenever someone proposes adding an artifact to the deployed surface, reinstating a retired one, or asks whether something belongs.
---

# Admitting an artifact

This is a gate, not a helper. The default verdict is **DECLINE**. Run the
checks in order; the first failure decides. Do not carry a failed candidate
forward with a note to fix it later.

## Scope

Applies to any artifact in a gated namespace: `rules`, `skills`, `commands`,
`agents`. Claude `workflows/` are not gated by the installer today; that is a
known hole.

Applies equally to a newly authored artifact and to one being reinstated after
retirement. **There is no grandfathering.** An artifact that shipped before
the bar existed gets the same evaluation as one written this morning.

## Verdict

Emit exactly one, with the failing check named:

| Verdict | Meaning |
|---|---|
| `ADMIT` | Passes every check as-is. Needs only the record and, if OSS-derived, the provenance header. |
| `ADMIT-WITH-CHANGES` | Passes on substance; named, bounded edits required first. List them as a work item's scope, not as suggestions. |
| `DECLINE` | Fails a check. Say which, and what observation would change the answer. |

A `DECLINE` is a good outcome. Most candidates should get one.

## The checks

### 1. Live counterpart

Search `src/` for anything already doing this job. An artifact that overlaps a
live one is a `DECLINE` — consolidate into the live artifact instead, or
retire the live one in the same change. Two artifacts asserting different
answers to the same question is a defect, not redundancy.

Then check the artifact's `claims:` (if any) against every live claimant. A
conflicting claim aborts the deploy, so catch it here rather than at install.

### 2. The record

The candidate MUST carry a complete `admission:` block in its front matter:
**exactly one** worth field, plus `cost` and `remove_when`.

```yaml
admission:
  prevents: <the failure this stops>        # preventative case
  # -- or --
  provides: <the capability this supplies>  # assistive case
  cost: <what it costs, in work or tokens or latency>
  remove_when: <the observation that would retire it>
```

Judge the content, not the presence. The installer checks the fields are
non-empty and that exactly one worth field is stated; you check they are true.

**Pick the case the artifact actually makes.** A guardrail that fires against
pressure is preventative. A repeatable procedure is assistive — it is worth
having though no failure precedes it, and dressing it as failure-prevention
produces a fiction, not a justification. Stating both is a malformed record and
aborts the deploy.

- **`prevents`** MUST name a failure that has happened or that the code makes
  reachable — not a hypothetical. "Prevents confusion" is not a failure.
  "Prevents an agent re-hitting a tool error the model defaults into" is.
- **`provides`** MUST name a capability the agent does not already have, and
  say what invoking it produces. "Provides guidance on testing" is not a
  capability; "produces a dated spec with red-test-convertible criteria" is.
  If the model already does it unprompted, there is nothing to provide.
- **`cost`** MUST be concrete and MUST name the surface it is paid on — see
  check 4 for which. "Minimal" is not a cost.
- **`remove_when`** MUST describe something observable. If nothing could ever
  retire the artifact, it is a belief, not a control.

"It was useful before" is neither a `prevents` nor a `provides`. Neither is
"we already wrote it".

### 3. The always-on test (rules only)

A rule loads before the user types, on every session, whether or not it is
relevant. It earns that only if **all five** hold:

1. **Universal** — true across projects, not just this one.
2. **Not model-default** — the model does not already do it unprompted. Verify
   this; do not assume it.
3. **Not owned by code** — no pipeline, contract, or CI gate already enforces
   it. If code can enforce it, the code is the fix and the rule is a `DECLINE`.
4. **Unconditional** — it applies at all times, not only when the agent is
   about to do a particular thing. A constraint that matters only during some
   activity should be **a skill invoked at that moment**, where it is paid for
   only when it is relevant. This is the most common reason a plausible rule is
   the wrong shape.
5. **Fits the sub-budget** — roughly 800 tokens across the whole always-on
   instruction file, so a rule is a paragraph, not a page.

Failing (3) but genuinely needed → a work item against the code. Failing (4)
→ re-scope as a skill and re-run this evaluation from check 1; do not decline
the idea, decline the shape.

### 4. Budget

Two surfaces, and an artifact is priced on the one it actually loads into.

| Artifact | Always-on cost | On-invoke cost |
|---|---|---|
| Rule | its whole body — it is always loaded | — |
| Skill / command / agent | its front-matter `description` only | its body, paid when invoked |

**A skill's body is not always-on.** Until something invokes it, a skill costs
its description line in the catalog and nothing else. So body size is a
question of whether the body earns its cap *at the moment of use*, and
description sprawl is the always-on concern — a vague description is worse than
a long body, because it is paid every session and buys mis-invocation.

Mechanical caps the installer enforces at deploy:

- always-on surface (instruction file + all rules): **10k tokens**
- each **model-invoked** skill body, after front matter: **2k tokens**
- each **user-invoked** skill body: **5k tokens**

A skill is user-invoked when its front matter carries
`disable-model-invocation: true`. That keeps its description out of the model's
catalog entirely, so it costs zero always-on tokens and its body is reached
only when the user names it — a cost asked for, at a moment chosen for it. A
model-invoked body is loaded on the model's own judgement, mid-task, against
whatever the context is already carrying, which is what the tighter number
prices. The flag is carried in the shared tree and projected per tool by the
installer, so it is not a reason to move a skill into `src/user/.claude/`.

**The raised ceiling is relief, not permission.** Progressive disclosure applies
to every skill regardless of which cap measures it. Where a body exceeds 2k the
first question is always what belongs in `references/`; the ceiling is what
catches the residue after that split, not a substitute for making it. A body
that fits 4,900 tokens only because nothing was ever moved out has failed the
intent while passing the gate — mark it `ADMIT-WITH-CHANGES` and name the split.

Measure; do not estimate. `wc -c` divided by four is the same approximation the
installer uses. A skill over its cap is `ADMIT-WITH-CHANGES` at best: delegate
the excess to code, or split it.

**Headroom is not an argument.** The budget is a ceiling, not a target to fill.

Choosing the invocation mode is a catalog-design decision, not a budget one:
every model-invoked description is one more entry the agent must disambiguate
before the user types anything. Do not set the flag to buy the looser cap.

Known gap: the installer does not currently count skill/command/agent
descriptions in the always-on surface, so that cost is on you to police.

### 5. Placement

By capability-dependency, never by asset type:

- works on every supported tool → `src/user/.agents/`
- needs a tool-specific capability (subagent orchestration, the Skill tool,
  interactive question UI, hooks) → that tool's tree, e.g. `src/user/.claude/`

Capability-dependency is about the artifact's *procedure*, not its front matter.
The installer projects capability keys per target tool — `allowed-tools`,
`argument-hint` and `disable-model-invocation` deploy to Claude and are dropped
for the tools that do not define them — so carrying one of those keys is not by
itself a reason to leave the shared tree. A skill whose steps only work under
one tool still belongs in that tool's tree.

Then: does it belong in the **deployed** surface at all? Deployed artifacts run
in other people's projects. An artifact whose subject is this repo — its
charter, its tracker, its `src/` layout — MUST NOT cite those from `src/`; it
either gets rewritten in portable terms or lives as a project-scoped artifact
here instead.

### 6. Provenance and drift

If the artifact is derived from or borrows substantively from a third-party
source, it MUST carry the provenance header immediately after the front matter,
using the literal audit keys (`Source:`, `Upstream:`, `Last sync:`,
`Drift policy:`), and MUST get a row in the shared skills registry.

Set the drift policy deliberately. Any local graft that diverges from upstream
flips the policy to a fork policy — a resync would silently revert the graft.

## Mechanical constraints

These the runtime enforces, so they carry MUSTs regardless of the artifact's
register:

- One skill per immediate subdirectory, **depth-1 only**. Nested skills are
  invisible to every supported runtime.
- Front matter `name:` MUST equal the folder name.
- A skill directory's record lives in `SKILL.md`.
- A malformed `admission:` block **aborts the whole deploy** — it is a defect,
  not a skip. A missing one is a silent drop.

## Register

Match the prose to what the artifact is, and do not mix:

| Type | Register |
|---|---|
| **Discipline** — obeyed under pressure | Hard MUSTs, explicit red-flag lists. The MUSTs are the skill. |
| **Technique** — a method the agent lacks | Explain the why; examples beat mandates. Hard MUSTs make it rigid. |
| **Reference** — looked up | Neutral, scannable, no admonitions. |

Mixed registers usually mean the artifact is doing two jobs and should split.

## Recording the outcome

An `ADMIT` or `ADMIT-WITH-CHANGES` enters the tracker through the `work` facade
as a child of the harness-rework milestone, carrying the same record (the worth
field, `cost`, `remove_when`) in its description. Implement on a worktree
branch; the installer's gate is the mechanical verification.

A `DECLINE` is recorded too — in the work item that proposed it, with the
failing check and the observation that would reopen it. An undocumented
decline gets re-proposed in six weeks.
