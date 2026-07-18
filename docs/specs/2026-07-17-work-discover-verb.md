# work discover verb — mechanical enforcement of discovered-work triage

**Date:** 2026-07-17
**Status:** Draft — pending review
**Depends on:** the track-partition design spec (2026-07-15) — acceptance criterion 13
only (the create gate’s track enforcement); criteria 1–12 are implementable against the
shipped lifecycle layer with no track-layer dependency.
**Bead:** agents-config-wgclw.9.3 (child of the work-facade CLI epic; the named
continuation of the discovered-work triage discipline spec, §6)
**Decision:** Add a `work discover` lifecycle verb that mechanizes the *form* of the
discovered-work triage discipline: it refuses to file a discovery without an anchor
(or an explicit `--orphan` escalation) and a complete, well-formed triage record
(Scope / Priority / Anchor), then mints the bead through the existing `create <noun>`
path — inheriting its noun template, duplicate guard, and track gate — adds the
`discovered-from` provenance edge, and returns the completion-report manifest row as a
structured envelope field. The verb enforces *form*; scope correctness stays caller
judgment. `Lands in` is **derived**, never a caller input.

## 1. Context / Problem

The discovered-work triage discipline (2026-07-11) ships as prose: an always-loaded
tripwire rule plus the `triaging-discovered-work` skill. Prose relies on invocation
discipline — an agent can file a bead with an orphan-plus-breadcrumb, a silent
self-assigned priority, and no anchor, then bury it as a footnote. Measured at that
spec's design time: of 93 open non-epic beads, 15 had no parent anchor and 14 carried
only a `discovered-from` breadcrumb — the exact leak.

That spec named the fix (§6 Continuations): a workcli `work discover` verb that makes
the filing contract mechanical — "refuses to file a discovery without an anchor parent
and a complete triage block; emits the manifest row as structured JSON." This spec
designs that verb.

The transport contract (2026-07-04) gives us the JSON envelope, typed error codes, and
protocol versioning; the lifecycle layer (2026-07-12 plan) gives us `create <noun>`
with noun templates, a duplicate-title guard, and placement validation; the track
partition (2026-07-15) adds a config-gated track resolution to that same `create`
path. `work discover` composes over all three rather than duplicating any of them.

## 2. Decision summary

| # | Decision | Rejected alternative |
|---|----------|----------------------|
| 1 | **Flags, not a JSON/stdin payload** — one flag per triage field, matching every other verb; the envelope stays output-only | A structured stdin payload invents an input convention no other verb uses |
| 2 | **Wrapper over `create <noun>`, not a new noun** — discover validates the triage form, then delegates minting to the shared creation path; the filed bead keeps a real noun (feat/bugfix/…) | A dedicated `discovered` noun template duplicates the create path and evidence rule |
| 3 | **`Lands in` is derived from scope + placement**, never a caller flag | `--lands-in` invites a value that contradicts scope/anchor and re-opens the vague-bucket leak |
| 4 | **Enforce form, not judgment** — refuse missing/malformed triage fields and missing edges; never adjudicate whether the scope call or anchor choice is *correct* | Trying to validate scope correctness mechanically (agents get it wrong both ways; not decidable from CLI inputs) |
| 5 | **Manifest row rides the stdout envelope `data`**, not a file | A sidecar file breaks the "stdout is always the envelope" invariant every consumer relies on |
| 6 | **Reuse `E_USAGE` for arg-shape; one new `E_TRIAGE_INCOMPLETE` for triage-semantic refusals** | An all-`E_USAGE` design gives consumers no greppable "triage rejected" signal; a code per field is surface bloat |

## 3. Verb contract

### 3.1 Usage

```
work discover --noun {feat|bugfix|chore|spike|decision} --title T [--description D]
              (--anchor ID | --orphan)
              --discovered-from CURRENT_WORK_ID
              --scope {out-of-scope | in-scope-deferred:HATCH}  --scope-why TEXT
              --priority P0-P4                                   --priority-why TEXT
              (--anchor-why TEXT  when --anchor  |  --escalation-why TEXT  when --orphan)
              [--track NAME]
```

`HATCH ∈ {externally-blocked, blast-radius, own-cycle}` (the three named deferral
hatches). `--noun` is restricted to **leaf** nouns — a discovery files a work item, not
a structural container; a discovered effort large enough to need its own cycle is filed
as a leaf (`feat`) and `promote`d later, not born a `spec`/`epic`.

### 3.2 Argument semantics

| Flag | Required | Meaning |
|---|---|---|
| `--noun` | yes | kind of discovered work; routes the shared noun template |
| `--title` / `--description` | `--title` yes; `--description` no | bead title/body (triage block is appended to the body by the verb) |
| `--anchor ID` | XOR `--orphan` | parent edge: best-fit epic under the mapped milestone (out-of-scope) or parent-of-in-flight-bead (in-scope deferral) |
| `--orphan` | XOR `--anchor` | the loud no-anchor-fits escalation; requires `--escalation-why` |
| `--discovered-from ID` | yes | the current-work bead; becomes a `discovered-from` provenance edge |
| `--scope` | yes | `out-of-scope` or `in-scope-deferred:HATCH`; drives `Lands in` derivation |
| `--scope-why` | yes | scope rationale; must be non-blank after strip and single-line (no embedded newline) — see the rationale-shape rule below |
| `--priority` | yes | `P0`–`P4` (regex `^P[0-4]$`); form only, not correctness |
| `--priority-why` | yes | priority rationale; same non-blank single-line rule |
| `--anchor-why` / `--escalation-why` | one, by placement | placement rationale (or why no anchor fits); same non-blank single-line rule |
| `--track NAME` | no | forwarded **unmodified** to the shared `create <noun>` path, where the track layer's normal resolution and validation apply; needed only when the track is *underivable* — an `--orphan` filing (no parent) or an `--anchor` under a track-less parent (a milestone carries no `track:*` label by design and falls through to enforcement). An `--anchor` under a *tracked* parent inherits that parent's track, so there `--track` only overrides it |

**Rationale-shape rule.** Each rationale flag (`--scope-why`, `--priority-why`, and the
applicable placement rationale `--anchor-why`/`--escalation-why`) is a required *one-line*
value, so presence alone is insufficient: the verb strips surrounding whitespace and
refuses a value that is empty post-strip or contains an embedded newline
(`\n`/`\r`), returning `E_TRIAGE_INCOMPLETE` naming the offending field, **before**
minting. This closes the `--scope-why ""` (and multiline-`*-why`) hole that would
otherwise let a discovery be filed with an empty or malformed triage block — defeating
the complete-record gate.

**Both edges in one call.** A valid invocation resolves `--discovered-from` *before*
minting (§4 step 2), then creates the parent edge atomically via the
`create --parent <anchor>` primitive, then adds the `discovered-from` edge — one
`work discover` call, both edges. The `discovered-from` add is a second bd operation
(bd `create` cannot express a typed non-blocks edge at birth), so the create→edge seam
is non-transactional like `work track set`'s label swap.

**Recovery contract — every post-create failure carries `created_id`.** Once the backend
`create` returns an id the bead exists, so *any* later step that fails must surface that
id in `detail.created_id`; the caller then replays only the failed step against the
already-minted bead, never a duplicate. Two post-create seams exist, both non-transactional:

1. **Orphan-marker note append** (`--orphan` only). The shared `create_noun` path writes
   the orphan marker as a *separate* `append_note` after the create returns
   (`lifecycle/create.py`, `--orphan` branch); a failure leaves a created-but-unmarked bead.
2. **`discovered-from` provenance edge add** (§4 step 5, every filing); a failure leaves a
   created bead with no provenance edge.

For either seam the verb returns the error **with `detail.created_id` set** so the caller
replays only that step — re-append the marker, or add the edge (`work dep add`). This
obliges the shared create path to surface `created_id` on its own post-create note-append
failure instead of raising a bare error that discards it; discover, as the wrapper,
guarantees the id reaches `detail` for every failure after the mint. Because the provenance
source is validated pre-mint, the edge replay always has a live target — the remaining
edge-add failure is a *transient* backend fault against an already-validated source, never
an unresolvable input (a deleted/invalid source is refused before anything is minted, per
§4 step 2). These post-create faults are the complete set of partial-failure windows, and
each is caller-recoverable, not silent.

**`Lands in` derivation** (never an input; this is what structurally disallows vague
temporal buckets):

| scope | placement | derived `lands_in` |
|---|---|---|
| `in-scope-deferred:HATCH` | `--anchor` | `parent work item (<anchor>)` |
| `out-of-scope` | `--anchor` | `<anchor>` |
| any | `--orphan` | `unanchored — needs your call` |

The fourth vocabulary value, `this PR`, is **never** produced by `discover`: a
fixed-in-session discovery files no bead, so it is a `verify-checklist` report-time
row, not a `discover` call. Stating this keeps the report-time and filing-time
contracts disjoint.

### 3.3 Envelope output

Success — the manifest row is a structured object under `data.manifest_row`, exactly
the five columns verify-checklist renders (protocol shown as `1.x` — the concrete MINOR
is assigned at merge time by landing order; see §7), plus a `remaining_work` flag the report uses
to honor the double-reporting rule (every in-scope-deferred row also appears under
Remaining Work):

```json
{"protocol": "1.x", "ok": true, "error": null,
 "data": {
   "item": {"id": "agents-config-abn9.8.41", "title": "retry config drift", "track": "prgroom"},
   "edges": {"parent": "agents-config-abn9.8", "discovered_from": "agents-config-vaac.12"},
   "triage": {"scope": "in-scope-deferred:blast-radius", "priority": "P1",
              "anchor": "agents-config-abn9.8"},
   "manifest_row": {"item": "retry config drift", "scope": "in-scope — deferred: blast-radius",
                    "lands_in": "parent work item (agents-config-abn9.8)",
                    "tracked_item": "agents-config-abn9.8.41",
                    "priority_why": "P1 — breaks overnight runs"},
   "remaining_work": true,
   "warnings": []
 }}
```

Refusal — nothing is created; the message names the missing/invalid field:

```json
{"protocol": "1.x", "ok": false, "data": null,
 "error": {"code": "E_TRIAGE_INCOMPLETE",
           "message": "scope 'in-scope-deferred:rushed' has an unknown hatch; use one of externally-blocked, blast-radius, own-cycle",
           "detail": {"field": "scope", "given": "in-scope-deferred:rushed"}}}
```

### 3.4 Error cases

| Condition | Code | Notes |
|---|---|---|
| adapter lacks dep-write support (`supports_dep_write` false; `supports_dep_types` false in shipped code) | `E_UNSUPPORTED_CAPABILITY` | registration gate (§4 step 0), refused **before** form validation, provenance resolution, or any mint; discover always writes a `discovered-from` edge, so it gates identically to the `dep` verb; creates nothing |
| missing `--title`; neither/both of `--anchor`/`--orphan`; `--noun` not a leaf noun | `E_USAGE` | pure arg-shape; argparse or cheap check |
| missing any of `--scope`/`--scope-why`/`--priority`/`--priority-why`/`--discovered-from` | `E_TRIAGE_INCOMPLETE` | names the missing triage field |
| `--scope` value not `out-of-scope` / `in-scope-deferred:HATCH`; unknown `HATCH`; `--priority` not `P0`–`P4` | `E_TRIAGE_INCOMPLETE` | names field + valid vocabulary (the refusal message names the accepted `P0`–`P4` range) |
| `--orphan` without `--escalation-why`; `--anchor` without `--anchor-why` | `E_TRIAGE_INCOMPLETE` | the loud-escalation / placement rationale is mandatory |
| any rationale flag (`--scope-why`, `--priority-why`, `--anchor-why`/`--escalation-why`) blank after strip or containing an embedded newline | `E_TRIAGE_INCOMPLETE` | the rationale-shape rule (§3.2): a required one-line value cannot be empty or multiline; names the offending field; creates nothing |
| duplicate exact title | `E_DUPLICATE_TITLE` | inherited from the `create <noun>` guard; names the collision |
| `--anchor` id does not exist | `E_NOT_FOUND` | inherited from the create path |
| `--scope out-of-scope` with a non-container `--anchor` (declared-state `is_container` false: no epic/milestone type or container shape label) | `E_TRIAGE_INCOMPLETE` | out-of-scope work must anchor under an epic or milestone (canonical discovered-work contract); names the rule; creates nothing. The in-scope-deferred path keeps the soft warning (below) |
| `--discovered-from` id does not exist (deleted/invalid) | `E_NOT_FOUND` | resolved pre-mint (§4 step 2); names `--discovered-from`; creates nothing |
| `required` track mode, underivable track (`--orphan`, or `--anchor` under a track-less parent such as a milestone), no `--track` | `E_TRACK_REQUIRED` | inherited from the track gate (§4 composition); a track-less parent falls through to enforcement exactly like `--orphan` |
| create succeeds, orphan-marker note append fails (`--orphan` path) | `E_BACKEND_DRIFT` / underlying | `detail.created_id` set for marker replay |
| create succeeds, `discovered-from` edge add fails | `E_BACKEND_DRIFT` / underlying | `detail.created_id` set for edge replay |

Non-container anchor handling is **scope-dependent**, keyed on the lifecycle layer's
declared-state `is_container` test (a bead is a container when it carries an
epic/milestone type or a container shape label — the same declared-state test the
create path's placement validation uses; no structural walk of children):

- **`--scope out-of-scope`** — a non-container anchor is a **refusal**
  (`E_TRIAGE_INCOMPLETE` naming the out-of-scope-must-anchor-under-a-container rule),
  never a filing. The canonical discovered-work contract requires out-of-scope work to
  be placed under an epic or milestone; permitting a leaf/task anchor would create the
  close-walk-unsafe child-of-current-work shape.
- **`--scope in-scope-deferred:HATCH`** — a non-container anchor is a **soft warning**
  in `data.warnings`, never a refusal: an in-scope deferral legitimately anchors as a
  sibling under the parent-of-in-flight work item, which may itself be a non-epic.

Only the container-vs-leaf *shape*, gated by scope, is mechanical; whether the chosen
container is the *right* home stays judgment (§5).

## 4. Composition with the create gate and lifecycle

`work discover` is a lifecycle verb (`lifecycle/discover.py`, handler signature
`(Backend, Namespace) -> JsonValue`, registered in `verbs/__init__.py`). Its body:

0. **Gate on the dep-write capability** — because discover *always* mints a typed
   `discovered-from` provenance edge (step 5, a dep **write**), it carries the same
   capability precondition as the `dep` verb and MUST declare it in the
   `REQUIRED_CAPABILITY` registration. When the adapter's `Capabilities` lacks dep-write
   support, discover refuses with `E_UNSUPPORTED_CAPABILITY` **at the registration gate,
   before its handler runs** — ahead of form validation, provenance resolution, and any
   mint — exactly as `dep` does. The gated capability is the dep-write capability
   (`supports_dep_write`; `supports_dep_types` in the shipped code until the
   contract-hardening reshape lands, where dep reads become ungated and only typed dep
   writes are gated). Minting first and failing on the edge would strand a created item on
   a no-dep-write adapter; gating before the handler closes that window and matches `dep`'s
   own pre-handler refusal.
1. **Validate triage form** (mechanical refusals above) — *before* any bd call, mirroring
   `create <noun>`'s pre-mint duplicate guard. Bad form creates nothing.
2. **Resolve the provenance source** — resolve `--discovered-from` against the backend via
   the `show`/get path, *before* any create call. If it names a deleted or non-existent
   bead, refuse with `E_NOT_FOUND` naming `--discovered-from` and create nothing.
   Validating the source here guarantees the step-5 provenance-edge add has a live target,
   so the only edge-add failure that remains (§3.2) is a transient backend fault, never an
   unresolvable input — the create-then-discover-the-edge-is-impossible ordering the seam
   would otherwise permit is closed.
3. **Render the triage block** into the description, exactly the skill's canonical
   markdown. The `--scope` CLI token is parse-time input vocabulary and is **never
   rendered verbatim**: `out-of-scope` renders the first Scope line; `in-scope-deferred:<hatch>`
   maps to `in-scope — deferred: <hatch>` for the second:
   ```
   ## Triage
   - Scope: out-of-scope — <scope-why>
   - Priority: <priority> — <priority-why>
   - Anchor: <anchor-or-"none: escalated"> — <anchor-why-or-escalation-why>
   ```
   For an in-scope deferral the Scope line instead reads
   `Scope: in-scope — deferred: <hatch> — <scope-why>`.
4. **Mint via the shared creation path** — build the `create <noun>` inputs
   (`--noun`, `--title`, composed `--description`, `--priority`, and `--parent <anchor>`
   or `--orphan`) and call the same `create_noun` code. discover adds **no** new minting
   logic: noun→type/shape templating, the duplicate-title guard, placement validation,
   and the track resolution all execute unchanged. For an `--orphan` filing this path also
   writes the orphan marker as a post-create `append_note`; per the §3.2 recovery contract,
   a failure there surfaces `detail.created_id` rather than discarding the mint.
5. **Add the provenance edge** — `dep add <new-id> <discovered-from> --type discovered-from`.
6. **Assemble the envelope** — derive `lands_in`, build `manifest_row`, set
   `remaining_work` (true iff scope is `in-scope-deferred:*`), pass through any create-path
   warnings.

**Track composition is free.** Because discover mints through `create <noun> --parent
<anchor>`, it inherits the track partition's create gate verbatim: parent-track
inheritance stamps the `track:*` label *when the parent has one*; a track-less parent
falls through to enforcement exactly like `--orphan`. Two placement outcomes therefore
leave the track underivable — an `--orphan` filing (no parent), and an `--anchor` under a
track-less parent (the canonical out-of-scope fallback is a milestone, and milestones
carry no `track:*` label by design). For either underivable case: in `advisory` mode the
create succeeds with an envelope warning; in `required` mode it is refused with
`E_TRACK_REQUIRED`. This is the correct coupling — a discovery with no derivable track is
exactly the case that should trip track enforcement — and discover re-implements none of
it. `--track NAME` (§3.1, §3.2) is forwarded **unmodified** to the same `create <noun>`
path, where the track layer's normal resolution and validation apply; it is how a
discovery whose track is underivable — `--orphan`, or `--anchor` under a track-less
parent — satisfies `required` track mode. An `--anchor` under a *tracked* parent inherits
that parent's track, so there `--track` only overrides it.

## 5. What stays prose (the judgment boundary)

The verb enforces that a **complete, well-formed, anchored, provenance-linked triage
record exists**. It never adjudicates whether the recorded values are *true*. These
stay caller judgment, owned by the `triaging-discovered-work` skill:

- **The sibling test / scope classification.** Whether this discovery is truly
  out-of-scope vs in-scope is the core judgment; the verb records the caller's answer
  and enforces its *shape*, it cannot compute it.
- **Whether fix-in-session should have applied.** If the agent chose to file rather than
  fix, the verb files; verify-checklist and the human audit whether that was right.
- **Best-fit anchor.** The verb checks the anchor exists and, via the declared-state
  `is_container` test, refuses a non-container anchor for an out-of-scope filing while
  soft-warning for an in-scope deferral (§3.4); *which* epic is the right home is
  judgment.
- **Priority level.** The verb enforces `P0`–`P4` form and a rationale; whether P1 vs P3 is
  correct is judgment.

The test for "mechanical": could a reviewer decide the refusal from the CLI inputs alone,
without reading the codebase or the roadmap? Missing field, unknown hatch, absent edge,
or a non-container anchor for an out-of-scope filing (`--scope` plus the anchor's
declared `is_container` state) — yes, mechanical. "Is this really out of scope?" or
"is *this* the best-fit epic?" — no, prose.

## 6. Acceptance criteria

1. `work discover` with a missing triage field (`--scope`, `--scope-why`, `--priority`,
   `--priority-why`, or `--discovered-from`) exits non-zero with `E_TRIAGE_INCOMPLETE`
   whose `detail.field` names the missing field, and **creates nothing** (fake records no
   `create` call).
2. `work discover` with neither `--anchor` nor `--orphan` (or both) exits `E_USAGE`.
3. An invalid `--scope` value, an unknown `HATCH`, or a `--priority` not matching `P0`–`P4`
   (regex `^P[0-4]$`) exits `E_TRIAGE_INCOMPLETE` naming the field and the valid vocabulary
   (the refusal message names the accepted `P0`–`P4` range).
4. `--orphan` without `--escalation-why`, or `--anchor` without `--anchor-why`, exits
   `E_TRIAGE_INCOMPLETE`. Likewise a rationale flag (`--scope-why`, `--priority-why`, or
   the applicable placement rationale) whose value is blank after strip (e.g.
   `--scope-why ""` or all-whitespace) or contains an embedded newline exits
   `E_TRIAGE_INCOMPLETE` naming the offending field, and **creates nothing**.
5. A valid `--anchor` invocation creates the bead with **both** edges — parent (via the
   `create --parent` primitive) and `discovered-from` — in one call (fake call log shows a
   `create --parent <anchor>` then a `dep add <new-id> <from> --type discovered-from`).
6. The success envelope's `data.manifest_row` carries all five columns (item, scope,
   lands_in, tracked_item, priority_why); `lands_in` is `parent work item (<anchor>)` for
   in-scope-deferred, `<anchor>` for out-of-scope, and `unanchored — needs your call` for
   `--orphan` — never a caller input.
7. `data.remaining_work` is `true` iff `--scope` is `in-scope-deferred:*`.
8. The rendered `## Triage` block appears in the created bead's description with the
   Scope/Priority/Anchor lines populated from the flags: an `out-of-scope` filing renders
   `Scope: out-of-scope — <scope-why>`, and an `in-scope-deferred:<hatch>` filing renders
   `Scope: in-scope — deferred: <hatch> — <scope-why>` — the raw `in-scope-deferred:<hatch>`
   CLI token never appears in the rendered block.
9. A duplicate exact title exits `E_DUPLICATE_TITLE` (inherited) and creates nothing.
10. A create that succeeds but whose `discovered-from` edge add fails returns an error with
    `detail.created_id` set (edge replayable, no duplicate bead).
11. `--noun spec` or `--noun epic` exits `E_USAGE` (leaf nouns only).
12. Every `work discover` invocation, success or failure, emits one parseable envelope
    carrying `protocol`, with exit code mirroring `ok` (contract invariant).
13. With the track layer active in `required` mode, `--orphan` with no `--track` exits
    `E_TRACK_REQUIRED` (inherited from the create gate), while `--orphan --track NAME`
    succeeds — the forwarded `--track` satisfies the create gate (fake call log shows the
    `--track` value reaching the `create` path); in `advisory` mode `--orphan` with no
    `--track` succeeds with a `data.warnings` entry. The same holds for an `--anchor` under
    a track-less parent (a milestone anchor, the canonical out-of-scope fallback): in
    `required` mode with no `--track` it exits `E_TRACK_REQUIRED`, and
    `--anchor <milestone> --track NAME` succeeds — the anchored filing under a track-less
    parent falls through to enforcement exactly like `--orphan`.
14. A `--discovered-from` naming a deleted or non-existent bead exits `E_NOT_FOUND` whose
    message names `--discovered-from`, and **creates nothing** — the fake call log shows
    the pre-mint source `show`/get and **zero** `create` calls (the provenance source is
    validated before any mint).
15. An `--orphan` create that succeeds but whose **orphan-marker note append** fails
    returns an error with `detail.created_id` set (marker replayable, no duplicate bead) —
    the fake call log shows exactly **one** `create` followed by the failing `append_note`,
    and the caller can re-run the marker step against the returned id.
16. `--scope out-of-scope` with an `--anchor` whose declared state is non-container (no
    epic/milestone type or container shape label) exits `E_TRIAGE_INCOMPLETE` naming the
    out-of-scope-must-anchor-under-a-container rule and **creates nothing** (fake records
    no `create` call); the *same* non-container anchor under
    `--scope in-scope-deferred:HATCH` succeeds with a `data.warnings` entry and no refusal.
17. `work discover` against a fake whose `Capabilities` declares dep-write support false
    (`supports_dep_write=False`; `supports_dep_types=False` in the shipped code) exits
    non-zero with `E_UNSUPPORTED_CAPABILITY` **before** any triage validation or mint — the
    fake call log shows **zero** `create` calls (the registration gate refuses ahead of the
    handler, exactly as the `dep` verb does).

## 7. Protocol impact

Additive: one new verb (`discover`) and one new `ErrorCode` member
(`E_TRIAGE_INCOMPLETE`). No existing envelope or `data` shape changes; a pinned-MAJOR
consumer neither breaks nor needs them. Per the transport spec's versioning rule
(additive ⇒ MINOR), `PROTOCOL_VERSION` bumps MINOR. The concrete version number is
assigned at merge time by landing order — competing MINOR claims (the track-partition
layer, the seam-hardening advertisement bump) are arbitrated by merge order, never at
spec-authoring time; the changes are independent and additive, so any order works.

## Continuations

- feat: implement `work discover` in packages/workcli — `lifecycle/discover.py` handler
  composing `create_noun`, the `discovered-from` edge, triage-block rendering, and
  manifest-row assembly; the `E_TRIAGE_INCOMPLETE` ErrorCode member; `cli.py` subparser
  and `verbs/__init__.py` registration; MINOR protocol bump — AC: acceptance criteria
  1–12 and 14–16 pass under `make ci-workcli` (criterion 13 passes once the track-partition
  create gate has landed — verify in whichever PR lands second); behavioral tests use `run_cli_with_runner` call-log
  assertions against the `ScriptedBdRunner` fake, no live bd.
- chore: retire the prose filing mechanics once the verb ships — repoint the
  `triaging-discovered-work` skill and the `wait-for-pr-comments` filing fallback at
  `work discover` for the mechanical steps, leaving only the judgment steps (sibling
  test, scope call, best-fit anchor) as prose. This is the same call-site work as the
  bd-to-work-facade migration spec’s Class C filing-recipe slice (2026-07-17) — one work
  item, referenced by both specs — AC: a grep across `src/` finds no raw
  `bd create`/`bd dep add` filing recipe for discovered work that the verb now owns; the
  skill names `work discover` as the filing command.
