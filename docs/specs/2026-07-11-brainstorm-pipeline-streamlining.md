# Brainstorm-Pipeline Streamlining — Design

**Date:** 2026-07-11
**Status:** Draft (pending review)
**Bead:** agents-config-r14bn (idea-origin; orphan by owner choice at capture)
**Decision:** Prose-only edits to the brainstorming and writing-plans skills (plus one
cross-reference line in grill-with-docs) that (1) auto-route a finished spec or plan
into a ralf-review pass when named complexity criteria hit, (2) replace
brainstorming's unconditional "please review" gate — and add the symmetric gate for
the plan document, which today has none — with an agent-decided attention-routing
policy that waives human review under strict conditions and otherwise directs the
human to specific sections, (3) adopt grill-with-docs' glossary discipline inline
whenever a `CONTEXT.md` exists, and (4) replace writing-plans' open-ended execution
question with a stated recommendation, a clean-context suggestion, and a copyable
kickoff prompt. No new skill asset; the heavy-review engine is `ralf-review` invoked
by name, so the vaac.2.3 engine rebuild upgrades this flow transparently.

## 1. Problem

The brainstorm → spec → plan → implementation pipeline stops for human decisions the
agent could make itself:

- **Deep review is out of mind.** The brainstorming skill's spec self-review is a
  four-lens inline check; nothing routes a complex or risky design into the heavier
  adversarial review (`ralf-review`) that exists precisely for that purpose. The
  human has to remember to ask.
- **Human review is unconditional.** The skill always stops with "please review the
  spec" — even when the written spec contains nothing the owner didn't already
  approve conversationally, and even when a frontier-tier model produced and
  reviewed it. For the plan document the failure inverts: writing-plans has no
  review stop at all — self-review goes straight to an execution-mode question —
  so a plan that silently absorbed a surprising change reaches execution with no
  gate anywhere.
- **grill-with-docs never fires.** Its trigger is fully manual, so the glossary
  discipline (challenge terms, sharpen language, maintain `CONTEXT.md`) is skipped
  in exactly the flows that coin new domain terms.
- **The terminal handoff asks instead of recommending.** writing-plans ends with an
  open "subagent-driven or inline?" question, when the owner's near-universal answer
  is: recommend the execution mode, suggest a clean-context start (compact or fresh
  session), and hand over a copyable prompt.

Each stop is a human intervention per brainstorm. The prime directive (AGENTS.md >
Vision) says to move human time upstream and into thin verification gates; these
gates are neither thin nor verification — they are unconditional pauses.

## 2. Locked owner decisions (2026-07-11 brainstorm — requirements, not options)

1. **Interim now, machinery later.** The behavior lands as prose in the calling
   skills immediately; the scheduled M2/M3 machinery (owqa gate, capture-spec
   verdict, adversarial-qa UC1 binding) absorbs or replaces it behind the same seams
   when it ships. The affected M2/M3 beads are amended at capture (§6).
2. **Auto-run, not suggest.** When complexity criteria hit, the deep review runs —
   announced, not offered. Deciding to run a review is a decision the agent makes.
3. **Waiver is acceptance-only and fail-closed.** Human review may be waived only on
   the conditions in §4; a review that terminates without clean acceptance always
   parks for the human, and uncertainty about any condition means no waiver.
4. **The waiver decision is always announced** — the owner is told, every time,
   whether their review is needed and why.
5. **One pause at the end (happy path).** When both attention gates waive, the flow
   pauses exactly once — after the plan, with the execution recommendation,
   clean-context suggestion, and kickoff prompt already composed. Directed-
   attention stops (§3.3, §4.1) are the only other legitimate pauses.
6. **Decision-record/ADR machinery is out of scope** — that is vaac.2.4's brief.

## 3. Brainstorming skill changes

Three edits to the skill body (checklist, process-flow digraph, and prose stay
mutually consistent; the digraph gains the new routing and gate nodes).

### 3.1 Glossary discipline (grill trigger)

At the "explore project context" step: check for `CONTEXT.md` (or `CONTEXT-MAP.md`
in multi-context repos). When present, announce it ("`CONTEXT.md` found — glossary
discipline active") and adopt grill-with-docs' glossary discipline inline for the
rest of the brainstorm: challenge the user's terms against the glossary, propose
precise canonical terms for fuzzy language, and update `CONTEXT.md` as terms resolve
— glossary entries only, no implementation details, per the glossary format that
travels with the grill-with-docs skill (referenced by skill name, never by path),
and explicitly excluding grill-with-docs' ADR-offering step.

When no `CONTEXT.md` exists but the design has coined load-bearing domain terms,
offer once — at spec-write time, not mid-questioning — to start a `CONTEXT.md` per
grill-with-docs. The offer is **non-blocking**: it rides along in the spec-write
(or attention-gate) message and lapses unless the owner takes it up — it never adds
a pause of its own. Declining is recorded by moving on; the offer does not repeat.

grill-with-docs itself remains the standalone deep session for stress-testing an
existing plan; brainstorming borrows its discipline, it does not replace the skill.

### 3.2 Review-depth routing (after the spec self-review)

A new step between the spec self-review and the human gate. Assess the written spec
against named criteria:

- multiple interacting components or subsystems;
- new or materially changed public contracts (APIs, schemas, file formats, skill or
  workflow contracts other agents rely on);
- security- or auth-adjacent surface;
- data migration or other hard-to-reverse operations;
- novel domain concepts introduced by this design;
- a genuinely balanced trade-off resolved by judgment during the brainstorm.

**No criterion hit** → announce `Review routing: lean (no criteria hit)` and proceed
to the attention gate (§4).

**Any criterion hit** → announce `Review routing: deep (criteria: <names>)` and
invoke the `ralf-review` skill **exactly once per artifact**: target = the spec
file; review criteria = the design's stated goals plus its acceptance criteria
(goals-only when the spec carries none — ralf-review fails fast on missing
criteria, so the invocation always supplies them); cycle cap = the skill's
default. Fix what the findings allow inline, but the
**recorded verdict is final**: inline fixes improve the artifact the human receives;
they never upgrade the verdict, and ralf-review is never re-invoked to earn a better
score — that loop is the treadmill the adversarial-qa design exists to kill. The
attention gate reads the recorded verdict.

Where the harness exposes no primitive for dispatching an independent agent — the
observable probe for whether ralf-review's fresh-eyes independence contract can be
honored — the deep route is unavailable: criteria-hit artifacts go straight to
directed-attention review, condition (a) is unmet, and the gate fails closed.

Engine-upgrade transparency (spec rationale, not shipped prose): because the engine
is invoked by skill name only, the adversarial-qa UC1 rebuild (vaac.2.3) and the
foreign-agent review pass (abn9.13) reach this flow without prose changes. The
PASS/not-PASS boundary the gate consumes is stable across the rebuild (clean →
acceptance either way); mid-band verdict semantics may shift, which the gate
tolerates by construction. The shipped skill text says only that the review engine
is the `ralf-review` skill, invoked by name.

### 3.3 Attention routing (replaces the unconditional User Review Gate)

The agent decides whether the owner's review is needed. The conversational
design-approval gate upstream (the skill's HARD-GATE enforcement point) is
untouched — only the post-write spec-review stop is waivable. **Waive** human
review only when ALL of:

- **(a) Review outcome clean.** Deep review was either not warranted (lean route) or
  ended in clean acceptance — a recorded `PASS`, which by ralf-review's contract
  carries no blocking, critical, or major concerns. `PASS_WITH_RESERVATIONS` and
  `FAIL` always park for the human — fix what the findings allow, then present
  directed attention with the verdict and residual concerns attached: those are
  termination-side exits, and per the adversarial-qa design a human reads the
  verdict at termination exits. The gate consumes the recorded Score only;
  ralf-review's "Recommended caller action" field stays advisory to the session and
  is never wired into the waiver.
- **(b) No divergence.** Nothing in the written spec goes beyond what the owner
  approved conversationally: no post-approval design changes, no material
  assumptions or trade-offs the owner has not seen. Material assumptions recorded
  in the artifact but never surfaced to the owner count as divergence, whatever
  marker the project uses for them (`ASSUMPTION:` ledger entries, in this repo).
- **(c) Frontier-tier session.** The session model is frontier-tier. Declared in one
  line in this skill's attention-routing section — currently: Claude Opus or above
  (Opus 4.x, Fable/Mythos 5) or an equivalent top-tier foreign model — and updated
  there when the flagship changes (the fablize Phase-0 pattern). The tier is read
  from the runtime's declared model identity (the harness states the powering model
  in the session context — self-knowledge, not a shell probe, and not the model's
  self-belief); a runtime that declares no model identity fails this condition.
  The declaration is a qualification check on whatever model the owner already put
  at the helm — never a model-selection or escalation instruction. Premium-tier
  models (Fable-class) run only on explicit owner request; no step of this flow
  selects one by default (cost). writing-plans cites this declaration by concept
  rather than duplicating it.

When unsure about any condition, do not waive. **Both branches are announced:**

- **Waived:** a compact notice — one-paragraph summary of what the spec commits to,
  plus "if you look anywhere, look at §X" pointing at the least-conventional
  decision — then proceed directly to writing-plans. No question, no pause.
- **Not waived:** a directed-attention request — 2–5 bullets, each naming a specific
  section, why it may surprise the owner or carry risk, and what judgment is being
  asked of them. Never a bare "please review." Any agentic review that could
  precede this ask (the §3.2 routing) has already run — the human is never asked to
  do review work the agent could have done itself.

Human-directed revisions do not re-enter deep review: when the owner requests
changes at a directed-attention stop, the revised artifact returns to the same
attention stop — the owner is already engaged, and approving their own requested
changes is the review. The once-per-artifact rule spans the whole pipeline run;
re-routing a human revision would either re-invoke the engine to earn a better
verdict (the treadmill) or bill the owner's own edits as fresh complexity. The
owner can always direct another deep review explicitly.

The terminal transition (invoke writing-plans) is unchanged, and the skill's
existing tracked-work handoff (the `## Continuations` convention) is orthogonal —
it fires the same way however the gate resolved. (Spec rationale, not shipped
prose:) when the capture-spec glue (qn0g.1.1) ships, it splices into this same
terminal seam ahead of the gate —
target sequence: distill/land → readiness verdict → review-depth routing →
attention gate. Its readiness verdict becomes an **additional** waiver input, not a
substitute for condition (a): readiness (no placeholders, parseable manifest) and
adversarial-review cleanliness are different properties, so a `not-ready`/
`spec-gaps` verdict blocks the waiver while condition (a) keeps reading the
deep-review outcome. The owqa gate strengthens the same readiness input when it
lands.

### 3.4 Edit surface (enumerated)

Brainstorming skill body:

- **Checklist:** the context-exploration item gains the `CONTEXT.md` detection; the
  "User reviews written spec" item is replaced by two items — "Review-depth
  routing" (§3.2) and "Attention routing" (§3.3); all other items unchanged.
- **Digraph:** the `"User reviews spec?"` diamond and its edges are replaced by:
  `"Spec self-review"` → `"Routing criteria hit?"` (diamond); yes →
  `"ralf-review (single invocation)"` → `"Fix findings, record verdict"` →
  `"Waive human review?"` (diamond); no → the same `"Waive human review?"` diamond;
  waive → `"Invoke writing-plans"`; no-waive → `"Directed-attention review"` with
  edges `approved → Invoke writing-plans` and `changes requested → Revise spec →
  Directed-attention review` — the revision loop returns to the attention stop and
  never re-enters the routing diamond (§3.3's human-revision rule).
- **Prose:** the "Explore project context" guidance gains the glossary-discipline
  paragraph (§3.1); the "User Review Gate" subsection under "After the Design" is
  replaced by the routing + attention-gate prose (§3.2–§3.3), including the
  frontier-tier declaration line.

writing-plans skill body:

- **Self-Review section:** gains the plan-flavored routing + attention gate (§4.1),
  citing the brainstorming skill's frontier-tier declaration by concept.
- **Execution Handoff section:** replaced wholesale per §4.2, including removal of
  the two "If … chosen" branches.

grill-with-docs skill body: one cross-reference line in its supporting-info section
noting that brainstorming adopts the glossary discipline inline when `CONTEXT.md`
exists, and that grill-with-docs remains the standalone deep session for
stress-testing an existing plan.

## 4. writing-plans changes

### 4.1 Same policy for the plan document

After the plan self-review, the same two steps run with plan-flavored criteria:

- routing criteria: the plan deviates from the spec; scope was discovered during
  planning that the spec does not cover; the plan contains irreversible or
  migration steps; the task graph is large or has subtle ordering constraints;
- deep route target = the plan file; review criteria = coverage of the spec plus
  the writing-plans quality bar (no placeholders, type consistency, exact paths);
- the attention gate applies verbatim — waiver conditions (a)–(c), citing the
  frontier-tier declaration in the brainstorming skill (a deliberate cross-skill
  read: both skills deploy together, so resolving the tier means consulting the
  installed sibling); directed attention otherwise. A plan that silently injected
  a surprising change never auto-proceeds. Resolution mirrors the spec gate:
  waived or approved → the execution handoff (§4.2); changes requested → revise
  the plan and return to the attention stop, never back through routing (§3.3's
  human-revision rule).

### 4.2 Execution handoff (replaces the open question)

The closing "which approach?" question is removed. Instead the skill states, in one
message:

1. **A recommendation with one line of reasoning** — subagent-driven per-task
   dispatch as the default where the harness supports independent dispatch;
   workflow-orchestrated execution where the harness additionally supports it and
   the task graph is large or parallelizable; inline execution (sequential, with
   per-task checkpoints) for trivially small plans, and as the degraded default on
   runtimes without independent dispatch.
2. **A clean-context suggestion** — compact the session or start a fresh one, so
   execution begins free of brainstorming residue; phrased in tool-agnostic terms.
3. **A copyable kickoff prompt**, e.g.:

   > Execute the implementation plan at `docs/plans/<plan-file>.md`
   > (spec: `docs/specs/<spec-file>.md`). Work on a feature branch in an isolated
   > worktree. Dispatch one fresh subagent per task; each task follows the
   > test-driven-development skill. Start at Task 1.

   The paths are runtime-filled from the session's actual plan/spec locations
   (project conventions override the shipped defaults), and the prompt body tracks
   the recommended mode — the template above is the subagent-dispatch default.

The existing "If Subagent-Driven chosen / If Inline Execution chosen" branches are
removed along with the question; their mechanics fold into the recommendation and
the kickoff prompt.

This is the pipeline's single terminal pause (locked decision 5). The pause exists
to hand the kickoff prompt to the human, who chooses when and where to clear
context and start execution.

## 5. Portability constraints (shipped-prose rules)

The edited skills deploy to every supported tool and to other projects; their prose
must therefore:

- reference sibling skills by name (`ralf-review`, `grill-with-docs`,
  `test-driven-development`) and concepts by block name — never by this repo's file
  paths;
- carry no tracker/bead IDs — shipped prose cites sibling work by skill or concept
  name only (this dated spec is exempt from the no-tracker-IDs rule; shipped skill
  bodies are not);
- keep the workflow-execution mention capability-conditional ("where the harness
  supports workflow orchestration") since only Claude Code has the Workflow tool;
- phrase clean-context guidance generically (compact / fresh session), not in
  Claude-specific command syntax;
- state defaults as "project conventions override the shipped default," matching the
  existing spec-location precedent in both skills.

## 6. Bead amendments at capture

Applied when this spec is captured (bead minted, PR opened):

- **vaac.2 and vaac.2.3** — append: brainstorming and writing-plans now route
  complex specs/plans into `ralf-review` by name; the UC1 binding (adversarial-qa
  design §10) gains a live caller and its engine rebuild reaches this flow
  transparently.
- **owqa and qn0g.1.1** — append: an attention-routing policy now consumes the
  verdict seam; when these land, their `ready`/`spec-ready` verdicts join the
  attention gate as an additional fail-closed input — readiness and adversarial-
  review cleanliness are different properties, so a `not-ready`/`spec-gaps` verdict
  blocks the waiver while condition (a) keeps reading the deep-review outcome. The
  interim inline readiness judgment is theirs to absorb, not to fight.
- **vaac.2.4** — untouched; §3.1 deliberately stops short of decision-record
  machinery.

Landing order is pinned: this streamlining lands first. The capture-spec glue
(unimplemented) splices against the post-streamlining skill text; §3.4's edit
anchors are stated against the current, pre-glue skill bodies.

## 7. Seams (siblings, cited by name)

| Sibling | Relationship |
|---|---|
| `ralf-review` skill | The deep-review engine, invoked by name with target + criteria + default cap; the internal rebuild (vaac.2.3, UC1 binding) and foreign-agent pass (abn9.13) reach this flow without prose changes — the PASS boundary the gate consumes is stable across the rebuild. |
| adversarial-qa team design (2026-07-05 spec) | Source of the acceptance-vs-termination split honored by waiver condition (a); its D2 report→rule ratchet is why every waiver is announced. Its "human reads the verdict at termination exits" posture is preserved. |
| spec-capture glue (qn0g.1.1, 2026-07-04 spec) | Future occupant of the same terminal seam; its verdict feeds condition (a). Nothing here blocks or duplicates it. |
| owqa verify-brainstorm gate | Future mechanical strengthener of condition (a). |
| vaac.2.4 decision-records | Owns ADR/decision-record requirements in brainstorm docs; explicitly out of scope here. |
| fablize skill | Pattern source for the one-line frontier-tier declaration (its Phase-0 model check). |
| handoff skill | Unaffected; it serves mid-work session handoffs and is user-invoked. The kickoff prompt in §4.2 is generated inline, not via handoff. |
| completion gate (rule + quality-gate workflow) | Untouched. This spec governs pre-implementation attention routing; post-implementation verification depth remains the completion gate's jurisdiction. |

## 8. Non-goals

- No new skill asset (no `spec-review-router`); the durable home for a standalone
  readiness assessor is the adversarial-qa design's planned extraction.
- No changes to ralf-review's internals, cycle contract, or scoring.
- No implementation of owqa, capture-spec, or any M2 machinery.
- No decision-record/ADR requirements (vaac.2.4).
- No completion-gate or merge-policy changes.
- No model-routing config integration — the frontier-tier condition is one declared
  prose line, not a lookup against the routing table.

## 9. Acceptance criteria (prose-only change; verified by transcript evidence)

No helper scripts are added or changed, so no `*_test.sh` additions; the smoke-test
gate is unaffected. Observable acceptance, on first live runs:

1. Brainstorming in a repo with `CONTEXT.md` announces glossary discipline and
   updates `CONTEXT.md` as terms resolve; in a repo without one, the offer appears
   at most once, at spec-write time, only when new domain terms are load-bearing.
2. A spec hitting no routing criteria produces the lean announcement and no
   ralf-review dispatch; a spec hitting any criterion produces the deep
   announcement naming the criteria and a single ralf-review invocation whose
   findings are addressed before the attention gate reads the recorded verdict —
   no re-invocation.
3. A clean-acceptance, no-divergence, frontier-tier run proceeds to writing-plans
   with the waiver notice and no user question; any failed condition produces a
   directed-attention request of 2–5 section-specific bullets.
4. The same routing and gate behavior is observable for the plan document.
5. writing-plans ends with recommendation + clean-context suggestion + copyable
   kickoff prompt; when both attention gates waived, that is the pipeline's only
   pause.
6. grill-with-docs standalone behavior is unchanged; it carries a one-line
   cross-reference to the brainstorming integration.
7. The brainstorming checklist, digraph, and prose agree with each other after the
   edit; no shipped prose cites this repo's internal paths or tracker IDs.
8. On a runtime lacking independent reviewer dispatch or a declared model
   identity, a criteria-hit artifact observably parks at directed attention
   (fail-closed), and the shipped prose carries capability-conditional wording for
   every harness-dependent feature (deep route, execution default, workflow
   mention).

## Residual risks

- **The lean + waived path ships with no external review** — only the inline
  four-lens self-review. This is the intended trade (human time moves upstream;
  simple designs stop paying a review tax), accepted deliberately. Mitigations:
  the fail-closed waiver conditions, the always-announced decision (the D2
  report-phase ratchet — every waiver is auditable in the transcript), and the
  spec post-mortem skill (bead 4htl) as the downstream audit when an escalation
  traces back to a waived artifact.
- **Model-tier misdeclaration** — a runtime that misstates its model identity
  defeats condition (c). Mitigated by reading the harness-declared identity rather
  than model self-belief, and by failing closed when no identity is declared.
- **Criteria drift** — the routing criteria are prose judgment; a lax reading
  under-routes. Mitigated by the mandatory announce line (the routing decision is
  always visible) and absorbed when the mechanical M2/M3 machinery lands.

## 10. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` the routing-criteria wording in §3.2/§4.1 — the set is locked; the
  exact prose is the implementer's.
- `ASSUMPTION:` frontier-tier membership line — "Claude Opus or above, or equivalent
  top-tier foreign model" — revised in place when the flagship changes.
- `ASSUMPTION:` announce-line formats (`Review routing: …`) and the waiver-notice /
  directed-attention shapes (one paragraph + pointer; 2–5 bullets).
- `ASSUMPTION:` kickoff-prompt template wording in §4.2.
- `ASSUMPTION:` the CONTEXT.md offer wording and its at-spec-write timing.
- `DECIDED (owner, 2026-07-11):` both skills are modified directly in-body (same
  resync posture as their existing drift-policy headers: in-tree copy authoritative;
  on upstream resync, diff against the `oss-snapshots/` baseline to port local
  edits).

## Continuations

- feature: Implement brainstorm-pipeline streamlining — AC: §9 items 1–8; edits
  confined to the brainstorming, writing-plans, and grill-with-docs skill bodies
  under the shared skills tree; single PR.
