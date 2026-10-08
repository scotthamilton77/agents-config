---
tier: frontier
transport: codex
standard: acceptance-criteria
enforces: [observable-obligation, document-deliverable, one-obligation, verification-contract, human-measurement, human-judgment, pending-until-performed, stochastic-and-window]
---
You are reviewing how each acceptance criterion in the document states and verifies its obligation.

Look for three things:

- **An artifact checked in place of an outcome.** The document promises that someone or something will see a different result, and the criterion checks only a thing the work produces. Examples: a sentence exists in a file, a constant holds a value, a test with a given name exists, two files are byte-identical, a gate exits 0. Such a check can pass while the promised result never happens. When the document's deliverable is that artifact, such as a file format another system reads, checking the artifact is correct.
- **Obligations bundled into one criterion.** One criterion requires two or more results that could each be delivered, accepted or rejected without the others.
- **No way to decide the result.** A criterion names no check, no rule that separates pass from fail, or no person or rule that makes the call.

Report a finding when the document itself supports it. Cite the promise, the criterion, and the check it names or lacks. If nothing in the document meets this bar, report empty. That is a complete and acceptable result.

State the scenario as a deliverable that meets the criterion as written while the promised outcome does not happen: given that deliverable, when the criterion's check runs, expect the check to pass while the outcome is absent.
