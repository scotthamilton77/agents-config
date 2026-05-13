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
- Operator-initiated audit before a phase boundary, milestone close, or merge.

## Workflow

1. Invoke `collect.py` to gather the bead inventory and deterministic findings.
   - `python3 collect.py --mode all` for repo-wide audit.
   - `python3 collect.py --mode focused --target <bead-id>` for focused scope.
2. Parse the JSON it returns. The schema has top-level keys:
   `project_prefix`, `mode`, `target`, `bead_count`, `truncated_count`,
   `capped`, `beads`, `findings`.
3. The LLM body processes the JSON: classifies each finding, assigns a
   confidence (HIGH/MED/LOW), drafts a rationale per item, and renders the
   report. In `--just-fix-it` mode the body also applies HIGH-confidence
   edges within the prohibitions below.

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

- **ONLY `bd dep add`** is allowed as a mutating primitive. No other write.
- HIGH-confidence threshold required. MED and LOW findings are listed in
  the report but never auto-applied.
- Cap of **at most 10 edges** per invocation (cap 10 / max 10 edges /
  10 per invocation / limit of 10). Excess HIGH-confidence findings are
  reported and deferred.
- The mode MUST NOT run `bd dep remove`. Never `bd dep remove`. Removing
  edges is prohibited — bd dep remove is forbidden in `--just-fix-it`.
- The mode MUST NOT run `bd close`. Never `bd close`. Closing beads is
  prohibited; bd close is forbidden in `--just-fix-it`.
- The mode MUST NOT run `bd label remove`. Never `bd label remove`.
  Removing labels is prohibited; bd label remove is forbidden in
  `--just-fix-it`.
- The mode MUST NOT run `bd update --notes`, `bd update --description`,
  `bd update --append-notes`, or any other bead-content mutation. No
  bead-content mutation. No content mutation. Do not mutate bead content
  in `--just-fix-it` mode. Never `bd update` that touches the spec.

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

The report renders two distinct sections, in this order:

### Deterministic findings section

The **deterministic findings** section (deterministic section) lists every
finding that `collect.py` produced mechanically. These are the HIGH-confidence
items: cycles, stale blockers, provenance mismatches, semantic-type
conflicts. Each row carries the bead IDs involved, the finding type, and
the corresponding deterministic rationale.

### LLM-inferred findings section

The **LLM-inferred findings** section (LLM-inferred section) lists every
finding the model inferred from bead content. These items carry a confidence
label (HIGH/MED/LOW) and a per-item rationale.

### Empty sections are omitted

Rule: omit empty sections — empty sections are omitted from the rendered
report, and we skip empty sections entirely (do not emit empty sections,
do not render placeholders for them). If `collect.py` produced no
deterministic findings, the deterministic section is omitted entirely
rather than rendered with a "(none)" placeholder. Likewise, when the LLM
inferred no additional findings the LLM-inferred section is omitted.

## LLM rationale rules

These rules are non-negotiable for every LLM-inferred finding:

- **Per-item rationale required.** Every LLM finding carries a per-item
  rationale. Each LLM-inferred finding has its own rationale; every
  finding requires its own rationale string.
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

## Scenarios

| Scenario | Symptom | Action |
|----------|---------|--------|
| Missing `discovered-from` for `produced-bead-Y` label | Provenance mismatch | HIGH — auto-add in `--just-fix-it`; otherwise propose |
| Cycle in dep graph | `bd dep cycles` non-empty | HIGH — report; never auto-resolve (`bd dep remove` prohibited) |
| Stale `blocks`-type blocker (all blockers closed) | Open bead with no live blocker | HIGH — report; cannot auto-unblock without `bd dep remove` |
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
