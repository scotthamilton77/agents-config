# Visualization Suite — Implementation Plan (full build map; bead `.2.1` at PR depth)

> **For agentic workers:** Implement this plan PR-slice by PR-slice using the
> `test-driven-development` skill (red-green-refactor per task). Dispatch one fresh
> subagent per PR slice. Steps use checkbox (`- [ ]`) syntax for tracking. Every
> slice must be green under `make ci-vizsuite` before its PR merges, and the
> always-run, change-detected CI job (§1.2) enforces that gate on every vizsuite PR.

**Date:** 2026-07-13
**Spec:** `docs/specs/2026-07-12-visualization-suite-design.md` (F0/V1/V2, V3-thin)
**Epic:** `agents-config-yf2ov.2` — children `.2.1`–`.2.8`
**This plan:** full build map for all 8 beads; bead `.2.1` (scaffold + V1 data build)
decomposed to individual PR slices.

**Goal:** Ship a new, isolated `packages/vizsuite` Python package that produces a
self-contained HTML PR-shape artifact from deterministic Tier-1 extracts — delivered
as small, independently-mergeable PRs whose own quality gate is CI-run from the
first PR and made a required merge gate on slice 1's PR (§1.2), yet cannot block or destabilize the rest of the repo.

**Architecture:** `packages/vizsuite` is a uv-managed package mirroring `workcli`'s
adapter / verb / envelope structure. Its `viz pr [<n>]` verb resolves the PR to an
**immutable head snapshot** (materialized via `git archive`), runs Tier-1 extractors
(estate scope via `git ls-tree`, churn via PyDriller, complexity via the `scc` binary
over the materialized snapshot, two-tier (EXTRACTED + INFERRED) centrality via
graphify's `graph.json`, PR metadata via `gh`), reconciles them to the PR's net
changed-file scope, assembles a shared **scene envelope**, and renders it to one
self-contained HTML file. CI isolation is by a **change-detected, always-run gate**: a
dedicated CI job runs `make ci-vizsuite` on vizsuite PRs (quality gate CI-run from slice
1; a merge gate once the check is marked required — §1.2), while the package stays out of
the repo-wide `make ci` aggregate (so a broken
vizsuite never blocks installer/prgroom/workcli PRs).

**Tech Stack:** Python 3.11 · uv · hatchling · stdlib `argparse` · `pydriller` (churn)
· `networkx` (centrality from graphify links) · `scc` Go binary (subprocess) · `gh`
(subprocess) · `git` (subprocess + PyDriller; blob SHAs from `git ls-tree -r <head_oid>`) ·
vendored `d3` (no JS toolchain) · pytest / ruff / mypy --strict / pip-audit.

---

## 0. OSS sub-claim verifications (hard AC of `.2.1`)

The spec (§5.1) flags two build-vs-buy sub-claims that must be **confirmed from
source** and recorded here before the pipeline relies on them.

### 0.1 cc.json per-file checksum field — **CONFIRMED**

- **Finding:** CodeCharta's `cc.json` schema added, at schema version **1.6**, an
  *optional* `checksum` property on `nodes` elements of type `File`, explicitly
  calculated from file content so analyzers can detect whether a node's metrics
  need recomputation (i.e. a content fingerprint, not an identity id).
- **Source:** `github.com/MaibornWolff/codecharta` →
  `CC_JSON_SCHEMA_CHANGELOG.md`, version 1.6 entry.
- **Implication for the plan:** vizsuite's scene envelope borrows the `checksum`
  attribute **slot** on file nodes (precedent-backed, not a novel field), and
  populates it with **the file's git blob SHA read from `git ls-tree -r <head_oid>`** — one
  deterministic, git-native content hash over one byte domain (the committed blob).
  This is pinned in §3.5.1 and resolves the algorithm/byte-domain ambiguity (R3-5):
  scc's `Hash` field is unusable (§0.3), and mixing `git hash-object` with raw
  `hashlib` would hash different domains. Only files tracked at the head snapshot are
  in the estate, so deletions/renames are handled by git's object model — a deleted
  path is simply absent from the estate node set.

### 0.2 doit md5-vs-mtime dependency check — **CONFIRMED (md5-content by default)**

- **Finding:** `doit/dependency.py` defines `MD5Checker` and `TimestampChecker`
  (both `FileChangedChecker` subclasses) in a `CHECKERS = {'md5': MD5Checker,
  'timestamp': TimestampChecker}` registry; `Dependency.__init__` defaults to
  `checker_cls=MD5Checker`, whose docstring states it is the default. It optimizes
  by checking `(timestamp, size)` first and only hashes when those look changed, but
  the up-to-date verdict is ultimately **content-hash based** — docs confirm
  behaviorally: `touch`-ing a `file_dep` (mtime only) does not re-run; appending a
  byte does. Switchable via `DOIT_CONFIG['check_file_uptodate']` / `--check_file_uptodate`
  (`'md5'` default | `'timestamp'` | custom checker).
- **Source:** `github.com/pydoit/doit` → `doit/dependency.py` (`MD5Checker`
  docstring, `CHECKERS` registry, `Dependency.__init__` default);
  pydoit docs `doc/tutorial-1.md` ("File Dependency MD5 Checksum") + `doc/cmd-run.md`.
- **Implication for the plan:** doit's default is a valid content-fingerprint
  substrate for the staleness funnel's rung 1 as-is (bead `.2.3`) — adopt the default
  `file_dep` behavior directly, and **`.2.3` must never set
  `check_file_uptodate='timestamp'`**, which would silently downgrade rung 1 to mtime
  semantics. **Not load-bearing for `.2.1`:** V1 has no funnel/`doit` dependency
  (§6.3); this gates `.2.3`.

### 0.3 Bonus finding (folds into 0.1): scc has no reliable checksum

scc's per-file `FileJob.Hash` is a Go `hash.Hash` accumulator tied to duplicate
detection, **not** a stable content-checksum string. Do not build identity or
fingerprinting on it. This is why 0.1's checksum slot is filled by the git blob SHA.

---

## 1. Incremental delivery strategy (the "small PRs, no destabilization" answer)

Three levers, all already supported by the repo's architecture:

### 1.1 New isolated package — zero blast radius on existing code

`packages/vizsuite` is purely additive. It is **not** in the installer's deployed
config surface (like `prgroom`/`workcli`, it is not installer-deployed), and it
**consumes** existing packages rather than modifying them. The `work` facade already
exposes every verb the later mutation beads need (`dep`, `create`, `label`, `note`);
the one gap (a resequence verb) the spec already designed around (§5.7 makes
resequencing `ruling-needed`, not one-click). No existing package changes for the
committed scope. `.2.1` specifically has **zero** tracker dependency — V1 is Tier-1
only (§6.3).

### 1.2 Change-detected CI enforcement — quality gated, blast radius contained

The design goal is two properties that must **not** be conflated (R3-6): vizsuite's
own quality gate must be **CI-enforced from the first PR** (lint, types, coverage,
audit, entry), *and* a broken/incomplete vizsuite must **not block** unrelated
installer/prgroom/workcli PRs. A "dark launch" that simply omits `ci-vizsuite` from
`make ci` fails the first property — GitHub Actions runs only `make ci`, so nothing
would mechanically enforce vizsuite's gate, and the completion gate is process
discipline, not a required PR status.

The mechanism that gives **both**:

- **Add `ci-vizsuite` as a Makefile target** (§3.4), mirroring `ci-workcli`.
- **Add a CI job that runs on _every_ PR** (§3.4.1) but does the expensive gate only
  when vizsuite paths changed. A cheap change-detection step (`git diff` vs the base)
  decides: vizsuite touched → run `make ci-vizsuite` (property 1, *run and reported* from
  the first PR — *gated* once the check is marked required, see the prerequisite below);
  untouched → the job no-ops in seconds and exits green (property 2, an
  unrelated PR is never blocked). The load-bearing detail: the `ci-vizsuite` **check is
  always reported**. A path-*filtered* workflow (`on: paths:`) would instead be *skipped*
  on unrelated PRs, and a skipped workflow reports **no** check at all — so a required
  `ci-vizsuite` status would hang forever on "Expected — waiting for status" and block
  every non-vizsuite PR (R4). An always-run job that self-skips its body avoids that trap.
- **Leave the repo-wide `make ci` aggregate unchanged**
  (`ci-installer ci-prgroom ci-workcli lint-actions`) — vizsuite is not in it, so a
  broken vizsuite is structurally invisible to the other packages' gate. The per-PR
  `ci-vizsuite` job is the enforcement; the aggregate stays isolated.

**Required-check prerequisite (F5 — an explicit delivery step, not a footnote).** The
change-detected job *runs and reports* `ci-vizsuite` from the first PR, but a reported
check is not a *gate* until it is marked **required** in branch protection — a GitHub
ruleset action that cannot live in the committed diff. This is the one step that turns
"enforced" from aspiration into fact, and it matters here because this repo merges via a
rule-based autonomous policy that could otherwise merge a red vizsuite PR. So: **on slice
1's PR, a repo-admin marks `ci-vizsuite` required and verifies it blocks a deliberately-red
test PR before slice 2 starts.** Marking it required is safe precisely because the job runs
and reports on every PR (green no-op when vizsuite is untouched), so it never leaves an
unrelated PR waiting on a status that never arrives.

### 1.3 Vertical tracer-bullet slices, not horizontal layers

Each PR is a thin end-to-end slice that ships green, per the spec's own framing of
V1 as "the pipeline's tracer bullet" (§6.3): EXTRACT → ASSEMBLE with no
inference/review machinery. PR #1 is a walking skeleton (real `viz pr` → real HTML
from a real estate-scope scene); each later PR thickens exactly one axis.

### 1.4 Bead granularity (recommended default)

The plan defines the PR slices; **mint a child bead per slice just-in-time** as each
slice starts (keeps `bd ready` clean, avoids a large speculative backlog, matches the
repo's "deferred beads are deliberate" culture). Vetoable — say the word to mint the
whole slice DAG up front instead.

---

## 2. Full build map — all 8 beads

Dependency chain (from `bd show agents-config-yf2ov.2`), 1:1 with the spec's
Continuations:

```
.2.1  scaffold + V1 data build ────┬──blocks──► .2.2  V1 PR-shape views ──┬─► .2.7 constellation eval
                                    │                                      └─► .2.8 V3 reaction round (design)
                                    └──blocks──► .2.3  sidecar + funnel + review queue (CLI) ──┬─► .2.4 viz skill ─► .2.5 V2 work-map ─► .2.8
                                                                                                └─► .2.6 overnight sweep cron
```

| Bead | Scope (one line) | Kind | New deps beyond `.2.1` | Tracker (`work` facade) | AC (spec test items) |
|------|------------------|------|------------------------|-------------------------|----------------------|
| **.2.1** | scaffold + Tier-1 extractors + PR reconciler + scene envelope/assembly + `viz pr` | build | `pydriller`, `networkx` | none | 6, 7, 8, 10, 11, 12 |
| **.2.2** | V1 views: estate treemap, attention ledger, file-sonar drill, constellation (eval-gated), heat model | build | (d3 view code) | none | playwright vs ≥2 real PRs; §6.1 |
| **.2.3** | `.viz/` sidecar, fingerprint manifest, funnel rungs 1–2, verdict recording, edge promotion + type-wall + cycle guard, `viz apply` `--dry-run`, locking | build | `doit`, `diskcache` | **enters here** (`dep`/`create`/`label`/`note`) | 1–5, 9, 13, 14, 16, 17 |
| **.2.4** | `viz` skill: rebuild driving, rung-3 doubt checks, edge/step inference, review-queue flow, annotation round-trip | build (Claude skill) | — | via CLI | e2e infer→review→verdict→promotion on this repo |
| **.2.5** | V2 work-map: lanes + territory, materialization slider, contested L1–L3 badging | build | (d3 view code) | reads plans/beads | 15; playwright; reaction round |
| **.2.6** | overnight sweep cron recipe (headless rungs 1–3, flag-only) | chore | — | read-only + flags | scheduled run → morning queue, zero beads writes |
| **.2.7** | V1 constellation keep/retire verdict | eval | — | — | verdict recorded in epic |
| **.2.8** | V3 reaction round → own dated spec | design | — | — | reaction verdicts recorded; time-reservation validated |

**Slice sketches for `.2.2`–`.2.8`** (refined just-in-time when each starts):

- **.2.2** — one PR per view module (treemap, ledger, sonar-drill, constellation),
  plus a heat-model PR (weighted-average of the three axes with the slider-explanation
  layer, §6.2). Views consume `.2.1`'s scene envelope; each is playwright-verified by
  the skill, not CI. Constellation ships behind the §11 evaluation gate.
- **.2.3** — PRs: (a) `.viz/` read/write + fingerprint manifest + atomic temp-then-rename
  + advisory lock; (b) funnel rungs 1–2 (hash check, provenance-intersection); (c)
  verdict recording (`viz verdict`); (d) edge promotion with type-wall mapping + the
  full-graph cycle guard + `--dry-run`; (e) `viz apply` mutation classes. `doit` +
  `diskcache` land here. `work`-facade tracker port lands in (a). **The INFERRED
  graphify edges that `.2.1` excludes from the deterministic axis (§3.6) belong to
  this tier** — if V2 wants to use them, they enter as Tier-2 facts with citations.
- **.2.4** — the thin `viz` skill in the Claude tree; PRs per capability (rebuild
  driver, rung-3 doubt check, edge/step inference with the fixed relation enum +
  passage citations, review-queue flow, annotation round-trip incl. claude-in-chrome).
- **.2.5** — PRs: lanes view; territory view; contested-semantics computation
  (generation index, L1–L3, contention window — test item 15) as CLI code; the
  step-naming experiment.
- **.2.6** — one PR: the cron recipe + headless dispatch allowlist.
- **.2.7 / .2.8** — evaluation and design beads; no package code (`.2.8` produces a
  new dated spec).

---

## 3. Bead `.2.1` — PR-sliced implementation

Five vertical slices. Each is one PR, green under `make ci-vizsuite` (CI-run via
the change-detected job; required-gating per §1.2), one just-in-time child bead. Boilerplate that is a
**structural mirror of an existing `workcli` file** is cited by exact path
(copy-and-adapt, do not re-invent); novel/load-bearing logic is shown in full. **All
paths are repo-root-relative and package-rooted under `packages/vizsuite/`** — workers
start at the worktree root, so a bare `src/vizsuite/...` would land outside the
package (R2).

### PR slice 1 — Walking skeleton + estate scope + CI enforcement

**Goal:** `viz pr <n>` produces a real self-contained HTML file whose scene is the
**estate tree** (`git ls-tree -r HEAD` minus curated excludes), with the CI gate wired and
change-detected. Exercises EXTRACT→ASSEMBLE end-to-end with a real (heat-free)
extractor. **Test items: 6, 12 (+ embedding-path half of 7).**

**Files:**
- Create: `packages/vizsuite/pyproject.toml` (see §3.6.pyproject — `dependencies = []`; extractor deps land in their slices)
- Create: `packages/vizsuite/uv.lock` (via `uv lock`)
- Create: `packages/vizsuite/src/vizsuite/__init__.py` (`PROTOCOL_VERSION = "1"`, `__version__`)
- Create: `packages/vizsuite/src/vizsuite/envelope.py` — **structural copy of** `packages/workcli/src/**/envelope.py`, renamed `WorkError`→`VizError`. **Pin the full `ErrorCode` enum now (stable across all slices):** `NOT_FOUND`, `USAGE`, `INTERNAL`, `ADAPTER_FAILURE` (scc/gh/git subprocess failure), `RECONCILER_DRIFT` (slice 2: local sets disagree with GitHub's scalar counts), `SNAPSHOT_MISMATCH` (slice 2: PR base/head OID still absent locally after fetch — stale clone / unreachable remote; the slice-3 `git archive` / materialization failure is `ADAPTER_FAILURE`, not this). Contract: one stdout JSON envelope `{"protocol","ok","data","error"}`, exit 0 on success / 1 on `VizError`|unhandled.
- Create: `packages/vizsuite/src/vizsuite/render.py` — mirror `workcli` human renderer (envelope→stderr).
- Create: `packages/vizsuite/src/vizsuite/cli.py` — mirror `workcli/cli.py`: `_EnvelopeArgumentParser`, `_build_parser()` with root flags `--protocol-version`/`--format {json,human}` and `add_subparsers(parser_class=_EnvelopeArgumentParser)`, `main(argv=None, *, git_runner=None, scc_runner=None, gh_runner=None, out=None, err=None) -> int`, `entry() -> None: sys.exit(main())`.
- Create: `packages/vizsuite/src/vizsuite/verbs/__init__.py` (`VERBS` registry), `verbs/pr.py` (the `viz pr` handler).
- Create: `packages/vizsuite/src/vizsuite/adapters/git/runner.py` — `GitRunner` protocol + `SubprocessGitRunner`, exposing `ls_tree(rev)` (`git ls-tree -r <rev>` → `(mode, type, blob_sha, path)` rows, reading the immutable commit tree, not the index). Slice 2 extends this same file with `rev_parse`/`cat_object_exists`/`rev_list`/`diff_name_only`/`fetch_pr`/`fetch_base`/`churn_for_commits` (and slice 3 adds `archive_tar`). The thin `ls_tree` exec is covered by a real-subprocess test (git is always available in CI).
- Create: `packages/vizsuite/src/vizsuite/extract/estate.py` — **the canonical file set** (§3.5.2): consumes `GitRunner.ls_tree(rev)` → `{path, blob_sha}` for files in `rev`'s tree, minus curated excludes (`graphify-out/`, `.beads/`, `.viz/`, `archive/`, lockfiles, generated). Slice 1 calls `estate(git, "HEAD")`; slice 2+ calls `estate(git, head_oid)`. Every axis and the assembler consume this one estate; the `blob_sha` fills the scene's per-file `checksum` slot.
- Create: `packages/vizsuite/src/vizsuite/scene/model.py` — typed scene dataclasses (envelope skeleton, §3.2).
- Create: `packages/vizsuite/src/vizsuite/scene/assemble.py` — minimal assembler (estate nodes → scene; no heat yet).
- Create: `packages/vizsuite/src/vizsuite/templates/html.py` — **script-safe serializer** (§3.5.3) for the inlined scene + minimal template. **Binding invariant from PR #1:** every repo-derived string (file `path`, later stories) is bound via `textContent` / HTML-escape, never `innerHTML` interpolation — no stored-self-XSS window between slice 1 and slice 5. `templates/static/d3.min.js` (vendored), `templates/static/scene.css`.
- Create tests: `packages/vizsuite/tests/conftest.py`, `packages/vizsuite/tests/fakes.py` (Scripted{Git,Scc,Gh}Runner — mirror `workcli/tests/fakes.py`), `tests/unit/test_envelope.py`, `test_cli_dispatch.py`, `test_verbs_pr.py`, `test_templates_html.py`, `test_assembly_determinism.py`, `test_extract_estate.py`.
- Modify: `Makefile` (§3.4 — add `ci-vizsuite` block + `.PHONY` + `VIZSUITE` var; **do not** touch the `ci:` aggregate line).
- Create: `.github/workflows/ci-vizsuite.yml` (§3.4.1 — change-detected enforcement of `make ci-vizsuite`).
- Create: `packages/vizsuite/src/vizsuite/output.py` — `ensure_viz_dir(root) -> Path`: idempotently creates `<root>/.viz/out/` and writes `<root>/.viz/.gitignore` containing `out/` if that line is absent. This **versioned sidecar** (committed in the target repo) makes `viz pr` portable — generated HTML is ignored in *any* target repo, not just agents-config, without editing the target's root `.gitignore` (R4). It ignores only `out/`, never other `.viz/` content (Tier-3 verdict sidecars are versioned; none exist in `.2.1`).

**Steps (TDD):**
- [ ] **1. Scaffold + gate first:** write `pyproject.toml` (`dependencies = []`), `uv lock`, copy the four boilerplate modules from `workcli` adapting names, add `output.py` (`ensure_viz_dir`, writes the portable `.viz/.gitignore`), add the Makefile block (§3.4), add `.github/workflows/ci-vizsuite.yml` (§3.4.1). Verify `uv --project packages/vizsuite run viz --help` exits 0.
- [ ] **2. Failing test — envelope invariants (item 12):** `test_cli_dispatch.py::test_unknown_verb_emits_usage_envelope` + `test_protocol_version_handshake_touches_no_adapter` (inject exploding runners). Run → FAIL → **3. Green** (mirrored `cli.main()` + `envelope.py`).
- [ ] **4. Failing test — estate extractor:** `test_extract_estate.py` — a scripted `git ls-tree -r HEAD` output → `{path, blob_sha}` records; tracked-but-excluded paths (`graphify-out/x`, a lockfile) are dropped; a `tree`/submodule (non-`blob`) row never appears. Run → FAIL → **5. Green.**
- [ ] **6. Failing test — `viz pr` end-to-end (item 6 setup):** `test_verbs_pr.py::test_pr_emits_html_from_estate` — `viz pr 1` with a `ScriptedGitRunner` → stdout envelope `ok:true`, `data.artifact` path exists, HTML non-empty and contains the estate nodes, and `.viz/.gitignore` contains `out/`. Run → FAIL → **7. Green** (`verbs/pr.py` → `extract.estate` → `scene.assemble` → `templates.html.render` → `output.ensure_viz_dir` → writes `.viz/out/pr-1.html`).
- [ ] **8. Failing test — assembly determinism (item 6):** `test_assembly_determinism.py::test_same_scene_same_html_modulo_stamp` — render the same scene twice, byte-identical HTML except the `generated_at` stamp. Run → FAIL → **9. Green** (sorted keys, single isolated stamp).
- [ ] **10. Failing test — script-safe embedding (item 7, embedding half):** `test_templates_html.py::test_scene_field_with_script_close_tag_survives_inline`. Run → FAIL → **11. Green** (§3.5.3 serializer).
- [ ] **12. Coverage + gate:** `make ci-vizsuite` → green (lint, format, mypy --strict, ≥90% branch, audit, verify-entry).
- [ ] **13. Commit:** `feat(vizsuite): scaffold + estate-scope viz pr skeleton + change-detected ci-vizsuite`.

### PR slice 2 — PR snapshot resolution + git+GitHub reconciler

**Goal:** resolve the PR's immutable `base_oid`/`head_oid` (fetching them so every read is
**object-DB**, not checkout-dependent), and reconcile the **local** net file/commit sets
against GitHub's **un-truncated scalar counts** (`changedFiles`, `commits{totalCount}`),
with a **loud drift error** on disagreement. estate (`ls-tree`) and churn (PyDriller
`only_commits`) read immutable objects — no checkout-state guard, no truncatable gh lists.
**Test item: 11.**

**Files:**
- Extend: `packages/vizsuite/src/vizsuite/adapters/git/runner.py` (the `GitRunner`/`SubprocessGitRunner` from slice 1) — add `rev_parse(rev)`, `cat_object_exists(oid)` (`git cat-file -e <oid>`), `rev_list(base, head)` (`git rev-list base..head`), `diff_name_only(base, head)` (`git diff base...head --name-only`), `fetch_pr(n)` (`git fetch origin pull/<n>/head` — works for fork PRs), `fetch_base(ref)` (`git fetch origin <ref>` — the base tip is not an ancestor of the PR head, so `pull/<n>/head` never brings it), and `churn_for_commits(oids)` (PyDriller `Repository(".", only_commits=oids)` — reads commit objects, not the worktree).
- Create: `packages/vizsuite/src/vizsuite/adapters/gh/runner.py` + `gh/parse.py` — `SubprocessGhRunner` (S603/S607-scoped) running one `gh api graphql` query for the PR's `baseRefOid`, `headRefOid`, `baseRefName`, `changedFiles` (Int scalar), and `commits{totalCount}` (Int scalar) — **all un-truncated**, sidestepping the `first:100` cap that `gh pr view --json files,commits` imposes (F4). Parse to typed `PrView` (`base_oid`, `head_oid`, `base_ref`, `changed_files: int`, `commit_count: int`). (PR author/review metadata is a separate widened call in slice 5.)
- Create: `packages/vizsuite/src/vizsuite/extract/churn.py` — Tier-1 churn extractor.
- Create: `packages/vizsuite/src/vizsuite/reconcile/pr_scope.py` — OID resolution + reconciler (§3.5 code).
- Create tests: `packages/vizsuite/tests/unit/test_reconcile_pr_scope.py`, `test_extract_churn.py`, `test_adapters_gh_parse.py`; **coverage seam:** `test_git_subprocess_runner.py` — real-subprocess test of `rev_parse`/`cat_object_exists`/`rev_list`/`diff_name_only` against a `tmp_path` fixture repo (git is always available in CI), mirroring `workcli/tests/unit/test_subprocess_runner.py`.
- Modify: `packages/vizsuite/pyproject.toml` — add `pydriller` to `dependencies`; re-`uv lock`.

**Key design (Path C — immutability by construction):**
- **Immutable-object reads, no checkout dependency (F1/F2):** `viz pr <n>` resolves
  `base_oid`/`head_oid`, then ensures **both** are present locally — `git fetch origin
  pull/<n>/head` for the head, fetching the base ref for the base (`pull/<n>/head` never
  brings the base tip) — with typed `SNAPSHOT_MISMATCH` otherwise (stale clones fail
  loud, not cryptically). Every
  slice-2 read is against the **immutable object DB**, never the working tree: `git diff`,
  `git rev-list`, estate via `git ls-tree -r head_oid`, churn via PyDriller `Repository(".",
  only_commits=…)` (which walks commit objects). So there is **no dependence on the operator's
  checkout** — no `HEAD == head_oid` requirement, no clean-tree guard — and a concurrent
  session mutating the main tree cannot corrupt the artifact. (The one extractor needing file
  *contents* on disk — `scc` — arrives in slice 3 and reads a materialized snapshot, not the
  checkout; a `git archive` extract has no `.git`, so `ls-tree`/PyDriller stay on the real repo.)
- **Scalar reconciliation, not truncatable lists (F4, spec §6.3):** local git is authoritative
  for the **sets** — `net_files = git diff base_oid...head_oid --name-only`, `commits =
  git rev-list base_oid..head_oid`. GitHub stays a genuine **second witness** via
  **un-truncated scalar counts**: `len(net_files) == pr.changed_files` and `len(commits) ==
  pr.commit_count`, else `VizError(RECONCILER_DRIFT)`. This preserves the spec's "two-source
  loud drift" join (test item 11) while being immune to the `first:100` cap that
  `gh pr view --json files,commits` imposes. Known rare false alarm, named in the drift
  detail: criss-cross histories have multiple merge bases, so GitHub's `changedFiles` (its
  chosen base) can differ from local git's 3-dot base — a loud false positive is acceptable.
- **Scope is the net set (R2/R3-3):** `PrScope.files` is the local net file set — a file
  added-then-reverted in the PR (in the churn union but not the net diff) is **excluded**
  from the scene, or it would misdirect review heat. Churn is the PyDriller `only_commits`
  union restricted to the net set.

**Steps (TDD):**
- [ ] **1. Failing test — unfetchable head (F1/F2):** `head_oid` absent locally and `fetch_pr` still can't resolve it → `VizError(SNAPSHOT_MISMATCH)`, no scene. Run → FAIL → **2. Green.**
- [ ] **2b. Failing test — unfetchable base:** `base_oid` absent locally and `fetch_base` still can't resolve it → `VizError(SNAPSHOT_MISMATCH)`, no scene (`pull/<n>/head` never brings the base tip). Run → FAIL → **Green.**
- [ ] **3. Failing test — estate at head_oid (object DB):** scripted `ls_tree` at `head_oid` → `estate(git, head_oid)` records; no checkout or tempdir involved. Run → FAIL → **4. Green.**
- [ ] **5. Failing test — file-count drift (item 11):** local net diff `{a}` (len 1) vs `changed_files=2` → `VizError(RECONCILER_DRIFT)`. Run → FAIL → **6. Green** (scalar reconcile).
- [ ] **7. Failing test — commit-count drift:** `len(rev_list)` ≠ `commit_count` → `VizError(RECONCILER_DRIFT)`. Run → FAIL → **8. Green.**
- [ ] **9. Failing test — big-PR no false drift (F4):** local net diff of 150 files with `changed_files=150` (a value a `first:100` list read would have truncated to 100) → **success**, artifact built. Run → FAIL → **10. Green** (proves the scalar path is cap-immune).
- [ ] **11. Failing test — reverted file EXCLUDED (R2/R3-3):** churn union `{a,b}` (b added then reverted), net diff `{a}`, counts agree → **success** AND `b` **absent** from `PrScope.files`. Run → FAIL → **12. Green.**
- [ ] **13. Failing test — happy path + churn:** matching counts → per-file churn (`added_lines`/`deleted_lines` summed via `commit.modified_files`: `mf.new_path`/`old_path`, `mf.added_lines`, `mf.deleted_lines`, `mf.change_type`), restricted to net files. Run → FAIL → **14. Green.**
- [ ] **15. Failing test — gh graphql parse:** scripted `gh api graphql` JSON → typed `PrView` (`base_oid`, `head_oid`, `base_ref`, `changed_files`, `commit_count`). Run → FAIL → **16. Green.**
- [ ] **17. Real-subprocess git seam:** `test_git_subprocess_runner.py` exercises `rev_parse`/`cat_object_exists`/`rev_list`/`diff_name_only` on a `tmp_path` repo. Run → PASS.
- [ ] **18. Wire `viz pr`** to fetch → resolve OIDs → reconcile → extract (estate + churn, object DB) → assemble → render (replace slice-1 estate-only path); inject scripted runners in `test_verbs_pr.py`.
- [ ] **19. Gate + commit:** `feat(vizsuite): PR OID resolution + fetch + scalar reconciler`.

### PR slice 3 — per-file heat axes (scc complexity + churn boost, consequence)

**Goal:** the complexity and consequence heat axes over the **estate scope** (slice 1),
making `.2.1` the complete extraction layer. `scc` is the first extractor needing file
*contents* on disk, so this slice introduces the **materialized snapshot** (`git archive
<head_oid>` → tempdir): `scc` scans that tempdir, never the live checkout (F2), its output
filtered to the estate. Consequence from `.critical-paths` (read from the same snapshot) + path-class heuristics (§6.2).
Complexity here is the full §6.2 axis — scc baseline plus a churn-scaled, never-cool boost on the PR-touched (net) files (consuming slice-2 churn), not scc alone; only the cross-axis *weighted average* of the three finished axes lives in `.2.2`. **No dedicated `.2.1` AC test item,
but both are required Tier-1 extractors.**

**Files:**
- Extend: `packages/vizsuite/src/vizsuite/adapters/git/runner.py` — add `archive_tar(oid) -> bytes` (`git archive --format=tar <oid>`).
- Create: `packages/vizsuite/src/vizsuite/reconcile/snapshot.py` — `materialize(git, head_oid, estate_paths) -> Path`: extracts the `git archive` tar (stdlib `tarfile`, `extractall(filter="data")` — supported on Python ≥3.11.4 and preempts ruff S202) into a `mkdtemp` dir; the caller tears it down in a `finally` via `shutil.rmtree`. Post-extract sanity: every estate path exists on disk, else `VizError(ADAPTER_FAILURE)` — guards `export-ignore` gitattribute drops in arbitrary target repos (agents-config has no `.gitattributes`). (LFS-managed repos yield pointer files, not content — irrelevant to scc on source; noted, not handled in V1.) **Join contract:** scc prefixes each `Location` with the path argument it was given, so an absolute-tempdir invocation would silently miss every estate key. `SubprocessSccRunner` therefore runs scc **from the snapshot dir** (`cwd=<tempdir>`, target `.`), and `scc/parse.py` normalizes each `Location` (strip a leading `./`) so keys are repo-relative and join estate keys. A post-parse sanity check requires a non-empty intersection with the estate, else `VizError(ADAPTER_FAILURE)` — a silently-empty complexity axis is the failure class this slice exists to prevent.
- Create: `packages/vizsuite/src/vizsuite/adapters/scc/runner.py` (`SubprocessSccRunner`, S603/S607-scoped, `scc --by-file --format json .` with `cwd=<snapshot-tempdir>` — scans the materialized snapshot root, not an argv path list, dodging ARG_MAX; not an absolute path, keeping `Location` repo-relative) + `scc/parse.py`.
- Create: `packages/vizsuite/src/vizsuite/extract/complexity.py` — the **full Complexity axis** per spec §6.2, not just the scc baseline: normalize scc `FileJob` records (keyed by `Location`; `Complexity`, `Code`, `Lines`, `Language`) **restricted to the estate scope** to a per-file 0–1 estate-wide baseline, then apply a **churn-scaled boost to the PR-touched (net) files** — consuming slice-2 `churn` and `PrScope.files` — clamped so a context file never scores below its scc baseline (**churn only heats, never cools** — §6.2). The boost weight is a tunable heat-model constant; the **never-cool clamp** and the **touched-files-only** application are the spec-mandated invariants tested here. (This intra-axis fusion is why complexity depends on slice-2 churn/reconcile; the cross-axis *weighted average* of the three finished axes stays in `.2.2`, §6.2 distinguishing the two.)
- Create: `packages/vizsuite/src/vizsuite/extract/consequence.py` — parse `.critical-paths` markers **from the materialized snapshot** (a tracked file, so it is in the archive; never the live checkout — F2; it is the same file the completion gate's triage reads — one source of truth, §6.2) + path-class heuristics (gate-policy, security-adjacent, public-contract paths) → per-file consequence 0–1, over the estate scope.
- Create tests: `packages/vizsuite/tests/unit/test_snapshot_materialize.py`, `test_extract_complexity.py`, `test_adapters_scc_parse.py`, `test_extract_consequence.py`.
- **scc preflight + coverage:** `shutil.which("scc")` preflight → typed `VizError(ADAPTER_FAILURE)` + install hint if absent. The unit suite uses `ScriptedSccRunner`; only the thin scc real-subprocess exec line carries `# pragma: no cover` (scc may be absent in CI) while the which-preflight branch is fake-covered. `archive_tar` gets a **real-subprocess test** — git is always available in CI, same as the slice-2 seam. Keeps the 90% floor honest.

**Steps (TDD):**
- [ ] **1. Failing test — materialize + sanity (F2):** scripted `archive_tar` (a tiny tar) → `snapshot.materialize` extracts to a tempdir, every estate path present, tempdir removed after; an estate path missing from the archive (simulated `export-ignore`) → `VizError(ADAPTER_FAILURE)`. Run → FAIL → **2. Green.**
- [ ] **2b. Real-subprocess test — a dirty tree cannot leak (the Path C invariant):** `tmp_path` repo with committed content A; dirty the worktree (edit a tracked file to content B, add an untracked file); `archive_tar` + `materialize` at the commit → every extracted file matches committed content A byte-for-byte and the untracked file is absent. This is the test the guard-based design could never pass. Run → PASS (real git).
- [ ] **3. Failing test — scc parse:** scripted scc JSON array (language elements embedding `Files[]`) → flat per-file records keyed by **normalized** `Location` (`./x/y.py` → `x/y.py`). Run → FAIL → **4. Green.**
- [ ] **5. Failing test — complexity axis = baseline + never-cool churn boost (§6.2):** fixture estate + scc records + slice-2 churn + net-file set → a context (non-net) file carries its scc baseline unchanged; a PR-touched file with churn scores **strictly above** its scc baseline (boost heats); a PR-touched file with a high scc baseline but zero churn **never scores below** that baseline (never-cool clamp); a file outside the estate is ignored; zero scc/estate overlap → `VizError(ADAPTER_FAILURE)` (join sanity). Run → FAIL → **6. Green.**
- [ ] **7. Failing test — scc preflight:** `scc` absent → typed `VizError` + install hint (fake `which`). Run → FAIL → **8. Green.**
- [ ] **9. Failing test — consequence:** fixture `.critical-paths` (living **in the snapshot dir**) + estate → per-file consequence 0–1; a gate-policy/security path scores high via heuristic without a marker. Run → FAIL → **10. Green.**
- [ ] **11. Wire `viz pr`** to materialize the snapshot for scc and `shutil.rmtree` it in a `finally`; scc scans the tempdir. Run → PASS.
- [ ] **12. Gate + commit:** `feat(vizsuite): scc complexity + consequence axis extractors (materialized snapshot)`.

### PR slice 4 — graphify centrality extractor (two-tier dependency in-degree)

**Goal:** load-bearing axis from graphify's `graph.json`, scoring **both EXTRACTED and
INFERRED dependency edges**, with per-edge provenance carried into the scene so
clients can distinguish the two tiers. **Test item: 10.**

**Files:**
- Create: `packages/vizsuite/src/vizsuite/extract/centrality.py` — the extractor (§3.6 code).
- Create tests: `packages/vizsuite/tests/unit/test_extract_centrality.py` (fixtures use the real `directed:false` node-link shape with mixed `confidence`, so the `Graph`-vs-`DiGraph` trap and the confidence acceptance are both exercised).
- Modify: `packages/vizsuite/pyproject.toml` — add `networkx>=3.4,<4`; re-`uv lock`.

**Key design (from verified ground truth — undirected, symbol-level, no stored centrality, 60% INFERRED):**
- **Two-tier acceptance with per-edge provenance — the load-bearing axis:** in the real
  graph, **60% (4278/7140) of dependency-relation edges are `confidence: INFERRED`**
  (`uses` is 100% inferred; `calls` is ~53% inferred). The load-bearing axis (spec
  §6.2) counts **both `EXTRACTED` and `INFERRED` dependency edges** into in-degree;
  any other confidence value is dropped. Each edge in `CentralityAxis.edges` carries
  its own provenance tag (`"extracted"`/`"inferred"`) so the scene and its clients can
  distinguish the two tiers rather than treating the axis as uniformly deterministic.
  When the same file pair arises from both tiers, `"extracted"` wins.
- **Build, don't load:** do NOT `nx.node_link_graph(raw)` — for this `directed:false`
  payload it returns an undirected `Graph` (no `in_degree` → `AttributeError`). Build a
  file-level `nx.DiGraph` from the accepted dependency-relation subset, edge
  `source_file → target_file`.
- **Intra-file exclusion:** drop edges whose endpoints resolve to the same file at the
  symbol→file rollup (the spec's real "self-edge" correction; zero literal node
  self-loops exist). Item 10, first half.
- **Projected = head-graph preflight, NOT an overlay:** require
  `built_at_commit == head_oid`. A head-built graph already contains new code's edges,
  so new load-bearing files score non-zero. Item 10, second half.
- **Optional-dependency, fail soft:** absent `graphify-out/` → axis unavailable;
  stale (`built_at_commit != head_oid`) → axis unavailable, never reported as post-PR;
  unparseable/torn `graph.json` (graphify may be mid-write in the live tree) → axis
  unavailable, never a crash.

**Steps (TDD):**
- [ ] **1. Failing test — confidence acceptance (item 10):** a fixture with EXTRACTED and INFERRED `calls`/`uses` edges → both tiers contribute to in-degree, each tagged with its own provenance in `edges`. Run → FAIL → **2. Green.**
- [ ] **3. Failing test — intra-file exclusion (item 10a):** a `directed:false` fixture where intra-file edges would flip the ranking → correct with them dropped (also fails first on the naive `node_link_graph`→`in_degree` path, locking the trap). Run → FAIL → **4. Green.**
- [ ] **5. Failing test — projected via head graph (item 10b):** head-built fixture (`built_at_commit == head_oid`) with a newly-added file's incoming edges → new hub scores non-zero. Run → FAIL → **6. Green.**
- [ ] **7. Failing test — preflight + fail-soft:** `built_at_commit` ≠ head_oid → unavailable; absent `graphify-out/` → fail soft; truncated/invalid JSON → unavailable. Run → FAIL → **8. Green.**
- [ ] **9. Failing test — relation filtering:** `contains`/`rationale_for` edges (non-dependency) do NOT contribute. Run → FAIL → **10. Green.**
- [ ] **11. Gate + commit:** `feat(vizsuite): graphify two-tier dependency centrality extractor`.

### PR slice 5 — scene envelope hardening (provenance, fingerprints, escaping, schema gate)

**Goal:** promote the minimal envelope to the full §4.4 contract and lock its
security/integrity invariants. **Test items: 7 (complete), 8.**

**Files:**
- Modify: `packages/vizsuite/src/vizsuite/scene/model.py` — full envelope: `schema_version`, `generated_at`, `generator`, `fingerprints` (input-hash manifest: tool versions, `base_oid`/`head_oid`, per-file `checksum` = estate blob SHA), `descriptors`, per-fact provenance (source/verdict + freshness axes), `recommendations[]` (empty for V1), reserved `events[]`/keyframes (V3).
- Modify: `packages/vizsuite/src/vizsuite/scene/assemble.py` — merge all extractors + PR metadata over the estate; **checksum from the estate `blob_sha`** (§0.1 — one pinned domain, not `git hash-object`/`hashlib`); **schema gate**: reject any Tier-2 fact lacking provenance/citations with a loud typed error.
- Create: `packages/vizsuite/src/vizsuite/extract/pr_metadata.py` (author/review-state/timestamps via a widened `gh pr view --json` call). Add the `meta` field to `PrScope` here (slice 2 deliberately returned no `meta`); wire it through `viz pr`.
- Modify: `packages/vizsuite/src/vizsuite/templates/html.py` — DOM-level escaping of all repo-derived strings via `textContent`/HTML-escape; footer notice that the artifact embeds repo data (spec §9).
- Create/extend tests: `packages/vizsuite/tests/unit/test_scene_assemble.py`, `test_schema_gate.py`, extend `test_templates_html.py` with the hostile-fixture set.

**Steps (TDD):**
- [ ] **1. Failing test — schema gate (item 8):** a scene whose Tier-2 fact lacks provenance → typed error, no silent default; an accepted-then-doubted fact carries both axes through assembly. Run → FAIL → **2. Green.**
- [ ] **3. Failing test — hostile strings (item 7 complete):** paths/stories/notes with `</textarea>`, `<script>`, `"><img onerror=…` render inert (templating/escaping boundary), plus the slice-1 `</script>` embedding case. Run → FAIL → **4. Green.**
- [ ] **5. Failing test — fingerprint checksum:** per-file `checksum` = the estate blob SHA (deterministic, git-native), identical across two assemblies of the same head. Run → FAIL → **6. Green.**
- [ ] **7. Gate + commit:** `feat(vizsuite): full scene envelope — provenance, fingerprints, escaping, schema gate`.

### Trailing PR (optional cross-package hardening, per §1.2)

After `.2.2` also lands green: fold `ci-vizsuite` into the `make ci` aggregate (so
cross-package changes exercise it) + (per repo memory) reconcile `uv.lock` audit across
all `packages/*`. This is defensive cross-package coverage, **not** the vizsuite
quality gate (already CI-run and required from slice 1 — §1.2). Its own bead.

---

## 3.4 Makefile block

Append after the `ci-workcli` block; extend `.PHONY`; add `VIZSUITE := packages/vizsuite`.
**Do not modify the `ci:` aggregate line** — vizsuite's gate is enforced by the
change-detected CI job (§3.4.1), not by the repo-wide aggregate, so a red vizsuite never
blocks other packages.

```makefile
# ── vizsuite (mirrors the ci-workcli block one-for-one; enforced via the
# always-run ci-vizsuite.yml job, NOT via the top-level `ci:` aggregate) ──
ci-vizsuite: lint-vizsuite format-check-vizsuite typecheck-vizsuite \
             cov-vizsuite audit-vizsuite verify-entry-vizsuite

test-vizsuite:
	cd $(VIZSUITE) && uv run pytest -q
lint-vizsuite:
	cd $(VIZSUITE) && uv run ruff check
format-check-vizsuite:
	cd $(VIZSUITE) && uv run ruff format --check
typecheck-vizsuite:
	cd $(VIZSUITE) && uv run mypy --strict src
cov-vizsuite:
	cd $(VIZSUITE) && uv run pytest --cov --cov-report=term-missing
audit-vizsuite:
	cd $(VIZSUITE) && uv sync --frozen && uv run pip-audit
verify-entry-vizsuite:
	uv --project $(VIZSUITE) run viz --protocol-version > /dev/null
	uv --project $(VIZSUITE) run viz --help > /dev/null
```

## 3.4.1 Always-run CI job (`.github/workflows/ci-vizsuite.yml`)

Runs on **every** PR but does the expensive gate only when vizsuite paths changed, so
the `ci-vizsuite` check is **always reported** (a green no-op on unrelated PRs) and can
safely be a required status. A path-*filtered* workflow would be *skipped* on unrelated
PRs and report no check at all, deadlocking a required status (R4). Change detection is
a cheap `git diff` vs the base; none of the gate steps need `scc`/`gh` binaries — the
unit suite uses fakes and `verify-entry` only runs `viz --help`.

```yaml
name: CI vizsuite
on:
  pull_request:
  push:
    branches: [main]
jobs:
  ci-vizsuite:                                   # required-check context; always completes
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0                         # base ref needed for change detection
      - id: changed
        run: |
          if [ "${{ github.event_name }}" = "push" ]; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          elif git diff --name-only "origin/${{ github.base_ref }}...HEAD" \
               | grep -qE '^(packages/vizsuite/|Makefile$|\.github/workflows/ci-vizsuite\.yml$)'; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          else
            echo "run=false" >> "$GITHUB_OUTPUT"   # no vizsuite change → no-op, check stays green
          fi
      - if: steps.changed.outputs.run == 'true'
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - if: steps.changed.outputs.run == 'true'
        run: uv python install 3.11
      - if: steps.changed.outputs.run == 'true'
        run: make ci-vizsuite
```

## 3.2 Scene model skeleton (slice 1; hardened in slice 5)

Typed dataclasses mirroring `workcli/model.py`. Slice-1 minimum: envelope with
`schema_version`, `generated_at`, `generator`, and a per-suite payload of estate file
nodes `{path, checksum, attributes:{}}` (`checksum` = git blob SHA). Slice 5 adds
`fingerprints`, `descriptors`, per-fact provenance, `recommendations[]`, reserved
`events[]`. No `Any` at the module boundary; parse once, trust the type inward.

## 3.5.1 Per-file checksum (pinned; §0.1, R3-5)

The estate extractor reads `git ls-tree -r <rev>`, whose object column is the file's git
blob SHA — a deterministic content hash over one byte domain (the committed blob at that
revision), computed by git itself. That SHA fills the scene node's `checksum` slot. **One
algorithm, one domain** — no `git hash-object`-vs-`hashlib` ambiguity. Reading the tree
object (not `git ls-files`, which reads the mutable index) makes the checksum a property
of the immutable commit, independent of checkout/index state (F1/F2). Only files present
in the tree at the head snapshot are in the estate, so deletions/renames need no special
fingerprint handling (a deleted path is absent from the estate; a rename is the new path
with its new blob).

## 3.5.2 Estate scope extractor (slice 1; §6.2 / findings principle 5)

```python
ESTATE_EXCLUDES = ("graphify-out/", ".beads/", ".viz/", "archive/")  # dir prefixes
ESTATE_EXCLUDE_SUFFIXES = ("uv.lock", "package-lock.json", ".min.js")  # lock/generated

def _in_estate(path: str) -> bool:
    return not (any(path.startswith(p) for p in ESTATE_EXCLUDES)
                or any(path.endswith(s) for s in ESTATE_EXCLUDE_SUFFIXES))

def estate(git: GitRunner, rev: str) -> dict[str, str]:
    """The canonical file set at an immutable revision: files in `rev`'s tree minus curated
    excludes, mapped to their git blob SHA. Reads the commit *tree object* (`git ls-tree -r
    <rev>`), never the mutable index, so the estate is a property of the snapshot, not the
    checkout (F1/F2). Every axis and the assembler consume this one estate (spec §6.2).
    Slice 1 passes rev="HEAD" (skeleton, pre-gh); slice 2+ passes the resolved head_oid."""
    return {path: blob_sha
            for mode, obj_type, blob_sha, path in git.ls_tree(rev)   # git ls-tree -r <rev>
            if obj_type == "blob" and _in_estate(path)}               # skip submodule/tree rows
```

## 3.5.3 Script-safe serializer (slice 1)

```python
def scene_to_script_json(scene: JsonValue) -> str:
    """Serialize the scene for inlining inside <script>. A repo-derived string
    containing '</script>' must never terminate the element (stored XSS via the
    embedding path, upstream of all DOM-level escaping — spec §4.6)."""
    raw = json.dumps(scene, sort_keys=True, separators=(",", ":"))
    return (
        raw.replace("<", "\\u003c")
           .replace(">", "\\u003e")
           .replace("&", "\\u0026")
    )
```

## 3.5 Reconciler core (slice 2)

`viz pr` resolves the PR's immutable OIDs and fetches them, then reconciles — every slice-2
read is against the **object DB**, never the checkout. Local git is authoritative for the
file/commit **sets**; GitHub is a second witness via **un-truncated scalar counts**
(`changedFiles`, `commits{totalCount}`), so the join survives PRs of any size (F4). The
PyDriller `only_commits` walk is the **union of per-commit touches**, used for churn only;
`PrScope.files` is the local net set so reverted-only files never reach the scene. (The `scc`
extractor — the only one needing files on disk — reads a materialized snapshot in slice 3.)

```python
def reconcile(pr_number: int, *, gh: GhRunner, git: GitRunner) -> PrScope:
    """Resolve immutable OIDs, reconcile local git's net sets against GitHub's un-truncated
    scalar counts. Disagreement is a loud drift error (spec §6.3, test item 11). The returned
    PrScope carries head_oid for the downstream extractors (estate/churn here; scc in slice 3)."""
    pr = gh.pr_view(pr_number)                        # graphql: OIDs + baseRefName + scalar counts
    if not git.cat_object_exists(pr.head_oid):
        git.fetch_pr(pr_number)                        # git fetch origin pull/<n>/head (forks too)
    if not git.cat_object_exists(pr.base_oid):         # pull/<n>/head never brings the base tip
        git.fetch_base(pr.base_ref)                    # git fetch origin <baseRefName>
    missing = [o for o in (pr.base_oid, pr.head_oid) if not git.cat_object_exists(o)]
    if missing:                                        # still absent ⇒ can't build the snapshot
        raise VizError(ErrorCode.SNAPSHOT_MISMATCH,
                       "PR base/head not present locally after fetch; check network/remote",
                       detail={"missing_oids": missing})

    net_files = set(git.diff_name_only(pr.base_oid, pr.head_oid))  # git diff base...head (authoritative)
    if len(net_files) != pr.changed_files:            # scalar file-count drift (cap-immune, F4)
        raise VizError(ErrorCode.RECONCILER_DRIFT, "local net file count disagrees with GitHub",
                       detail={"local": len(net_files), "github_changedFiles": pr.changed_files,
                               "note": "criss-cross histories may pick different merge bases"})

    commit_oids = git.rev_list(pr.base_oid, pr.head_oid)           # authoritative commit set
    if len(commit_oids) != pr.commit_count:           # scalar commit-count drift (cap-immune, F4)
        raise VizError(ErrorCode.RECONCILER_DRIFT, "local commit count disagrees with GitHub",
                       detail={"local": len(commit_oids), "github_commits": pr.commit_count})

    union_churn = git.churn_for_commits(sorted(commit_oids))       # union of per-commit touches
    files = {p: c for p, c in union_churn.items() if p in net_files}  # canonical NET set only
    return PrScope(pr_number=pr_number, head_oid=pr.head_oid, files=files)  # meta added slice 5
```
`git.diff_name_only` runs `git diff base...head --name-only` (3-dot = merge-base..head net
diff, matching GitHub's "Files changed"). `git.churn_for_commits` uses
`Repository(".", only_commits=oids).traverse_commits()` — commit objects, **not** the
worktree — summing `mf.added_lines`/`mf.deleted_lines` per `mf.new_path` (fallback
`old_path`). estate reads `git ls-tree -r head_oid`, also object-DB. Slice 2 touches no
tempdir; the `git archive` snapshot is materialized only for `scc` in slice 3 (§ slice 3).

## 3.6 Centrality extractor core (slice 4)

Ground truth (verified against `graphify-out/graph.json`): the graph is **undirected**
(`directed: false`), **symbol-level** (5578 nodes / 377 files), stores **no per-node
centrality**, has **zero** literal self-loops, and **60% of dependency-relation edges
are `INFERRED`** (`uses` 100% inferred; `calls` ~53%). The extractor keeps **both
`EXTRACTED` and `INFERRED` dependency edges**, tagging each with its provenance, builds
a file-level `DiGraph`, drops intra-file edges, and scores in-degree over the union.
`nx.node_link_graph` is deliberately NOT used (it returns an undirected `Graph` with no
`in_degree`).

```python
DEP_RELATIONS = frozenset({"calls", "uses", "imports_from", "inherits", "implements"})
_PROVENANCE_BY_CONFIDENCE = {"EXTRACTED": "extracted", "INFERRED": "inferred"}

def centrality_axis(graph_path: Path, head_oid: str) -> CentralityAxis:
    """Load-bearing axis from graphify. Scores both EXTRACTED and INFERRED edges,
    tagging each with its tier. Intra-file edges dropped; projected post-PR
    centrality via the head-graph preflight (no overlay)."""
    if not graph_path.exists():
        return CentralityAxis.unavailable("graphify-out absent")   # optional dep, fail soft
    try:
        raw = json.loads(graph_path.read_text())
    except (OSError, json.JSONDecodeError):
        return CentralityAxis.unavailable("graph.json unreadable (torn mid-write?)")  # fail soft
    if raw.get("built_at_commit") != head_oid:
        return CentralityAxis.unavailable("graph build-commit != PR head")  # never stale-as-fresh
    id_to_file = {n["id"]: n["source_file"] for n in raw["nodes"] if n.get("source_file")}
    g: nx.DiGraph = nx.DiGraph()
    for link in raw["links"]:
        if link.get("relation") not in DEP_RELATIONS:
            continue
        confidence = link.get("confidence")
        if confidence not in _PROVENANCE_BY_CONFIDENCE:             # two-tier acceptance
            continue
        src = id_to_file.get(link["source"]); dst = id_to_file.get(link["target"])
        if src is None or dst is None or src == dst:               # drop intra-file
            continue
        existing = g.get_edge_data(src, dst)
        if existing is None or existing["provenance"] != "extracted":  # extracted wins
            g.add_edge(src, dst, provenance=_PROVENANCE_BY_CONFIDENCE[confidence])
    edges = tuple((s, t, d["provenance"]) for s, t, d in g.edges(data=True))
    return CentralityAxis.from_indegree(dict(g.in_degree()), edges=edges)  # normalized 0–1 per file
```
If a later slice needs the full raw graph, load it with
`nx.node_link_graph(raw, edges="links")` to silence networkx's deprecated-default-key
`FutureWarning`.

## 3.6.pyproject — `pyproject.toml` (`.2.1`)

```toml
[project]
name = "vizsuite"
version = "0.1.0"
description = "vizsuite — repo/PR visualization suite (Tier-1 extractors, PR-scoped reconciliation, scene assembly, HTML rendering)."
requires-python = ">=3.11.4"
dependencies = []
# Extractor deps are staged in the slice that first needs them (avoids landing
# unexercised deps in the skeleton PR): slice 2 adds "pydriller"; slice 4 adds
# "networkx>=3.4,<4". doit + diskcache are the .2.3 funnel substrate (not here).
# scc + gh + git are external binaries invoked as subprocesses (not pip deps).
# d3 is vendored JS.

[project.scripts]
viz = "vizsuite.cli:entry"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/vizsuite"]

[dependency-groups]
dev = ["pytest", "pytest-xdist", "pytest-cov", "ruff", "mypy", "pip-audit"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E","W","F","I","B","UP","SIM","S","RET","ARG","PTH","TRY","RUF","N"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "TRY003"]
"src/vizsuite/adapters/scc/runner.py" = ["S603", "S607"]
"src/vizsuite/adapters/gh/runner.py" = ["S603", "S607"]

[tool.ruff.format]
docstring-code-format = true

[tool.mypy]
strict = true
warn_unreachable = true
disallow_any_decorated = true
enable_error_code = ["redundant-expr", "truthy-bool", "possibly-undefined"]
# If pydriller/networkx lack complete stubs under --strict, add a surgical
# [[tool.mypy.overrides]] with ignore_missing_imports for that module only.

[tool.coverage.run]
branch = true
source = ["src/vizsuite"]

[tool.coverage.report]
fail_under = 90
exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:", "@overload"]
show_missing = true
skip_covered = true
```

---

## 4. Test-item → slice traceability (`.2.1` AC)

| Spec test item | Slice | Assertion |
|---|---|---|
| 6 Assembly determinism | 1 | same scene+template → byte-identical HTML modulo stamp |
| 12 Envelope invariants | 1 | JSON envelope on stdout, exit mirrors `ok`, success + failure |
| 7 Escaping | 1 (serializer + DOM-bind invariant) + 5 (hostile-fixture test) | `</script>` survives inline; repo strings bound via `textContent`/escape from PR #1; full hostile test in slice 5 |
| 8 Schema gate | 5 | assembler rejects Tier-2 facts lacking provenance/citations |
| 10 Centrality corrections | 4 | EXTRACTED+INFERRED with per-edge provenance; intra-file edges excluded; head-graph new hub non-zero |
| 11 Reconciler drift alarm | 2 | local git sets vs GitHub un-truncated scalar counts (`changedFiles`/`commits{totalCount}`) → typed drift; cap-immune, big-PR no-false-drift proven |

Supporting extractors with their own tests but no dedicated AC item: estate (slice 1),
churn (slice 2), complexity + consequence (slice 3). All six `.2.1` AC items are
covered; items 1–5, 9, 13–17 belong to `.2.3`/`.2.5`.

---

## 5. Self-review (writing-plans gate)

- **Spec coverage (`.2.1`):** §4.4 envelope (slices 1/5), §4.6 packaging + script-safe
  serializer (slices 1/5), §5.6 packaging split + `viz` CLI + envelope pattern (slice 1),
  §6.1 estate scope (slice 1), §6.2 heat axes — the complete Complexity axis (scc baseline
  + never-cool churn boost, slice 3) + consequence (slice 3),
  two-tier centrality (slice 4), §6.3 reconciler + snapshot + tracer-bullet framing
  (slice 2). All three axis **values** (each the complete §6.2 per-file axis, incl.
  complexity's intra-axis churn boost) + the estate live in `.2.1`; only the cross-axis
  **weighted average** and the views live in `.2.2` (§6.2 separates the intra-axis churn
  boost — `.2.1` — from the cross-axis average — `.2.2`). No `.2.1` AC item is orphaned.
- **Scope boundaries:** doit + diskcache → `.2.3` (V1 has no funnel/sidecar, §6.3); the
  `viz build` verb is not `.2.1` (§5.6 lists no such verb); consequence pulled into
  `.2.1` (trivial `.critical-paths` parse — completes the extraction layer).
- **Provenance integrity:** the load-bearing axis scores both EXTRACTED and INFERRED
  graph edges, with per-edge provenance carried into the scene so clients can
  distinguish the two tiers rather than treating the axis as uniformly deterministic.
  Per-file checksum is one pinned domain (git blob SHA), not an ambiguous hash choice
  (R3-5).
- **PR correctness:** `viz pr` extracts from immutable git objects (estate via `ls-tree`,
  churn via PyDriller) plus a materialized `git archive` snapshot for `scc` — never the live
  checkout (F1/F2) — reconciled against GitHub's un-truncated scalar counts (F4); `PrScope`
  is the local net file set, so reverted-only files never reach the scene (R2/R3-3).
- **CI enforcement vs isolation:** the always-run `ci-vizsuite.yml` runs and reports
  the gate from slice 1 (marked required per the §1.2 prerequisite), while the `make ci`
  aggregate stays untouched so a broken vizsuite can't block other packages (R3-6) —
  quality enforcement is decoupled from feature activation.
- **Type consistency:** `VizError`/`ErrorCode` (full enum pinned in slice 1, incl.
  `RECONCILER_DRIFT`/`SNAPSHOT_MISMATCH`/`ADAPTER_FAILURE`), `GhRunner`/`GitRunner`/
  `SccRunner` protocols, `PrView`/`PrScope`/`CentralityAxis` used consistently.
- **Coverage honesty:** uncoverable subprocess exec lines (scc absent) are
  `# pragma: no cover`; git gets a real-subprocess test; which-preflight branches are
  fake-covered. The 90% branch floor is achievable.
- **Paths:** every file path is package-rooted under `packages/vizsuite/` (R2).
- **Placeholder scan:** none — both OSS sub-claims (§0) sourced-confirmed.

## 6. Execution handoff

**Recommended mode: subagent-driven per-PR-slice dispatch.** The five `.2.1` slices are
sequential (each builds on the last's package state) but self-contained; dispatch one
fresh subagent per slice, each using `test-driven-development`, review between slices,
merge each PR before the next starts. Not parallelizable (shared package state).

**Completion-gate tier:** every vizsuite PR touches `packages/**` (slice-1 PRs also
touch `Makefile`/`.github/workflows/`), all in `.critical-paths` → each triages to the
**HEAVY** gate (the `quality-gate` workflow), not SERIAL. Budget between-slice review
accordingly. The change-detected CI job enforces `make ci-vizsuite` at the PR status
level in parallel with the local HEAVY gate.

Kickoff prompt (after Scott approves this plan and a clean-context start):

> Execute PR slice 1 of the vizsuite implementation plan at
> `docs/plans/visualization-suite/2026-07-13-implementation-plan.md` (spec:
> `docs/specs/2026-07-12-visualization-suite-design.md`). Work in the existing
> `viz-impl-plan` worktree on a feature branch. Use the `test-driven-development`
> skill, red-green-refactor per step. Ship green under `make ci-vizsuite`; the
> `ci:` aggregate stays untouched, and slice 1 adds the always-run,
> change-detected `.github/workflows/ci-vizsuite.yml`. Stop after slice 1's PR for review.

---

## Review ledger

> Entries are point-in-time records of each review round. A mechanism named in an
> early round may be **superseded** by a later one (e.g. R3/R4's `git ls-files` /
> porcelain-guard → R5 Path C's `git ls-tree` / snapshot-by-construction). The
> canonical current design is the body (§3.x), not these historical entries.

**R1 — adversarial review (ralf-review, opus fresh-eyes) — FAIL, all resolved.**
- **B1** centrality `in_degree()` on undirected graph → crash. **Fixed:** file-level `DiGraph` (§3.6).
- **C1** no relation filter / symbol-vs-file hand-waved. **Fixed:** `DEP_RELATIONS` + explicit rollup.
- **C2** reconciler union-vs-net → false drift. **Fixed:** net-vs-net + membership; union churn-only.
- **M1/M2** `pr_import_edges` no producer / contradicted preflight. **Fixed:** overlay dropped; head-graph preflight.
- **M3** 90% floor vs uncoverable adapters. **Fixed:** git real-subprocess test; scc `# pragma: no cover`.
- **M4** `RECONCILER_DRIFT` unpinned. **Fixed:** full `ErrorCode` enum pinned in slice 1.
- **M5** item-7 escaping window. **Fixed:** slice-1 DOM-bind invariant.
- **m1–m5** merge_base / meta wiring / networkx pin / consequence / edge vocab. **Fixed.**

**R2 — Codex regular review (`gpt-5.6-terra`) — needs-attention, all resolved.**
- **[P1]** reverted files leak into scene. **Fixed:** `PrScope.files` filtered to net set (§3.5).
- **[P1]** slices 2–5 used repo-root paths, not package-rooted. **Fixed:** all paths under `packages/vizsuite/`.
- **[P2]** `.viz/out` not gitignored. **Fixed:** slice 1 modifies `.gitignore` (→ superseded by R4: portable `.viz/.gitignore` sidecar).
- **[P2]** deps staged in slice 1 but "added" in slices 2/4. **Fixed:** `dependencies = []`; staged per slice.

**R3 — Codex adversarial review (`gpt-5.6-sol`) — needs-attention/no-ship, all resolved.**
- **[high]** INFERRED graph edges promoted to Tier-1 (60% inferred). **Fixed:** `confidence == "EXTRACTED"` filter (§3.6); INFERRED → Tier-2 (`.2.3`).
- **[high]** PR revision not pinned. **Fixed:** immutable head snapshot via `baseRefOid`/`headRefOid` + `SNAPSHOT_MISMATCH` guard (§3.5, slice 2).
- **[high]** reverted files leak into scope (= R2-P1). **Fixed:** net-set scope + explicit absence test.
- **[high]** no whole-estate extractor. **Fixed:** `extract/estate.py` — `git ls-files` minus excludes, consumed by every axis (slice 1, §3.5.2).
- **[high]** checksum algorithm/domain ambiguous + deletion-unsafe. **Fixed:** pinned to the git blob SHA from `git ls-files -s` (§0.1, §3.5.1).
- **[high]** dark launch disables enforced package CI. **Fixed:** path-filtered `ci-vizsuite.yml` enforces the gate from slice 1, aggregate stays isolated (§1.2, §3.4.1) (→ refined by R4: always-run job, since a *filtered* required check deadlocks).

**R4 — Codex regular (`gpt-5.6-terra`) + adversarial (`gpt-5.6-sol`), both on the corrected plan — needs-attention, all resolved.** Both models converged independently on the first two.
- **[P1/high]** Path-*filtered* `ci-vizsuite` as a required check deadlocks unrelated PRs (a workflow skipped by `on: paths:` reports no status → "Expected — waiting" forever). **Fixed:** always-run job + `git diff` change-detection; the check always completes (green no-op off-path), so it is safe to mark required (§1.2, §3.4.1).
- **[P1/high]** Snapshot guard checked only `HEAD == head_oid`; `git ls-files -s` reads the index and `scc` reads the worktree, so a dirty checkout leaks uncommitted content into a "PR head" artifact. **Fixed:** added `git status --porcelain` clean-guard → `SNAPSHOT_MISMATCH`, with dirty-index/worktree tests (§3.5, slice 2); temp-worktree-at-head noted as V2 hardening. (→ superseded by R5 Path C: the porcelain-guard fix collided with the `.viz/.gitignore` sidecar; the guard is removed entirely in favor of snapshot-by-construction.)
- **[P2]** `.viz/out` ignore added only to agents-config's root `.gitignore` → not portable to other target repos. **Fixed:** `viz` writes a versioned `.viz/.gitignore` (`out/`) via `output.ensure_viz_dir`, portable to any target repo (slice 1).

**R5 — Codex regular (`gpt-5.6-terra`) + adversarial (`gpt-5.6-sol`) confirm passes on the R4-corrected plan, then a `fable` deep-analysis ruling — needs-attention, all resolved.** Both Codex models converged on F1/F2; an 11-agent adversarial severity workflow graded them; `fable` supplied the winning mechanism (Path C).
- **[BLOCKING] F1** `.viz/.gitignore` self-collision: R4's own sidecar (untracked) tripped R4's own `git status --porcelain` guard → 2nd `viz pr` run deadlocked (and blocked *any* later PR until manual commit). Flagged by both R5 models. **Fixed:** Path C removes the porcelain guard outright — immutability is by construction, so the untracked sidecar is inert.
- **[MAJOR, silent] F2** TOCTOU: the one-time guard left `scc` (slice 3, in-scope) reading the live checkout mid-run → a concurrent edit yields a mixed-snapshot artifact stamped "PR head." **Fixed:** `scc` now reads a **materialized snapshot** (`git archive <head_oid>` → tempdir, stdlib `tarfile`, slice 3); estate/churn read immutable git objects (`ls-tree`/PyDriller `Repository(".")`, slice 2). None touch the live checkout, so concurrent mutation cannot corrupt the artifact.
- **[MAJOR] F4** `gh pr view --json files,commits` caps at `first:100` → a >100-file PR truncates → false `RECONCILER_DRIFT`. Verified against gh's `query_builder.go`. **Fixed:** reconcile local git's authoritative **sets** against GitHub's **un-truncated scalar counts** (`changedFiles`, `commits{totalCount}` via `gh api graphql`), preserving the spec-§6.3 two-source join (test item 11) cap-free. (Correction to the ruling: `commitsCount` is not a `gh pr view --json` field — the count comes from a graphql `commits{totalCount}` query; verified.)
- **[MAJOR] F5** CI "run" ≠ "gated": nothing in the diff makes `ci-vizsuite` required. **Fixed:** promoted the branch-protection required-check to an explicit slice-1 delivery step verified on a deliberately-red test PR before slice 2; reworded the "enforced" overclaim to run-vs-gate (§1.2).
- **[NOT-A-DEFECT] F3** *(rejected — verified false.)* R5-regular claimed `built_at_commit` is nested under a `graph` object → centrality always disabled. Independently reloaded `graph.json`: `built_at_commit` is a **root** key (`6505d208…`); `graph` holds only `{hyperedges}`; `nodes`/`links` are at root. The plan's preflight reads the correct path. No change.
- **Path C rationale:** `git archive` over `git worktree` for materialization — same immutability invariant, no `.git`-state mutation / stale-worktree scar tissue, a crash leaves only a tempdir. `git ls-tree -r <oid>` replaces `git ls-files -s` (immutable tree object vs mutable index). One construction dissolves F1+F2+F4. `export-ignore` gitattribute risk closed by a post-extract sanity check (agents-config has no `.gitattributes`; verified).

**R6 — `fable` verification pass on the Path C fold-in — needs-attention, all resolved.**
- **[MAJOR]** `base_oid` never fetched/verified — `pull/<n>/head` doesn't bring the base tip; a stale clone died with a raw git error, not the typed refusal. **Fixed:** `fetch_base(baseRefName)` + both-OID existence check → `SNAPSHOT_MISMATCH` (§3.5; slice-2 step 2b).
- **[MAJOR]** the Path C invariant was untested, and `archive_tar` was `# pragma: no cover` despite real-subprocess git tests being the slice-2 norm. **Fixed:** real-subprocess dirty-tree-cannot-leak test (slice-3 step 2b); pragma removed from `archive_tar`.
- **[MAJOR]** the scc `Location` join claim was wrong — scc prefixes `Location` with its path argument, so an absolute-tempdir invocation misses every estate key (silently-empty complexity axis). **Fixed:** `cwd=<tempdir>` + `.` target + `Location` normalization + non-empty-join sanity check (slice 3).
- **[MAJOR]** two live-tree reads survived the F2 sweep: `.critical-paths` (consequence) and `graphify-out/graph.json` (centrality). **Fixed:** consequence reads the materialized snapshot; centrality fail-softs on torn/unparseable JSON (staleness already content-guarded by the head-commit preflight).
- **[MAJOR]** spec §6.3 / test item 11 still described the truncatable gh file-list mechanism — a direct spec-plan conflict. **Fixed:** review-feedback appendix appended to the spec amending §6.3 + item 11 to the scalar-count reconciliation.
- **[minor]** `tarfile.extractall` pinned to `filter="data"` (py ≥3.11.4; preempts ruff S202); "CI-enforced from the first PR" overclaim swept to run-vs-gate wording (Goal, §3 intro, trailing PR, self-review); slice-2 commit message no longer claims `git archive` (it lands in slice 3).

**R7 — HEAVY-tier adversarial verification workflow (4 plan-scoped finders → 2 refuters/finding → synthesis; opus/high) — 2 findings folded.** Triaged HEAVY on size (830 LOC docs); ran despite the docs-only class because this plan has surfaced a real defect every prior round. Technical-correctness and delivery-gate finders returned clean.
- **[MAJOR] spec-cov-1** the §6.2 Complexity axis's churn-scaled boost (PR-touched files heat above their scc baseline; context files never cool) was **cited but unbuilt** — slice-3 `complexity.py` was scc-only, churn was extracted raw in slice 2 but never fused, and no slice owned the boost, contradicting the "complete extraction layer" claim. **Fixed:** `complexity.py` (slice 3) now produces the full §6.2 axis — scc baseline + never-cool churn boost over the net files, consuming slice-2 churn/`PrScope.files` — with a boost/clamp test (slice-3 step 5); the self-review and slice-3 goal clarify that the intra-axis boost is `.2.1` while only the cross-axis weighted average is `.2.2`. (One refuter affirmed `is_real`; its paired refuter died on a StructuredOutput cap, so the unanimity gate auto-dropped the finding — recovered by inspecting the run journal, not the summary.)
- **[MINOR] drift-1** slice-1's forward reference enumerating slice-2's `GitRunner` surface omitted `fetch_base` (added in R6). **Fixed:** the enumeration now lists `fetch_base`.
- **Refuted, no change:** drift-2 (a non-defect) and delivery-gate-f5-1 (the F5 required-check step was verified correct by both refuters).
- **[contract nit]** the `ErrorCode` enum's `SNAPSHOT_MISMATCH` inline doc claimed it covered `git archive` failure; that path raises `ADAPTER_FAILURE` (slice 3). **Fixed:** `SNAPSHOT_MISMATCH` reworded to its true scope (OIDs absent after fetch).
