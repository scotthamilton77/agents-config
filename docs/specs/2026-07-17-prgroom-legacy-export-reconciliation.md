# prgroom legacy-export reconciliation — the two-surface story and the sunset condition

**Date:** 2026-07-17
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.43 (disposition-contract §2 stale vs shipped LegacyExportStore).
**Related:** `2026-07-05-prgroom-disposition-contract.md` — its §2 is amended in place by this spec's PR (§3); `2026-07-16-merge-gate-triage-aware-thread-blocker.md` — builds its thread-partition ground truth on the legacy export (its §2 decision 3); `2026-07-16-prgroom-silent-path-observability.md` — extends the legacy export with escalation metadata (its §3) and names this reconciliation in its Related line; agents-config-abn9.8.27 (`items[]` envelope, implementation-ready) and agents-config-abn9.8.13.1 (shipped, PR #274) are the two beads whose artifacts this spec reconciles.

## 1. Problem

The prgroom spec set tells two contradictory stories about one surface:

1. `2026-07-05-prgroom-disposition-contract.md` §2 lists "**prgroom writes the legacy inventory format** — chains prgroom to a dying schema through a lossy 7→3 disposition mapping. Pure debt." as a rejected alternative.
2. Bead agents-config-abn9.8.13.1 (Option B, decided 2026-07-14, PR #274) shipped exactly that mechanism: `LegacyExportStore` (`packages/prgroom/src/prgroom/prsession/legacy_export.py`), wired as the production store decorator at `registry.py`'s `resolve_store()`, emitting byte-compatible legacy inventory files (+ `.replyids` sidecar) on every persisted state write.
3. Two newer **Approved** specs stand on the shipped store: the merge-gate triage-aware thread blocker takes the completed-inventory union — fed by `LegacyExportStore` — as its thread-partition ground truth and explicitly *rejected* waiting for `items[]`; the silent-path observability spec extends the export with `escalation_filed`/`rationale` (bead agents-config-abn9.8.42).
4. Meanwhile the same disposition-contract spec's `items[]` bead (agents-config-abn9.8.27) is implementation-ready and unamended.

The live risk: an abn9.8.27 implementer reading the unamended §2 treats `LegacyExportStore` as rejected debt and deprecates or routes around a surface merge-guard actively consumes (`check-merge-eligibility.sh`'s inventory glob-union: the `untriaged_feedback` block, the thread-partition records, and the `bot_review_cap_exhausted` fact all read files this store writes).

## 2. Ruling

**The shipped Option B store wins; the §2 rejection is superseded by events it did not foresee.** The rejection predates two facts: the legacy schema stopped "dying" on the original schedule (merge-guard's thread partition chose the inventory union as ground truth *because* `items[]` had not shipped), and the "lossy 7→3 mapping" turned out to be the deliberate fail-closed bridge semantics (fail-toward-human on collapse; see `2026-07-17-prgroom-resolve-two-axis-vocabulary.md` for the valence ruling on that collapse).

The current, single story is **two surfaces with distinct jobs, not two competing contracts**:

| Surface | Role | State |
|---|---|---|
| Legacy inventory files (written by `LegacyExportStore` and, until its retirement, `wait-for-pr-comments`) | The **shipped merge-guard bridge**: the only surface `check-merge-eligibility.sh` reads today for dispositions, thread triage records, reply-ID exclusions, and the cap fact. Byte-compatible with the wait-for-pr-comments writer; survives the Phase-1 cutover. | Live, load-bearing, being *extended* (abn9.8.42 escalation metadata) |
| `items[]` on `prgroom status --json` | The **forward per-item contract**: full 7-kind disposition fidelity, versioned JSON over the CLI, additive to the envelope. Merge-guard unions it as an *additional* exclusion source when abn9.8.13.1's consumption sibling lands; reserved as a future *additive* thread-partition source. | Specified (disposition contract §3), implementation-ready, unshipped |

Neither replaces the other today. `items[]` remains the direction of travel; the legacy export is the bridge that keeps merge-guard truthful until the sunset condition (§4) holds.

Rejected alternatives:

- **Uphold the §2 rejection and rip out `LegacyExportStore`** — reverts a shipped, tested mechanism (PR #274), breaks two Approved specs that stand on it, and re-opens the PR #211 class of defect (prgroom-groomed PRs permanently blocked because merge-guard cannot see prgroom's triage).
- **Leave the stale spec unamended and let this ruling doc carry the correction** — the risk in §1 is precisely a reader who opens the disposition contract first; a correction the reader never sees is not a correction.
- **Standardize on the legacy format and drop `items[]`** — forfeits 7-kind fidelity permanently (the legacy classification cannot express `deferred`/`wont_fix` distinctly), and reverses an implementation-ready forward contract two other envelope extensions (`verify` block, dispatcher observability) already compose with.

## 3. Amendment to the disposition-contract spec

Shipped in this spec's PR, in place, stating the decision without change-log narration:

1. **§2 decision paragraph** — the sentence scoping the legacy union's lifetime ("…which stays intact until the Phase-1 cutover retires it") now points at the real retirement condition: the legacy union stays intact until the sunset condition of this spec's §4 holds (the Phase-1 cutover removes only the wait-for-pr-comments *writer*, not the surface).
2. **§2 rejected-alternatives list** — the "prgroom writes the legacy inventory format" bullet is replaced by a statement of the current decision: prgroom *does* write the legacy inventory format via `LegacyExportStore` as the shipped merge-guard bridge, with role and sunset governed by this spec.
3. **Related line** — gains a pointer to this spec.

No other section of the disposition contract changes: §3's `items[]` shape, §4's consumption design, and §9's ACs are untouched and remain the abn9.8.27 / abn9.8.13.1 implementation contract.

## 4. Legacy-export lifecycle — kept, extended, then sunset

**Kept and first-class.** Until sunset, `LegacyExportStore` is a supported production surface, not tolerated debt: changes to merge-guard's inventory reading must keep the export in scope, and the abn9.8.42 metadata extension proceeds as specified.

**Sunset condition.** The legacy inventory surface carries exactly three fact families for its one consumer (`check-merge-eligibility.sh`). It can be retired only when every family has a served replacement:

| Fact family | Current source | Replacement condition |
|---|---|---|
| Non-thread disposition exclusions (`untriaged_feedback` union) | inventory `items[]` glob | `items[]` consumption shipped in merge-guard (abn9.8.13.1's remaining consumption work) |
| Thread-partition triage records (SKIP/ESCALATE ladder) | inventory `review_thread` items | a full-fidelity thread source adopted per the reserved-future note in the triage-aware spec §7, with the deferred-valence pin of `2026-07-17-prgroom-resolve-two-axis-vocabulary.md` honored |
| `bot_review_cap_exhausted` (head-scoped) | inventory `polling` block | a PR-scoped envelope surface (the `rereview` block charted in disposition contract §7) shipped and consumed |

**Plus one writer condition:** the wait-for-pr-comments retirement (agents-config-abn9.8.14, behind the abn9.8.20 cutover) has removed the other writer — retiring the reader while a live pipeline still writes the files would silently disconnect that pipeline from merge-guard.

When all four hold, retirement is a deletion, not a migration: drop the `LegacyExportStore` decorator from `resolve_store()`, delete `legacy_export.py` and its tests, and remove merge-guard's inventory glob blocks. Until then, any proposal to deprecate the export is a spec violation of this ruling.

## Assumption ledger

- `check-merge-eligibility.sh` is the sole reader of the legacy inventory directory (verified by grep at HEAD; wait-for-pr-comments scripts write it and read their own files, but the merge-gate facts flow only through merge-guard).
- abn9.8.27 remains implementation-ready under the disposition contract as amended; nothing in this ruling changes its shape or ACs.
- The Phase-1 cutover (abn9.8.20) does not itself remove the legacy inventory directory or the export — verified against the cutover references in `2026-07-05-prgroom-disposition-contract.md` §6 and `2026-07-15-prgroom-e2e-write-path-proof.md`.
- The disposition-contract spec's Status ("Draft (pending review)") is unchanged by this spec; its promotion is that spec's own concern.

## Continuations

- task (deferred): retire `LegacyExportStore` and the legacy inventory surface — AC: all three §4 fact families read from prgroom CLI surfaces in `check-merge-eligibility.sh`, abn9.8.14 retirement landed, then the decorator, `legacy_export.py`, its tests, and merge-guard's inventory glob blocks are deleted in one PR; gated on the §4 sunset condition, anchored under the cutover epic's tail.
