# Beads — Labels & Escalation

## Label Reference

| Label | Set by | Meaning |
|-------|--------|---------|
| `brainstormed` | brainstorm-bead finalize | Spec written and reviewed |
| `implementation-ready` | brainstorm-bead finalize | Ready for implement-bead / run-queue |
| `implementation-readied-session-<sid>` | brainstorm-bead finalize | Session marker for Route A gating (`<sid>` = first 8 hex chars of session ID) |
| `for-bead-<bead-id>` | start-bead / implement-bead | On molecule (not bead). Lookup edge from bead→molecule |
| `human` | `bd label add <id> human` | Visibility tag for `bd human list`. NOT a gate on `bd ready` — only blocking deps gate readiness |
| `ralf:required` | brainstorm-bead finalize or manual | Formula dispatch signal for ralf-implement / ralf-review |
| `ralf:cycles=N` | brainstorm-bead finalize or manual | Max-cycle override; remove existing `ralf:cycles=` label before adding replacement |

```bash
bd label add <id> <label>
bd label remove <id> <label>
bd label list <id>
bd ready --label <label>
```

## Human-Escalation Pattern (HEP)

When an agent stage cannot proceed without human input, create an escalation bead with a blocking dep — do NOT stamp `human` on the source bead.

**Escalation:**
```bash
HUMAN_ID=$(bd create \
    --title "Human input needed: <one-line summary>" \
    --type task \
    --priority "<inherited from source bead>" \
    --description "<context: what the stage was doing, what is blocked, what is needed>" \
    --json | jq -r '.id')
bd label add "$HUMAN_ID" human
bd update "$HUMAN_ID" --append-notes \
    "Source: <source-bead-id>
Step-bead: <step-bead-id>
Molecule: <mol-id>
Worktree: <worktree-path, or 'N/A' if no worktree exists yet (e.g. preflight escalation before worktree creation)>
Scenario hint: <one of: spec-amended | scope-expanded | tooling-credentials | architectural-rework | abandoned>"
bd dep add "<source-bead-id>" "$HUMAN_ID"
bd update "<source-bead-id>" --status open
# Exit cleanly (zero exit code; stage is paused, not failed).
```

Result: source bead has open dep blocker → filtered from `bd ready`; escalation bead appears in `bd human list`.

**Resolution:** `bd human respond <human-id> --response "..."` (resumes work) or `bd human dismiss <human-id>` (abandonment). Never bare-remove the `human` label.

Special cases:
- **`[h]` follow-up beads**: parent-child + I2 close-walk + `verified-by-human` label — NOT HEP
- **Merge-gate** (`[Merge gate]`-titled bead with `human` + `merge-ready`): resolve via `/merge-and-cleanup`, NOT `bd human respond/dismiss`

Full protocol: `docs/specs/bead-pipeline-architecture.md` §5.6. The escalation snippet above is byte-identical with §5.6's — any change must land in both files in the same commit.

## Molecule → Bead Linkage

Molecules have no structural link to their source bead (upstream bug `lp3`). Stamp a label immediately after pour/wisp:

```bash
bd label add <mol-id> for-bead-<bead-id>
```

**Existence probe** — always use `--json` (tree mode silently drops `--type`/`--label` filters, bug `2dx`):

```bash
bd list --label for-bead-<bead-id> --type molecule --json \
  | jq '[.[] | select(.status != "closed")]'
```

When upstream bugs `lp3` and `2dx` are fixed, drop the stamp and switch probe to `bd list --parent <bead-id> --type molecule --json`.
