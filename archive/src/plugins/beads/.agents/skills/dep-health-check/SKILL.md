---
name: dep-health-check
description: Audit the dependency graph across open beads — find missing deps, false existing deps, cycles, stale blockers, and provenance mismatches. Two scopes (focused / all) × two modes (interactive / --just-fix-it).
model: sonnet[1m]
effort: high
---

# dep-health-check

Audit the dependency graph across open beads. Surface missing deps,
false-existing deps, cycles, stale blockers, and provenance mismatches.
Two scopes (focused / all) × two modes (interactive / --just-fix-it).

## When to Use

- User runs `/dep-health-check` (no args) — defaults to `--mode all` interactive.
- User runs `/dep-health-check <bead-id>` — focused on a target bead's
  1-hop neighborhood + full parent/child chain.
- User runs `/dep-health-check --just-fix-it [<bead-id>]` — apply HIGH-confidence
  fixes automatically (see prohibitions below).
- User runs `/dep-health-check --show-stale [<bead-id>]` — render the full
  stale-blocker section in addition to the default report (see Report
  rendering / Stale-blocker rendering rule below).
- Operator-initiated audit before a phase boundary, milestone close, or merge.

## Workflow

### Step 1 — Run collect.py (once)

Invoke with its **absolute path** from the **project working directory** —
never `cd` to the skill directory first. `bd` discovers the `.beads/`
database by walking up from the current directory; running from the wrong
directory returns an empty result.

```
python3 /absolute/path/to/skills/dep-health-check/collect.py --mode all
```
or for focused scope:
```
python3 /absolute/path/to/skills/dep-health-check/collect.py --mode focused --target <bead-id>
```

`collect.py` writes two files to `/tmp/` and prints a **small summary JSON**
to stdout (always under 1KB — always fits in context). The summary schema:

```json
{
  "project_prefix": "...",
  "mode": "all",
  "target": null,
  "bead_count": 188,
  "open_bead_count": 136,
  "finding_counts": { "stale_blocker": 15, "orphan_step_bead": 10 },
  "capped": false,
  "findings_file": "/tmp/dep-health-<ts>-findings.json",
  "beads_file": "/tmp/dep-health-<ts>-beads.txt"
}
```

Finding types emitted: `provenance_mismatch`, `semantic_type_conflict`,
`stale_blocker`, `orphan_step_bead`, `cycle`.

### Step 2 — Read the findings file into context

Read `findings_file` directly. It is ~10–20KB and always fits in context.
It contains the full `findings` array plus run metadata. Do NOT re-run
`collect.py` to get this data.

### Step 3 — Render deterministic + orphan sections

Apply the stale-blocker overlap rule and render all sections (except
LLM-inferred, which comes next). See Report rendering for section order
and formatting rules.

### Step 4 — LLM-inferred pass via fresh subagent

Dispatch a fresh **read-only** subagent (no Bash, no Edit, no Write — Read
only) with a clean sonnet[1m] context. Pass it:

- The absolute path to `beads_file`
- The `findings` array from Step 2 (so it can dedup against deterministic findings)
- The existing dep graph summary (list of `(dependent_id, blocker_id)` pairs already present, extracted from bead `dependencies` fields in the findings context)

Subagent instructions must include:
1. Read the beads file completely.
2. Find bead pairs where a dependency edge appears to be missing and is not already present in the existing dep graph.
3. For each inferred finding, cite the specific bead field content (title, description, notes, or labels) that supports the inference. No LLM-internal-only reasoning.
4. Do NOT re-report findings already present in the provided deterministic findings list.
5. Return findings as a structured list: `dependent_id`, `blocker_id`, `dep_type` (suggest the appropriate type), `confidence` (HIGH/MED/LOW), `rationale`.

Beads file format (for subagent context): one block per bead separated by
`---`; header line starts with `===`; fields are `Title`, `Labels`,
`Parent`, `Deps`, `Desc`, `Notes`. Mol/wisp workflow artifacts are excluded.

### Step 5 — Dedup and render LLM-inferred section

Apply the deduplication rules (see LLM-inferred finding deduplication) to
the subagent's returned findings, then render the LLM-inferred section and
footer.

## Confidence taxonomy

Every finding (deterministic or LLM-inferred) carries one of three confidence
levels:

- **HIGH** — mechanically derivable from observable bead content with no
  judgment call. Examples: provenance label `produced-bead-Y` on X with no
  matching `discovered-from` dep edge; semantic-type conflict
  (`blocks` between parent and child); cycle detected by `bd dep cycles`;
  stale `blocks`-type blocker where every blocker is closed.
- **MED** — strongly suggested by bead content (descriptions, comments,
  parent-chain context) but requires light interpretation. Example: two
  beads describe overlapping subsystems and one's notes reference the
  other but no dep edge exists.
- **LOW** — speculative pattern based on title/topic similarity alone, or
  weak signals like shared labels. Always reviewed interactively; never
  auto-applied.

`--just-fix-it` only acts on HIGH-confidence findings.

## --just-fix-it mode

`--just-fix-it` is the autonomous mode for the audit. It applies edges
unattended. The rules are deliberately narrow:

- **Only two writes are permitted**, both tied to applying a single edge:
    1. `bd dep add <dependent> <blocker> --type <dep-type>` — adds the new dep edge. ONLY `bd dep add` mutates the dep graph. The `--type` argument is REQUIRED: `--just-fix-it` applies non-`blocks` edges (e.g., provenance fixes use `--type discovered-from`), and omitting `--type` lets `bd` default to the wrong type. Pass the finding's dep type explicitly on every invocation.
    2. `bd comments add <dependent-id> "dep-health-check (just-fix-it): ..."` —
       the required audit comment on the dependent bead (see next section).

  Every other mutating primitive is prohibited.
- HIGH-confidence threshold required. MED and LOW findings are listed in
  the report but never auto-applied.
- Cap of **at most 10 edges** per invocation. Excess HIGH-confidence findings are reported and deferred.
- The mode MUST NOT run `bd dep remove`, `bd close`, or `bd label remove`.
- The mode MUST NOT run any bead-content mutation commands (`bd update --notes`, `bd update --description`, `bd update --append-notes`, etc.). Only add-only dep edges plus their audit comments are permitted.

Any finding that would require one of the prohibited primitives is
**surfaced in the report** (with rationale) and left for interactive
follow-up. The mode reports each skipped finding so the operator can
act on it manually.

## Audit comment on every applied edge

When `--just-fix-it` applies an edge it MUST leave an audit trail. Each
applied edge produces ONE comment, posted on the **dependent bead**
(the bead carrying the new outgoing dep), via `bd comments add`:

```
dep-health-check (just-fix-it): added dep <dependent-id> -> <blocker-id> (type <type>); reason: <rationale>
```

The audit comment lands on the dependent bead (not the blocker) so the
trail is co-located with the bead whose graph just changed. Use
`bd comments add` (not `bd update --append-notes`) so the entry shows up
as a first-class comment in `bd show` output and does not mutate the bead
spec.

Format requirements:

- Literal prefix: `dep-health-check (just-fix-it): added dep`
- Arrow form: `<dependent-id> -> <blocker-id>`
- Type segment: `(type <type>)` — `<type>` is the dep type
  (`blocks`, `discovered-from`, `parent-child`, `relates-to`, `tracks`)
- Reason segment: `reason: <rationale>` — a one-line rationale citing the
  observable bead content that supports the edge

## Report rendering

The report renders these sections, in this order:

1. **Deterministic findings** (excluding stale-blockers and orphan-step-beads, which have their own sections)
2. **Mol/wisp orphan step-beads** (grouped by classification)
3. **LLM-inferred findings**
4. **Stale blockers** — rendered only when (a) `--show-stale` is invoked, or (b) a stale-blocker's `dependent` ID overlaps with a bead referenced by any other finding (see overlap rule below)
5. **Recommended Actions** — structured triage table (see section below)
6. **Footer summary** — counts of any hidden categories so the operator can ask to see them

### Deterministic findings section

Lists provenance mismatches, semantic-type conflicts, and cycles emitted
by `collect.py` (HIGH confidence). Each row carries the bead IDs involved,
the finding type, and the deterministic rationale. **Stale-blockers and
orphan-step-beads are emitted by collect.py too, but render in their own
sections** (next two).

### Mol/wisp orphan step-beads section

`collect.py` emits each open mol/wisp step-bead whose parent chain
contains any closed ancestor as a `type: "orphan_step_bead"` finding with
a `classification` field. Render these grouped by classification, in
this order, with empty groups omitted:

1. **safe-cleanup** — step open, all walked ancestors closed, source bead closed. Safe to close manually.
2. **live-work** — source bead is `in_progress`. Step is likely live; do NOT clean up without verifying.
3. **needs-review** — mixed-state ancestor chain (e.g. step open, source still open). Human triage required.
4. **untraceable** — no `for-bead-<X>` label resolvable in the chain, or the labelled source is a ghost. No provenance trail; manual investigation.

For each orphan, render a three-row forensic table:

| Layer | id | title | status | updated_at |
|-------|----|----|-------|----|------------|
| Step-bead | step.id | step.title | step.status | step.updated_at |
| Parent molecule | parent_mol.id | parent_mol.title | parent_mol.status | parent_mol.updated_at |
| Source bead | source_bead.id | source_bead.title | source_bead.status | source_bead.updated_at |

Render `(none)` for any layer that is None (e.g. untraceable orphans have
no source bead). When `ghost_encountered` is true, note it inline — the
parent chain hit a ghost reference and the walk stopped early.

### LLM-inferred findings section

Lists findings the model inferred from bead content. Each item carries a
confidence label (HIGH/MED/LOW) and a per-item rationale citing observable
bead content.

### Stale-blocker rendering rule

`collect.py` emits stale_blocker findings as before. The rendering layer
suppresses them by default and applies this overlap rule:

- **Render a stale_blocker** if its `dependent` ID matches a bead ID
  referenced by ANY other finding (deterministic, orphan, or LLM-inferred).
  Specifically, the dependent ID must appear in another finding's
  `dependent`, `blocker`, `step.id`, `parent_mol.id`, or `source_bead.id`
  field (whichever are present).
- **Otherwise suppress** the stale_blocker from rendering. The footer
  reports the suppressed count so the operator can request the full list.

When the user invokes with `--show-stale`, render ALL stale_blocker
findings regardless of overlap. The overlap-only subset still appears
first (in its normal position), followed by a "Remaining stale blockers"
sub-section for the suppressed-by-default items.

### Recommended Actions

After all finding sections, emit a triage table that maps every surfaced
finding to one of three action tiers. Omit the table entirely when no
findings were surfaced in any section.

The table has five columns:

| Finding | Type | Tier | Action | Rationale |

**Tier definitions and per-type rules:**

| Tier | Label | When to assign |
|------|-------|---------------|
| 1 | **Act now** | Safe to execute immediately with no additional investigation |
| 2 | **Likely safe — verify first** | Strong signal but needs a quick sanity-check before acting |
| 3 | **Hold / Investigate / Ignore** | Leave alone, dig deeper, or consciously defer |

**Per-finding-type classification:**

| Finding type | Tier | Suggested action |
|---|---|---|
| `orphan_step_bead` — `safe-cleanup` | 1 | `bd close <step-id>` — all ancestors + source bead are closed |
| `orphan_step_bead` — `live-work` | 3 — Hold | Leave alone; source bead is `in_progress` — the step may be actively used |
| `orphan_step_bead` — `needs-review` | 3 — Investigate | Inspect the parent-chain state table; determine if work stalled or is ongoing |
| `orphan_step_bead` — `untraceable` | 3 — Investigate | No `for-bead` label — manually trace parentage before closing |
| `provenance_mismatch` | 1 (in `--just-fix-it`) / 2 (interactive) | Add missing `discovered-from` dep edge; cite the `produced-bead-Y` label as evidence |
| `semantic_type_conflict` | 2 | Fix the dep type manually (`bd dep remove` + `bd dep add`); auto-fix is prohibited |
| `cycle` | 2 | Identify the weakest edge and remove it manually; `bd dep remove` is prohibited in `--just-fix-it` |
| `stale_blocker` (overlapping) | 2 | Verify the blocking relationship is still meaningful; if not, remove the dep edge manually |
| LLM-inferred — HIGH | 2 | Inspect the cited bead fields; if the rationale holds, `bd dep add` |
| LLM-inferred — MED | 3 — Review | Read the cited bead content; judgment call before adding any edge |
| LLM-inferred — LOW | 3 — Ignore | Weak signal; file a bead for later if worth tracking, otherwise discard |

**Rendering rules:**

- One row per surfaced finding (or per orphan bead for `orphan_step_bead` findings).
- The **Action** cell includes the literal `bd` command where one exists.
- The **Rationale** cell is one sentence citing the observable fact that drives the tier assignment (classification field, status values, bead field content).
- Group rows by tier (Tier 1 first, then Tier 2, then Tier 3) with a blank separator row between tiers.
- Omit tiers with no rows — do not emit a tier heading when there are no findings for it.

### Footer summary

After all sections, emit a one-line footer with counts of suppressed
items, e.g.:

```
N stale blockers hidden (no overlap with other findings) — pass --show-stale or ask to see them.
```

Omit the footer line when no items are suppressed.

### Empty sections are omitted

Rule: omit empty sections entirely — do not emit a section heading when
there are no findings for it. If `collect.py` produced no deterministic
findings, the deterministic section is omitted. Likewise for orphan
groups, the LLM-inferred section, and the stale-blocker section.

## LLM rationale rules

These rules are non-negotiable for every LLM-inferred finding:

- **Per-item rationale required.** Every LLM finding carries a per-item rationale string citing observable bead content.
- **Cite observable bead content.** The rationale MUST cite observable
  bead content — quote the bead description, reference the bead field
  (description, notes, comments, labels, AC) or quote a bead snippet that
  supports the inference. Rationales that reference bead content by field
  name are acceptable; rationales that name no observable bead content
  are not.
- **No LLM-internal-only reasoning.** No finding may cite only
  LLM-internal reasoning. Model-internal hunches, internal reasoning
  unsupported by bead content, or "it feels related" arguments are not
  acceptable as a rationale. If you can't quote or cite bead content,
  drop the finding.

## LLM-inferred finding deduplication

The orchestration code MUST post-process the LLM's inferred findings and
drop duplicates against two sources before rendering the LLM-inferred
section:

1. **Pass 1 (deterministic findings).** Skip any inferred finding whose
   `(dependent_id, blocker_id, dep_type)` tuple already appears in the
   Pass 1 deterministic findings emitted by `collect.py`. The deterministic
   pass already covers provenance mismatches, semantic-type conflicts,
   stale blockers, and cycles — re-emitting them as LLM inferences is
   noise.
2. **Existing dep edges in the current graph.** Skip any inferred finding
   whose `(dependent_id, blocker_id)` pair already has an existing dep
   edge in the current graph (regardless of dep type). The graph snapshot
   in the collected JSON is the source of truth; if the edge exists
   already, the proposal is redundant.

This dedup pass runs in the SKILL.md orchestration layer — it is not the
LLM prompt's job to perform the dedup itself. The orchestration filters
the LLM's output before rendering.

## Scenarios

| Scenario | Symptom | Action |
|----------|---------|--------|
| Missing `discovered-from` for `produced-bead-Y` label | Provenance mismatch | HIGH — auto-add in `--just-fix-it`; otherwise propose |
| Cycle in dep graph | `bd dep cycles` non-empty | HIGH — report; never auto-resolve (`bd dep remove` prohibited) |
| Stale `blocks`-type blocker (all live blockers closed) | Open bead with no live blocker | HIGH — collected always; rendered only when overlapping another finding or `--show-stale` invoked. Cannot auto-unblock (`bd dep remove` prohibited) |
| Orphan mol/wisp step-bead (closed ancestor in chain) | Workflow artifact left behind | HIGH — render under the appropriate classification group; cleanup requires manual `bd close` (prohibited in `--just-fix-it`) |
| Ghost blocker reference (dep target in no status) | Dep edge pointing at a non-existent bead | Stripped from stale-blocker evaluation by `collect.py` ghost filter; the underlying ghost dep is informational only |
| Semantic-type conflict (`blocks` between parent and child) | Type mismatch | HIGH — report; manual fix |
| Bidirectional `discovered-from` | Symmetric provenance | HIGH — report |
| Asymmetric `relates-to` | Informational only | LOW — note |
| Title/notes overlap suggests `relates-to` | LLM-inferred kinship | MED/LOW — never `--just-fix-it` |

## Red Flags

- **Applying a non-HIGH finding in `--just-fix-it`** — STOP. Only HIGH-confidence
  findings are eligible.
- **More than 10 edges proposed in one `--just-fix-it` run** — STOP. Cap is 10
  per invocation. Defer the rest.
- **Reaching for `bd dep remove` / `bd close` / `bd label remove`** in
  `--just-fix-it` — STOP. These are prohibited. Surface in the report and
  bounce to interactive mode.
- **Rationale that doesn't cite bead content** — STOP. Drop the finding;
  no LLM-internal-only reasoning.
- **Emitting an empty section** — STOP. Omit empty sections.

## Exit conditions

- Interactive mode: present the report; let the operator decide.
- `--just-fix-it`: apply HIGH-confidence edges within the cap; emit audit
  comments; print the full report including skipped items.
