# Discovered-Work Placement

When mid-implementation work surfaces a new issue, **classify before filing** to avoid auto-closing the in-flight parent. Apply the **sibling test**: *"would this have been on the parent bead's original plan?"*

| Sibling test answer | Edge to use | Why |
|---|---|---|
| **Yes** — would have been in original scope | Child: `bd create --parent <parent-id>` | The parent stays open until ALL structural children close; closing the child rolls into the parent's close-walk naturally. |
| **No** — out of original scope but related | Orphan + provenance: `bd create` (no `--parent`), then `bd dep add <new-id> <current-id> --type discovered-from` | Keeps the discovery breadcrumb without entangling the new bead in the parent's close-walk. |

**The trap:** filing an out-of-scope discovery as `--parent <in-flight-bead>` then closing it mid-session. Close-walk closes the parent the moment all structural children are closed — so the in-flight bead auto-closes while its work is still pending. Recovery needs `bd reopen <parent>` plus an audit of beads the close-walk propagated through. Classify with the sibling test BEFORE filing, not after.
