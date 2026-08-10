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
  cost: <what it spends that no gate measures>
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
- **`cost`** MUST name what the artifact spends that no gate measures: the
  user's time or money, a runtime dependency, disk, other model runs, an upkeep
  obligation tied to a fact outside this repo, a step it blocks, reading that
  scales with the target rather than with the skill, or a downside it
  introduces. It MUST NOT state a token count or a byte count of its own text,
  and MUST NOT restate the always-on / on-invoke split — `content-lint` prints
  the surface totals (catalog descriptions included) and every body against its
  cap, and a hand-copy drifts the moment the text it measures is edited. An
  artifact whose only cost is its own footprint carries the sentinel verbatim:
  `Context footprint only, bounded by the caps content-lint enforces.`
  "Minimal", "None" and their synonyms are not costs; `content-lint` rejects
  those and any mention of tokens.

  **The sentinel is a claim, not a default.** Carry it only when nothing on that
  list is true of the artifact — not merely when nobody wrote one down, which is
  how an omission becomes a false assertion. One question settles it: does the
  spend fall on someone other than the invoking agent, or leave a standing
  obligation once the invocation ends? Reading, deciding, and running a bounded
  command are the procedure the invoker asked for by invoking, and belong in the
  body. A file left behind, a record written to a tracker, a change committed to
  the user's repository, a dependency that must already be installed, a human
  round-trip, or a fan-out of model runs are none of those, and belong here.
  Invocation mode decides one of these: a round-trip a **user-invoked** artifact
  produces is the thing the user typed for, while the same round-trip in a
  model-invoked one is their time spent on their behalf, and only the second is
  a cost. Reading is the other close call — it counts when it scales with the
  target rather than with the artifact, so widening to a whole codebase is a
  cost and a fixed handful of lookups is not. Beware the opposite failure: "the
  agent must read and follow this skill" is true of every skill, and restating
  it per artifact rebuilds the defect the narrowing removed.
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
5. **Fits the always-on budget** — a rule's bytes are charged to the 10k
   always-on surface, in every session, on every tool that stages it. That is
   the cap a rule can breach: the 800-token sub-budget beside it weighs the
   assembled instruction file, which no rule's bytes enter. So no single rule
   trips a cap and fifteen reasonable ones breach a ceiling none of them
   approaches — the discipline is proportion, not a number to check against.
   A rule is a paragraph, not a page.

Failing (3) but genuinely needed → a work item against the code. Failing (4)
→ re-scope as a skill and re-run this evaluation from check 1; do not decline
the idea, decline the shape.

### 4. Budget

Two surfaces, and an artifact is priced on the one it actually loads into.

| Artifact | Always-on cost | On-invoke cost |
|---|---|---|
| Rule | its whole body — it is always loaded | — |
| Skill / agent | its front-matter `description` only | its body, paid when invoked |
| Command | none — it appears in no catalog | its body, paid when the user types it |

**A skill's body is not always-on.** Until something invokes it, a skill costs
its description line in the catalog and nothing else. So body size is a
question of whether the body earns its cap *at the moment of use*, and
description sprawl is the always-on concern — a vague description is worse than
a long body, because it is paid every session and buys mis-invocation.

**A command is not in any catalog at all.** Neither its body nor its
description reaches a session until the user types it, so a command has no
always-on figure to state and its whole cost is one the user asked for. Do not
ask a command to justify a context cost it does not impose.

Mechanical caps the installer enforces at deploy, each a hard abort before any
write:

- always-on surface (instruction file + every admitted rule + every skill
  catalog entry that tool's runtime publishes): **10k tokens**
- the deployed instruction file alone, a sub-budget inside that surface:
  **800 tokens**
- each **model-invoked** skill body, after front matter: **2k tokens**
- each **user-invoked** skill body: **5k tokens**

A skill is user-invoked **on a given tool** when the front matter it deploys
with there carries `disable-model-invocation: true` — a property of each
deployed copy rather than of the source, since the projection strips the key
for any tool whose loader does not define it. Where the key survives, it keeps
that skill's description out of the model's catalog entirely, so the skill
costs zero always-on tokens on that tool and its body is reached only when the
user names it — a cost asked for, at a moment chosen for it. A model-invoked
body is loaded on the model's own judgement, mid-task, against whatever the
context is already carrying, which is what the tighter number prices.

**Only Claude honours the flag today.** The installer strips it for Codex,
Gemini and OpenCode, which have no equivalent to translate onto. The cap is
then keyed on the **deployed** front matter, one measurement per target, so
losing the key costs more than the exemption: on Codex and OpenCode the skill
is model-invocable whatever its author declared, which puts that tool's copy
under the strict cap and its description back into that tool's catalog. Two
consequences to hold:

- The 5k number is Claude-shaped, and it is Claude-only. A 4,900-token
  user-invoked body passes on Claude and **aborts the deploy** on Codex and
  OpenCode, where the same bytes are weighed against 2k. The looser ceiling is
  relief on one target, never permission on the rest. Gemini is not a third
  case: no vendor documentation establishes whether a deployed skill reaches
  its runtime at all, so this project models its skill loading not at all
  rather than guessing at it — no catalog charge, no body cap, and no claim
  here about how it invokes.
- Carrying the flag is not by itself a reason to leave the shared tree, since it
  is projected out cleanly. But dropping a key removes the bytes, not the gap: a
  skill whose worth claim *depends* on never firing unprompted is still
  model-invocable on Codex and OpenCode, and belongs in
  `src/user/.claude/` where the claim holds. Check 5 decides this; check 4 only
  tells you which number to measure against.

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

A skill's catalog entry — its `name` and `description` — is charged to the
always-on surface of every tool whose runtime publishes it, so description
sprawl reads as a number here rather than as something you had to notice.

Two descriptions are still charged nothing, for two different reasons. A command
is in no catalog, so there is nothing to charge. An agent would be in one, and
the charge counts the `skills` namespace alone — no agent is in the tree today,
so nothing is mispriced now, but admit one and its description is yours to
police. Either way, police a description by reading it and cutting it, never by
recording its size in `cost:`, where the number drifts the next time the
description is edited and where `content-lint` now rejects it.

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

An artifact we authored ourselves MUST NOT carry a provenance header at all — no
comment, and none of those keys. The header means one thing — there is an outside
party, at a known commit, whose future changes could collide with ours — and a
reader who has learned to read it that way has to open the upstream to discover
that this instance meant something else. `Source: authored <date>` is not
provenance; it is history, which git already holds. An artifact that is partly
ours and partly derived keeps the header and scopes it, naming which files have
an upstream and which do not.

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
