# prgroom Verb Effect Idempotency — Crash-Safe Remote Side Effects Under the Single-Persist Contract

**Date:** 2026-07-16
**Status:** Draft (pending review)
**Beads:** agents-config-z4m2h (verb remote side-effects are non-atomic vs single persist → duplicate replies on retry; root cause of the 4x recursive duplicate self-reply incident on PR #211).
**Related:** agents-config-tjgu7 (PR-body GET→PATCH lost-update race in the same `_route_memory` — §7 rules its remediation shape onto this spec's substrate); agents-config-oav16 (response-file persistence lifecycle — §8 establishes independence, no ordering constraint); agents-config-abn9.8.28 / PR #274 (`own_reply_id` ledger — poll-side self-exclusion; §6 closes its partial-failure blind spot); `docs/plans/2026-05-12-prgroom-cli-design.md` line 1651 (names this exact double-post shape for the legacy-drain boundary but never hardens `reply`'s own retry path — the gap this spec closes).

## 1. Problem

Every prgroom lifecycle verb follows one contract: deepcopy the state, perform its
remote effects, return the mutated copy; the run loop's single shared error site
`_execute_step` (`lifecycle/run.py:442-461`) assigns the return value and persists it
**once**, after the entire verb body has succeeded. On a tagged `PrgroomError` raise,
the deepcopy — and every "this effect is done" flag the verb set on it — is discarded;
`handle_verb_error` mutates the **pre-call** state and *that* is what gets persisted.

The contract is safe when a verb issues at most one remote mutation per invocation
(`push`: one `git push` guarded by the `has_queued_fix_commits` existence check,
`push.py:20-28`) or when the mutation is idempotent server-side (`resolve`'s
`resolveReviewThread`, documented at `resolve.py:58-61`). It is **not** safe for
`reply_pr`, which loops two non-idempotent mutation families in one invocation:

1. **Per-item reply POSTs** (`reply.py:197-219`): one REST POST per un-replied
   `ReviewItem`, gated only by `item.replied` — a flag that lives on the discarded
   deepcopy until the whole call returns. Item 1's POST succeeds, item 2's raises →
   the persisted state still shows item 1 `replied=False` → the next run re-POSTs
   item 1. **Duplicate reply.**
2. **Per-entry GraphQL thread replies** (`_route_memory`, `reply.py:160-180`): one
   `addPullRequestReviewThreadReply` mutation per target-hinted `pending_memory`
   entry, with **zero** per-entry dedup of any kind — no marker, no captured id; only
   the aggregate `state.pending_memory = []` at the end says "done". A mid-loop raise
   leaves every entry pending, including the already-posted ones.

The compounding failure — the live PR #211 incident (comments 4875007359 →
4875038469 → 4875057073 → 4875069469) — is poll-side: a crash after a POST but
before persist also loses `own_reply_id`, so the abn9.8.28 self-exclusion set
(`poll.py:207`) does not contain the posted comment, and the next `_ingest_items`
ingests prgroom's own reply as a **fresh review item** to triage, reply to, and
re-ingest again. PR #274's ledger fixed the ingestion filter only for ids that
*were* persisted; the partial-failure window that loses the id was left open, which
is why z4m2h is the root cause and abn9.8.28 the symptom.

The third remote mutation in `reply_pr` — the PR-body Decisions PATCH — is already
rerun-safe: `merge_decisions_block` (`reply.py:136-157`) is content-addressed by
`<!-- d:r<retry>:<item> -->` markers (skip-existing-key, byte-identical rerun) and
the no-op PATCH is skipped (`reply.py:174-179`). It needs no change here.

No test today exercises partial-failure-then-rerun for either loop: every
`reply_pr` test uses a `_RecordingGh` fake that never raises
(`tests/unit/test_reply_per_item.py:11-27`), and
`test_execute_step_propagate_flushes_then_raises` covers whole-verb failure, not
intra-verb partial progress.

## 2. Decision

**Option (a): crash-idempotent remote effects via stable hidden idempotency markers
plus a pre-flight existence scan that adopts already-posted effects.** Every
non-idempotent comment-creating call in `reply_pr` appends a hidden, content-stable
HTML-comment marker to the posted body; at verb entry, `reply_pr` reads the PR's
comment listings once, scans bodies for markers, and for each found marker *adopts*
the effect (records the id, flips the flag, skips the call) instead of re-issuing
it. GitHub — not the local state file — is the source of truth for "was this
posted", so a rerun from any stale pre-call state converges without duplicates. The
verb contract (`deepcopy → effects → return; caller persists once`) is unchanged.

Rejected alternatives:

- **Option (b) — per-effect progress persistence before later remote calls** —
  structurally insufficient *and* contract-breaking. Insufficient: a crash between
  a POST and its own persist still loses the flag, and a non-idempotent POST then
  duplicates on rerun — (b) shrinks the window from N calls to one call but cannot
  close it; only a remote-truth check does. Contract-breaking: verbs would need
  `Store`/`PRRef` injected (today only the run loop writes state —
  `resolve.py:14-16` "never touches the store" is the norm) or `_execute_step`
  would need per-item step restructuring, touching every verb and every
  orchestration test, to buy a guarantee it still cannot deliver.
- **Hybrid (a)+(b)** — once (a) holds, (b)'s persistence adds no safety; it only
  saves the pre-flight GET on recovery, one read per crash. Not worth carrying two
  disciplines.
- **State-side dedup key with no remote marker** (the original abn9.8.12 AC's
  "idempotent by (round, source-item) with NO persisted dedup flag") — any purely
  local key is exactly as durable as the persist that carries it; this is the
  design that failed. Remote truth or nothing.

The codebase already reasons in option-(a) terms at three sites — `push`'s natural
existence check, `resolve`'s server-idempotent mutation, and the escalation flush
hooks' "double-fire absorbed by the effect's own idempotency"
(`escalation.py:17-22`) — this spec names that reasoning as a contract invariant
(§3) and supplies it to the two loops that lack it.

## 3. The effect-idempotency invariant (resolves the shared-contract question)

`_execute_step`, `VerbStep`, `Verbs`, the `Store` protocol, and every verb signature
are **unchanged**. The fix is reply-scoped in code and contract-wide in
documentation: the verb contract gains one named invariant, recorded in
`lifecycle/run.py`'s module docstring —

> **Effect-idempotency invariant:** every remote mutation a verb issues must be
> safe to re-issue on a rerun from the pre-call state: naturally idempotent
> server-side, guarded by a natural existence check, content-addressed, or
> marker-guarded via pre-flight existence adoption. The single-persist contract
> discards a raising verb's progress by design; each effect must tolerate that.

Per-verb audit (pipeline order per `run.py:403-413`), the mechanism satisfying the
invariant, and what this spec changes:

| Verb / hook | Remote mutations per invocation | Rerun-safety mechanism | Change here |
|---|---|---|---|
| `poll` | none (reads only) | n/a | marker self-exclusion backstop on ingest (§6) |
| `cluster` | none (reads + local dispatch) | n/a | none |
| `fix` | none remote (local git; effects deferred to `reply` via `pending_memory`) | n/a | none |
| cap-guard | none | n/a | none |
| `push` | 1 × `git push` | natural existence check (`has_queued_fix_commits`) | none |
| `reply` — item POSTs | N × REST POST | **none today** → reply markers + adoption | **§5** |
| `reply` — memory thread replies | M × GraphQL `addPullRequestReviewThreadReply` | **none today** → memory markers + adoption | **§5** |
| `reply` — Decisions PATCH | ≤1 × REST PATCH | content-addressed merge + no-op skip (existing) | none (§7 relocates it under tjgu7) |
| `resolve` | N × GraphQL `resolveReviewThread` | server-side idempotent (`resolve.py:58-61`) | test pin only (§10, behavior 11) |
| `rereview` | N × (DELETE + POST) review-request dances | DELETE idempotent; a crash-rerun repeats the dance → at worst one extra re-review request, which was owed anyway (`rereview.py:64-67`) | none; tolerance documented in the audit |
| flush hooks | Sink emit + `add_label` | dedup flags persisted immediately; `add_label` server-idempotent (`escalation.py:16-22`) | none |

## 4. Marker grammar and the `idempotency` module

New module `packages/prgroom/src/prgroom/lifecycle/idempotency.py` — pure helpers,
no I/O, importable by `reply` and `poll` without a cycle:

```python
import hashlib
import re

_MARKER_RE = re.compile(r"<!-- prgroom:(?:reply|mem):\S+ -->")

def reply_marker(item: ReviewItem) -> str:
    """Stable marker for the one reply this item ever gets."""
    return f"<!-- prgroom:reply:{item.kind.value}:{item.identity.gh_id} -->"

def memory_marker(rm: RoutedMemory) -> str:
    """Globally-unique marker for one routed-memory thread reply: a readable
    batch-key prefix (whitespace-sanitized for marker-grammar safety) plus a
    content digest that carries the identity."""
    digest = hashlib.sha256(
        f"{rm.retry}\x1f{rm.source_item}\x1f{rm.target_hint or ''}\x1f{rm.content}".encode()
    ).hexdigest()[:12]
    prefix = re.sub(r"\s+", "-", f"r{rm.retry}:{rm.source_item}")
    return f"<!-- prgroom:mem:{prefix}:{digest} -->"

def with_marker(body: str, marker: str) -> str:
    """Append the hidden marker on its own trailing paragraph."""
    return f"{body}\n\n{marker}"

def scan_markers(*comment_lists: list[JsonObj]) -> dict[str, int]:
    """Map each full marker string found in any comment body to that comment's
    numeric ``id``. First occurrence wins — the earliest (original) comment
    claims the marker; listing order is ascending (§11 ledger). Entries with a
    missing/zero id are skipped."""
    ...

def carries_own_marker(body: str) -> bool:
    """True iff ``body`` contains a full-grammar prgroom idempotency marker."""
    return bool(_MARKER_RE.search(body))
```

Grammar decisions:

- **Reply markers: key = logical effect identity, not body content.** `replied` is
  monotonic and nothing resets it (`resolve_escalated` flips dispositions only), so
  one item gets at most one POST over its lifetime — `{kind}:{gh_id}` (the §2
  natural key) is unique and stable across retries. Bodies may legally differ
  across cycles (the empty-rationale → later-rationale path, `reply.py:212-217`);
  the marker keys the effect, so adoption is body-independent.
- **Memory markers: key = batch prefix + content digest, because
  `(retry, source_item)` alone is only batch-unique.** `source_item` is
  `{cluster_id}#{ordinal}` where the ordinal restarts at 0 on every
  `resolve_routed_memory` call (`fix.py:204,226`) and `cluster_id` is LLM-minted
  with uniqueness enforced only within a single clustering output
  (`agent/cluster_audit.py:45-52`); `retry` (`pr_review_retries_used`,
  `fix.py:142`) advances only on a push (`push.py:121`) or an external push
  (`poll.py:459`). Two fix passes inside one un-pushed retry can therefore mint
  *distinct* entries sharing the batch key — and a batch-key-only marker would
  adopt-skip the second, never-posted reply silently. The sha256 digest over
  `(retry, source_item, target_hint, content)` restores global uniqueness, and it
  is crash-stable: a rerun replays the same `pending_memory` entries verbatim from
  the persisted pre-call state, so the digest re-derives byte-identically. Entries
  identical in all four fields collide by construction — skipping such a duplicate
  is correct dedup, not loss. (Body-independence, deliberate for reply markers, is
  not wanted here: a `RoutedMemory`'s content is fixed at fix-time; the content
  *is* the effect.)
- **`prgroom:` namespace** extends the existing `<!-- prgroom:decisions:start -->`
  sentinel family (`snapshot.py:56-57`) — one vocabulary, already proven to
  round-trip through GitHub's REST `body` field.
- **Strict full-grammar matching everywhere.** Both adoption and the poll backstop
  match the complete `<!-- prgroom:(reply|mem):... -->` form, never a bare
  substring, so prose *mentioning* markers cannot be mis-adopted or mis-skipped.
- **Cross-PR non-idempotency is preserved** (the legacy-drain protocol relies on
  it, design doc line 1651): markers are only ever consulted against *this* PR's
  comment listings.

## 5. `reply_pr` changes — pre-flight scan and adoption

All changes inside `lifecycle/reply.py`; the public signature
`reply_pr(state, *, gh, ref) -> PRGroomingState` is unchanged.

**Surface computation** — new private helper:

```python
def _reply_surfaces(state: PRGroomingState) -> tuple[bool, bool]:
    """(need_issue_comments, need_review_comments) for this invocation."""
```

An item needs a surface iff `not item.replied`, `item.disposition` is set with
`kind in _REPLYABLE`, and it is not on the bookkeeping-only no-post path
(`item.kind is not REVIEW_THREAD and kind in _BOOKKEEPING_ONLY`). `REVIEW_THREAD`
items and target-hinted `pending_memory` entries need the review-comment surface
(thread replies land in `pulls/{n}/comments`); all other replyable items need the
issue-comment surface (`issues/{n}/comments`). An item whose body will render empty
still counts — the render happens inside the loop, and one tolerated over-fetch
beats a pre-render pass.

**Pre-flight scan** — new private helper, called once at verb entry:

```python
def _existing_markers(
    gh: GhClient, ref: PRRef, *, issue: bool, review: bool
) -> dict[str, int]:
```

At most two reads, each `gh.rest("GET", ..., paginate=True)` (the jkha6 pagination
discipline): `repos/{o}/{r}/issues/{n}/comments` when `issue`,
`repos/{o}/{r}/pulls/{n}/comments` when `review`; merged through `scan_markers`.
When both flags are false it returns `{}` **without any gh call**, preserving the
§3.2 no-op-when-all-replied contract at zero cost. Error semantics are unchanged:
the reads sit inside `reply_pr`'s existing `try`, so a 404 maps to
`vanished_pr_terminal(ref)` and transient/terminal `PrgroomError`s propagate to the
single error site like every other gh call.

**Item loop** — after the existing gates and *before* rendering:

```python
marker = reply_marker(item)
adopted = markers.get(marker)
if adopted is not None:
    item.own_reply_id = adopted   # remote truth, even if the original POST
    item.replied = True           # response was malformed (id degraded to 0)
    continue
...
item.own_reply_id = _post_reply(gh, ref, item, with_marker(body, marker))
item.replied = True
```

Adoption precedes rendering deliberately: the posted comment is the historical
truth, regardless of what today's render would produce. Adoption also *upgrades*
reliability over the POST-response path — `scan_markers` recovers the real comment
id even when the original POST response lacked a usable `id`
(`_post_reply`'s degrade-to-0 branch, `reply.py:89-93`), which then feeds both the
poll exclusion set and the `.replyids` legacy export.

**`_route_memory`** — signature gains the scan (private function):

```python
def _route_memory(
    state: PRGroomingState, *, gh: GhClient, ref: PRRef, markers: Mapping[str, int]
) -> None:
```

The target-hinted loop becomes: skip the GraphQL mutation when
`memory_marker(rm) in markers`; otherwise post
`with_marker(rm.content, memory_marker(rm))`. The thread-less path
(GET body → `merge_decisions_block` → no-op-skipped PATCH) is byte-unchanged — it
already satisfies §3's invariant. `state.pending_memory = []` still clears only at
the end of a fully-successful pass; a partial failure keeps every entry pending,
and the markers make the rerun drain only the truly-unposted remainder.

No state-schema change anywhere: no new fields, `schema_version` stays 1
(`prsession/state.py:27`). The mechanism is stateless by design — remote truth
survives even a deleted state file.

## 6. `poll` ingest backstop — closing abn9.8.28's partial-failure blind spot

Marker adoption in §5 stops the duplicate POST, but the recursive-echo incident had
a second leg: `poll` runs *before* `reply` in the cycle, so on the recovery run
`_ingest_items` sees the orphaned reply (its id lost with the discarded deepcopy,
hence absent from the `own_replies` set at `poll.py:207`) and mints a phantom
`ReviewItem` from prgroom's own words before `reply_pr` ever gets to adopt the
marker. Fix: in the `_ingest_items` entry loop (`poll.py:225-240`), adjacent to the
`own_replies` check:

```python
if carries_own_marker(str(entry.get("body") or "")):
    continue  # prgroom's own posted effect — never ingest, ledger or no ledger
```

Uniform across all three kinds (a `review_summary` body never carries a marker in
practice — prgroom posts no reviews — so the check is a no-op there). This is the
state-independent complement to the abn9.8.28 ledger: `own_reply_id` remains the
fast path and the `.replyids` export source; the marker scan is the crash-proof
backstop that holds even when the persist never happened. Exclusion stays
content-keyed, never author-keyed — the deliberate abn9.8.28 / merge-policy-spec
property ("never excluded by author login") is preserved.

## 7. Reconciliation with tjgu7 — one remediation shape

`tjgu7` is a *different* race on the *same* function: an external actor (human or
bot) editing the PR description between `_route_memory`'s GET and PATCH loses their
edit — a cross-actor lost update, no crash required. This spec rules the
remediation shape for both beads so `_route_memory` never grows two competing
mechanisms:

**Ruling: content-addressed markers on prgroom-owned surfaces — tjgu7 adopts its
option (a) (relocate thread-less memory to a dedicated marked issue comment) built
on this spec's substrate; tjgu7's option (b) (ETag/If-Match optimistic concurrency)
is rejected** as a second, orthogonal discipline that leaves prgroom writing to a
shared artifact it does not own and adds a retry loop the marker mechanism makes
unnecessary.

The tjgu7 landing, spec'd here so it needs no further design pass:

- **Surface:** one prgroom-owned issue comment, first line
  `<!-- prgroom:decisions -->` (a head marker, same namespace), body = the existing
  sentinel-bounded Decisions block. Located via the §5 issue-comments scan (the
  alternation in `_MARKER_RE` and the poll backstop extend to `decisions`).
- **Create:** on first thread-less routing with no marked comment found, POST the
  comment, seeding its block from `extract_decisions_block(PR body)` (one-time,
  read-only migration of any legacy in-body block, preserving its dedup keys —
  upgraded to §4's digest-suffixed form for new lines, closing the batch-scoped
  line-drop collision recorded in §9). The create is itself crash-safe by the same
  adoption rule: a rerun finds the head marker and updates instead of re-creating.
- **Update:** `PATCH repos/{o}/{r}/issues/comments/{comment_id}` with
  `merge_decisions_block` output (function unchanged); no-op skip retained.
- **Read path:** `assemble_snapshot`'s `detail["decisions"]`
  (`snapshot.py:210`) sources from the marked comment, falling back to the PR-body
  block for legacy PRs.
- **Why this closes the race:** prgroom becomes the sole writer of the surface it
  mutates; human PR-description edits leave the write path entirely. A human
  editing prgroom's own bookkeeping comment is out of contract.

Scoped **out of z4m2h's implementation**: the PR-body PATCH path is already
rerun-idempotent (§1), so z4m2h does not touch it; folding the relocation in would
also move `snapshot`'s read path and a body-seeding migration into an
already-nontrivial PR (the small-PR discipline). tjgu7 stays a separate, already-
filed bead that revives against §4/§5's shipped substrate — one shape, two
landings.

## 8. Sequencing

`z4m2h` has no dependencies and lands first, in one PR: `idempotency.py` (§4),
`reply.py` (§5), `poll.py` (§6), `run.py` docstring (§3), tests (§10).

- **vs `oav16` (response-file persistence): independent, no ordering constraint.**
  `reply_pr` renders bodies purely from `Disposition` fields (`rationale`,
  `commits` — verified: `response_path` does not appear in `reply.py`), and §4 keys
  markers on item identity, never body content — so a future oav16 change to body
  sourcing cannot perturb idempotency, and durable `state.items` referencing does
  **not** need to land first. oav16 stays deferred.
- **vs `tjgu7`: after.** Revives once z4m2h merges, consuming §4's grammar, §5's
  scan, and §7's landing plan.

```
z4m2h (this spec) ──> tjgu7 (Decisions-comment relocation, §7)
oav16 ──(independent, stays deferred)
```

## 9. Out of scope

- **Cleanup of historical duplicates** (the PR #211 comment chain, any pre-fix
  double-posts): markers protect only posts made after the fix; retroactive
  deletion needs author-based heuristics the exclusion design deliberately avoids.
- **Backfilling markers onto pre-fix replies:** a PR half-replied under the old
  code can still double-post once after upgrade (no marker to adopt). One-time,
  bounded, self-healing — the new post carries a marker.
- **`rereview` hardening:** the crash-rerun repeat of the DELETE+POST dance can
  re-notify a reviewer once; the re-request was owed (§3 audit). Markers cannot
  help (review requests carry no body); revisit with a state-side stamp only if
  duplicate Copilot review runs become a measured cost.
- **`resolve` markers:** `resolveReviewThread` is server-idempotent; adding markers
  would be dead weight. §10 behavior 11 pins the reasoning instead.
- **The Decisions-block line-key collision** — `merge_decisions_block`'s dedup key
  `{retry}:{source_item}` (`reply.py:152-155`) is batch-scoped exactly like §4's
  memory key, so a colliding *distinct* decision line is silently dropped from the
  PR-body block today. Same root, different blast: a lost bookkeeping line, not a
  duplicated remote effect — outside z4m2h's crash-idempotency scope. Carried to
  tjgu7's landing, which rebuilds that surface with digest-suffixed line keys
  (§7, Continuations).
- **tjgu7's implementation** (§7): shape ruled here, code lands under its own bead.
- **A generic transactional-outbox layer for verbs:** rejected with option (b) —
  no verb outside `reply` needs it (§3 audit), and the invariant makes any future
  need explicit at design time.

## 10. Test plan and acceptance criteria

### 10.1 agents-config-z4m2h — new behaviors, pytest, `packages/prgroom/tests/unit/`

Two fixture idioms serve this plan, matched to each target file's existing seam
(fakes, not mocks; no live gh):

- **`tests/fakes.py` gains `RecordingGh`** — a `GhClient`-protocol fake, the
  protocol-seam sibling of that module's existing subprocess-seam
  `RecordedRunner`. It records `rest_calls` / `graphql_calls`; `rest()` accepts
  `paginate: bool = False`; constructor args: `post_reply_id: int | None = None`
  (the POST response id), `pr_body: str = ""` (the `GET pulls/{n}` body),
  `listed: dict[str, list[dict]] | None = None` (GET path → canned comment list;
  unlisted list-paths return `[]`), and `fail_at: tuple[str, int] | None = None` —
  raise `PrgroomError(tier=Tier.RUNTIME_TRANSIENT,
  code=ErrorCode.RUNTIME_GH_TRANSIENT)` on the N-th call of the named surface
  (`"post"` | `"graphql"`). Used by the new `test_reply_partial_failure.py` and
  the two migrated reply files (§10.2).
- **`test_lifecycle_poll.py` and `test_lifecycle_resolve.py` keep their
  `GhCli` + `RecordedRunner` subprocess seam** — each file's own stated
  convention. Behaviors 9–10 add the marker-bearing comment as one more entry in
  the canned issue-comments JSON page of poll's queued responses; behavior 11
  injects the mid-loop failure by queuing a failing `CommandResult` between
  `_resolved_ok()` results — the `test_gh_fit.py:40-43` `_gh_http_error(500, …)`
  shape (returncode 1, stderr `"gh: … (HTTP 500)"`). `RecordingGh` and its
  `fail_at` are **not** wired into these two files.

New behaviors land in `test_reply_partial_failure.py` (plus the two RecordedRunner
files for 9–11), one red-green cycle at a time:

1. `test_partial_failure_rerun_does_not_duplicate_posted_reply` — two unreplied
   FIXED items; run 1: item A's POST returns id 91, item B's POST raises transient
   → `reply_pr` raises and its return value is discarded (simulating
   `_execute_step`); run 2 from the pre-call state, with the fake listing A's
   posted comment (body carrying A's marker, id 91) → exactly one POST for A
   across both runs, B posted on run 2, final state has both `replied=True` and
   `A.own_reply_id == 91`. **This is the bead's required partial-failure
   regression test — the PR #211 duplicate-reply shape.**
2. `test_posted_reply_body_carries_item_marker` — a thread reply and an
   issue-comment reply each POST a body ending with
   `\n\n<!-- prgroom:reply:{kind}:{gh_id} -->` (pins the wire contract the scan
   and the poll backstop both depend on — contract-pinning, not tautology).
3. `test_adoption_recovers_reply_id_lost_to_malformed_post_response` — run 1's
   POST returned no usable id; run 2's listing carries the marker with id 77 →
   adoption sets `own_reply_id == 77` without a POST.
4. `test_noop_reply_makes_zero_gh_calls` — all items replied, no pending memory →
   no GET, no POST, no GraphQL (cost pin: the §3.2 no-op contract survives the
   pre-flight scan).
5. `test_scan_fetches_only_needed_surfaces` — only a non-thread unreplied item →
   exactly one GET (`issues/{n}/comments`); only a REVIEW_THREAD item → exactly
   one GET (`pulls/{n}/comments`).
6. `test_partial_failure_rerun_does_not_duplicate_memory_thread_reply` — two
   target-hinted `RoutedMemory` entries; run 1: first GraphQL mutation succeeds,
   second raises → `pending_memory` survives on the pre-call state; run 2 with the
   first entry's marker visible in the review-comments listing → GraphQL fires
   only for the second entry; `pending_memory == []` after the clean pass.
7. `test_memory_thread_reply_body_carries_memory_marker` — the GraphQL `body`
   variable equals `with_marker(rm.content, memory_marker(rm))` and its suffix
   matches the full digest-suffixed `<!-- prgroom:mem:\S+ -->` grammar;
   generator/scanner round-trip pinned (`carries_own_marker` is True on the
   posted body).
8. Existing thread-less routing tests (`test_thread_less_routes_via_patch_and_clears`,
   `test_thread_less_noop_merge_skips_patch_but_clears`,
   `test_merge_is_byte_identical_on_rerun`) stay green unmodified — the regression
   pin that §5 left the Decisions path byte-unchanged.
9. `test_ingest_skips_marker_bearing_comment_without_ledger_entry` — state with no
   `own_reply_id` recorded anywhere; the issue-comments listing includes a comment
   whose body carries a reply marker → not ingested. **Regression guard for the
   PR #211 recursive-echo leg** (the ledger-lost window).
10. `test_ingest_keeps_marker_free_comments_from_any_author` — a marker-free
    comment (any author, including one that merely mentions "prgroom:reply" in
    prose without the full grammar) still ingests — pins strict-grammar matching
    and the never-exclude-by-author property.
11. `test_resolve_rerun_reissues_idempotent_mutation_after_midloop_failure` — two
    resolvable threads; first `resolveReviewThread` succeeds, second raises (the
    queued failing `CommandResult`); rerun from the pre-call state re-issues both
    mutations and both items end `resolved=True` — pins the §3 audit-table
    reasoning `resolve.py:58-61` claims, which today has zero retry-path coverage.
12. `test_scan_markers_maps_first_occurrence_and_ignores_non_grammar` — a listing
    with the same marker in comments 5 and 9 maps to 5 (earliest wins — the
    original claims the marker); marker-like text outside the exact
    `<!-- ... -->` grammar is ignored; entries with missing/zero `id` are skipped.
13. `test_colliding_batch_keys_with_distinct_content_both_post` — two
    target-hinted entries sharing `(retry, source_item)` (the §4 batch-key
    collision: ordinal restart + LLM-reused cluster id) but with different
    content; the first already posted (its digested marker in the listing) → the
    second still fires its GraphQL mutation. **Regression guard against silent
    adopt-skip of a never-posted reply.**

### 10.2 Existing-test migration (same PR)

The pre-flight scan changes observable call sequences, so four existing files are
in this PR's red-green scope — three migrate, one is analyzed and untouched:

- `test_reply_per_item.py` — swaps its file-local `_RecordingGh` (lines 11–27) for
  `tests.fakes.RecordingGh`. The ten positional `rest_calls[0]` reads (lines 64,
  85, 94, 110, 118, 134, 154, 185, 200, 220) become first-POST selection via a
  file-local `_first_post(gh)` helper — the pre-flight GET occupies index 0
  whenever a surface is needed. Body-equality literals gain the marker suffix
  (`with_marker(<literal>, reply_marker(item))`; not tautological — behavior 2
  pins the raw grammar independently).
  `test_empty_rendered_body_skips_post_and_keeps_replied_false` (its
  `rest_calls == []`, line 167) becomes "no POST calls" — an empty-render item
  still triggers its surface GET (§11 over-fetch assumption).
  `test_failed_item_gets_no_reply` and `test_idempotent_skips_already_replied`
  keep `rest_calls == []` unchanged; they now double as §5's no-surface/no-GET
  pins.
- `test_reply_memory_routing.py` —
  `test_thread_hint_routes_via_graphql_and_clears` swaps the fake and asserts the
  marker-suffixed GraphQL body (`with_marker("why", memory_marker(rm))`). The
  three thread-less tests (behavior 8) compute no surface (no unreplied item, no
  target hint), so no scan fires — green byte-unchanged.
- `test_run_cycle_reply_resolve_e2e.py` — keeps its local ordering-specialized
  fake (single `ops` list + graphql opname mapping, a shape `RecordingGh` does not
  cover); it grows `paginate: bool = False` and path-keyed GET dispatch (comment
  listings → `[]`, `pulls/{n}` → `{"body": …}`). Its ordering assertions are
  relative `.index()` comparisons and survive the added GETs.
- `test_phantom_review_flood.py` — untouched: its one `reply_pr` test is a SKIPPED
  `REVIEW_SUMMARY` on the bookkeeping-only no-post path, which computes no
  surface, so the scan never runs and the file's paginate-less fake never sees the
  new kwarg.

**AC (agents-config-z4m2h):** behaviors 1–13 covered as named red-green tests;
behaviors 1 and 9 are the incident regression guards, 13 the collision guard;
existing tests migrated exactly per §10.2 with no behavioral pin dropped; no
signature change to `VerbStep` / `_execute_step` / `Verbs` / `Store` / `reply_pr`
/ `resolve_pr` (the `run.py` diff is docstring-only, adding the §3 invariant); no
state-schema change (`schema_version` stays 1, no new fields); `make ci-prgroom`
green from the worktree root (repo coverage floor applies).

## 11. Assumption ledger (scan here, Scott)

- `ASSUMPTION:` GitHub REST comment listings return `body` as raw markdown with
  HTML comments intact. Anchored in-repo: `extract_decisions_block` already
  round-trips `<!-- prgroom:decisions:start -->` through the PR-body GET
  (`snapshot.py:107-113`) — same API family, same media type. Alternative
  (GraphQL `bodyText`-style rendered fields) — not used; the reads stay REST.
- `ASSUMPTION:` both comment listings (`issues/{n}/comments`,
  `pulls/{n}/comments`) return ascending (oldest-first) order by default, so
  `scan_markers`' first-occurrence-wins maps a duplicated marker to the original
  comment. Behavior 12 pins first-occurrence-wins mechanically regardless; if the
  live order ever differed, adoption would pick a different duplicate of the same
  already-posted effect — never re-post.
- `ASSUMPTION:` a thread reply created via `addPullRequestReviewThreadReply`
  surfaces in `GET pulls/{n}/comments` with its body intact — it creates an
  ordinary review comment; `_ingest_items` already reads prgroom-posted thread
  replies from exactly this endpoint (`poll.py:214`).
- `ASSUMPTION:` the listing `id` equals the id the reply POST returns (both are
  the REST comment object's numeric `id` — the field abn9.8.28 already captures).
- `ASSUMPTION:` a human pasting a full raw marker (e.g. quoting one inside a code
  fence) would be skipped by the poll backstop — accepted: the grammar is
  namespaced and full-form, rendered-text copying drops HTML comments, and
  rendering-aware parsing was rejected as unjustified complexity.
- `ASSUMPTION:` one tolerated over-fetch class — an unreplied item whose body
  renders empty still triggers its surface's GET. Alternative (pre-render pass to
  compute surfaces exactly) — rejected, duplicates render logic for one paginated
  read per rare edge.
- `ASSUMPTION:` `rereview`'s crash-rerun re-notification (§9) stays tolerable at
  current Copilot economics; a state-side stamp is the tool if it ever isn't.

## Continuations

- no new beads — existing bead agents-config-z4m2h is the implementation unit;
  tjgu7 (remediation shape ruled in §7, revives after z4m2h) and oav16
  (independent, stays deferred per §8) pre-exist and need no new filings.
- one discovered defect to carry as a note on tjgu7, not a new bead: the PR-body
  Decisions block's line dedup key is batch-scoped (§9), silently dropping a
  colliding distinct decision line today; tjgu7's relocated Decisions comment
  adopts §4's digest-suffixed line keys and closes it.
