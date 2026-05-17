# Roadmap Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `docs/plans/2026-05-09-roadmap.md` — a strategic roadmap doc with up to 5 user-capability-framed milestones, cut/defer recommendations, and structural-change proposals — by orchestrating three parallel research forks, a human checkpoint, opus[1m] synthesis, and a self-reviewed doc handoff.

**Architecture:** Five-phase pipeline (parallel discovery → checkpoint → synthesis → doc → deferred adversarial+beadification). Phases 1-4 are in scope here. Phase 5 is gated on Scott's review of the Phase 4 output and gets its own plan. The orchestrator is the persistent agent throughout; forks are ephemeral subagents.

**Tech Stack:** Claude Code (orchestrator at opus[1m] xhigh), three parallel subagents (sonnet 4.6 — A medium, B high, C high), `bd` CLI for bead queries, plain markdown output. No code is written; deliverables are markdown + bead-state digests.

**Reference:** Design spec at `docs/plans/2026-05-09-roadmap-analysis-design.md`.

---

## File Structure

| Path | Producer | Consumer | Lifetime |
|---|---|---|---|
| `/tmp/roadmap-bead-snapshot.json` | Task 1 | Tasks 2, 5 | Session |
| `/tmp/roadmap-fork-a.md` | Fork-A | Orchestrator (Tasks 3, 5) | Session |
| `/tmp/roadmap-fork-b.md` | Fork-B | Orchestrator (Tasks 3, 5) | Session |
| `/tmp/roadmap-fork-c.md` | Fork-C | Orchestrator (Tasks 3, 5) | Session |
| `/tmp/roadmap-checkpoint-tables.md` | Task 3 (conditional) | Scott | Session |
| `docs/plans/2026-05-09-roadmap.md` | Task 6 | Scott (review), ralf-review (Phase 5a) | Permanent |

---

## Task 1: Pre-flight — capture bead snapshot

**Files:**
- Create: `/tmp/roadmap-bead-snapshot.json`

- [ ] **Step 1: Capture full bead state for the analysis scope**

The forks need a stable snapshot — running `bd list` mid-flight risks drift if Scott (or another agent) modifies state. Capture once, all forks read the same data.

Run:
```bash
TODAY=$(date +%Y-%m-%d)
THIRTY_DAYS_AGO=$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d "30 days ago" +%Y-%m-%d)
{
  bd list --status open --json
  bd list --status in_progress --json
  bd list --status closed --json | python3 -c "
import sys, json
data = json.load(sys.stdin)
cutoff = '$THIRTY_DAYS_AGO'
recent = [b for b in data if b.get('closed_at', '') >= cutoff]
print(json.dumps(recent))
"
} > /tmp/roadmap-bead-snapshot.json
wc -l /tmp/roadmap-bead-snapshot.json
```

Note: `bd list --json` may emit concatenated arrays. Forks must use the resilient parser pattern from the design (try `json.loads`; on failure use `json.JSONDecoder().raw_decode` in a loop).

- [ ] **Step 2: Verify snapshot non-empty and parseable**

Run:
```bash
python3 -c "
import json
with open('/tmp/roadmap-bead-snapshot.json') as f:
    raw = f.read()
decoder = json.JSONDecoder()
all_beads, idx = [], 0
while idx < len(raw):
    s = raw[idx:].lstrip()
    if not s: break
    chunk, end = decoder.raw_decode(s)
    items = chunk if isinstance(chunk, list) else [chunk]
    all_beads.extend(items)
    idx = idx + (len(raw[idx:]) - len(s)) + end
from collections import Counter
status = Counter(b.get('status','?') for b in all_beads)
print(f'Total beads in snapshot: {len(all_beads)}')
print(f'Status distribution: {dict(status)}')
"
```

Expected output: total ≥ 100 beads, status distribution showing open + in_progress + closed-30d. If total is suspiciously low (<50), STOP and investigate `bd list` behavior before dispatching forks.

- [ ] **Step 3: Capture vision-section anchor for Fork-C**

Forks should reference AGENTS.md by path, but a stable anchor for the 5 commitments helps Fork-C avoid hallucinating them. Verify the section exists:

Run:
```bash
grep -n "five load-bearing commitments" /Users/scott/src/projects/agents-config/AGENTS.md
```

Expected: one match in the AGENTS.md "Vision & Mission" section. If missing, STOP — the design assumes this anchor exists.

- [ ] **Step 4: Update bead snapshot location into the design (skip; design already references it)**

No action — the design spec already documents the snapshot at `/tmp/roadmap-bead-snapshot.json`. Move on.

---

## Task 2: Phase 1 — dispatch three forks in parallel

**Files:**
- Read: `/tmp/roadmap-bead-snapshot.json` (forks consume)
- Create: `/tmp/roadmap-fork-a.md`, `/tmp/roadmap-fork-b.md`, `/tmp/roadmap-fork-c.md` (forks produce)

- [ ] **Step 1: Dispatch all three forks in a single message**

Use a single Agent-tool message with three subagent calls. Each fork is general-purpose model=sonnet, with effort encoded in the prompt verbosity and explicit reasoning depth instructions. Each writes its digest to its assigned `/tmp/` file.

**Fork-A prompt (Inventory & Cluster — sonnet, medium effort):**

```
You are Fork-A of a three-fork roadmap analysis pipeline. You work
INDEPENDENTLY. You do NOT read other forks' output. You do NOT communicate
with other forks. The orchestrator synthesizes across forks later.

# Mission: thematic clustering + title/intent mismatch flags

## Input
Read the bead snapshot at `/tmp/roadmap-bead-snapshot.json`. It contains
all open + in_progress beads + closed beads from the last 30 days for the
agents-config project (located at /Users/scott/src/projects/agents-config).

The snapshot may contain concatenated JSON arrays. Use this resilient
parser:

```python
import json
with open('/tmp/roadmap-bead-snapshot.json') as f:
    raw = f.read()
decoder = json.JSONDecoder()
beads, idx = [], 0
while idx < len(raw):
    s = raw[idx:].lstrip()
    if not s: break
    chunk, end = decoder.raw_decode(s)
    items = chunk if isinstance(chunk, list) else [chunk]
    beads.extend(items)
    idx = idx + (len(raw[idx:]) - len(s)) + end
```

## Output
Write your digest to `/tmp/roadmap-fork-a.md`. Format:

```markdown
# Fork-A digest — Inventory & Cluster

## Cluster shape (narrative)
[3-5 sentences describing the clusters that emerged, count per cluster,
anything surprising about the distribution.]

## Clusters
| cluster name | bead-ids (id only, comma-separated) | one-line theme | momentum (closed-30d count) |
|---|---|---|---|
| ... | ... | ... | ... |

## Title/intent mismatch flags
| bead-id | title | content suggests actually about | proposed action |
|---|---|---|---|
| ... | ... | ... | retitle to "..." / rescope to ... |

## Doesn't fit any cluster (≤10 beads)
| bead-id | title | one-line note |
|---|---|---|
```

## Mission rules
- Cluster by *what beads are trying to achieve*, not by labels or types.
  Examples that may emerge: "brainstorm-readiness gate stack," "worker
  fleet redesign chain," "multi-tool parity," "PR delivery automation,"
  "memory/audit hygiene." Don't force these names — derive from content.
- Aim for 5-10 clusters. Too few = under-clustered; too many = noise.
- Title/intent mismatch: if a bead's title and description disagree on
  what it's about, flag it. Cite a phrase from the description as evidence.
- Closed-30d beads count toward momentum signal but should NOT define
  cluster names — they show what's shipping, not what's planned.

## Anti-patterns (REJECT)
- Bead-id without title in any output line.
- Proposals without specific evidence (a phrase from description).
- Re-pasting bead descriptions instead of synthesizing.
- Clusters defined by labels (e.g., "vision-85-5-10 beads") — those are
  Fork-C's territory.

## Effort guidance
Medium effort. Read titles + descriptions of all snapshot beads. Cluster
by intent. Surface ≤500 words of narrative + as many table rows as
warranted. Do not exceed 1500 words total in the digest file.

WRITE YOUR DIGEST TO /tmp/roadmap-fork-a.md AND RETURN A ONE-SENTENCE
COMPLETION CONFIRMATION.
```

**Fork-B prompt (Dependency Critique — sonnet, high effort):**

```
You are Fork-B of a three-fork roadmap analysis pipeline. You work
INDEPENDENTLY. You do NOT read other forks' output.

# Mission: structural sequencing AND structural critique

## Input
Read the bead snapshot at `/tmp/roadmap-bead-snapshot.json` (use the
resilient parser pattern). For each bead, fields you'll use: id, title,
description, parent, dependencies, labels, status, issue_type.

For dependency edges, the snapshot's `dependencies` array on each bead
shows OUTGOING deps. To find incoming, build a reverse map.

## Output
Write your digest to `/tmp/roadmap-fork-b.md`. Format:

```markdown
# Fork-B digest — Dependency Critique

## Structural shape (narrative)
[3-5 sentences: what chains exist, what's load-bearing, orphan count,
overall structural-health read.]

## Existing chains worth preserving
| chain | beads (id + title) | why this sequence holds up |
|---|---|---|
| chain-1 | A (title) → B (title) → C (title) | ... |

## Load-bearing beads (high in-degree)
| bead-id | title | dependents count | what it unblocks |
|---|---|---|---|

## Orphans (no parent, no incoming dep)
| bead-id | title | candidate parents (if any) | one-line note |
|---|---|---|---|

## Structural critique
| change type | beads involved (id + title) | rationale |
|---|---|---|
| REMOVE EDGE | A (title) ⊥ B (title) | false dependency: <evidence> |
| ADD EDGE | A (title) → B (title) | actual unblocking: <evidence> |
| REPARENT | X (title) under Y (title) → Z (title) or orphan | <evidence> |
| SUSPECT LABEL | bead-id (title) carries label-X | <evidence> |
```

## Mission rules
- The existing structure (deps, parents, labels) is NOT SACRED. Treat it
  as proposals from past-Scott, not ground truth.
- For every existing edge / parent / label: ask "does this serve
  roadmap-coherent sequencing?" If not, flag for change.
- For missing edges: if reading bead A's description reveals it logically
  unblocks bead B (e.g., A defines a worker-report schema that B's
  implementation consumes), propose ADD EDGE.
- Cycles, dead-end chains, orphans-that-should-have-parents: surface them.

## Anti-patterns (REJECT)
- Proposals without (1) specific bead pair / bead+parent and (2) one-line
  evidence citing bead title/description content. "This feels wrong" is
  not evidence.
- Inventing edges based on title pattern-matching alone. Read both beads'
  descriptions before proposing.
- Bead-id without title in any output line.

## Effort guidance
HIGH effort. The critique work is judgment-heavy — Scott explicitly
invested in precision here. For each proposed change, name the specific
phrase or fact from the bead descriptions that supports it. If you can't
cite evidence, don't propose the change.

Aim for ≤500 words narrative + as many table rows as warranted. Do not
exceed 2500 words total.

WRITE YOUR DIGEST TO /tmp/roadmap-fork-b.md AND RETURN A ONE-SENTENCE
COMPLETION CONFIRMATION.
```

**Fork-C prompt (Vision Alignment — sonnet, high effort):**

```
You are Fork-C of a three-fork roadmap analysis pipeline. You work
INDEPENDENTLY. You do NOT read other forks' output.

# Mission: vision alignment tagging + label drift critique

## Input
1. The bead snapshot at `/tmp/roadmap-bead-snapshot.json` (use the
   resilient parser pattern).
2. The Vision & Mission section of
   `/Users/scott/src/projects/agents-config/AGENTS.md` — specifically the
   five load-bearing commitments enumerated under "the mechanism rests on
   five load-bearing commitments". Read the section yourself; do not rely
   on summarized commitments.

## Output
Write your digest to `/tmp/roadmap-fork-c.md`. Format:

```markdown
# Fork-C digest — Vision Alignment

## Distribution narrative
[3-5 sentences: how the open backlog distributes across load-bearing /
multiplier / hygiene / off-thesis. What's surprising about the
distribution.]

## Load-bearing for MVP (the critical set)
| bead-id | title (+ outcome if title unclear) | which commitment served | why load-bearing |
|---|---|---|---|

## Multiplier (post-MVP accelerator)
| bead-id | title (+ outcome if unclear) | which commitment amplified | how it amplifies |
|---|---|---|---|

## Hygiene / keep-the-lights-on
| bead-id | title (+ outcome if unclear) | one-line note |
|---|---|---|

## Off-thesis (cut candidates)
| bead-id | title (+ outcome if unclear) | rationale for cut candidacy |
|---|---|---|

## Vision gaps NOT covered by any open bead
- [Gap 1: which commitment is under-served, what's missing, evidence]
- [Gap 2: ...]

## Label drift
| change | bead-id (+ title) | rationale |
|---|---|---|
| REMOVE label vision-85-5-10 | ... | doesn't actually serve a load-bearing commitment because <evidence> |
| ADD label vision-85-5-10 | ... | serves commitment-N because <evidence> |
```

## Mission rules
- Each tag must name the SPECIFIC commitment served (or amplified, or
  contradicted). "Aligned with vision" is not an answer; "serves
  commitment 2 (no-not-ready gate) by enforcing AC completeness at
  bd update --status implementation-ready" is.
- For every bead currently labeled `vision-85-5-10`, judge whether the
  label is correct. If a load-bearing bead lacks the label, flag ADD.
- Vision gaps section: surface commitments that NO open bead currently
  serves. This drives recommended-discovered-work in the synthesis pass.

## Anti-patterns (REJECT)
- Vague alignment claims without naming a specific commitment.
- Bead-id without title in any output line.
- Label-drift proposals without rationale citing the commitment served (or
  not served).

## Effort guidance
HIGH effort — this fork's judgment quality drives the synthesis pass.
For each load-bearing tag, write 1-2 sentences of "why" that would
withstand contrarian read. For each off-thesis cut candidate, write a
one-sentence rationale that names which commitment makes it off-thesis
(or names a covering bead that supersedes it).

Aim for ≤500 words narrative + table rows as warranted. Do not exceed
2500 words total.

WRITE YOUR DIGEST TO /tmp/roadmap-fork-c.md AND RETURN A ONE-SENTENCE
COMPLETION CONFIRMATION.
```

Dispatch all three in a single message with three Agent tool calls. Use `general-purpose` subagent_type for each.

- [ ] **Step 2: Verify all three digest files were created**

Run:
```bash
ls -la /tmp/roadmap-fork-a.md /tmp/roadmap-fork-b.md /tmp/roadmap-fork-c.md
wc -w /tmp/roadmap-fork-a.md /tmp/roadmap-fork-b.md /tmp/roadmap-fork-c.md
```

Expected:
- All three files exist.
- Word counts: Fork-A ≤1500, Forks B/C ≤2500 each.
- If a file is missing or empty, the fork failed silently — re-dispatch that fork before proceeding.

- [ ] **Step 3: Sanity-check digest structure**

Run:
```bash
for f in a b c; do
  echo "=== Fork-$f headers ==="
  grep "^##" /tmp/roadmap-fork-$f.md || echo "NO HEADERS - DIGEST MALFORMED"
done
```

Expected: each digest has ≥4 `##` section headers matching the format spec. If a digest is malformed, re-dispatch that fork with stricter format reminders.

---

## Task 3: Phase 2 — compose and send the checkpoint message

**Files:**
- Read: `/tmp/roadmap-fork-a.md`, `/tmp/roadmap-fork-b.md`, `/tmp/roadmap-fork-c.md`
- Possibly create: `/tmp/roadmap-checkpoint-tables.md`

- [ ] **Step 1: Read all three fork digests fully**

Use the Read tool on each digest. Do not summarize at this stage — internalize the content for cross-fork comparison.

- [ ] **Step 2: Identify cross-fork tensions**

Look specifically for:
- A bead Fork-A clustered as "infrastructure" but Fork-C tagged "load-bearing for MVP" → infrastructure IS user-facing here, note for synthesis posture.
- A bead Fork-B proposes to REPARENT but Fork-A's cluster suggests its current parent is correct → disagreement, raise with Scott.
- Fork-C's "vision gaps not covered" section vs Fork-A's clusters → does any cluster actually address the gap implicitly?
- Beads Fork-C tagged off-thesis but Fork-B identifies as load-bearing structurally → contradiction worth Scott's attention.

Aim for 2-5 tensions surfaced. If you find zero tensions, you're not looking hard enough — re-read the digests.

- [ ] **Step 3: Estimate checkpoint message size**

Sum approximately:
- Fork narratives: ~3 × 200 words = 600
- Proposal tables: depends on fork output, count rows × ~30 words/row
- Cross-fork tensions: ~5 × 100 words = 500
- Synthesis posture: ~150

If estimate exceeds 3000 words, split proposal tables to a separate file (Step 4); otherwise keep inline (Step 5).

- [ ] **Step 4 (conditional, if size > 3000 words): Split tables to side file**

Write the proposal tables (title/intent mismatch from A; structural critique from B; load-bearing/multiplier/hygiene/off-thesis/label-drift from C) to `/tmp/roadmap-checkpoint-tables.md` with one-line previews retained in the main checkpoint message.

- [ ] **Step 5: Compose the checkpoint message**

Use this exact template:

```markdown
## Phase 2 checkpoint — your sign-off needed before synthesis

### Fork-A digest
**Cluster shape (narrative):**
[3-5 sentences from Fork-A's narrative.]

**Title/intent mismatch flags:**
[Inline table from Fork-A, or "Full table at /tmp/roadmap-checkpoint-tables.md (count: N rows)" if split.]

### Fork-B digest
**Structural shape (narrative):**
[3-5 sentences from Fork-B's narrative.]

**Existing chains worth preserving:**
[Inline or split.]

**Structural critique:**
[Inline table or split. Always show counts: "REMOVE: N, ADD: M, REPARENT: K, SUSPECT LABEL: J".]

### Fork-C digest
**Distribution narrative:**
[3-5 sentences from Fork-C's narrative.]

**Load-bearing beads (MVP-critical set):**
[Inline or split.]

**Off-thesis cut candidates:**
[Inline or split.]

**Vision gaps not covered by any open bead:**
[Bullet list — these tend to be few and important; always inline.]

**Label drift:**
[Inline or split.]

### Cross-fork tensions
[2-5 tensions. Each as: "Fork-X said A about bead-id (title); Fork-Y said B; my read of the disagreement is C; need your steer on D — or proceed and I'll synthesize toward E."]

### My intended synthesis posture
[2-4 sentences: how I plan to weight cluster intent vs structural critique vs vision alignment when they disagree. How cut candidates will appear in the doc. Anything else I'm pre-deciding so you can object now.]

### Your response options
1. Green-light → I synthesize.
2. Redirect → "I disagree with Fork-X's tag on bead-id, re-evaluate."
3. Add a lens → "Also consider [thing]."
4. Pull-back → "Show me Fork-X's full digest before I decide."
```

- [ ] **Step 6: Send the checkpoint message and PAUSE**

Send the composed message as your turn output. Do not proceed to Task 4 or Task 5 until Scott responds. The orchestrator's pause here is the entire point of the checkpoint contract.

---

## Task 4: Phase 2 redirect handling (conditional, based on Scott's response)

- [ ] **Step 1: Classify Scott's response**

| Response type | Indicator | Action |
|---|---|---|
| Green-light | "go", "proceed", "synthesize", "looks good" | Skip to Task 5 |
| Redirect | "I disagree with X", "re-evaluate Y" | Step 2 below |
| Add a lens | "also consider", "include this perspective" | Step 3 below |
| Pull-back | "show me Fork-X's full digest" | Step 4 below |

If Scott's response is ambiguous, ASK ONE CLARIFYING QUESTION before acting.

- [ ] **Step 2 (Redirect): Re-dispatch the relevant fork**

If the redirect concerns one fork's analysis, re-dispatch THAT fork only with an updated prompt that includes Scott's specific objection. Use the same model/effort as the original dispatch (or escalate if Scott's objection suggests the original was shallow). Overwrite the digest file. Then return to Task 3 Step 1 and re-compose the checkpoint with the updated digest.

If the redirect is about cross-fork synthesis posture, NO re-dispatch needed — fold the steer into Task 5's synthesis directly.

- [ ] **Step 3 (Add a lens): Extend synthesis brief**

Note Scott's added lens in the synthesis prep. No fork re-dispatch. Proceed to Task 5 with the lens documented as a synthesis input.

- [ ] **Step 4 (Pull-back): Surface specific findings from a fork digest**

Read the requested digest file fully. Reply to Scott with the specific section he wants to see (don't dump the entire file). After his follow-up response, classify again per Step 1.

---

## Task 5: Phase 3 — synthesis (orchestrator, opus[1m] xhigh)

This task happens entirely in the orchestrator's context. No subagent dispatch. The opus[1m] xhigh budget lands here.

- [ ] **Step 1: Re-read all three fork digests + checkpoint feedback in full**

Use the Read tool on `/tmp/roadmap-fork-{a,b,c}.md`. Internalize. Hold Scott's checkpoint response (any redirects, lenses, or postures) in working context.

- [ ] **Step 2: Identify natural cleavages → milestone candidates**

Walk the merged data:
1. Start from Fork-C's load-bearing set — these MUST land in MVP or pre-MVP.
2. Apply Fork-B's chains: a load-bearing bead with prerequisite chain length L means the chain plus the bead form a candidate milestone.
3. Apply Fork-A's clusters: beads that share intent likely share a milestone.
4. Look for cleavages: where does the load-bearing set split into independent groups? Each independent group is a candidate milestone.

Cap at 5 milestones. If more cleavages emerge, collapse or defer the lowest-value ones.

- [ ] **Step 3: Apply the stability bar test for pre-MVP milestone necessity**

Per design: pre-MVP stabilization is needed if there are unresolved (a) active bugs in formulas/molecules OR (b) documented contradictions in instructions. Architectural incompleteness and multi-tool drift do NOT trigger pre-MVP.

Walk the in-progress + open P0/P1 beads:
- Any bead matching (a) → goes in M1 (pre-MVP) if not already in flight.
- Any bead matching (b) → same.
- If the (a) + (b) set is empty, NO pre-MVP milestone is needed — start at MVP.

- [ ] **Step 4: Sequence milestones**

For each milestone candidate:
- Identify which other milestones it depends on (via Fork-B's chains).
- A milestone may not depend on a later-numbered one.
- If the dependency graph forces re-ordering, re-order.
- If milestones can run in parallel (no inter-dependency), still serialize for the doc — pick a primary order based on user-visible value delivery, but note "parallelizable with M_x" in the milestone's dependencies section.

- [ ] **Step 5: Draft milestone definitions with user-capability framing**

For each milestone, draft (in working context, not yet writing the doc):
- **User-capability headline.** Format: "<Audience> can <observable capability> [under <constraint>]." Example: "Scott can run a feature bead from `bd ready` through PR merge overnight without intervening, on Claude Code only."
- **Business outcome (1-2 sentences):** what changes in the user's day.
- **Broader-adopter readiness:** YES / PARTIAL / NO with one-line note.
- **DoD criteria:** each MUST be mechanically or behaviorally verifiable. If you can't write a `bd` command, a test invocation, or a behavioral check that confirms the criterion, demote to bead-level AC or remove.
- **Beads in scope** with id + title + role (load-bearing / supporting / acceptance test).
- **Risks & open questions.**
- **Estimated relative effort:** S / M / L / XL.

- [ ] **Step 6: Identify cuts, deferrals, supersessions**

For each bead in Fork-C's off-thesis set:
- If a covering bead exists in a milestone → SUPERSEDE.
- If the bead is valid but not roadmap-horizon-relevant → DEFER post-roadmap.
- If the bead is genuinely not aligned with the vision → CUT.

Each gets a one-sentence rationale citing evidence.

- [ ] **Step 7: Identify structural changes that survive synthesis**

For each STRUCTURAL CRITIQUE row from Fork-B:
- Cross-validate against Fork-A's cluster assignment for the involved beads.
- Cross-validate against Fork-C's vision-alignment tag for the involved beads.
- If both validate → keep the proposal for Section 8 of the doc.
- If one disagrees → mark as a flagged uncertainty in Section 9.
- If both disagree → drop the proposal.

- [ ] **Step 8: Identify discovered work for vision gaps**

For each item in Fork-C's "vision gaps not covered" section:
- If gap is roadmap-horizon-relevant → discovered-work bead recommended in Section 7 of the doc.
- If gap is acknowledged out-of-scope → mark as such with rationale.

- [ ] **Step 9: Identify open questions that need Scott's decision**

Anything synthesis surfaced that:
- Has architectural or requirements implications NOT specified in the design or earlier conversation, AND
- You cannot decide from the codebase, prior answers, or standard engineering judgment.

These become Section 9 of the doc. Each gets options + recommendation + rationale. Be ruthless: if you can decide it, decide it. Lazy escalation is a self-review failure.

---

## Task 6: Phase 4 — write the roadmap doc

**Files:**
- Create: `docs/plans/2026-05-09-roadmap.md`

- [ ] **Step 1: Write the doc skeleton**

Use this exact section structure (per design Section 5):

```markdown
# Roadmap — agents-config — 2026-05-09

## 1. Scope & method
[~150 words: what this doc is, what it isn't, audience (Scott primary,
broader users secondary), method (3 forks + synthesis), how to update.]

## 2. Vision recap
[~100 words: 85/5/10 thesis + 5 commitments, synthesized through "what
this means for the next 3-5 milestones." NOT copy-pasted.]

## 3. Where the backlog stands today
- Total count, status distribution
- Cluster shape (from Fork-A) — narrative
- Vision-alignment distribution (from Fork-C) — narrative
- Structural health (from Fork-B) — narrative
[~250 words combined]

## 4. Milestones
[Per Task 5 Step 5 drafts. Each milestone gets the full schema:
headline, outcome, readiness, DoD, beads in scope, dependencies, risks,
effort.]

## 5. Cross-cutting decisions baked into the sequence
[Where forks raised tensions, the synthesis chose a posture. Each
decision documented with rationale.]

## 6. Recommended cuts and deferrals
[Table from Task 5 Step 6.]

## 7. Vision gaps NOT addressed by any milestone
[From Task 5 Step 8. Each gap acknowledged out-of-scope with rationale OR
flagged as discovered-work-recommended bead.]

## 8. Structural changes recommended (separate from milestone work)
[Table from Task 5 Step 7. Each change: REMOVE / ADD / REPARENT / SUSPECT
LABEL with bead pair + rationale. Queued for Phase 5b execution if Scott
approves at review.]

## 9. Open questions for Scott
[From Task 5 Step 9. Each question gets options + recommendation +
rationale.]
```

- [ ] **Step 2: Fill in each section using the synthesis output from Task 5**

Schema enforcement during writing:
- Every bead reference: id + title minimum. Add outcome line where title is unclear. NO naked IDs.
- Every milestone DoD criterion: mechanically or behaviorally verifiable. If you write "feature X exists," rewrite to "bd command Y returns Z" or "test suite W passes."
- Every cut/defer recommendation: one-sentence rationale citing evidence.

- [ ] **Step 3: Self-review pass**

Run the 6-point checklist in order:

1. **Placeholder scan** — search for "TBD", "TODO", vague language. Fix.
2. **DoD verifiability** — for each milestone, read each DoD bullet aloud and ask "how would I observe this is true?" If you can't answer in one sentence with a concrete check, rewrite.
3. **Bead-reference completeness** — grep the doc for naked bead-IDs:
   ```bash
   grep -oE 'agents-config-[a-z0-9.]+' docs/plans/2026-05-09-roadmap.md | sort -u | while read id; do
     # for each id, ensure it appears with a title nearby
     grep -A1 -B1 "$id" docs/plans/2026-05-09-roadmap.md | grep -q "title\|—\|:" || echo "Naked: $id"
   done
   ```
   Fix any "Naked:" findings.
4. **Cut-rationale evidence** — for Section 6, each row's rationale should cite specific evidence (a phrase, a covering bead). If a rationale just says "off-thesis" or "low-priority," strengthen it.
5. **Cross-section consistency** — milestone N+1 must not reference beads that Section 6 cuts. Manually walk the milestone bead lists vs the cut list.
6. **Open-questions discipline** — re-read Section 9. For each question, ask: "Could I have decided this from the codebase, prior answers, or standard judgment?" If yes, decide it inline and remove from Section 9.

Fix issues inline. No re-review loop. Move on.

- [ ] **Step 4: Verify file written and structurally sound**

Run:
```bash
wc -l docs/plans/2026-05-09-roadmap.md
grep "^##" docs/plans/2026-05-09-roadmap.md | head -20
grep -c "^### Milestone" docs/plans/2026-05-09-roadmap.md
```

Expected:
- File ≥200 lines (under that suggests skipped sections).
- All 9 top-level `## N.` sections present.
- Milestone count ≤5.

---

## Task 7: Handoff to Scott

- [ ] **Step 1: Compose the handoff message**

Use this template:

```markdown
Roadmap drafted at `docs/plans/2026-05-09-roadmap.md`.

**Highlights:**
- M1: [user-capability headline]
- M2: [user-capability headline]
- M3: [user-capability headline]
- [...up to 5]

**Open questions for you:** [count]
**Recommended cuts/deferrals:** [count cuts + count defers + count supersessions]
**Structural changes proposed:** [count]

Please review when ready. Your call on whether to proceed to:
- Phase 5a: optional adversarial review (`ralf-review` opus xhigh, max 2 cycles)
- Phase 5b: beadification (staged, per-stage rollback, gated on your "go beadify")

I will NOT begin Phase 5 without your explicit go.
```

- [ ] **Step 2: Send the handoff and PAUSE**

This is the terminal step of the Phases 1-4 plan. Do not proceed to Phase 5 unless Scott explicitly authorizes it. Phase 5 has its own implementation plan (to be written after Scott approves Phase 4 output).

- [ ] **Step 3 (housekeeping): Memory update if anything non-obvious surfaced**

After Scott reviews and approves the doc, capture any non-obvious decisions or patterns to memory (per the Claude memory system rules in your context). Examples worth saving:
- A novel fork-orchestration pattern that worked well.
- A cluster shape that was non-obvious until forks ran.
- A failure mode in the checkpoint contract that needed mid-flight adjustment.

DO NOT save bead lists, transient state, or anything derivable from the doc itself.

---

## Self-Review (this plan, against the design spec)

**Spec coverage check:**
- Design Section 1 (Purpose) → covered by plan Goal + Architecture
- Design Section 2 (Audience) → covered by Task 5 Step 5 (user-capability headlines per audience)
- Design Section 3 (Constraints) → covered: bead scope (Task 1), in-progress treatment (Task 5 Step 4 sequencing), stability bar (Task 5 Step 3), cut latitude (Task 5 Step 6), structural authority (Task 5 Step 7)
- Design Section 4 (Method) → covered by Tasks 1-6 (one per phase, 5b deferred)
- Design Section 5 (Doc structure) → covered by Task 6 Step 1 + Step 2
- Design Section 6 (Model selection) → covered by Task 2 fork prompts + Task 5 orchestrator-only synthesis
- Design Section 7 (Files & artifacts) → covered by File Structure table at top
- Design Section 8 (Decision log) → no plan-side coverage needed; design captures rationale
- Design Section 9 (Out of scope) → enforced in Task 7 Step 2 (Phase 5 not started without explicit go)
- Design Section 10 (Next step) → THIS IS THAT NEXT STEP. Self-recursion verified.

**Placeholder scan:** all step descriptions have concrete commands or content. No TBDs.

**Type/name consistency:**
- File paths: `/tmp/roadmap-bead-snapshot.json`, `/tmp/roadmap-fork-{a,b,c}.md`, `/tmp/roadmap-checkpoint-tables.md`, `docs/plans/2026-05-09-roadmap.md` — used consistently across tasks.
- Fork names (A/B/C) and missions: identical across Task 2 prompts and Task 3 cross-references.
- Phase numbering matches design.

**Gaps fixed inline:** none found.

---

## Execution notes

- Phase 1 fork dispatch in Task 2 must be a SINGLE message with three Agent tool calls. Sequential dispatch defeats the parallel-discovery design.
- Task 3 PAUSE is mandatory. Synthesis (Task 5) is the expensive step; gating on Scott's cheap response is the entire point.
- Task 5 must happen in the orchestrator's context (opus[1m] xhigh). Do not dispatch synthesis to a subagent — the 1M window is the differentiator.
- Phase 5 is OUT OF SCOPE for this plan. A separate plan will be written if/when Scott authorizes it after reviewing Phase 4 output.
