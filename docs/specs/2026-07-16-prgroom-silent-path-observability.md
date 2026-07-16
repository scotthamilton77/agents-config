# prgroom Silent-Path Observability — Degenerate-Cluster WARNING + Legacy-Export Escalation Metadata

**Date:** 2026-07-16
**Status:** Approved (design)
**Beads:** agents-config-abn9.8.41 (cluster degenerate-fallback is silent at the `run_cluster` layer), agents-config-abn9.8.42 (`LegacyExportStore`: emit `escalation_filed` + rationale on exported ESCALATE items). One spec, two beads — both give an already-computed outcome a voice on the surface an operator or downstream gate actually reads; each bead's AC section is separate (§5).
**Related:** `2026-07-16-prgroom-dispatcher-observability.md` — both beads were minted from its Continuations (`.41` explicitly carved out of its §7); its §2 channel story governs `.41`'s channel choice, its §3 `run_cluster` signature narrowing constrains where `.41` may hook, and its §5 logging wiring is why `.41` sequences after it. `2026-07-16-merge-gate-triage-aware-thread-blocker.md` — `.42`'s AC is minted verbatim from its Continuations; its consumer (`check-merge-eligibility`'s `escalations_pending` blocker) is what the new keys feed. `2026-07-05-prgroom-disposition-contract.md` — deliberately omits these fields from the *status-json* projection; §3 here explains why that is not a conflict. (Separately, that spec's §2 rejection of the legacy-export mechanism predates the shipped Option B store this spec extends — reconciling those two stories is tracked as bead agents-config-abn9.8.43, out of scope here.)

## 1. Problem

Two outcomes are computed, persisted — and told to no one:

**A degenerate clustering is indistinguishable from a real one.** When both
of `run_cluster`'s dispatch attempts fail (chain exhaustion or audit
rejection — `_try_dispatch` collapses both to `None`,
`agent/cluster.py:77-87`), it silently synthesizes per-item degenerate
clusters and returns `ClusterRunResult(degenerate=True, attempts=2)`. The
caller, `cluster_pr` (`lifecycle/cluster.py:75-80`), reads only
`.assignments`; `.degenerate`/`.attempts` are discarded unread. No log line,
no Sink event, nothing operator-facing — the only trace is a rationale string
buried in persisted state. An operator watching a groom run cannot tell that
clustering quality just fell off a cliff and every item is now its own
cluster.

**An exported escalation loses its question.** `_legacy_item`
(`prsession/legacy_export.py:106-130`) exports exactly four fixed keys plus
ids. `Disposition.rationale` — the actual pending question a human is
supposed to answer — and any escalation marker never leave the state file,
even though both `DEFERRED` and `ESCALATED` collapse to legacy
classification `"ESCALATE"` (`_DISPOSITION_TO_LEGACY`,
`legacy_export.py:54-62`). Downstream, merge-guard's `escalations_pending`
blocker prints `"(no rationale recorded)"` for every prgroom-sourced
escalation — even when prgroom's own state holds a perfectly good rationale.

## 2. Decision — degenerate-cluster WARNING (abn9.8.41)

**Emit one stderr WARNING from `cluster_pr`, via stdlib logging** — channel 3
of the dispatcher-observability spec's §2 story:

- **Site:** `lifecycle/cluster.py` gains a module-level
  `_logger = logging.getLogger(__name__)`; after `run_cluster` returns,
  `if result.degenerate:` emits the WARNING. This is the only layer with the
  `PRRef` already in scope next to the result, and it reads two fields §3 of
  the observability spec does not remove — so the change is purely additive
  against that spec's in-flight `run_cluster` rewrite.
- **Message:** names the PR (`ref.display()` — the same identity format
  `StderrSink.emit` uses), the attempt count, and the outcome:
  `"%s: degenerate per-item clustering after %d failed dispatch attempts"`.
  One WARNING per clustering regardless of cause — cause-level distinction
  (audit-reject vs chain-exhausted) would require `_try_dispatch` changes
  that collide with the observability spec's §3 rewrite, and the per-dispatch
  fallback summaries that spec adds already narrate the *how*; this WARNING
  states the *outcome* those summaries cannot: the clustering ended
  degenerate. A clean clustering emits nothing.
- **Rejected:** threading `ref` into `run_cluster` (breaks its documented
  purity, and widens a signature the observability spec is simultaneously
  narrowing); routing through `EscalationSink` (that spec's §2 explicitly
  rejects Sink-based cluster telemetry — the cluster verb builds no Sink, and
  a degenerate fallback is not a human-judgment event); the lifecycle
  `warn()` callback (grandfathered channel; the AC names channel 3).

## 3. Decision — legacy-export escalation metadata (abn9.8.42)

**`_legacy_item` gains two keys on ESCALATE-classified items**, branched on
the *post-lookup* classification (`classification == "ESCALATE"`) so the
exhaustive `_DISPOSITION_TO_LEGACY` table remains the single source of truth
for what is escalation-shaped:

- `escalation_filed: true` — constant for the branch. This key carries the
  legacy inventory's semantics ("this item awaits a human answer"), which is
  true by definition of the classification — it is **not** a mirror of
  `Disposition.escalation_filed`, whose lifecycle-Sink-ledger semantics
  (`lifecycle/escalation.py:62-98`) differ and may legitimately be `False` on a
  `DEFERRED` item the Sink never filed. The blocker spec's AC asks for the
  constant (`escalation_filed: true` on exported ESCALATE items); the
  consumer routes on `classification == "ESCALATE"` alone either way, and the
  key only enriches details.
- `rationale: <Disposition.rationale>` — the pending question, verbatim.
  **Omitted when empty** (mirroring `Disposition.to_dict`'s falsy-omission
  idiom, `state.py:97-98`): an emitted `""` would defeat the consumer's
  `"(no rationale recorded)"` fallback exactly where that fallback is telling
  the truth.
- All other disposition kinds are untouched — the export shape for
  `FIXED`/`SKIPPED`/`WONT_FIX`/`ALREADY_ADDRESSED`/`FAILED` items stays
  byte-identical.
- **Not a conflict with the disposition contract:** the
  `2026-07-05-prgroom-disposition-contract.md` status-json projection
  deliberately omits `escalation_filed`/`rationale` ("escalations surface via
  human-gated phase, not per-item") — that governs `status --json`, a
  different boundary with a different consumer. The legacy inventory exists
  precisely to feed merge-guard's item-level details; the two surfaces are
  governed by their own rules, and this spec changes only the latter.

## 4. Sequencing

- **`.41` lands after `abn9.8.26`** (the dispatcher-observability
  implementation) — a **hard dependency, recorded as a bead edge at this
  spec's merge** (Continuations), not just prose: `.26`'s §5 root-logging
  wiring is what makes a module-level WARNING reach stderr deterministically
  (the two pre-existing logger sites depend on CPython's
  handler-of-last-resort happenstance today; landing this WARNING before the
  wiring repeats their defect), and unit tests cannot catch the ordering —
  `caplog` attaches its own handler and passes green either way, so only the
  tracker edge carries the constraint. `.26`'s §3 also rewrites
  `run_cluster`/`_try_dispatch` internals this bead must not race.
- **`.42` is independent** — no in-flight spec touches
  `legacy_export.py`'s export functions (verified against both P1 specs; the
  observability spec cites two line numbers in the module that will drift,
  nothing more). It may land any time; one PR per bead.

## 5. Test plan and acceptance criteria

### 5.1 agents-config-abn9.8.41 — `tests/unit/test_lifecycle_cluster.py`

All three behaviors live in `test_lifecycle_cluster.py` — the WARNING site is
`cluster_pr`; `run_cluster` stays pure and unlogging, so `caplog` tests
against `test_agent_cluster.py` are unwritable by design.

1. `test_degenerate_clustering_emits_one_warning` — a both-attempts-fail
   clustering; `caplog` captures exactly one WARNING from
   `prgroom.lifecycle.cluster` containing the PR identity and `2` (attempts).
   The existing `ClusterDispatcherStub([])` drives this (empty clusters fail
   the audit twice).
2. `test_clean_clustering_emits_no_warning` — a first-attempt success;
   `caplog` empty at WARNING level for that logger.
3. `test_degenerate_after_retry_success_emits_no_warning` — fail-once,
   succeed-once: `degenerate=False` → silent (pins the guard on the outcome
   flag, not on retries having happened). Fixture note:
   `ClusterDispatcherStub` returns the same canned output every call and
   cannot script this sequence — promote `test_agent_cluster.py`'s
   per-call-scripted dispatcher fake into `tests/fakes.py` (the
   `RecordingGh` precedent for shared fakes) rather than duplicating it.
4. Existing degenerate-path tests (`two_audit_failures`, `both_fail_twice`,
   etc.) stay green unmodified — no signature change anywhere.

### 5.2 agents-config-abn9.8.42 — `tests/unit/test_legacy_export.py`

1. `test_escalated_item_exports_filed_and_rationale` — `ESCALATED` with
   rationale → `escalation_filed: true` + the rationale text.
2. `test_deferred_item_exports_filed_and_rationale` — `DEFERRED` likewise
   (including when `Disposition.escalation_filed` is `False` — pins the
   constant-vs-mirror ruling in §3).
3. `test_escalate_item_empty_rationale_omits_key` — empty rationale →
   `escalation_filed: true`, no `rationale` key.
4. `test_non_escalate_kinds_carry_neither_key` — a `FIXED` and a `SKIPPED`
   item's exported dict carries exactly today's key set (a **new** full-dict
   shape pin — the current suite asserts single keys only; no exact-dict
   baseline exists to extend).
5. Implementation checks `tests/integration/` for any exact-dict ESCALATE
   assertions (`test_legacy_export_store.py` or similar) and extends them the
   same way.

**AC (both beads):** the named behaviors red-green; `make ci-prgroom` green
from the worktree root; `.41` adds no signature changes and no Sink wiring;
`.42` changes only `_legacy_item`'s output for ESCALATE-classified items and
touches neither `_DISPOSITION_TO_LEGACY`'s shape nor the `.replyids` sidecar.

## 6. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` merge-guard's inventory consumer treats extra keys as a valid
  superset. Inferred, not directly tested: the blocker spec's
  `test_prgroom_export_escalate` pins only the pre-fix no-keys shape (and its
  `"(no rationale recorded)"` fallback), so no test yet exercises the
  enriched shape — `.42`'s implementation adds one consumer-side fixture
  carrying both keys to close that inference, alongside the coverage note
  that the fallback path loses real-output coverage.
- `ASSUMPTION:` `escalation_filed: true` as classification-derived constant
  (not a state-field mirror) is the intended consumer semantics — the AC's
  verbatim wording and the consumer's routing rule both support it; if the
  Sink-ledger nuance ever needs to surface, it is an additive second key, not
  a change to this one.
- `ASSUMPTION:` `ref.display()` is the right PR identity for the `.41`
  message (matches `StderrSink.emit`'s established operator-facing format).

## Continuations

- no new beads — agents-config-abn9.8.41 and agents-config-abn9.8.42 are the
  pre-existing implementation units (one PR each, sequenced per §4). At this
  spec's merge, record §4's hard ordering as a tracker edge:
  `bd dep add agents-config-abn9.8.41 agents-config-abn9.8.26` (`.41` depends
  on `.26`), so the constraint that tests cannot enforce lives where dispatch
  queues can see it.
