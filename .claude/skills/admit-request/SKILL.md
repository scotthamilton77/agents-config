---
name: admit-request
description: Evaluate a request to admit or re-admit a rule, skill, command, or agent into src/. Use whenever someone proposes adding an artifact to the deployed surface, reinstating one from archive/, or asks whether something "should come back".
---

# Admitting an artifact

The admission bar exists because the previous harness accreted. Every artifact
in it was individually defensible and collectively fatal: an instruction
surface nobody could hold, mandates pointing at deleted skills, and a token
budget spent on prose that changed no outcome. The bar's whole job is to make
*re-adding* harder than adding was.

So this skill is a gate, not a helper. Its default verdict is **DECLINE**.
Run the checks in order; the first failure decides. Do not carry a failed
candidate forward "with a note to fix it later" — that is how the last surface
was built.

## Scope

Applies to any artifact in a gated namespace: `rules`, `skills`, `commands`,
`agents`. Claude `workflows/` are not gated by the installer today; that is a
known hole, not a licence to route new content through it.

Applies equally to a brand-new artifact and to one being lifted out of
`archive/`. **There is no grandfathering.** An artifact that shipped before
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
answers to the same question is the exact failure the bar was built to stop.

Then check the artifact's `claims:` (if any) against every live claimant. A
conflicting claim aborts the deploy, so catch it here rather than at install.

### 2. The record

The candidate MUST carry a complete `admission:` block in its front matter —
three non-empty fields:

```yaml
admission:
  prevents: <the failure this stops>
  cost: <what running it costs, in work or tokens or latency>
  remove_when: <the observation that would retire it>
```

Judge the content, not the presence. The installer only checks that the fields
are non-empty; you check that they are true.

- **`prevents`** MUST name a failure that has actually happened or that the
  code makes reachable — not a hypothetical. "Prevents confusion" is not a
  failure. "Prevents an agent re-hitting a tool error the model defaults into"
  is. If you cannot write this sentence, that is the answer.
- **`cost`** MUST be honest about the always-on or on-invoke price. "Minimal"
  is not a cost.
- **`remove_when`** MUST describe something observable. If nothing could ever
  retire the artifact, it is a belief, not a control.

"It was useful before" is not a `prevents`. Neither is "we already wrote it".

### 3. The always-on test (rules only)

A rule loads before the user types. It earns that only if **all four** hold:

1. **Universal** — true across projects, not just this one.
2. **Not model-default** — the model does not already do it unprompted. Verify
   this; do not assume it.
3. **Not owned by code** — no pipeline, contract, or CI gate already enforces
   it. If code can enforce it, the code is the fix and the rule is a `DECLINE`.
4. **Fits the sub-budget** — roughly 800 tokens across the whole always-on
   instruction file, so a rule is a paragraph, not a page.

Anything failing (3) but genuinely needed becomes a work item against the code,
not a rule.

### 4. Budget

Mechanical caps, enforced by the installer at deploy:

- always-on surface (instruction file + all rules): **10k tokens**
- each skill body (after front matter): **2k tokens**

Measure; do not estimate. `wc -c` on the body divided by four is the same
approximation the installer uses. A skill over the cap is `ADMIT-WITH-CHANGES`
at best: delegate the excess to code, or split it.

**Headroom is not an argument.** The budget is a ceiling, not a target to fill.

### 5. Placement

By capability-dependency, never by asset type:

- works on every supported tool → `src/user/.agents/`
- needs a tool-specific capability (subagent orchestration, the Skill tool,
  interactive question UI, hooks) → that tool's tree, e.g. `src/user/.claude/`

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
as a child of the harness-rework milestone, carrying the same record
(`prevents` / `cost` / `remove_when`) in its description. Implement on a
worktree branch; the installer's gate is the mechanical verification.

A `DECLINE` is recorded too — in the work item that proposed it, with the
failing check and the observation that would reopen it. An undocumented
decline gets re-proposed in six weeks.
