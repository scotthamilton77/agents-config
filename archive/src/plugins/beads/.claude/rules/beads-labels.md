# Beads — Labels & Escalation

## Label Reference

| Label | Set by | Meaning |
|-------|--------|---------|
| `brainstormed` | brainstorm-bead finalize | Spec written and reviewed |
| `implementation-ready` | brainstorm-bead finalize | Ready for implement-bead / run-queue |
| `implementation-readied-session-<sid>` | brainstorm-bead finalize | Session marker for Route A gating (`<sid>` = first 8 hex chars of session ID) |
| `for-bead-<bead-id>` | start-bead / implement-bead | On molecule (not bead). Lookup edge from bead→molecule |
| `human` | `bd label add <id> human` | Visibility tag for `bd human list`. NOT a gate on `bd ready` — only blocking deps gate readiness |
| `hep-pause` | HEP procedure (container branch only) | Identifies a human-escalation bead (HEB) created as a CHILD of a container source. Unlike bare human-labeled children (formula-gate artifacts), hep-pause children ARE counted in active_child_count so the container stays classified while awaiting human resolution. |
| `ralf:required` | brainstorm-bead finalize or manual | Formula dispatch signal for ralf-implement / ralf-review |
| `ralf:cycles=N` | brainstorm-bead finalize or manual | Max-cycle override; remove existing `ralf:cycles=` label before adding replacement |
| `epic-decomposed` | brainstorm-bead finalize (container path) | Audit-trail only; not a filter input. Container bead brainstormed for decomposition; no impl bead produced. Query historical decompositions: `bd list --label epic-decomposed --status closed --limit 0` (the `--limit 0` is required — `bd list` defaults to 50 rows and historical decomposition inventories may exceed that). |

```bash
bd label add <id> <label>
bd label remove <id> <label>
bd label list <id>
bd ready --label <label>
```

## Molecule → Bead Linkage

Molecules have no structural link to their source bead. Stamp a label immediately after pour/wisp:

```bash
bd label add <mol-id> for-bead-<bead-id>
```

**Existence probe** — always use `--json` (tree mode silently drops `--type`/`--label` filters):

```bash
bd list --label for-bead-<bead-id> --type molecule --json \
  | jq '[.[] | select(.status != "closed")]'
```
