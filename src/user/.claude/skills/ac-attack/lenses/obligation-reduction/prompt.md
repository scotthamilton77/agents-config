---
tier: frontier
transport: codex
standard: acceptance-criteria
enforces: [coverage, sufficiency, can-fail, has-basis]
workings: required
---
You are checking two things: that the document's acceptance criteria discharge every obligation the document takes on, and that every criterion discharges one of them.

First, build an obligation inventory. List each obligation the document states or its scope plainly implies: the results it promises, the guarantees it preserves, and the failure behaviour it commits to. Give each obligation an ID, its kind, a statement of it, and the passage it comes from.

Then map the criteria onto the inventory. A criterion discharges an obligation completely when any work that passes the criterion's check also meets the obligation in full. A check that work violating the obligation would still pass discharges nothing. Where the criteria discharge only part of an obligation, split the obligation into parts, so that each part is either discharged completely or not at all, and record the criteria that discharge each part. List every criterion the document states.

Report one finding for each part that no criterion discharges. Name the part's ID in `obligation` and cite its passage. Report one finding for each criterion that discharges no part, naming it in `target_ac`. Such a criterion either lacks a basis in the document, or serves an obligation the inventory missed, and the author decides which. If every part is discharged and every criterion discharges a part, report empty. That is a complete and acceptable result.

State the scenario for an undischarged part as work that passes every criterion's check while the part is not met. State it for a criterion that discharges no part as the criterion's check running while no obligation of the document depends on its result.

Return the inventory as `workings`, in this shape:

```json
{
  "obligations": [
    {"id": "O1", "kind": "result|guarantee|failure", "statement": "what the document commits to",
     "source": "the passage it comes from",
     "parts": [{"id": "O1.1", "statement": "one part of it", "discharged_by": ["A3"]}]}
  ],
  "criteria": ["A1", "A2", "A3"]
}
```
