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
| `SKIP` | Trivial diff (≤1 file, ≤`trivial_max_loc`), no critical-path hit | Step 5 evidence only (tests/build where applicable; otherwise nothing) |
| `SERIAL` | Default | Existing steps 1–5 |
| `HEAVY` | Quant floor exceeded, risk-class hit, or `.critical-paths` match | Saved `quality-gate` workflow replaces steps 1–4; step 5 runs after, non-substitutable |

Routing decisions settled during design:

- **Cost autonomy:** full autonomy with announce. The agent routes on its own judgment when the rubric fires; it announces tier, reasons, and estimated cost before launching, and does not wait for approval. Ultracode or an explicit user ask still forces `HEAVY` at full scale.
- **Tier signal:** hybrid. A deterministic script computes a quantitative floor; a short, named risk-class list can escalate (never downgrade below the script's floor); a declarative `.critical-paths` marker file forces `HEAVY` in code.
- **Fleet size:** scales to the diff. The triage script emits a `scale_hint` the workflow consumes; full wgclw.14 scale is reserved for ultracode / explicit ask.
- **Step 5 (verify-checklist mechanical evidence) is non-substitutable under every tier and every option.** The workflow replaces judgment steps only (mission pillar 4).

## 3. Tier contract (shared, tool-agnostic)

The `<verification-checklist>` block in the shared template gains the three-tier wording. The `SKIP` tier formalizes the existing "one-liners, config changes, typos" provision as a **size bound**, not a file-type bound (§4.3): file type is irrelevant to `SKIP` eligibility, so the mechanism has no dependency on marker seeding or docs-root enumeration to stay safe.

`HEAVY` is Claude-only. On tools without a Workflow harness (Codex, Gemini, OpenCode), `HEAVY` resolves to `SERIAL`; the existing optional codex adversarial-pass prose is unchanged. The tier contract lives in the shared template so every tool shares the same vocabulary; only the heavy implementation is per-tool.

## 4. gate-triage script (the quant floor)

A small Python helper shipped as a skill asset (same pattern as merge-guard's `resolve_policy.py`). Run via `uv run` with PEP 723 inline metadata; `pathspec` is the one anticipated dependency (gitignore-syntax matching — hand-rolling gitignore semantics with `fnmatch` is a known defect farm).

### 4.1 Contract

Pure core over a value type; git interaction confined to a thin boundary:

```python
@dataclass(frozen=True)
class ChangedFile:
    path: str             # repo-relative POSIX path; new path for R, the path itself for A/M/D
    old_path: str | None  # repo-relative POSIX pre-rename path; set only when status == "R"
    loc_changed: int      # added + deleted lines; for untracked files, total line count
    status: str           # A/M/D/R — untracked working-tree files (`??`) map to "A"

@dataclass(frozen=True)
class DiffFacts:
    files: tuple[ChangedFile, ...]  # merge-base..HEAD unioned with staged, unstaged, AND untracked changes, deduped by path
    new_deps: bool       # any recognized dependency manifest/lockfile appears in `files`, any status
    base_ref: str

@dataclass(frozen=True)
class TriageConfig:     # defaults; overridable via project-config.toml [completion-gate]
    heavy_min_files: int = 8
    heavy_min_loc: int = 400
    heavy_min_subsystems: int = 3
    trivial_max_loc: int = 3   # SKIP eligibility ceiling; see §4.3; hard-capped at 20 on load

def load_config(repo_root: Path) -> TriageConfig
    # boundary: reads project-config.toml [completion-gate]. Config is a trust boundary —
    # it decides whether review runs at all — so it is validated, not merely parsed:
    # - every field must be a positive integer; a non-integer or negative value raises,
    #   caught by the caller and treated as "section absent" (defaults apply), not a crash
    # - trivial_max_loc is clamped to [1, 20] regardless of the configured value — a config
    #   cannot raise SKIP eligibility high enough to functionally disable the gate
    # - heavy_min_loc/heavy_min_files/heavy_min_subsystems have no upper clamp (a repo may
    #   legitimately want a higher HEAVY bar) but a value below trivial_max_loc is rejected
    #   (nonsensical: HEAVY would trigger below SKIP's own ceiling)
    # - unknown keys in [completion-gate] are ignored, not an error (forward-compatible)
    # - absent section, absent file, or any validation failure → TriageConfig() defaults;
    #   gate-triage never fails open to "no gate" on a config problem

DEPENDENCY_FILES = frozenset({
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "requirements.txt", "poetry.lock",
    "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile", "Gemfile.lock",
})

def collect_diff(repo_root: Path, base_ref: str) -> DiffFacts      # boundary: shells to git (committed diff + `git status --porcelain=v1 --untracked-files=all`)
def load_markers(repo_root: Path) -> tuple[CriticalMarker, ...]    # boundary: reads .critical-paths files
def classify_file(path: str) -> FileClass                          # DOCS | CONFIG | CODE — diagnostic only, not tier-determining
def critical_hits(files, markers) -> tuple[CriticalHit, ...]       # pure; checks path AND old_path per file
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

- Exactly 1 changed file AND `loc_changed` ≤ `trivial_max_loc` AND no critical hit → `SKIP` floor. File type is irrelevant — a 2-line code fix and a 2-line doc fix are equally trivial; a 2-line change to a critical-path file is not (next bullet wins).
- Any of: subsystems ≥ `heavy_min_subsystems`, files ≥ `heavy_min_files`, LOC ≥ `heavy_min_loc`, `new_deps` → `HEAVY` floor.
- Any `critical_path_hits` entry → `HEAVY` floor, unconditionally — no threshold math, overrides `SKIP` eligibility too.
- Otherwise → `SERIAL`.

`new_deps` = `Path(changed.path).name in DEPENDENCY_FILES` for any `changed` in `files`, regardless of status — matched by **basename**, not full path, so nested manifests (`packages/installer/pyproject.toml`, `packages/prgroom/uv.lock`, etc.) trigger it exactly like a root-level one. Touching a dependency manifest or lockfile at all is the signal, not just adding one. Detecting *which* dependency changed inside the file is out of scope; the file-level signal is deliberately coarse and cheap.

"Subsystem" = distinct top-level directory of the repo touched by the diff (dotfile directories and the repo root itself count as one subsystem each).

File classification: `DOCS` = `.md`, `.rst`, `.txt`, `.adoc`; `CONFIG` = `.json`, `.jsonc`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, plus dotfiles with no extension; `CODE` = everything else. Unknown or missing extensions default to `CODE` — fail toward scrutiny.

Diff scope: merge-base of the current branch against the repo's default branch, **unioned with staged, unstaged, and untracked working-tree changes**, deduped by path. Dedupe is **evidence-preserving, not last-write-wins**: `loc_changed` and `status` reflect the working-tree state (the current candidate), but if *either* the committed or working-tree source reports rename provenance for a path, the merged entry keeps `old_path` — a committed rename followed by an unstaged edit to the new path must not silently drop which subtree the file passed through. The gate tier must describe the actual candidate at gate time, not the last commit — a triage run against committed history alone would let uncommitted high-risk edits route on stale facts while step 5 verifies a different tree. Untracked files (`git status --porcelain` `??`) are real candidate files too — a new script sitting unadded at gate time must count toward `files`/`loc_changed` and be checked against `.critical-paths` exactly like a tracked addition.

Rename handling: for `status == "R"`, `critical_hits` evaluates both `old_path` and `path` against every marker — a critical file renamed out of a marked subtree, or a file renamed into one, both count as a hit. `status == "D"` evaluates `path` (the file being removed) the same way.

## 5. `.critical-paths` marker file

Declarative, code-evaluated escalation — the load-bearing complement to the judgment-based risk list.

- Any folder may contain a `.critical-paths` file; gitignore syntax; patterns are anchored relative to the file's own folder and apply to that subtree only.
- Multiple marker files may exist (nested, like `.gitignore`); their matches are **unioned** — a nested marker never shadows an ancestor's.
- Negation (`!pattern`) applies within a single marker file's pattern list, per gitignore semantics.
- A modified file matching any marker forces `HEAVY` on Claude. Non-Claude tools: no effect — the serial gate stands.
- Evaluated entirely by gate-triage; no agent judgment involved.

**Required seeding (implementation deliverable, not a dogfood nicety):** markers have exactly one job — force `HEAVY` on anything touching a load-bearing path, at any size; they do not gate `SKIP` eligibility (§3, §4.3). An unmarked path falls through to the quant floor and risk-class list like everything else; the maximum exposure is a `SKIP`-eligible diff, which is capped at 1 file / `trivial_max_loc` lines everywhere, marked or not — so an incomplete seeding list is a coverage gap, not a safety hole.

Coverage is defined at the **source-root** level, not the namespace level: one `.critical-paths` file at the root of every deployable source directory, matching its full subtree recursively (`.critical-paths` patterns already apply to their folder's whole subtree, §5 above — a root-level marker therefore covers that directory's namespace subdirectories, e.g. `skills/`, `rules/`, AND its own loose tool-root files, e.g. `AGENTS.md.template`, `settings.json.template`, uniformly, with no separate case for either). Deriving coverage from each tool adapter's `scoped_namespaces()` tuple was tried and found incomplete (Round 6): namespace directories are only part of what a tool adapter stages — `stage_templates`/`stage_settings` (`packages/installer/src/installer/core/staging.py`) deploy tool-root files like `AGENTS.md.template` through a separate path that a namespace-only derivation never reaches. Seeding at the source root sidesteps the distinction entirely.

Required roots: every tool adapter's `source_dir(repo_root)` (`src/user/.claude/`, `src/user/.codex/`, `src/user/.gemini/`, `src/user/.opencode/`), plus `src/user/.agents/` (shared skills/agents/rules), `src/plugins/`, and `packages/installer/` (the installer's own source — not staged anywhere, but load-bearing in its own right). This ships in the same change as gate-triage, with an acceptance test (§9) asserting every required root's marker produces a `critical_path_hits` entry for both a namespace-nested file and a root-level loose file — so a new tool, namespace, or tool-root file added later is covered by construction, not by remembering to re-enumerate.

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

### 7.1 Installer deployment requirement (blocking)

The Claude installer's namespace list (`packages/installer/src/installer/tools/claude.py:30`) currently stages only `("commands", "skills", "agents", "rules", "hooks")` — no `workflows`. A workflow placed at `src/user/.claude/workflows/` as written above would never reach `~/.claude/` and `HEAVY` routing would silently fail or no-op at invocation time. This is a required implementation deliverable, not an implementation detail to discover later.

Namespace awareness is **not centralized** in the installer — it is four independently hardcoded lists, verified by inspection, each of which must add `workflows` or the feature is broken in a different way than "doesn't deploy":

- `claude.py::scoped_namespaces()` — staging source (what gets copied in).
- `install.sh`'s staging and sync loops (two separate loops per the two-subdir-namespace-loop gotcha — both need patching).
- `ownership.py::PRUNE_NAMESPACES` — which namespaces the receipt tracks as wholesale-owned/prune-eligible. Omitting `workflows` here means a renamed or removed `quality-gate` source leaves a stale `~/.claude/workflows/quality-gate` behind, uncleaned — and since `HEAVY` invokes the workflow by stable name, a stale deployed copy keeps running silently after the source is gone.
- `backup.py::_SCOPED_NAMESPACES` — which namespaces route backups to a sibling `<namespace>-backup/` dir on conflict, rather than in-place.

Deliverables:
- Add `workflows` to all four lists above.
- An installer test asserting a file under `src/user/.claude/workflows/` lands at `~/.claude/workflows/` after install (staging/sync).
- An installer test asserting that renaming or removing a source workflow prunes (or explicitly reports) the stale destination on the next install, rather than leaving it callable.
- This ships in the same change as the `quality-gate` workflow itself — `HEAVY` routing must not merge ahead of its own deployment path.

*Aside, out of scope for this design:* four independently hardcoded namespace lists is itself a latent maintenance risk in the installer — each addition since `hooks` has had to be threaded through by hand, and `backup.py` already carries a `formulas` namespace absent from the other three. Worth a follow-up outside this spec; not fixed here.

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
1. Single file, `loc_changed` at `trivial_max_loc` exactly, no critical hit → `SKIP`. One line over → not `SKIP`.
2. Single trivial-size file WITH a critical hit → `HEAVY` (override beats skip, regardless of file type).
3. Two files, each individually trivial → not `SKIP` (file-count bound, not just LOC).
4. Mixed docs+code under all thresholds, more than 1 file → `SERIAL`.
5. Each quant threshold trips `HEAVY` independently at its boundary value (files = min, LOC = min, subsystems = min); one below each → not `HEAVY`.
6. A `DEPENDENCY_FILES` entry present with any status (A/M/D, tracked or untracked) → `HEAVY`, even with otherwise-trivial LOC. Matched by basename at a nested path (e.g. `packages/installer/pyproject.toml`), not just repo root.
7. Critical hit with an otherwise-trivial one-line diff → `HEAVY` (no threshold math).

**Classification behaviors (`classify_file`):**
8. Representative extensions map to DOCS / CONFIG / CODE per the chosen table; unknown extensions default to CODE (fail toward scrutiny).

**Critical-paths behaviors (`critical_hits`, pure over constructed markers):**
9. Pattern in `src/auth/.critical-paths` matches `src/auth/token.py` and `src/auth/sub/x.py`; does NOT match `src/other/token.py` (subtree scoping + relative anchoring).
10. Nested marker and ancestor marker both match different files → both hits reported (union, no shadowing).
11. Negation within one marker file exempts a matched file per gitignore semantics.
12. Hit report carries file ← marker:pattern provenance (the announce line's evidence).
13. A file with `status == "R"` renamed OUT of a marked subtree → hit on `old_path`. Renamed INTO a marked subtree → hit on `path`. Renamed WITHIN the same marked subtree → one hit, not two.
14. A file with `status == "D"` deleted from a marked subtree → hit on `path`.

**Scale-hint behaviors (`compute_scale_hint`):**
15. Small/medium/large bucket boundaries produce the mapped (dimensions, refuters, effort) tuples; monotonic — a strictly larger diff never gets a smaller fleet.

**Config behaviors:**
16. `project-config.toml` `[completion-gate]` overrides replace defaults; absent section → defaults (mirrors merge-guard's policy-resolution behavior).
17. `trivial_max_loc: 999` in config → clamped to 20, not accepted as-is; a config cannot raise the `SKIP` ceiling high enough to functionally disable the gate.
18. `heavy_min_loc` configured below `trivial_max_loc` → rejected, falls back to defaults (nonsensical ordering).
19. A non-integer or negative value for any field → falls back to defaults, does not raise past `load_config`'s boundary.
20. An unknown key in `[completion-gate]` → ignored, remaining known keys still applied.

**Boundary (integration, temp git repo):**
21. `collect_diff` on a crafted branch reports correct file set, LOC, and rename handling (`old_path`/`path`) against the merge-base.
22. `collect_diff` includes an unstaged edit and a staged-new file alongside committed branch changes, deduped against a file that appears both committed and re-touched in the working tree.
23. `collect_diff` includes a wholly untracked (`??`) file — status maps to "A", `loc_changed` is the file's full line count, and it participates in `files`/critical-path matching like any other addition.
24. `collect_diff` detects a `DEPENDENCY_FILES` entry present only as an untracked or unstaged change (not yet committed) and sets `new_deps: true`, including at a nested path (`packages/prgroom/uv.lock`).
25. `load_markers` discovers nested `.critical-paths` files and anchors patterns correctly end-to-end.
26. A file committed as a rename OUT of a marked subtree (`status == "R"`, `old_path` in the marked subtree), then further edited unstaged at its new path, still carries `old_path` in the deduped `DiffFacts` and still produces a `critical_hits` entry.

**Repo-level acceptance check (this repo, not the gate-triage package):**
27. For every required source root (§5), assert **effective coverage, not file existence**: seed each root's `.critical-paths` with a `**` pattern by default (narrower only when a root deliberately excludes a known-safe subpath), then assert BOTH a representative namespace-nested file (e.g. `skills/some-skill/SKILL.md`) AND a representative tool-root loose file (e.g. `AGENTS.md.template`) under that root actually produce a `critical_path_hits` entry when run through `critical_hits`. An empty or mis-anchored marker file fails this test even though the file exists; a marker that only covers namespaces (missing the root-level case Round 6 found) fails too.
28. Installer test: renaming or removing the source `quality-gate` workflow prunes (or explicitly reports) the stale `~/.claude/workflows/quality-gate` on the next install.

Coverage target per the shared constraints (80% line / 70% branch on changed code) is expected to fall out of the behavior list naturally; no coverage-theater tests to close gaps.

## 10. Consequences

- The run-both duplication is resolved: on the `HEAVY` path, the workflow **is** steps 1–4; simplify is folded in, not repeated.
- The gate becomes reproducible: same diff, same markers, same config → same tier floor; the only judgment surface is the escalate-only risk list.
- Non-Claude tools keep a coherent contract with graceful degradation and zero new obligations.
- Auto-`HEAVY` spend is bounded by scale_hint; the ~2.7M full-scale run remains opt-in.
- New maintenance surface: threshold defaults and scale buckets will need tuning from real sessions.
- **Blocking prerequisites, not follow-ups:** the installer must gain a `workflows` namespace (§7.1) before `HEAVY` can invoke anything, and this repo's `.critical-paths` markers (§5) must ship in the same change so discipline-layer edits floor at `HEAVY` from day one. `SKIP` does not depend on seeding — it is size-bound (§3, §4.3) — so an unseeded repo carries no `SKIP`-related exposure beyond the bound itself.

## 11. Options considered

- **A (chosen):** codify as alternative implementation of steps 1–4 + automatic router (this design).
- **B:** status quo ad-hoc — leaves conflicting instructions and non-reproducible gate quality; every session pays the conflict.
- **C:** primer-only documentation — captures knowledge, resolves nothing.
- **Self-triaging workflow** (routing as workflow phase 0): rejected — Claude-only to the bone, taxes every gated change with a triage hop, puts the routing call in the least-context agent, and cannot implement `SKIP` (workflow startup already paid).
- **Prose-only rubric:** rejected — concentrates the whole mechanism in per-session judgment; violates code-over-prose for facts a script measures trivially.

## Review feedback

Bounded record of adversarial-review rounds (`codex adversarial-review --wait --base main --scope branch`) run against this spec before implementation. The body above reflects only the resolved state; this section is the audit trail.

**Round 1** (2 high, 0 medium/critical) — resolved:
- `HEAVY`'s saved workflow targeted `src/user/.claude/workflows/`, a namespace the installer does not stage (verified against `claude.py:30`). → promoted to a blocking deliverable, §7.1.
- Docs-only `SKIP` could ship before any `.critical-paths` markers existed. → added a fail-closed default (later superseded in Round 3, see below).

**Round 2** (2 high, 1 medium) — resolved:
- Diff scope was committed-history-only; uncommitted high-risk edits could route on stale facts. → `collect_diff` unions staged + unstaged changes, §4.3.
- `ChangedFile.path` was underspecified for renames (`status == "R"` has two paths in git, one field in the contract). → added `old_path`; `critical_hits` checks both sides.
- (medium) Required marker seeding covered only 2 of the repo's deployable discipline-layer roots. → expanded to the full surface, §5.

**Round 3** (2 high, 1 medium) — resolved:
- The Round-1 fail-closed default only gated `SKIP` on marker *existence*, not marker *coverage* — a single marker anywhere still enabled repo-wide `SKIP` for every unmarked `.md` file, including this spec's own class of document. → root-caused rather than patched again: `SKIP` redefined as a size bound (≤1 file, ≤`trivial_max_loc` LOC), independent of file type or marker state. This removes marker seeding as a `SKIP`-safety dependency entirely (§3, §4.3, §5).
- Untracked (`??`) working-tree files were outside the triage contract — a new file could sit at gate time without contributing to any threshold. → `collect_diff` now includes untracked files, mapped to status `"A"`.
- (medium) `new_deps` only covered whole-manifest additions, missing version bumps or edits inside existing manifests/lockfiles. → redefined as file-presence in `DEPENDENCY_FILES`, any status — coarser but complete.

**Round 4** (2 high, 0 medium/critical) — resolved:
- The required-seeding list (still hand-enumerated after Round 2's expansion) omitted `src/user/.codex/`, `src/user/.gemini/`, `src/user/.opencode/`, and `src/user/.claude/hooks/` — all verified as real deployable content, including a hook script already known to be load-bearing. → root-caused rather than expanded a third time: coverage is now defined generically as every namespace root any tool adapter declares, plus the fixed shared/plugin/installer roots, with an acceptance test (§9 item 22) that fails on drift instead of a prose list that can silently miss the next one.
- `DEPENDENCY_FILES` matched bare filenames against full repo-relative paths, so nested manifests (`packages/*/pyproject.toml`, `packages/*/uv.lock` — verified, 4 packages) would never match. → matching redefined as basename comparison, §4.3.

**Round 5** (2 high, 0 medium/critical) — resolved, and the loop's 5-round cap:
- Round 4's acceptance test (§9 item 23) only asserted marker *file existence*, not that the marker's pattern actually matched anything under its root — an empty or mis-anchored `.critical-paths` file would pass the test while protecting nothing. → test redefined to assert effective coverage: a representative file under every required root must produce a `critical_path_hits` entry, not just "the file is present."
- The dedupe rule ("working-tree status wins on conflict") could drop `old_path` when a committed rename out of a marked subtree was followed by an unstaged edit to the new path, silently defeating rename-based critical-path detection. → dedupe redefined as evidence-preserving: working-tree state wins for `loc_changed`/`status`, but `old_path` is retained if either source reports rename provenance for that path.

Original 5-round cap reached at Round 5; extended by up to 3 more rounds on user request to verify Round 5's unverified fixes.

**Round 6** (1 high, 0 medium/critical) — resolved:
- Coverage was derived from each tool adapter's `scoped_namespaces()` tuple only, but `stage_templates`/`stage_settings` (verified in `packages/installer/src/installer/core/staging.py`) deploy tool-root loose files — `AGENTS.md.template`, `settings.json.template` — through a separate staging path a namespace-only derivation never reaches. A one-line edit to the assembled instruction template for an entire tool could satisfy `SKIP`'s size bound with no marker coverage. → root-caused again: coverage moved from namespace-level to **source-root level** — one recursive marker per tool/shared/plugin/installer root covers namespaces and root-level loose files uniformly, since subtree matching is already recursive. Acceptance test (§9 item 23) now asserts both a namespace-nested and a root-level representative file per root.

**Round 7** (1 high, 1 medium) — resolved:
- §7.1's installer deliverable named only staging/sync as touch points, but namespace awareness in the installer is **four independently hardcoded lists**, verified by inspection: `claude.py::scoped_namespaces()`, `install.sh`'s two loops, `ownership.py::PRUNE_NAMESPACES`, and `backup.py::_SCOPED_NAMESPACES`. Missing `workflows` from `PRUNE_NAMESPACES` specifically means a renamed/removed `quality-gate` source leaves a stale, still-invocable copy in `~/.claude/workflows/` — `HEAVY` calls it by stable name and would keep running outdated gate logic silently. → all four lists named explicitly as required touch points; added an installer test asserting rename/removal prunes the stale destination (§9 item 28). Flagged, not fixed here: the installer's namespace-list duplication across four files is itself a latent maintenance risk, out of scope for this spec.
- (medium) `[completion-gate]` config had no validation — a malformed or adversarial config could set `trivial_max_loc` high enough to functionally disable `SKIP`'s safety bound, or crash triage on bad types. → added `load_config` with bounds (`trivial_max_loc` hard-capped at 20, ordering checked against `heavy_min_loc`), fail-closed-to-defaults on any invalid value, unknown keys ignored.
