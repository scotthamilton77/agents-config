# Completion-Gate Routing — Design

**Date:** 2026-07-02
**Status:** Draft (pending review)
**Bead:** agents-config-abn9.38
**Decision:** Option A (codify gate-as-workflow as a sanctioned completion-gate variant), extended with an automatic three-tier router.

## 1. Problem

The completion-gate rule prescribes a serial skill path (quality-reviewer → fix → simplify → fix → verify-checklist). Ultracode sessions run the gate as a Workflow orchestration (multi-dimension finders, adversarial refuter panels, synthesis). No rule states that one substitutes for the other, so sessions run both — duplicated spend, near-duplicate findings (measured in the wgclw.14 session, PR #209: ~2.7M-token workflow gate followed by a serial simplify pass that still surfaced 5 additional findings).

Separately, the verification checklist's skip provision ("one-liners, config changes, typos") and the rule's "optional adversarial pass for high-stakes changes" are two informal tier boundaries with no crisp routing mechanism.

## 2. Decision summary

One verification contract, three tiers, routed automatically at gate time:

| Tier | Trigger | What runs |
|---|---|---|
| `SKIP` | Trivial/doc-only change, no overrides hit | Step 5 evidence only (tests/build where applicable; otherwise nothing) |
| `SERIAL` | Default | Existing steps 1–5 |
| `HEAVY` | Quant floor exceeded, risk-class hit, or `.critical-paths` match | Saved `quality-gate` workflow replaces steps 1–4; step 5 runs after, non-substitutable |

Routing decisions settled during design:

- **Cost autonomy:** full autonomy with announce. The agent routes on its own judgment when the rubric fires; it announces tier, reasons, and estimated cost before launching, and does not wait for approval. Ultracode or an explicit user ask still forces `HEAVY` at full scale.
- **Tier signal:** hybrid. A deterministic script computes a quantitative floor; a short, named risk-class list can escalate (never downgrade below the script's floor); a declarative `.critical-paths` marker file forces `HEAVY` in code.
- **Fleet size:** scales to the diff. The triage script emits a `scale_hint` the workflow consumes; full wgclw.14 scale is reserved for ultracode / explicit ask.
- **Step 5 (verify-checklist mechanical evidence) is non-substitutable under every tier and every option.** The workflow replaces judgment steps only (mission pillar 4).

## 3. Tier contract (shared, tool-agnostic)

The `<verification-checklist>` block in the shared template gains the three-tier wording. The `SKIP` tier expands "one-liners, config changes, typos" to explicitly include docs-only changes (subject to overrides — see §5 dogfood note).

`HEAVY` is Claude-only. On tools without a Workflow harness (Codex, Gemini, OpenCode), `HEAVY` resolves to `SERIAL`; the existing optional codex adversarial-pass prose is unchanged. The tier contract lives in the shared template so every tool shares the same vocabulary; only the heavy implementation is per-tool.

## 4. gate-triage script (the quant floor)

A small Python helper shipped as a skill asset (same pattern as merge-guard's `resolve_policy.py`). Run via `uv run` with PEP 723 inline metadata; `pathspec` is the one anticipated dependency (gitignore-syntax matching — hand-rolling gitignore semantics with `fnmatch` is a known defect farm).

### 4.1 Contract

Pure core over a value type; git interaction confined to a thin boundary:

```python
@dataclass(frozen=True)
class ChangedFile:
    path: str            # repo-relative, POSIX separators
    loc_changed: int     # added + deleted lines
    status: str          # A/M/D/R

@dataclass(frozen=True)
class DiffFacts:
    files: tuple[ChangedFile, ...]
    new_deps: bool       # lockfile/manifest additions detected
    base_ref: str

@dataclass(frozen=True)
class TriageConfig:     # defaults; overridable via project-config.toml [completion-gate]
    heavy_min_files: int = 8
    heavy_min_loc: int = 400
    heavy_min_subsystems: int = 3

def collect_diff(repo_root: Path, base_ref: str) -> DiffFacts      # boundary: shells to git
def load_markers(repo_root: Path) -> tuple[CriticalMarker, ...]    # boundary: reads .critical-paths files
def classify_file(path: str) -> FileClass                          # DOCS | CONFIG | CODE
def critical_hits(files, markers) -> tuple[CriticalHit, ...]       # pure
def compute_tier(facts, hits, config) -> Tier                      # pure: SKIP | SERIAL | HEAVY
def compute_scale_hint(facts) -> ScaleHint                         # pure
def triage(facts, markers, config) -> TriageResult                 # pure composition → JSON payload
```

### 4.2 Output

```json
{
  "tier_floor": "SERIAL",
  "files": 12, "loc_changed": 340, "subsystems": 3,
  "new_deps": false, "file_classes": ["code", "docs"],
  "critical_path_hits": ["src/auth/token.py ← src/auth/.critical-paths:*.py"],
  "scale_hint": {"finder_dimensions": 4, "refuters": 2, "synthesis_effort": "high"}
}
```

### 4.3 Tier floor logic

- All changed files classify as `DOCS` (and no critical hit) → `SKIP` floor.
- Any of: subsystems ≥ `heavy_min_subsystems`, files ≥ `heavy_min_files`, LOC ≥ `heavy_min_loc`, `new_deps` → `HEAVY` floor.
- Any `critical_path_hits` entry → `HEAVY` floor, unconditionally — no threshold math.
- Otherwise → `SERIAL`.

"Subsystem" = distinct top-level directory of the repo touched by the diff (dotfile directories and the repo root itself count as one subsystem each).

File classification: `DOCS` = `.md`, `.rst`, `.txt`, `.adoc`; `CONFIG` = `.json`, `.jsonc`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, plus dotfiles with no extension; `CODE` = everything else. Unknown or missing extensions default to `CODE` — fail toward scrutiny.

Diff scope: merge-base of the current branch against the repo's default branch (matching how code-review scopes a working diff).

## 5. `.critical-paths` marker file

Declarative, code-evaluated escalation — the load-bearing complement to the judgment-based risk list.

- Any folder may contain a `.critical-paths` file; gitignore syntax; patterns are anchored relative to the file's own folder and apply to that subtree only.
- Multiple marker files may exist (nested, like `.gitignore`); their matches are **unioned** — a nested marker never shadows an ancestor's.
- Negation (`!pattern`) applies within a single marker file's pattern list, per gitignore semantics.
- A modified file matching any marker forces `HEAVY` on Claude. Non-Claude tools: no effect — the serial gate stands.
- Evaluated entirely by gate-triage; no agent judgment involved.

Dogfood note: this repo should mark `src/user/.agents/rules/` (and the installer package) critical, so discipline-layer edits — which are `.md` files that would otherwise classify as docs — route `HEAVY` instead of `SKIP`. The marker file is what makes a docs-only `SKIP` floor safe to adopt.

## 6. Risk-class override (the bounded judgment)

A short, closed, named list in the rule text. Any hit escalates the script's floor to `HEAVY`; judgment can only escalate, never downgrade:

- Security or auth surface
- Concurrency / locking
- Public API or contract change
- Data migration / schema change
- Cross-subsystem architectural change

Stated bias: when unsure whether a class applies, it applies — wasted tokens on a borderline change beat a missed defect in an auth path. This list is where the design's accepted non-determinism concentrates, by intent.

## 7. Saved workflow: `quality-gate`

Ships as a saved named workflow (source: `src/user/.claude/workflows/`), invoked as `Workflow({name: "quality-gate", args: {...triage JSON...}})`. Codifies the wgclw.14 operational lore:

- Finder dimensions scale per `scale_hint`. **Simplify's axes (reuse, quality, efficiency) fold in as finder dimensions**; the simplify skill is therefore not separately required on the workflow path — this is the equivalence mapping that resolves the run-both duplication.
- Adversarial refuter panels (width per `scale_hint`), dedup-vs-seen across rounds, synthesis at high/xhigh effort.
- Apply-vs-flag bright line preserved in the fix wave.
- Hardening baked in: bounded StructuredOutput report fields (retry-cap choke: work lands, report dies), one-repair-attempt-then-abort chains, model/effort tiering (cheap finders, expensive synthesis), `resumeFromRunId` recovery documented in the workflow header comment.

Scale mapping (initial, tunable): `scale_hint` buckets small/medium/large from the same quant facts → (finder_dimensions, refuters, synthesis_effort) of roughly (3,2,high) / (4,2,high) / (6,3,xhigh). Full scale = the large bucket regardless of diff, triggered only by ultracode or explicit ask.

## 8. Rule-text changes

`src/user/.agents/rules/completion-gate.md` gains a routing preamble ahead of the numbered steps:

1. Run gate-triage → tier floor + scale_hint.
2. Apply the risk-class list (escalate-only).
3. Announce one line: tier, driving facts, estimated cost if `HEAVY` (e.g. *"Gate router: HEAVY (critical-path hit: src/auth; 12 files). Launching quality-gate workflow, ~600k tokens est."*). Do not wait for approval.
4. Route per the tier table. `HEAVY` unavailable (no Workflow harness) → `SERIAL`.

The existing serial steps, subagent-dispatch rules, HARD STOP delivery sequence, and merge-authorization language are unchanged.

## 9. Test plan (gate-triage helper)

Discipline per the writing-unit-tests skill: behaviors, not implementation; pure core tested directly with constructed `DiffFacts` values — no mocks, no subprocess stubs. The boundary functions (`collect_diff`, `load_markers`) get a small number of integration tests against a temp git repo. Implementation commits one test → one implementation slice at a time (no horizontal slicing); the list below enumerates behaviors, not a test-authoring order.

Tautology filter applied: no tests of `pathspec`'s raw pattern matching (library behavior). Tests target **our composition semantics** — anchoring to the marker's folder, subtree scoping, union across nested markers.

**Tier floor behaviors (pure, `compute_tier`):**
1. Docs-only diff, no hits → `SKIP`.
2. Docs-only diff WITH a critical hit → `HEAVY` (override beats skip).
3. Mixed docs+code under all thresholds → `SERIAL`.
4. Each quant threshold trips `HEAVY` independently at its boundary value (files = min, LOC = min, subsystems = min); one below each → not `HEAVY`.
5. `new_deps: true` alone → `HEAVY`.
6. Critical hit with an otherwise-trivial one-line diff → `HEAVY` (no threshold math).

**Classification behaviors (`classify_file`):**
7. Representative extensions map to DOCS / CONFIG / CODE per the chosen table; unknown extensions default to CODE (fail toward scrutiny).

**Critical-paths behaviors (`critical_hits`, pure over constructed markers):**
8. Pattern in `src/auth/.critical-paths` matches `src/auth/token.py` and `src/auth/sub/x.py`; does NOT match `src/other/token.py` (subtree scoping + relative anchoring).
9. Nested marker and ancestor marker both match different files → both hits reported (union, no shadowing).
10. Negation within one marker file exempts a matched file per gitignore semantics.
11. Hit report carries file ← marker:pattern provenance (the announce line's evidence).

**Scale-hint behaviors (`compute_scale_hint`):**
12. Small/medium/large bucket boundaries produce the mapped (dimensions, refuters, effort) tuples; monotonic — a strictly larger diff never gets a smaller fleet.

**Config behaviors:**
13. `project-config.toml` `[completion-gate]` overrides replace defaults; absent section → defaults (mirrors merge-guard's policy-resolution behavior).

**Boundary (integration, temp git repo):**
14. `collect_diff` on a crafted branch reports correct file set, LOC, and rename handling against the merge-base.
15. `load_markers` discovers nested `.critical-paths` files and anchors patterns correctly end-to-end.

Coverage target per the shared constraints (80% line / 70% branch on changed code) is expected to fall out of the behavior list naturally; no coverage-theater tests to close gaps.

## 10. Consequences

- The run-both duplication is resolved: on the `HEAVY` path, the workflow **is** steps 1–4; simplify is folded in, not repeated.
- The gate becomes reproducible: same diff, same markers, same config → same tier floor; the only judgment surface is the escalate-only risk list.
- Non-Claude tools keep a coherent contract with graceful degradation and zero new obligations.
- Auto-`HEAVY` spend is bounded by scale_hint; the ~2.7M full-scale run remains opt-in.
- New maintenance surface: threshold defaults and scale buckets will need tuning from real sessions; `.critical-paths` files must be seeded in repos that want the protection (this repo first).

## 11. Options considered

- **A (chosen):** codify as alternative implementation of steps 1–4 + automatic router (this design).
- **B:** status quo ad-hoc — leaves conflicting instructions and non-reproducible gate quality; every session pays the conflict.
- **C:** primer-only documentation — captures knowledge, resolves nothing.
- **Self-triaging workflow** (routing as workflow phase 0): rejected — Claude-only to the bone, taxes every gated change with a triage hop, puts the routing call in the least-context agent, and cannot implement `SKIP` (workflow startup already paid).
- **Prose-only rubric:** rejected — concentrates the whole mechanism in per-session judgment; violates code-over-prose for facts a script measures trivially.
