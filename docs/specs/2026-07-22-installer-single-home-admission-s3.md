# S3 — Installer: Single-Home Deploy, Admission Bar, Surface Budget

**Date:** 2026-07-22
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S3 slice; implements D15 and D16; delivers charter ACs AC1, AC2, AC3 and the S3 reproduction requirement). Also discharges `agents-config-9k9.10` — the "wire the zero-base back into the assembled per-tool file" fix that S4 (#372) explicitly deferred to `packages/installer/`.
**Supersedes where they conflict:** the installer's existing single-home routing, receipts, and prune are *inherited and guarded*, not rewritten. Where it meets **S4 (#372, merged)**: S4 deleted the `INSTRUCTIONS.md` mountain and left the per-tool templates composing persona + user-persona + session-primer + ALL-RULES onto the assembled surface, with the zero-base laws no longer wired in (its own §1.2 flags this gap and hands it to S3). This spec resolves that gap toward the **charter zero-base** (Appendix A) rather than S4's kept-composition — mandated by AC1 (S4's composed surface was ~14 KB for Codex/OpenCode, over the 10 KB cap), by the S0 hand-deploy (zero-base only), and by Scott's standing instruction to quarantine the persona/primer/extension fragments. That reverses S4's keep-composing decision; the reversal is deliberate and flagged (charter wins).

The harness of tomorrow admits nothing to the always-on surface without
justification and terminates every deploy that breaches the bar (D16). This
spec records how the installer (`packages/installer/`) enforces that bar
mechanically, deploys to exactly one home per tool with receipts and
prune-on-install (D15), and reproduces the S0 hand-deploy: the zero-based
user instruction file plus empty `rules/skills/commands/agents`.

All new logic lands in `packages/installer/` as Python; the only `src/`
change is the thin instruction-template redirect (charter Option A, chosen by
Scott 2026-07-22) that points every per-tool instruction template at a single
canonical zero-base fragment. The INSTRUCTIONS.md mountain and the
DYNAMIC-INCLUDE machinery are **not** deleted here — that is S4.

---

## 1. V-audit — what the installer already does (inherited)

Audited 2026-07-22 against `packages/installer/src/installer/`.

| D15/D16 capability | Verdict | Evidence |
| --- | --- | --- |
| **single target per tool** | **already true** | One `Config.home` (`config.py:27`), resolved once (`cli.py:205`); each adapter maps it to exactly one dest via `dest_dir(home)` (`tools/claude.py:22`, `codex.py:19`, `gemini.py:83`, `opencode.py:24`). No dual-home / `home2` / secondary-target concept exists anywhere. `--project` is an *alternate* single target, not a second simultaneous one. → S3 pins this with a regression guard, not new routing. |
| **deploy receipts** | **already true** | `Receipt`/`ReceiptEntry` (`receipt.py:21-55`), written atomically to `home/.config/agents-config/install-receipt.json` (`cli.py:358`, `receipt_store.py:172`) inside the receipt lock. → S3 asserts the admitted set matches the receipt. |
| **prune-on-install** | **already true** | `prune_pipeline` (`run.py:64`) removes recorded entries no longer in the desired set, TOCTOU-guarded, backup-before-delete, drift-relinquish (`prune_hash.py`, `prune_flow.py`). → **this is the lever that empties `rules/skills/commands/agents`**: content the admission gate drops is no longer desired, so prune removes any previously-deployed copy. |
| **surface-budget enforcement (AC1)** | **missing** | No token accounting anywhere. → S3 builds it. |
| **admission record + check (AC3)** | **missing** | No artifact carries an admission record; no schema, no check. → S3 defines both. |
| **conflict audit (AC2)** | **missing** | No cross-artifact claim reconciliation. → S3 builds the pairwise-claims lint. |

The `home2` isolation requirement of D15 ("keeps only its hand-managed
`settings.json`") is satisfied by construction: the installer only ever writes
under `Path.home()` (or an explicit `--project` root). It never enumerates a
second home. S3-A1 guards that invariant against regression.

## 2. Decisions

**S3-D1 — Gated artifact namespaces.** The admission bar applies to
`rules`, `skills`, `commands`, and `agents`. D16 names "rule/skill/command";
`agents` is added here — an agent is an on-invoke capability indistinguishable
from a skill for admission purposes, and S0's hand-deploy emptied `agents/`
too, so reproducing it requires gating agents. Root instruction files
(`AGENTS.md`/`GEMINI.md`), `settings.json`, and plugin-routed/CLI artifacts are
**not** gated by admission record — the instruction file is the surface itself
(governed by the budget gate, S3-D4), and settings/CLI are not always-on prose.

**S3-D2 — Admission record schema.** Every gated artifact carries an
`admission` block in its YAML frontmatter with three required, non-empty
string fields:

```yaml
admission:
  prevents: <the concrete failure this artifact prevents>
  cost: <what carrying it costs — tokens, attention, maintenance>
  remove_when: <the observation that would justify removing it>
```

A record is **complete** iff all three keys are present and non-empty after
whitespace strip. Frontmatter is the home because it is co-located, versioned
with the artifact, and already parsed by the toolchain — lintable, not prose.

**S3-D3 — Admission gate semantics (fail-closed for claimants, skip for
abstainers).** At deploy time, per gated item:

- **No `admission` block at all** → *not admitted*: the item is dropped from
  the plan and reported (`skipped: no admission record`). This is the S0
  mechanism — today's content carries no records, so all of it is skipped and
  prune empties the deployed dirs.
- **`admission` block present but incomplete/malformed** (missing key, empty
  value, non-mapping) → **hard failure**: the deploy aborts. Something claiming
  admission must be complete; a half-authored record is a mechanical defect,
  not a silent skip.
- **Complete record** → *admitted*: the item deploys and its claims (S3-D5)
  join the conflict audit.

By construction this makes AC3 hold: 100% of *deployed* gated artifacts carry
a complete record, because the only alternatives are drop or abort.

**S3-D4 — Surface budget (AC1), fail-closed.** The always-on surface for a
tool = the deployed instruction-file bytes **plus** the bytes of every
admitted loose rule for that tool (rules are always-on). Token count uses the
**bytes/4 approximation** (documented choice; no tokenizer dependency added).
Margin is ample: the zero-base is ~1670 bytes ≈ 418 tokens against the 10k
cap. Two caps, each a hard failure that aborts before any write:

- **Always-on ≤ 10 000 tokens** per tool.
- **Each admitted skill body ≤ 2 000 tokens** — the SKILL.md content after its
  frontmatter (the on-invoke payload). A skill needing more must delegate to
  code (D16).

The approximation is a deliberate under-count risk accepted because the cap
carries >20× margin at the zero-base and the erosion tripwire (D19) watches the
trend; swapping in `tiktoken` is a later refinement, not a blocker.

**S3-D5 — Conflict audit (AC2) as a pairwise-claims lint.** An artifact may
declare a `claims` mapping in frontmatter: `<claim-key>: <value>`, where a
claim-key names a fact about the live workflow (e.g.
`pr-review-medium: verdict-artifact`). The audit groups every admitted
artifact's claims by key; if any key carries ≥2 *distinct* values across
artifacts, that pair is a conflict and the deploy aborts, naming the two
artifacts, the key, and the two values. With zero admitted claimants the audit
is vacuously green. This is the deliberately simple first implementation the
charter sanctioned; richer semantic conflict detection (NLI over prose) is
future work, not S3.

**S3-D6 — Instruction-template redirect (Option A).** The canonical zero-base
(charter Appendix A) lives in one new fragment,
`src/user/.agents/USER-CORE.md.template`. Each per-tool instruction template
(`.claude/AGENTS.md.template`, `.codex/AGENTS.md.template`,
`.gemini/GEMINI.md.template`, `.opencode/AGENTS.md.template`) is reduced to a
single `<!-- DYNAMIC-INCLUDE: src/user/.agents/USER-CORE.md.template -->`. The
fragment basename (`USER-CORE.md`) deliberately differs from the instruction
dest (`AGENTS.md`/`GEMINI.md`) to avoid the Phase-6.75 standalone-removal
collision (`templates.py:168`) — this *is* the "rename the survivor's install
destination" fix S4's §1.2 named as one of the two ways to close its gap.
`USER-CORE.md.template` is the single canonical home of the zero-base; S4's
surviving `src/user/.agents/AGENTS.md.template` (identical content, but its
`AGENTS.md` basename both collides and produces a stray Gemini `AGENTS.md`
beside `GEMINI.md`) is dropped in its favour.

The ALL-RULES marker and the persona/user-persona/session-primer/extension
includes are dropped from the redirected templates: the assembled always-on
surface is the zero-base **only** (reproduces S0; passes AC1 with >20x margin).
The orphaned fragments those includes used to pull —
`AGENT-PERSONA.md.template`, `USER-PERSONA.md.template`,
`SESSION-PRIMER.md.template`, the four `*-EXTENSIONS.md.template`, plus the
S4-deleted `INSTRUCTIONS.md.template` recovered from history — are
**quarantined under `archive/src/user/...`** (not deleted), preserved as
reference material for harness evals once the harness is rebuilt. Because
`stage_templates` globs `src/user/<tool>/*.md.template` unconditionally (it
never consults `.installignore`) and `.installignore` is basename-only (so it
cannot exclude the shared `AGENTS.md.template` without also killing the per-tool
one), relocating out of the staged roots is the only mechanism that stops these
fragments deploying as strays. Persona and user-persona are injected
dynamically at session start by the companion tooling, so removing their static
copies loses nothing live; session-primer's skill-usage discipline and the
workflow rules re-enter through the admission bar in later slices if they earn a
record. The DYNAMIC-INCLUDE **engine** (`templates.py`) is left intact — its
teardown/reassessment remains future work (charter D17 "reassess once content
shrinks").

**S3-D7 — The gate runs on the user-home deploy.** The admission/budget/
conflict gate wires into `cli._run` (the `Path.home()` deploy) after the plan
is finalized and before the write block. The `--project` deploy (`_run_project`)
is **not** gated in S3 — the always-on surface budget is a user-home concept,
and project-scoped installs are a separate surface. Gating project deploys is a
noted follow-up, not an S3 AC.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible against a temp-dir fake home / fixture source
tree. Edge-case taxonomy (inverse, boundary, dependency failure, repeated
invocation, idempotency) applied per slice.

### Slice A — single-home guard + reproduction harness (D15, D7)

- **S3-A1** For a run over all four tools against fake `home`, the resolved
  dest set is exactly one dir per tool, each equal to `adapter.dest_dir(home)`;
  no dest lies outside `home` (inverse: a second home is never enumerated).
- **S3-A2** The receipt written after a user-home install lists exactly the
  admitted artifacts (plus root instruction files and settings) and no dropped
  artifact (idempotency: a second identical run writes an integrity-equal
  receipt).
- **S3-A3** A `--dry-run` over the finalized, admission-filtered plan writes
  nothing to disk and to the receipt path (dependency failure: a read-only
  home still produces the full preview).

### Slice B — admission record schema + gate (D16, AC3)

- **S3-B1** A gated item whose source frontmatter has **no** `admission` block
  is dropped from the deploy and reported as skipped; it is absent from the
  receipt and from disk (this is the S0 mechanism).
- **S3-B2** A gated item with a **complete** `admission` block deploys and
  appears in the receipt.
- **S3-B3** A gated item with an **incomplete/malformed** `admission` block
  (missing `remove_when`, empty `cost`, or a non-mapping `admission`) aborts
  the deploy with `return 1`; **no file is written** (the whole-install abort,
  not a partial deploy) and the error names the offending file and missing
  field.
- **S3-B4** All four gated namespaces (`rules`, `skills`, `commands`,
  `agents`) are subject to B1–B3 (boundary: an item in a non-gated location —
  e.g. the root `AGENTS.md` — is never dropped for lacking a record).
- **S3-B5** Repeated invocation is stable: running twice with the same source
  drops the same items and admits the same items (no order-dependence in the
  partition).

### Slice C — surface budget gate (D16, AC1)

- **S3-C1** A tool whose always-on surface (instruction file + admitted loose
  rules) exceeds 10 000 tokens (bytes/4) aborts the deploy with `return 1`
  before any write; the error reports the tool, the measured token count, and
  the cap.
- **S3-C2** The zero-base surface (~418 tokens) passes (inverse of C1); a
  surface exactly at the 10 000-token boundary passes and one token over fails
  (boundary).
- **S3-C3** An admitted skill whose post-frontmatter body exceeds 2 000 tokens
  aborts the deploy, naming the skill; a skill at/below the cap passes.
- **S3-C4** The budget is computed only over **admitted** content — a dropped
  (no-record) 50k-token skill never counts toward any cap (dependency between
  B and C: the admission filter precedes the budget measurement).

### Slice D — conflict audit (D16, AC2)

- **S3-D1** Two admitted artifacts declaring the same `claims` key with
  distinct values abort the deploy, naming both files, the key, and both
  values.
- **S3-D2** Two admitted artifacts declaring the same key with the **same**
  value do not conflict (inverse); an artifact with no `claims` block
  contributes nothing (empty/boundary).
- **S3-D3** With zero admitted claimants the audit is green (vacuous case —
  the S0 state).
- **S3-D4** A dropped (no-record) artifact's claims never enter the audit
  (dependency: only admitted claims are reconciled).

### Slice E — instruction redirect + S0 reproduction (D15, D16, D6)

- **S3-E1** After the redirect, flattening each per-tool instruction template
  yields exactly the zero-base text (byte-equal to `USER-CORE.md.template`) —
  for `.claude`/`.codex`/`.opencode` `AGENTS.md` and `.gemini` `GEMINI.md`.
- **S3-E2** A full install of the real `src/` tree into a fake home reproduces
  the S0 hand-deploy: the tool's instruction file equals the zero-base, its
  `CLAUDE.md` (Claude) is the pointer stub, and `rules/`, `skills/`,
  `commands/`, `agents/` contain zero deployed files.
- **S3-E3** Reproduction is prune-driven: seeding the receipt + disk with a
  pre-S0 populated home (loose rules, skills) and re-running the installer
  removes them (they are no longer admitted) — the empty end-state is reached
  from a populated start, not only from an empty one.
- **S3-E4** No stray instruction file is produced (boundary: `.gemini` gets
  `GEMINI.md` and **not** a second `AGENTS.md` from the retired shared
  template).

## 4. Out of scope

Tearing down / reassessing the DYNAMIC-INCLUDE **engine** itself (charter D17,
future — the engine is left intact, only the mountain *content* it composed is
gone); gating the `--project` deploy surface (follow-up); authoring admission
records for the harness keepers that re-enter in later slices (S5/S6/S8 author
their own); swapping bytes/4 for `tiktoken` (later refinement); semantic (NLI)
conflict detection beyond the pairwise-claims lint (future); the broader prose
sweep of the persona/extension descriptions still living in the per-tool
`README.md`/`AGENTS.md` meta-docs, root `README.md`, and `docs/guide` — S4
swept the `INSTRUCTIONS.md` references but those files still describe persona +
session-primer + rules as composed into the always-on surface, which the
zero-base-only surface no longer does (tracked as a documentation follow-up,
not an S3 AC; the dangling references to files this slice moved/removed are
fixed here).
