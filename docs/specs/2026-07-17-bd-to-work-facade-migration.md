# Discipline-layer migration from raw bd to the work facade

**Date:** 2026-07-17
**Bead:** agents-config-wgclw.9.4 (promoted to EPIC by this spec)
**Status:** Draft — pending review
**Blocked by:** installer CLI-deploy (`docs/specs/2026-07-15-installer-cli-deploy-design.md`, bead agents-config-wgclw.9.9) — assets may call `work` only once the installer puts it on PATH as a deployment invariant.

## 1. Context / Problem

Discipline-layer assets under `src/**` shell out to `bd` directly, each re-implementing
the same quirk shims (`--json` shape drift, 50/100-row truncation, dolt sync ceremony,
one-label-per-`label remove`, `--append-notes` vs clobber). The work facade
(`packages/workcli`) exists precisely to quarantine bd behind one tested JSON-envelope
contract, but no installed asset consumes it yet. This epic migrates every asset that
*invokes* bd onto the facade, so assets depend on the stable contract, not the bd
implementation — landing the M0 charter's "beads is quarantined behind our own CLI"
all the way to the asset surface.

Facade verb surface migrated against — transport (`docs/specs/2026-07-04-work-facade-cli-contract.md` §3):
`show`, `create --raw`, `update`, `note`, `close`, `reopen`, `list`, `ready`, `dep`, `label`,
`search`, `sync`; lifecycle (`docs/plans/2026-07-12-workcli-lifecycle-layer.md`): `create <noun>`,
`claim`, `release`, `deliver`, `plan`, `promote`, `reconcile`. A bd usage maps only if one of
these covers it.

## 2. Decision summary (owner-ratified)

These four decisions were ratified by the repo owner in an interactive brainstorming
session before this spec was drafted; they bind the implementing agent and are not for
that agent to reopen. Review comments on them during this PR are still welcome.

1. **Classification is exhaustive.** Every bd reference in `src/**` (and the primer
   knowledge base) is classified exactly one of **route-through-facade** (a shipped/
   spec'd verb covers it — migrate), **stays-bd-specific** (teaches or depends on a bd
   implementation detail with no facade verb — keep), or **facade-gap** (mappable in
   principle but no verb exists yet — file the verb, annotate the site). The mapping
   table (§3) is the central design artifact.
2. **Work structure.** This bead is an EPIC with per-asset-class children (§5). Each
   child is a reviewable PR-sized slice; asset classes with zero facade-gaps ship
   independently while gap-blocked classes wait on their verb.
3. **Facade-gap policy.** Migrate everything mappable **now**. Each gap gets a filed
   workcli-verb work item; the call site keeps an annotated raw bd call until the verb
   ships. The annotation names the missing *capability* — `# facade-gap: no work verb
   for typed provenance dep edges yet` — **never a bead ID** (repo rule: no tracker IDs
   in source assets).
4. **Teaching docs stay bd-specific.** Assets that intentionally teach bd implementation
   gotchas (the `beads.md` gotchas rule, `bd dolt push` session-close, `--json` jq
   shapes, the formulas primer) are **stays-bd-specific** until the facade covers the
   concept — the rationale is recorded in the mapping table, not necessarily in the asset.

## 3. Mapping table (central artifact)

Classification is per **file** by dominant usage. `RTF` = route-through-facade,
`BDS` = stays-bd-specific, `GAP` = facade-gap (partial).

| asset (path) | bd usages (summarized) | class | target work verb(s) / gap | asset-class |
|---|---|---|---|---|
| `src/user/.agents/skills/whats-next/collect.py` | `ready --json --limit 0`, `list --status open,in_progress --limit 0`, `list --label`, `list --parent`, three `list --type {milestone,epic,feature} --ready` (planning queue), `show <id> --json`; parses `id/parent/labels/notes/started_at/assignee` | RTF (+verify G2; gaps G3,G4) | `work ready`, `work list [--status --label --parent]`, `work show`; planning-queue typed+ready query needs G4; envelope replaces jq/`--limit 0` | A |
| `src/user/.agents/skills/whats-next/collect_test.sh` | 12 `bd` shims fixture the CLI seam | RTF | re-point shims to `work`; assert envelope shape | A |
| `src/user/.agents/skills/whats-next/SKILL.md` | prose `bd ready --label`, `bd show <id>`; run-queue calls `bd ready --label implementation-ready` | RTF | `work ready --label`, `work show` | A |
| `src/user/.agents/skills/where-does-this-fit/SKILL.md` | `show <id> --json`, `show <parent> --json`, `list --parent` | RTF | `work show`, `work list --parent` | A |
| `src/user/.agents/skills/merge-guard/SKILL.md` | `label list <id> --json \| jq join` | RTF | `work label list` (envelope `string[]`, no jq) | B |
| `src/user/.agents/skills/wait-for-pr-comments/SKILL.md` | `label add <id> human`, `update --append-notes`, `label list --json`; `.beads/worker-audit/` path | RTF (path=BDS) | `work label add`, `work note`, `work label list`; `.beads/` audit path stays bd infra | B |
| `src/user/.agents/skills/reply-and-resolve-pr-threads/SKILL.md` | `label add <id> human` + `update --append-notes`; "no bd jargon in replies" policy | RTF (policy=BDS) | `work label add`, `work note`; PR-hygiene policy unaffected (output rule, not a call) | B |
| `src/user/.agents/skills/triaging-discovered-work/SKILL.md` | `create --parent`, `dep add --type discovered-from`, `reopen`, `create` | RTF | the filing recipe targets **`work discover`** (the composed verb — see the 2026-07-17 work-discover-verb spec), NOT raw `work create` + `work dep add`, which would reinstate the unanchored-filing leak the verb closes; `work reopen` and reads migrate directly (typed dep edges verified shipped end-to-end if ever needed raw) | C |
| `src/user/.claude/skills/fablize/SKILL.md` | reads sibling closed-bead `notes`/close text; "spec out beads" trigger vocab | RTF | `work list --parent <id>` (open children) **and** `work list --parent <id> --status closed` (close-note supersession evidence — bd/facade default omits closed items), each read via `work show`; trigger vocabulary unchanged | C |
| `src/user/.claude/skills/orchestrating-subagents/SKILL.md` | prose "verify git/gh/bd first" | RTF (light) | swap bd→`work show` in the verify-state noun | C |
| `src/user/.agents/skills/simplify/SKILL.md` | "Do NOT use `bd remember`" steer-away note | BDS | no call site; names a bd anti-usage — keep | D |
| `src/user/.claude/skills/handoff/SKILL.md` | "don't duplicate beads content" | BDS | no call; teaching — keep | D |
| `src/user/.agents/skills/optimize-my-agent/SKILL.md` + `references/AGENTS_PRIMER.md` | lint heuristic "bead refs in shared agents → plugin namespace" | BDS | meta-lint about the repo convention; no call — keep | D |
| `src/user/.agents/skills/optimize-my-skill/SKILL.md` + `references/SKILLS_PRIMER.md` | same lint heuristic for skills | BDS | keep (meta) | D |
| `src/plugins/beads/.agents/rules/beads.md` | bd truncation, dolt sync, label-remove sig, claim lease | BDS | facade *absorbs* these quirks for facade consumers, but the rule teaches raw bd — keep; note "moot for `work` callers" | D |
| `src/plugins/beads/.agents/rules-readmes/beads-readme.md` | dolt commit/push, label remove, dep list examples | BDS | bd reference doc — keep | D |
| `src/plugins/AGENTS.md` | describes beads plugin routing `~/.beads/` | BDS | installer/plugin infra, not agent bd usage — keep | D |
| `src/user/.agents/INSTRUCTIONS.md.template` | "Database safety: Dolt/SQLite WAL, worktree DB ops" | BDS | Dolt-storage safety; `work sync` absorbs sync ceremony, not raw-DB-copy safety — keep | D |
| `src/kits/beads/.beads/PRIME.md` | full bd cheatsheet, `--json` shapes, formulas | BDS | the bd project-onboarding doc — keep; may gain a `work` section later | E |
| `src/user/.agents/agents/tech-lead.md` | prose "beads pipeline / `implement-feature` formula" | BDS | formula/pipeline concept, no call; flag for the separate "bd-refs-in-shared-agents" cleanup | E |
| `docs/primers/FORMULAS_PRIMER.md` | `bd mol pour`/`cook`, close-walk scripts, `ready --json` | BDS | formulas are a bd-native subsystem, deliberately outside the v1 verb set — keep | E |
| `docs/primers/{AGENTS,SKILLS,COMMANDS}_PRIMER.md` | "bead refs in shared X → plugin" lint rows | BDS | meta-teaching; reference docs, not invokers — keep | E |
| `docs/primers/RULES_PRIMER.md` | incidental path to a beads plugin rule | n/a | not a bd call — no action | E |

## 4. Facade-gap register

Deduplicated missing capabilities. Each needs a filed workcli-verb work item before its
dependent asset-class child can fully close.

- **G1 — typed dep edges: VERIFIED COVERED, not a gap.** `work dep add --type <type>`
  ships end-to-end today: the `dep` subparser carries `--type`, the handler runs the
  type-wall pre-check before any mutation, and the adapter forwards `dep_type` to
  `bd dep add --type`. Class C migrates fully; no verb work owed.
- **G2 — multi-value `--status` filter: VERIFIED COVERED.** The adapter forwards
  `filters.status` verbatim to `bd list --status`, which accepts the comma list
  (`open,in_progress`) `collect.py` uses today. Pin a contract test in the Class A
  child rather than filing a verb.
- **G3 — in-flight audit envelope fields (`started` AND `assignee`): CONFIRMED REAL
  GAP.** The `Item` model carries `created`/`updated` but neither a claim/started
  timestamp nor an assignee; `collect.py`'s in-flight section reads bd's `started_at`
  (for claim age) **and** bd's `assignee` (emitted per in-flight item). Both are absent
  from `Item` and its serialized envelope, so a naive migration would render every
  assigned in-flight item as unassigned and lose claim age. Resolution: two additive
  `Item` fields sourced from bd — `started` (from `started_at`, `None` when unset) and
  `assignee` (from bd's `assignee`, `None`/empty when unset) — one MINOR protocol bump.
  Filed as a single continuation. Additionally, the Class A migration must confirm the
  normalized `type`/`created` fields remap correctly onto `collect.py`'s consumers (bd's
  raw `created_at`/type strings are renamed on the `Item` boundary), so the in-flight
  and ready sections read the envelope's normalized names, not the raw bd keys.
- **G4 — readiness-filtered typed list: CONFIRMED REAL GAP.** `collect.py`'s planning
  queue issues three `bd list --type {milestone,epic,feature} --ready` queries, but the
  facade exposes `--type` only on `work list` (no `--ready`) and `--label` only on `work
  ready` (no `--type`) — neither verb can express "ready items of this type," so a direct
  replacement would leak dependency-blocked containers into the planning queue. Resolution:
  add a `--ready` flag to `work list` (it already carries `--type`), mirroring bd's own
  `list --ready` — one additive flag, no new verb. Filed alongside G3.

G3 and G4 are the real gaps — a pair of additive envelope fields (G3) and one additive
`work list --ready` flag (G4), neither a new verb.
Formulas (`bd mol`/`cook`) are a **deliberate v1 exclusion**, not a gap — FORMULAS_PRIMER
stays bd-specific by decision, no verb is owed.

## 5. Migration partition (child slices)

| slice | asset-class | files | gap-blocked? | ships |
|---|---|---|---|---|
| **A — programmatic skills** | A | whats-next (collect.py + collect_test.sh + SKILL.md), where-does-this-fit | G3 (item `started` + `assignee` fields) for the in-flight audit, G4 (`work list --ready`) for the planning queue | first — heaviest value, exercises the full envelope |
| **B — PR-workflow skills** | B | merge-guard, wait-for-pr-comments, reply-and-resolve-pr-threads | no | after A |
| **C — triage/create skills** | C | triaging-discovered-work, fablize, orchestrating-subagents | no verb gap; filing recipe sequenced after `work discover` lands | after B and after the discover verb |
| **D — rules + templates + plugin/optimizer docs** | D | beads.md, beads-readme.md, plugins/AGENTS.md, INSTRUCTIONS.md.template, simplify, handoff, optimize-my-{agent,skill} | no (audit-only) | anytime, parallel — annotate stays-bd-specific rationale; no code migration |
| **E — agents + primers** | E | tech-lead, kits PRIME.md, primers | no (audit-only) | anytime, parallel |

Ordering: A → B → C, with D/E and the G3/G4 facade additions runnable in parallel (G3 must
land before Class A's in-flight audit migrates and G4 before its planning-queue migrates;
the rest of Class A does not wait). All
slices sit behind installer 9.9. Class C's triaging-discovered-work *filing recipe*
additionally waits on `work discover` (spec ships alongside this one); if the verb has
not landed when Class C runs, the slice defers that file — it never migrates the filing
path to raw create+dep-add. D and E are audit-and-annotate passes (confirm each file is genuinely
stays-bd-specific and record the mapping-table rationale) — no behavioral change, so they
are low-risk and can land early to shrink the epic.

## 6. Rollout & compatibility

- **Sequencing.** No migrated asset merges before installer 9.9 deploys `work` to PATH.
  9.9 makes PATH-reachability a *deployment invariant* (its §6), so steady state has
  `work` present; the guards below cover partial/broken installs only.
- **`work` absent from PATH → fail loud.** A migrated asset that cannot find `work` must
  emit a not-configured error and stop — **never silently fall back to `bd`** (that would
  re-introduce the drift the facade removes). Prose skills: a one-line guard ("if `work`
  is not on PATH, stop and tell the operator to run the installer — do not use raw `bd`").
  `collect.py`: on `FileNotFoundError` for `work`, exit non-zero with a
  `work-not-installed` error naming the installer. That error deliberately does NOT echo a
  real `ErrorCode` member — it fires in the calling script before `work` is ever invoked.
  This replaces `collect.py`'s current behavior, which silently swallows `bd` absence into
  an empty list.
- **Envelope parsing.** Migrated call sites parse the JSON envelope (`{ok, data, error}`)
  and branch on `ok`/`error.code`, replacing every `--json | jq` idiom and every
  `--limit 0` truncation workaround (facade verbs are unbounded by default).
- **bd remains for humans.** Raw `bd` stays available for direct human use and for the
  stays-bd-specific teaching docs; the migration removes bd from *asset call paths* only.

## 7. Acceptance criteria (mechanically checkable)

1. `grep -rn 'bd ' <Class A/B/C asset paths>` returns only lines carrying a `facade-gap:`
   annotation (with G1/G2 verified covered, the expected count is zero; the policy
   remains for any gap a migration child uncovers).
2. Every migrated call site invokes `work <verb>` and parses the `{ok,data,error}`
   envelope — no residual `--json | jq` or `--limit 0` in Class A/B/C.
3. Every retained raw-bd call in a migrated class has a `facade-gap: <capability>`
   comment that names no bead ID and no tracker ID.
4. `collect.py` invokes `work`; `collect_test.sh` shims `work`; `make`/test run green.
5. Every migrated asset has a `work`-absent guard that fails loud (no silent bd fallback);
   grep confirms no `bd` fallback branch in Class A/B/C.
6. A filed workcli work item exists for G3 (the additive `started` **and** `assignee`
   envelope fields) **and** for G4 (the additive `work list --ready` flag) before the
   Class A child closes; the epic does not close with an unfiled gap. The Class A child's
   in-flight audit preserves both fields (no assigned item renders as unassigned) and
   confirms the normalized `type`/`created` remapping, and its planning queue gates typed
   queries on readiness (no dependency-blocked container leaks in).
7. Class D/E files are unchanged except optional mapping-rationale annotations; each is
   confirmed stays-bd-specific in the child's review notes.
8. The migrated fablize recipe issues **both** the open-children query (`work list
   --parent <id>`) **and** an explicit closed-sibling query (`work list --parent <id>
   --status closed`) before candidate selection — the facade's default `list` omits
   closed items, so without the explicit `--status closed` pass the survey loses the
   close-note supersession evidence the skill requires and can select stale candidates.

## Continuations

- feat: migrate Class A programmatic skills (whats-next collect.py/collect_test.sh/SKILL.md, where-does-this-fit) onto `work` — AC: §7.1,2,4,5 pass for Class A; collect tests green against `work` shims.
- feat: migrate Class B PR-workflow skills (merge-guard, wait-for-pr-comments, reply-and-resolve-pr-threads) onto `work label`/`work note` — AC: §7.1,2,5 pass for Class B; PR-hygiene policy text intact.
- feat: migrate Class C triage/create skills — triaging-discovered-work’s filing recipe onto `work discover` (sequenced after the verb lands; same call-site work as the discover spec’s retire-prose continuation — one work item), its reads plus fablize and orchestrating-subagents onto the read/lifecycle verbs — AC: §7.1,2,5 pass for Class C; no raw bd remains.
- chore: audit-and-annotate Class D rules + templates + optimizer docs as stays-bd-specific — AC: §7.7; mapping rationale recorded, no behavioral change.
- chore: audit-and-annotate Class E agents + primers as stays-bd-specific; flag tech-lead for the bd-refs-in-shared-agents cleanup — AC: §7.7.
- feat: workcli additive `started` + `assignee` item-envelope fields (G3) plus a `--ready` flag on `work list` (G4), sourced from bd `started_at`/`assignee` and bd's `list --ready`, one MINOR protocol bump — AC: `work show`/`work list` items carry `started` and `assignee` (`null` when unset) and `work list --type <t> --ready` returns only dep-unblocked items; contract test pins the G2 multi-status passthrough in the same PR; unblocks Class A's in-flight audit and planning queue.
