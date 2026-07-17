# prgroom resolve() and the two-axis policy — the disposition-valence reconciliation

**Date:** 2026-07-17
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.29 (reconcile resolve()'s skip/deferred/wont_fix threads with the two-axis policy's unresolved-thread gate).
**Related:** `docs/architecture/review-merge-policy/design.md` — the two-axis policy whose eligibility floor this spec's valence table serves; `2026-07-16-merge-gate-triage-aware-thread-blocker.md` — dissolved the original deadlock and named this bead's residual scope ("reconciling skip/deferred/wont_fix vocabularies", its §7); `2026-07-17-prgroom-legacy-export-reconciliation.md` — governs the legacy-export bridge whose 7→3 collapse this spec assigns valence semantics to; `2026-07-05-prgroom-disposition-contract.md` §4.2 — the non-thread CLEARING_SET this spec affirms; agents-config-abn9.8.20 (Phase-1 cutover) — this ruling is recorded before that cutover locks current behavior in as the only implementation.

## 1. Problem

The original deadlock this bead was filed against — resolve() deliberately never GraphQL-resolves SKIP/ESCALATE threads (`lifecycle/resolve.py`, `_RESOLVABLE = {FIXED, ALREADY_ADDRESSED}`) while the eligibility floor counted every live unresolved thread — was dissolved by the triage-aware thread blocker spec: the gate now partitions live unresolved threads against durable triage records instead of blind-counting them. What remains is the residual scope that spec explicitly left to this bead: **three vocabularies describe the same triage decisions with divergent merge-gate valence**, and nothing records which valence is canonical.

1. **prgroom's 7-kind `DispositionKind`** (`prsession/enums.py`): `fixed`, `already_addressed`, `skipped`, `deferred`, `wont_fix`, `escalated`, `failed`.
2. **The legacy 3-way classification** (`_DISPOSITION_TO_LEGACY`, `prsession/legacy_export.py`): collapses `SKIPPED`/`WONT_FIX` → `SKIP`, `FIXED`/`ALREADY_ADDRESSED`/`FAILED` → `FIX`, and — the contested edge — **`DEFERRED`/`ESCALATED` → `ESCALATE`**.
3. **wait-for-pr-comments' live practice**: its persisted classification vocabulary is FIX/SKIP/ESCALATE with no DEFER at all; a deferral is routed as **SKIP** whose public reply points at the tracked follow-up via a public tracking reference (a GitHub issue or PR cross-reference — never an internal bead ID) — and SKIP-with-posted-reply threads *clear* the gate (partition rung 2).

The divergence in one sentence: **a deferred thread blocks the merge (lands in `escalations_pending` via the prgroom export's ESCALATE collapse) while the semantically identical wait-for-pr-comments deferral clears (rides SKIP)** — and meanwhile the disposition contract's non-thread CLEARING_SET treats `deferred` as clearing. Same human decision, three valences, chosen by which pipeline and item kind happened to carry it.

## 2. Ruling

### 2.1 resolve() is affirmed, permanently

`_RESOLVABLE = {FIXED, ALREADY_ADDRESSED}` is the contract, not an interim behavior. prgroom GraphQL-resolves a thread only when the fix flow addressed it; it never resolves skip-family threads (the SKIP/wont_fix reply is an *argument to the reviewer*, never accepted on their behalf) and never resolves escalated threads (resolution is the human's ruling gesture — the exact clearing semantics the triage-aware spec's `escalations_pending` blocker depends on; a prgroom that resolved escalated threads would erase the human's signal channel). The merge gate accommodates permanently-unresolved threads by partition; resolve() does not bend toward the gate.

Rejected: **extend resolve() to GraphQL-resolve skip/deferred/wont_fix after the rationale reply posts** — the bead's other candidate direction, and the triage-aware spec's already-rejected "largest behavioral blast radius" option. It accepts the agent's own argument on the reviewer's behalf and destroys the distinction the partition ladder now runs on.

### 2.2 The canonical valence table

Disposition valence at full 7-kind fidelity — binding on every current and future consumer that can see the full vocabulary:

| DispositionKind | Family | Thread valence (live-unresolved thread) | Non-thread valence (`untriaged_feedback`) | resolve() |
|---|---|---|---|---|
| `fixed` | fix | leaves the live set (resolved by resolve()) | clears | resolves |
| `already_addressed` | fix | leaves the live set (resolved by resolve()) | clears | resolves |
| `skipped` | skip | **clears** once the rationale reply is posted (rung 2) | clears | never |
| `wont_fix` | skip | **clears** once the rationale reply is posted (rung 2) — wont_fix is skip-with-finality, same argument-posted semantics | clears | never |
| `deferred` | skip + tracking obligation | **clears** once the rationale reply (pointing at the deferral's public tracking reference) is posted — see §2.3 | clears | never |
| `escalated` | human | **blocks** (`escalations_pending`) until a human resolves the thread | blocks | never |
| `failed` | actionable | **blocks** (`unresolved_threads` rung 3 — an unaddressed fix failure is actionable work) | blocks | never |

This is one story told three times: the disposition contract's non-thread CLEARING_SET `{fixed, already_addressed, skipped, deferred, wont_fix}` (affirmed unchanged), the thread-partition ladder (affirmed, with §2.3's fidelity qualifier), and wait-for-pr-comments' defer-rides-SKIP practice (affirmed as the correct full-fidelity valence, reached by collapse rather than by vocabulary).

### 2.3 `deferred` — the valence is skip-family; the legacy collapse is a fidelity artifact

**Ruling: at full fidelity, a deferred thread with a posted rationale reply clears like SKIP.** A deferral is an argument plus a durable tracking commitment: the public reply points at the tracked follow-up via a public tracking reference (a GitHub issue or PR cross-reference, never an internal bead ID), and enforcing that the follow-up actually gets filed is the triage discipline's job (the discovered-work discipline), not the merge gate's. This is already the live behavior for every wait-for-pr-comments deferral (routed as SKIP) — the ruling makes prgroom's future full-fidelity behavior converge with existing practice instead of diverging from it.

**The legacy export's `DEFERRED → "ESCALATE"` collapse is affirmed as-is** — for the bridge only. The exported record carries no rationale and no tracking evidence (until abn9.8.42 lands the metadata), so a consumer of the collapsed record cannot distinguish "deferred with a filed bead and a posted argument" from "parked and forgotten"; failing toward human attention is the correct fail-closed default for an evidence-free record, exactly as the triage-aware spec reasoned. The collapse is therefore *bridge semantics under lossy fidelity*, not the canonical valence.

**The pin (binding on future work):** when any full-fidelity source becomes a thread-partition input — `items[]` adopted for threads per the triage-aware spec's reserved-future note, or any successor — `deferred` maps to the **skip rung** (excluded when the reply is posted), not the escalation rung. Copying `_DISPOSITION_TO_LEGACY`'s ESCALATE collapse into a full-fidelity consumer is a spec violation of this ruling. Until such a source ships, deferred threads continuing to land in `escalations_pending` is accepted, documented behavior — a human glances at a deferral that was already tracked, which costs attention but never merges past an untracked one.

### 2.4 Scope of change: none, today

No code changes under this spec. resolve() stays as shipped; the partition ladder stays as specified; `_DISPOSITION_TO_LEGACY` stays as shipped; the CLEARING_SET stays as specified. The deliverable is the recorded valence contract above, landed before the abn9.8.20 cutover can lock current behavior in as an accident rather than a decision. Evergreen architecture docs (`review-merge-policy/design.md`, `prgroom/design.md`) are *not* amended by this PR — they document built behavior, and the §2.3 pin describes intended future behavior; the amendment ships with the first full-fidelity thread-source implementation, per the lockstep convention the triage-aware spec set.

## Assumption ledger

- `_RESOLVABLE`, `_DISPOSITION_TO_LEGACY`, and the `DispositionKind` enum verified at HEAD (`lifecycle/resolve.py`, `prsession/legacy_export.py`, `prsession/enums.py`); the review-merge-policy unresolved-thread row verified at `docs/architecture/review-merge-policy/design.md` (the "Always a live GitHub query… prgroom state is never a substitute" eligibility row — line ~142 at HEAD; the bead's ~134 citation had drifted).
- wait-for-pr-comments' defer-rides-SKIP characterization is practice (triage discipline + 3-way vocabulary), not a coded DEFER branch — verified that its inventory vocabulary has no deferred classification.
- The triage-aware thread blocker spec is Approved and its partition ladder is the agreed target for `check-merge-eligibility.sh`; this spec's §2.2 thread column restates that ladder rather than re-deciding it.
- abn9.8.42 (escalation metadata on the legacy export) does not change the DEFERRED→ESCALATE routing — it adds rationale text to the blocker details only; nothing in it conflicts with §2.3.

## Continuations

- task (deferred): full-fidelity thread partition honors the deferred pin — AC: when `items[]` (or a successor full-fidelity source) is adopted as a thread-partition input in `check-merge-eligibility.sh`, `deferred`-dispositioned threads with a posted rationale reply land on the skip rung (excluded), `escalated` stays on `escalations_pending`, and a regression test pins each; gated on that adoption work (the triage-aware spec §7 reserved-future item), anchored under the prgroom implementation epic.
