# S5 — Spec Contract: grilling + to-spec Admissions, Spec Lint, Brainstorming Teardown

**Date:** 2026-07-24
**Status:** Child spec of `docs/specs/2026-07-21-harness-rework-way-forward.md` (S5 slice; implements D1/D2/D18, discharges AC4 and the `writing-plans` clause of AC5)
**Tracker:** `agents-config-9k9.15`

The readiness gate needs an authoring path that cannot emit a goals-only
spec. S5 installs that path: admit the two grilling skills and `to-spec`
under the D18 per-item bar with grafts that make the D1/D2 output contract
their exit criterion, add the AC4 mechanical spec lint, and delete
`brainstorming` and `writing-plans` — the goals-only escape dies with them.

---

## 1. Inventory (audited 2026-07-24)

| Artifact | State | Facts |
| --- | --- | --- |
| `grill-with-docs` | deployed, `src/user/.agents/skills/grill-with-docs/` | 3 files, 225 lines (~1.3k tokens). Content-identical to upstream `mattpocock/skills @ e74f0061` except the provenance header and a brainstorming cross-ref note (SKILL.md:26–29). Drift policy `accept-periodic-resync`. No admission record. |
| `grill-me` | upstream only, `oss-snapshots/pocock/grill-me/` | 10-line flat interview loop; the verbatim ancestor of grill-with-docs' `<what-to-do>` block. No output contract. Never promoted to `src/`. |
| `to-spec` | vendored only, `oss-snapshots/pocock/skills/skills/engineering/to-spec/` | Synthesis-not-interview; `disable-model-invocation: true`. Its embedded spec template has **no Acceptance Criteria section and no slice pattern** — Pocock's own template would fail AC4. The D18 graft is load-bearing, not cosmetic. Absent from `src/`. |
| `brainstorming` | deployed | 8 files, 1,484 lines (~9–10k tokens, dominated by the browser-companion server) — over the 2k skill-body cap by itself. Hard-chains into writing-plans at SKILL.md:40, :91, :225–228. Nine referencing files outside its folder. |
| `writing-plans` | deployed | 245 lines. Exactly one external reference: its provenance-registry row (`skills/AGENTS.md:61`). |
| Admission machinery | `packages/installer/src/installer/core/admission.py`, `surface_budget.py` | `admission:` frontmatter with `prevents`/`cost`/`remove_when`; three-valued classify (no-record → dropped, malformed → abort, complete → admitted). Caps: 10k always-on, 2k per skill body. **Zero deployed artifacts carry a record today.** |
| Spec lint | nowhere | No Makefile/CI step touches `docs/specs/**`. `work lint` is a tracker-invariant sweep (advisory, work items), not a doc linter — wrong home. |

Blast radius (grep-verified): `rules/delegation.md:5` (routes Planning →
brainstorming), `skills/AGENTS.md:57,61` (registry rows),
`grill-with-docs/SKILL.md:26` (cross-ref note), `handoff/SKILL.md:51`
(example skill list), `whats-next/SKILL.md:219` (a `brainstorm` bead-queue
label), plus generic-word prose mentions in `SKILLS_PRIMER.md:14`,
`writing-unit-tests/SKILL.md:6`, `where-does-this-fit/SKILL.md:11`,
`fablize/SKILL.md:112`.

## 2. Decisions

**S5-D1 — Two grill skills, two seats.** `grill-me` is admitted (promoted
from `oss-snapshots/pocock/grill-me/` to `src/user/.agents/skills/grill-me/`)
as the lightweight interview core — the brainstorming replacement's front
half. `grill-with-docs` is regularized in place as the standalone deep
session for stress-testing an existing plan against `CONTEXT.md`/ADR docs.
Each carries its own admission record; neither is grandfathered.

**S5-D2 — The graft is an exit criterion, not a process rewrite.** Both
grill variants gain a terminal **exit-criterion section**: the session does
not end until the plan's acceptance criteria are enumerated with IDs, each
red-test-convertible, with the D1 edge-case taxonomy (inverse,
empty/boundary, dependency failure, repeated/concurrent invocation,
idempotency) applied per AC. The graft is additive and small; bodies stay
under the 2k cap.

**S5-D3 — `to-spec` is adapted, not copied.** Imported to
`src/user/.agents/skills/to-spec/` with its output contract replaced: the
embedded template gains an **Acceptance Criteria** section (IDs,
red-test-convertible, taxonomy applied) and an **ordered slice list** with
per-slice AC citations and the D2 size tripwire (spec > 400 lines or > 8
slices splits). The upstream "publish to tracker with `ready-for-agent`
label" step is dropped — output lands as a dated file in the project's spec
home; tracker publication is `to-tickets`' seat (admitted separately per
D18). `disable-model-invocation: true` is retained (user-invoked).

**S5-D4 — Drift policy flips to local-fork at graft time.** All three
skills keep their provenance headers but change `Drift policy:` to
`local-fork` — the graft is deliberate divergence; a periodic resync would
erase the contract.

**S5-D5 — The spec lint lives with the other structural-AC enforcement.**
`packages/installer` already enforces AC1 (`surface_budget.py`) and AC3
(`admission.py`); AC4 lands beside them as `core/spec_lint.py` with a CLI
entry, a `make spec-lint` target, and a step in the CI gate. Scope: files
matching `docs/specs/YYYY-MM-DD-*.md` with date ≥ **2026-07-24** (legacy
specs are exempt by date, no allowlist file; this spec itself is inside the
gate — self-hosting). Mechanical checks only: (1) an `Acceptance criteria`
heading exists (case-insensitive); (2) at least one AC ID matching
`[A-Z0-9]+-[A-Z]\d+|AC\d+` is defined under it; (3) if slice headings exist
(`Slice` in a heading), every slice section cites ≥ 1 AC ID. Prose quality
stays advisory review; the lint never judges content.

**S5-D6 — brainstorming and writing-plans die unreformed; the blast radius
is re-pointed, never annotated.** Both skill folders and their registry rows
are deleted. Re-pointing: `delegation.md` routes planning to the
grill → to-spec path; `handoff`'s example skill list swaps `brainstorming`
for `grill-me`; `whats-next`'s `brainstorm` queue routing re-points at the
grill/to-spec path; the cross-ref note inside `grill-with-docs` is deleted.
Generic-word prose mentions ("brainstorming" as an activity, not the skill)
in `SKILLS_PRIMER.md`, `writing-unit-tests`, `where-does-this-fit`, and
`fablize` are left alone — they reference the activity, which survives.

**S5-D7 — The three admitted skills are the first artifacts to carry real
admission records.** Frontmatter `admission:` blocks conforming to
`admission.py`'s schema (`prevents`/`cost`/`remove_when`). No sweep of other
deployed content happens here — AC3 closure over the rest of the catalog is
separate work.

## 3. Slices and acceptance criteria

Each AC is red-test-convertible; IDs are cited by tests and by the
implementing PRs. Ordering: A before C (C's re-pointing needs the grill and
to-spec targets to exist); B is independent and may run in parallel.

### Slice A — Admissions and grafts

- **S5-A1** `src/user/.agents/skills/grill-me/SKILL.md` exists with a
  provenance header (`Drift policy: local-fork`), a complete `admission:`
  block (`admission.classify()` → `COMPLETE`), and an exit-criterion
  section requiring enumerated AC IDs with the edge-case taxonomy applied.
- **S5-A2** `grill-with-docs/SKILL.md` carries the same triple (admission
  block, local-fork policy, exit-criterion graft) and the brainstorming
  cross-ref note is gone.
- **S5-A3** `src/user/.agents/skills/to-spec/SKILL.md` exists with the
  admission block; its embedded template contains an Acceptance Criteria
  section and an ordered slice list with per-slice AC citations and the
  size tripwire; no tracker-publish step remains.
- **S5-A4** All three skill bodies pass
  `surface_budget.skill_body_violations` (≤ 2k tokens each — boundary).
- **S5-A5** The provenance registry (`skills/AGENTS.md`) rows for the three
  skills show `local-fork`; running the registry table against `src/`
  finds no row pointing at a nonexistent skill (dependency failure guard).

### Slice B — Spec lint (AC4)

- **S5-B1** A spec dated ≥ 2026-07-24 with no Acceptance-criteria heading
  fails the lint (nonzero exit, message names the file).
- **S5-B2** A spec with the heading but zero AC IDs under it fails
  (inverse of "heading is enough").
- **S5-B3** A spec with slice headings where any slice cites no AC ID
  fails naming the slice; the same spec with every slice citing ≥ 1 AC
  passes (inverse pair).
- **S5-B4** The lint over the current `docs/specs/` tree exits 0 (legacy
  specs date-exempt; this spec passes on content), and a second run
  returns the identical result (idempotency).
- **S5-B5** A missing or empty `docs/specs/` directory exits 0 with a
  clean report, not a crash (dependency failure / empty input).
- **S5-B6** `make spec-lint` exists, is included in the CI gate, and a
  deliberately malformed fixture spec under the test tree (never
  `docs/specs/`) is proven red by the unit tests.

### Slice C — Teardown (partial AC5)

- **S5-C1** `src/user/.agents/skills/brainstorming/` and
  `src/user/.agents/skills/writing-plans/` are absent from `src/`.
- **S5-C2** `grep -rn "writing-plans" src/` returns zero hits;
  `grep -rn "brainstorming" src/` returns hits only in the four
  generic-word files named in S5-D6, and none of them backtick-quotes the
  skill name or references its path.
- **S5-C3** `delegation.md` routes planning to the grill/to-spec path;
  `handoff`'s suggested-skills example names `grill-me`; `whats-next`'s
  `brainstorm` queue routing points at the grill/to-spec path (verified at
  implementation time against its actual routing semantics).
- **S5-C4** The registry rows for `brainstorming` and `writing-plans` are
  removed in the same change that deletes the folders (no dangling row —
  repeated-invocation safe: re-running the sweep finds nothing to do).

## 4. Out of scope

`to-tickets` admission (D18, separate item), `tdd` (executor-side, S7/S9),
the AC-attack review round (D3, S6), scaffold pipeline and dispatch briefs
(D4/D5, S7), enforcing the spec lint in other repos (pipeline work),
sweeping admission records onto the rest of the deployed catalog (AC3
closure), deletion of `wait-for-pr-comments` / `reply-and-resolve-pr-threads`
/ `monitor-pr` (S8, per D13/AC5), and any redesign of the grill skills'
interview mechanics beyond the exit-criterion graft.
